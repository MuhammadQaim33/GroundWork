from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from auth import login, logout, refresh, require_service_user, signup
from compile import OUT_DIR, compile_tex
from llm import active_provider, chat
from store import (
    brag_content,
    cv_content,
    delete_brag,
    delete_cv,
    get_brag,
    list_cvs,
    set_cv_preferred,
    upload_brag,
    upload_cv,
)
from user_settings import get_openrouter_key, set_openrouter_key

app = FastAPI(title="Groundwork Generator API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
OUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/out", StaticFiles(directory=OUT_DIR), name="out")


@app.exception_handler(httpx.HTTPStatusError)
async def llm_provider_error(_request: Request, exc: httpx.HTTPStatusError):
    status = 502 if exc.response.status_code >= 500 else 400
    snippet = exc.response.text[:300]
    return JSONResponse(
        status_code=status,
        content={"detail": f"LLM provider error ({exc.response.status_code}). {snippet}"},
    )


class Answer(BaseModel):
    question: str
    answer: str


class Credentials(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class GenerateRequest(BaseModel):
    job_description: str
    answers: list[Answer] = []
    cover_letter_format: Literal["pdf", "text"] = "pdf"


class FileOut(BaseModel):
    name: str
    kind: Literal["pdf", "text"]
    url: str | None = None


class GenerateResult(BaseModel):
    resume: FileOut
    cover_letter: FileOut
    cover_letter_text: str | None = None
    used_master_cv: str | None = None


@app.post("/api/auth/signup")
def api_signup(req: Credentials):
    return signup(req.email, req.password)


@app.post("/api/auth/login")
def api_login(req: Credentials):
    return login(req.email, req.password)


@app.post("/api/auth/refresh")
def api_refresh(req: RefreshRequest):
    return refresh(req.refresh_token)


@app.post("/api/auth/logout")
def api_logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.startswith("Bearer "):
        logout(authorization[len("Bearer ") :].strip())
    return {"ok": True}


@app.get("/api/master-cvs")
def api_list_cvs(_sv: Annotated[dict, Depends(require_service_user)]):
    return list_cvs()


@app.post("/api/master-cvs")
def api_upload_cv(
    _sv: Annotated[dict, Depends(require_service_user)],
    file: Annotated[UploadFile, File(...)],
):
    if not file.filename or not file.filename.lower().endswith(".tex"):
        raise HTTPException(400, "Master CVs must be .tex (LaTeX) files.")
    return upload_cv(file.filename, file.file.read())


@app.delete("/api/master-cvs/{cv_id}")
def api_delete_cv(cv_id: int, _sv: Annotated[dict, Depends(require_service_user)]):
    delete_cv(cv_id)
    return {"ok": True}


@app.put("/api/master-cvs/{cv_id}/preferred")
def api_cv_preferred(cv_id: int, _sv: Annotated[dict, Depends(require_service_user)]):
    set_cv_preferred(cv_id)
    return {"ok": True}


@app.get("/api/brag-doc")
def api_get_brag(_sv: Annotated[dict, Depends(require_service_user)]):
    return get_brag()


@app.post("/api/brag-doc")
def api_upload_brag(
    _sv: Annotated[dict, Depends(require_service_user)],
    file: Annotated[UploadFile, File(...)],
):
    if not file.filename or not file.filename.lower().endswith(".md"):
        raise HTTPException(400, "The brag document must be a Markdown (.md) file.")
    return upload_brag(file.filename, file.file.read())


@app.delete("/api/brag-doc")
def api_delete_brag(_sv: Annotated[dict, Depends(require_service_user)]):
    delete_brag()
    return {"ok": True}


@app.get("/api/settings")
def api_get_settings(_sv: Annotated[dict, Depends(require_service_user)]):
    return {"provider": active_provider(), "openrouter_key_set": bool(get_openrouter_key())}


class SettingsUpdate(BaseModel):
    openrouter_api_key: str = ""


@app.put("/api/settings")
def api_put_settings(req: SettingsUpdate, _sv: Annotated[dict, Depends(require_service_user)]):
    set_openrouter_key(req.openrouter_api_key)
    return {"ok": True}


@app.post("/api/generate")
def api_generate(
    req: GenerateRequest, _sv: Annotated[dict, Depends(require_service_user)]
) -> GenerateResult:
    jd = _clamp(req.job_description, 6000)
    if not jd.strip():
        raise HTTPException(400, "A job description is required.")
    answers = _clamp_answers(req.answers)
    cvs = list_cvs()
    if not cvs:
        raise HTTPException(400, "Upload at least one master CV in Settings first.")

    cv = _pick_cv(cvs, jd)
    master_tex = cv_content(cv).decode("utf-8", errors="replace")
    if active_provider() == "groq" and len(master_tex) > 18000:
        raise HTTPException(
            400,
            "Master CV is too large to fine-tune on the free tier (over 18KB). "
            "Split or simplify the .tex file, or add an OpenRouter key in Settings for no limits.",
        )
    brag = get_brag()
    # A real brag doc can be 60KB+; stuffing it verbatim into the fine-tune prompt
    # blows Groq's free-tier request budget. Condense to the strongest wins once,
    # then cache the summary (keyed by the stored file) for repeat generates.
    brag_text = _summarize_brag(brag) if brag else ""

    fine_tuned = _fine_tune(master_tex, brag_text, jd)
    resume_pdf = _compile(fine_tuned, "custom-resume")
    resume = FileOut(name="custom-resume.pdf", kind="pdf", url=f"/out/{resume_pdf.name}")

    letter_text = _cover_letter(jd, answers, cv["file_name"])

    if req.cover_letter_format == "pdf":
        letter_pdf = _compile(_letter_to_tex(letter_text), "cover-letter")
        cover = FileOut(name="cover-letter.pdf", kind="pdf", url=f"/out/{letter_pdf.name}")
    else:
        cover = FileOut(name="cover-letter.txt", kind="text")

    return GenerateResult(
        resume=resume,
        cover_letter=cover,
        cover_letter_text=letter_text,
        used_master_cv=cv["file_name"],
    )


def _out_name(base: str) -> str:
    return f"{base}-{uuid4().hex[:8]}"


def _compile(tex: str, base: str) -> Path:
    """Compile LaTeX to PDF; surface tectonic failures as a readable 502, not a traceback."""
    try:
        return compile_tex(tex, _out_name(base))
    except RuntimeError as exc:
        raise HTTPException(502, f"LaTeX compile failed. {exc}") from exc


def _clamp(text: str, max_chars: int) -> str:
    return text[:max_chars]


def _clamp_answers(answers: list[Answer]) -> list[Answer]:
    out = []
    for a in answers:
        q = a.question.strip()
        ans = a.answer.strip()
        if q and ans:
            out.append(Answer(question=q[:500], answer=ans[:2000]))
    return out[:20]


BRAG_SUMMARY_SYSTEM = (
    "You condense a candidate's brag document into a compact brief for tailoring a resume. "
    "Keep the strongest, most metric-rich wins. Preserve factual claims and numbers EXACTLY as "
    "written — never add, rephrase, or embellish. Drop filler. "
    "Output compact markdown, no more than 4000 characters."
)

SUMMARY_CACHE = Path(__file__).resolve().parent / "data" / "brag_summary.json"

# Groq free tier: llama-3.3-70b-versatile is capped at 12,000 TPM (rolling/minute).
# A single request counts input + max_tokens against that, so we fit output to the
# remaining budget and bail with a clear error if input alone leaves no room.
# Only enforced on Groq; BYOK OpenRouter and local Ollama have no such ceiling.
TPM_BUDGET = 11000
MAX_OUT_TOKENS = 5000


def _fit_max_tokens(system: str, user: str, floor: int = 800) -> int:
    est_input = (len(system) + len(user)) // 4
    if active_provider() != "groq":
        return max(floor, MAX_OUT_TOKENS)
    max_out = max(floor, min(MAX_OUT_TOKENS, TPM_BUDGET - est_input))
    if est_input + max_out > TPM_BUDGET + 500:
        raise HTTPException(
            400,
            "Input is too large for the model's free-tier token budget. "
            "Shorten the job description or simplify the master CV "
            "(or add an OpenRouter key in Settings for no limits).",
        )
    return max_out


def _summarize_brag(brag: dict) -> str:
    cache: dict[str, str] = _load_summary_cache()
    cached = cache.get(brag["storage_path"])
    if cached:
        return cached
    text = _clamp(brag_content(brag), 24000)
    try:
        summary = chat(
            BRAG_SUMMARY_SYSTEM, text, temperature=0.2, max_tokens=_fit_max_tokens(BRAG_SUMMARY_SYSTEM, text, floor=800)
        ).strip()
    except Exception:
        summary = text[:20000]
    _save_summary_cache({**cache, brag["storage_path"]: summary})
    return summary


def _load_summary_cache() -> dict[str, str]:
    try:
        return json.loads(SUMMARY_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_summary_cache(cache: dict[str, str]) -> None:
    SUMMARY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_CACHE.write_text(json.dumps(cache), encoding="utf-8")


def _pick_cv(cvs: list[dict], job_description: str) -> dict:
    """Auto-pick the best master CV for the JD. LLM scores candidates; preferred breaks ties."""
    if len(cvs) == 1:
        return cvs[0]
    listing = "\n".join(
        f"- {c['file_name']}{' (preferred)' if c['preferred'] else ''}" for c in cvs
    )
    prompt = (
        f"Job description:\n{job_description[:4000]}\n\n"
        f"Master CVs available:\n{listing}\n\n"
        "Reply with ONLY the exact file name of the single best master CV for this role."
    )
    try:
        choice = chat(
            "You pick the best resume template for a given job description.",
            prompt,
            temperature=0.0,
            max_tokens=200,
        ).strip()
        for c in cvs:
            if c["file_name"].lower() in choice.lower():
                return c
    except Exception:
        pass
    return next((c for c in cvs if c["preferred"]), cvs[0])


FINE_TUNE_SYSTEM = (
    "You are a resume editor. Rewrite the provided LaTeX resume to better match a job "
    "description, using facts from the brag document when they strengthen the fit. "
    "NEVER invent experience, skills, or metrics that appear in neither the resume nor the "
    "brag document. Keep the document structure and keep the LaTeX valid. "
    "Respond with ONLY the .tex source code — no markdown fences, no commentary."
)


def _fine_tune(master_tex: str, brag_text: str, job_description: str) -> str:
    user = (
        f"JOB DESCRIPTION:\n{job_description}\n\n"
        + (f"BRAG DOCUMENT:\n{brag_text}\n\n" if brag_text else "")
        + f"MASTER RESUME (.tex):\n{master_tex}"
    )
    max_tokens = _fit_max_tokens(FINE_TUNE_SYSTEM, user, floor=1500)
    edited = chat(FINE_TUNE_SYSTEM, user, temperature=0.3, max_tokens=max_tokens).strip()
    if edited.startswith("```"):
        edited = "\n".join(edited.splitlines()[1:])
        if edited.rstrip().endswith("```"):
            edited = "\n".join(edited.splitlines()[:-1])
    # ponytail: LLM LaTeX may not compile — one retry, then fail loud. No silent fallback.
    if "documentclass" not in edited.lower():
        edited = chat(FINE_TUNE_SYSTEM, user, temperature=0.3, max_tokens=max_tokens).strip()
        if "documentclass" not in edited.lower():
            raise HTTPException(502, "Model produced invalid LaTeX (no documentclass). Try again.")
    return edited


def _cover_letter(job_description: str, answers: list[Answer], cv_name: str) -> str:
    answers_block = "\n".join(
        f"Q: {a.question}\nA: {a.answer}"
        for a in answers
        if a.question.strip() and a.answer.strip()
    )
    user = (
        f"JOB DESCRIPTION:\n{job_description}\n\n"
        + (f"FORM ANSWERS:\n{answers_block}\n\n" if answers_block else "")
        + f"RESUME FILENAME: {cv_name}"
    )
    system = (
        "You write concise, specific cover letters (about 250 words). Ground every claim in the "
        "job description and the candidate's own answers; never invent experience or numbers. "
        "Leave the signature as '[Your Name]'. Output plain text only, with blank lines between paragraphs."
    )
    return chat(system, user, temperature=0.4, max_tokens=1500).strip()


_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "%": r"\%",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def _escape_latex(s: str) -> str:
    return re.sub(r"[\\{}%$&#_~^]", lambda m: _LATEX_SPECIALS[m.group(0)], s)


def _letter_to_tex(letter_text: str) -> str:
    paragraphs = [_escape_latex(p.strip()) for p in letter_text.split("\n\n") if p.strip()]
    body = "\n\\par\\medskip\n".join(f"\\noindent {p}" for p in paragraphs)
    return (
        "\\documentclass[11pt]{article}\n"
        "\\usepackage[a4paper,margin=1in]{geometry}\n"
        "\\pagestyle{empty}\n"
        "\\begin{document}\n"
        f"{body}\n"
        "\\end{document}"
    )
