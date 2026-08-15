from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from auth import login, logout, refresh, require_service_user, signup
from compile import OUT_DIR, compile_tex
from llm import active_provider, chat, vision_chat
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
from user_settings import get_links, get_openrouter_key, set_links, set_openrouter_key

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
    cover_letter_formats: list[Literal["pdf", "text"]] = ["pdf"]
    parts: list[Literal["resume", "cover_letter", "feedback"]] = ["resume", "cover_letter"]


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
    return list_cvs(_sv["id"])


@app.post("/api/master-cvs")
def api_upload_cv(
    _sv: Annotated[dict, Depends(require_service_user)],
    file: Annotated[UploadFile, File(...)],
):
    if not file.filename or not file.filename.lower().endswith(".tex"):
        raise HTTPException(400, "Master CVs must be .tex (LaTeX) files.")
    return upload_cv(file.filename, file.file.read(), _sv["id"])


@app.delete("/api/master-cvs/{cv_id}")
def api_delete_cv(cv_id: int, _sv: Annotated[dict, Depends(require_service_user)]):
    delete_cv(cv_id, _sv["id"])
    return {"ok": True}


@app.put("/api/master-cvs/{cv_id}/preferred")
def api_cv_preferred(cv_id: int, _sv: Annotated[dict, Depends(require_service_user)]):
    set_cv_preferred(cv_id, _sv["id"])
    return {"ok": True}


@app.get("/api/brag-doc")
def api_get_brag(_sv: Annotated[dict, Depends(require_service_user)]):
    return get_brag(_sv["id"])


@app.post("/api/brag-doc")
def api_upload_brag(
    _sv: Annotated[dict, Depends(require_service_user)],
    file: Annotated[UploadFile, File(...)],
):
    if not file.filename or not file.filename.lower().endswith(".md"):
        raise HTTPException(400, "The brag document must be a Markdown (.md) file.")
    return upload_brag(file.filename, file.file.read(), _sv["id"])


@app.delete("/api/brag-doc")
def api_delete_brag(_sv: Annotated[dict, Depends(require_service_user)]):
    delete_brag(_sv["id"])
    return {"ok": True}


@app.get("/api/settings")
def api_get_settings(_sv: Annotated[dict, Depends(require_service_user)]):
    return {"provider": active_provider(), "openrouter_key_set": bool(get_openrouter_key())}


class SettingsUpdate(BaseModel):
    openrouter_api_key: str = ""


class LinksUpdate(BaseModel):
    links: list[str] = []


@app.put("/api/settings")
def api_put_settings(req: SettingsUpdate, _sv: Annotated[dict, Depends(require_service_user)]):
    set_openrouter_key(req.openrouter_api_key)
    return {"ok": True}


@app.get("/api/links")
def api_get_links(_sv: Annotated[dict, Depends(require_service_user)]):
    return {"links": get_links()}


@app.put("/api/links")
def api_put_links(req: LinksUpdate, _sv: Annotated[dict, Depends(require_service_user)]):
    links = _clamp_links(req.links)
    set_links(links)
    return {"links": links}


@app.post("/api/generate")
def api_generate(
    req: GenerateRequest, _sv: Annotated[dict, Depends(require_service_user)]
) -> StreamingResponse:
    """Stream each generated artifact as an SSE event the moment it's ready."""
    jd = _clamp(req.job_description, 6000)
    if not jd.strip():
        raise HTTPException(400, "A job description is required.")
    answers = _clamp_answers(req.answers)
    cvs = list_cvs(_sv["id"])
    if not cvs:
        raise HTTPException(400, "Upload at least one master CV in Settings first.")

    cv = _pick_cv(cvs, jd)

    # Feedback always runs, so the master CV is always needed.
    master_tex = cv_content(cv).decode("utf-8", errors="replace")
    if "resume" in req.parts and active_provider() == "groq" and len(master_tex) > 18000:
        raise HTTPException(
            400,
            "Master CV is too large to fine-tune on the free tier (over 18KB). "
            "Split or simplify the .tex file, or add an OpenRouter key in Settings for no limits.",
        )

    brag_text = ""
    brag = get_brag(_sv["id"])
    if brag:
        brag_text = brag_content(brag)

    return StreamingResponse(
        _generate_stream(
            req,
            jd,
            answers,
            cv["file_name"],
            _sv.get("name") or "",
            get_links(),
            brag_text,
            master_tex,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_error(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    if isinstance(exc, httpx.HTTPStatusError):
        return f"LLM provider error ({exc.response.status_code}). {exc.response.text[:300]}"
    return f"Generation failed: {exc}"


def _generate_stream(
    req: GenerateRequest,
    jd: str,
    answers: list[Answer],
    cv_name: str,
    name: str,
    links: list[str],
    brag_text: str,
    master_tex: str,
):
    """Emit each requested artifact as an SSE event; a failed part doesn't kill the rest."""
    yield _sse("used_master_cv", {"used_master_cv": cv_name})

    if "resume" in req.parts:
        try:
            fine_tuned = _fine_tune(master_tex, brag_text, jd)
            resume_pdf = _compile(fine_tuned, "custom-resume")
            yield _sse(
                "resume",
                {"name": "custom-resume.pdf", "kind": "pdf", "url": f"/out/{resume_pdf.name}"},
            )
        except Exception as exc:
            yield _sse("error", {"part": "resume", "message": _stream_error(exc)})

    if "cover_letter" in req.parts:
        try:
            letter_text = _cover_letter(jd, answers, cv_name, name, links)
            yield _sse("cover_letter_text", {"text": letter_text})
            if "text" in req.cover_letter_formats:
                yield _sse(
                    "cover_letter_txt",
                    {"name": "cover-letter.txt", "kind": "text", "text": letter_text},
                )
            if "pdf" in req.cover_letter_formats:
                letter_pdf = _compile(_letter_to_tex(letter_text), "cover-letter")
                yield _sse(
                    "cover_letter_pdf",
                    {"name": "cover-letter.pdf", "kind": "pdf", "url": f"/out/{letter_pdf.name}"},
                )
        except Exception as exc:
            yield _sse("error", {"part": "cover_letter", "message": _stream_error(exc)})

    # feedback is non-optional — always generated
    try:
        rating, feedback_text = _feedback(jd, master_tex, brag_text)
        yield _sse("feedback", {"rating": rating, "text": feedback_text})
    except Exception as exc:
            yield _sse("error", {"part": "feedback", "message": _stream_error(exc)})

    yield _sse("done", {})


MAX_SCREENSHOTS = 6
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024


@app.post("/api/screenshot-questions")
def api_screenshot_questions(
    files: Annotated[list[UploadFile], File(...)],
    _sv: Annotated[dict, Depends(require_service_user)],
) -> list[Answer]:
    """Read questions off uploaded screenshots and answer them from resume + brag doc.

    Images are read into memory and sent to the vision model as data URIs — nothing is
    saved to disk, storage, or the database.
    """
    if not files:
        raise HTTPException(400, "Upload at least one screenshot.")
    if len(files) > MAX_SCREENSHOTS:
        raise HTTPException(400, f"At most {MAX_SCREENSHOTS} screenshots per request.")
    cvs = list_cvs(_sv["id"])
    if not cvs:
        raise HTTPException(400, "Upload at least one master CV in Settings first.")

    images: list[tuple[str, bytes]] = []
    for f in files:
        mime = f.content_type or "image/png"
        if not mime.startswith("image/"):
            raise HTTPException(400, f"{f.filename or 'file'} is not an image.")
        data = f.file.read()
        if len(data) > MAX_SCREENSHOT_BYTES:
            raise HTTPException(400, f"{f.filename or 'file'} is over 5MB.")
        if data:
            images.append((mime, data))
    if not images:
        raise HTTPException(400, "No readable screenshots were uploaded.")

    brag_text = ""
    brag = get_brag(_sv["id"])
    if brag:
        brag_text = brag_content(brag)
    cv = next((c for c in cvs if c["preferred"]), cvs[0])
    master_tex = cv_content(cv).decode("utf-8", errors="replace")

    system, user = _screenshot_questions_prompt(master_tex, brag_text)
    try:
        raw = vision_chat(system, user, images, temperature=0.3, max_tokens=2500)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    out = _parse_question_answers(raw)
    if not out:
        raise HTTPException(
            502, "Model returned no usable questions/answers. Try clearer screenshots."
        )
    return out


SCREENSHOT_SYSTEM = (
    "You read application-form questions from screenshots and answer them for a job "
    "candidate. Extract EVERY question you can see, in order. Answer each one in the "
    "candidate's voice, grounded ONLY in the candidate's resume and brag document below — "
    "never invent experience, skills, or metrics. Keep answers to 1-4 specific, honest "
    "sentences. "
    "Reply with ONLY JSON: an array of objects, each {\"question\": \"...\", \"answer\": \"...\"}. "
    "No markdown fences, no commentary."
)


def _screenshot_questions_prompt(master_tex: str, brag_text: str) -> tuple[str, str]:
    user = (
        f"RESUME:\n{master_tex}\n\n"
        + (f"BRAG DOCUMENT:\n{brag_text}\n\n" if brag_text else "")
        + "Answer the questions visible in the attached screenshots."
    )
    return SCREENSHOT_SYSTEM, user


def _parse_question_answers(raw: str) -> list[Answer]:
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:])
        if text.rstrip().endswith("```"):
            text = "\n".join(text.splitlines()[:-1])
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("questions") or data.get("answers") or []
    if not isinstance(data, list):
        return []
    rows = []
    for item in data:
        if isinstance(item, dict) and item.get("question") and item.get("answer"):
            rows.append(Answer(question=str(item["question"]), answer=str(item["answer"])))
    return _clamp_answers(rows)


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


def _clamp_links(links: list[str]) -> list[str]:
    out = []
    for link in links:
        s = link.strip()
        if s:
            out.append(s[:2048])
    return out[:50]


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


FEEDBACK_SYSTEM = (
    "You are a career advisor reviewing a candidate against a job description. "
    "Base your assessment ONLY on the candidate's resume and brag document below — "
    "never invent skills, experience, or metrics. "
    "Reply with ONLY JSON with exactly two fields: "
    "\"rating\": an integer 1-10 rating how well the candidate matches this job, and "
    "\"feedback\": a concise bullet-point list (each line starting with '- '), at most "
    "6 bullets, covering strengths that fit the job, gaps or weak spots relative to it, "
    "and one practical piece of advice for this application or interview. "
    "Be specific and honest. No preamble, no markdown fences."
)


def _feedback_prompt(job_description: str, master_tex: str, brag_text: str) -> tuple[str, str]:
    user = (
        f"JOB DESCRIPTION:\n{job_description}\n\n"
        + (f"BRAG DOCUMENT:\n{brag_text}\n\n" if brag_text else "")
        + f"RESUME:\n{master_tex}"
    )
    return FEEDBACK_SYSTEM, user


def _parse_feedback(raw: str) -> tuple[int | None, str]:
    """Parse the model's JSON into (rating 1-10, feedback text); fall back on failure."""
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:])
        if text.rstrip().endswith("```"):
            text = "\n".join(text.splitlines()[:-1])
        text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            fb = data.get("feedback")
            if isinstance(fb, str) and fb.strip():
                rating = data.get("rating")
                if isinstance(rating, str):
                    rating = rating.strip()
                try:
                    rating = int(float(rating))
                except (TypeError, ValueError):
                    rating = None
                rating = max(1, min(10, rating)) if isinstance(rating, int) else None
                return rating, fb.strip()
    except (json.JSONDecodeError, TypeError):
        pass
    return None, raw.strip()


def _feedback(job_description: str, master_tex: str, brag_text: str) -> tuple[int | None, str]:
    system, user = _feedback_prompt(job_description, master_tex, brag_text)
    max_tokens = _fit_max_tokens(system, user, floor=800)
    return _parse_feedback(chat(system, user, temperature=0.3, max_tokens=max_tokens).strip())


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
    "You are a resume editor. Tailor the provided LaTeX resume to a job description, using "
    "facts from the brag document when they strengthen the fit. "
    "NEVER invent experience, skills, or metrics that appear in neither the resume nor the "
    "brag document. "
    "Ensure that metrics are preserved"
    "Don't strip a line if you feel like its already fine and is attractive to the recruiter"
    "Keep the document structure and keep the LaTeX valid. "
    "Respond with ONLY the .tex source code — no markdown fences, no commentary."
)


def _fine_tune(master_tex: str, brag_text: str, job_description: str) -> str:
    user = (
        f"JOB DESCRIPTION:\n{job_description}\n\n"
        + (f"BRAG DOCUMENT:\n{brag_text}\n\n" if brag_text else "")
        + f"MASTER RESUME (.tex):\n{master_tex}"
        
    )
    max_tokens = _fit_max_tokens(FINE_TUNE_SYSTEM, user, floor=3000)
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


def _cover_letter(
    job_description: str,
    answers: list[Answer],
    cv_name: str,
    name: str = "",
    links: list[str] | None = None,
) -> str:
    system, user = _cover_letter_prompt(job_description, answers, cv_name, name, links or [])
    return chat(system, user, temperature=0.4, max_tokens=1500).strip()


def _cover_letter_prompt(
    job_description: str,
    answers: list[Answer],
    cv_name: str,
    name: str,
    links: list[str],
) -> tuple[str, str]:
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
    if name:
        user += f"\n\nCANDIDATE NAME: {name}"
    if links:
        user += "\n\nCANDIDATE LINKS:\n" + "\n".join(f"- {link}" for link in links)
    system = (
        "You write concise, specific cover letters (about 250 words)"
        "Short sentences, one idea per sentence, simple "
        "unambiguous vocabulary. Ground every claim in the job description and the candidate's "
        "own answers; never invent experience or numbers. "
    )
    if name:
        system += (
            f"Sign the letter with the candidate's real name ('{name}') "
            "— do not use a placeholder. "
        )
    else:
        system += "Leave the signature as '[Your Name]'. "
    if links:
        system += (
            "List the candidate's links at the bottom of the letter under a 'Links:' heading, "
            "one per line. "
        )
    system += "Output plain text only, with blank lines between paragraphs."
    return system, user


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
