# ============================================================================
# main.py — the web API. Everything users can do from the dashboard lands here.
#
# Think of it as a RESTAURANT:
#   - The dashboard (Next.js) is the customer's table.
#   - This file is the kitchen with a menu of endpoints. Each `@app.post(...)`
#     or `@app.get(...)` decorated function is ONE dish on the menu.
#   - The browser calls a URL like POST /api/generate with some JSON; FastAPI
#     routes it to the matching function, which does the work and returns data.
#
# What the kitchen does for the user:
#   1. Sign up / log in / log out          (delegated to auth.py)
#   2. Manage master CVs + brag document   (delegated to store.py)
#   3. Save per-user settings & links      (delegated to user_settings.py)
#   4. POST /api/generate — the flagship: given a job description, produce a
#      tailored resume (PDF), a cover letter (text + optional PDF), and honest
#      feedback — all grounded in the user's real materials.
#   5. POST /api/screenshot-questions — read application-form questions off
#      uploaded screenshots and draft answers to them.
#
# The generation pipeline streams results as they're ready (SSE) and runs the
# resume / cover-letter / feedback jobs CONCURRENTLY — one slow part doesn't
# hold the others hostage, and a failing part doesn't kill the request.
# ============================================================================

# Lets us write modern type hints without evaluation headaches (see config.py).
from __future__ import annotations

import asyncio  # concurrency toolkit (run several jobs at once)
import json  # parse/serialize JSON (the data format web APIs use)
import re  # regular expressions — text pattern matching
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4  # unique IDs for naming generated files

import httpx

# FastAPI bits: Depends (dependency injection), FastAPI (the app itself),
# File/UploadFile (receiving uploaded files), Header (reading HTTP headers),
# HTTPException (returning an error to the client), Request (the raw request).
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware  # lets the dashboard domain call us
from fastapi.responses import JSONResponse, StreamingResponse  # response types
from fastapi.staticfiles import StaticFiles  # serve static files (generated PDFs)

# Pydantic BaseModel: a validation layer. Classes that extend it validate the
# incoming JSON before our code ever touches it.
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
from user_settings import (
    get_gemini_key,
    get_links,
    get_openrouter_key,
    set_gemini_key,
    set_links,
    set_openrouter_key,
)

# Create the FastAPI application object. Decorators like @app.post(...) attach
# routes to it. "title" is just the API's display name.
app = FastAPI(title="Groundwork Generator API")

# CORS = who is allowed to call this API from a browser. This opens it up to
# the local dashboard (localhost:3000) and all methods/headers. In production
# this would be locked to the real dashboard domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# Make sure the folder for generated PDFs exists, then serve it at /out so
# the dashboard can fetch files by URL (e.g. /out/custom-resume-a1b2c3d4.pdf).
OUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/out", StaticFiles(directory=OUT_DIR), name="out")


# A GLOBAL ERROR HANDLER: if any endpoint accidentally lets an LLM provider
# error (an httpx.HTTPStatusError) bubble up, this converts it into a clean,
# readable JSON error instead of an ugly server traceback.
@app.exception_handler(httpx.HTTPStatusError)
async def llm_provider_error(_request: Request, exc: httpx.HTTPStatusError):
    # 5xx provider errors = the AI service is broken → 502 (bad gateway).
    # Anything else (e.g. 400 bad request) → 400. Include a snippet of the
    # provider's message so the user has a clue what happened.
    status = 502 if exc.response.status_code >= 500 else 400
    snippet = exc.response.text[:300]
    return JSONResponse(
        status_code=status,
        content={"detail": f"LLM provider error ({exc.response.status_code}). {snippet}"},
    )


# --- Request/response models --------------------------------------------------
# These Pydantic classes define the exact SHAPE of JSON the endpoints accept.
# If the browser sends JSON that doesn't match, FastAPI returns 422 before any
# of our logic runs. Each field's type is validated: `str` must be text,
# `int` must be a number, `list[...]` must be a list of that thing.

class Answer(BaseModel):
    """One question+answer pair (for application-form questions)."""
    question: str
    answer: str


class Credentials(BaseModel):
    """Signup/login payload."""
    email: str
    password: str


class RefreshRequest(BaseModel):
    """Refresh-token payload."""
    refresh_token: str


class GenerateRequest(BaseModel):
    """The body of a /api/generate call: what the user asked for."""
    job_description: str
    answers: list[Answer] = []                       # optional answers to form questions
    cover_letter_formats: list[Literal["pdf", "text"]] = ["pdf"]   # which formats of the letter
    parts: list[Literal["resume", "cover_letter", "feedback"]] = ["resume", "cover_letter"]
    # ^ which artifacts to produce. Literal[...] means ONLY those exact values are allowed.


# --- Auth endpoints (thin wrappers around auth.py) -----------------------------

@app.post("/api/auth/signup")
def api_signup(req: Credentials):
    """Create an account. Returns tokens + service_user_id."""
    return signup(req.email, req.password)


@app.post("/api/auth/login")
def api_login(req: Credentials):
    """Log in. Returns tokens + service_user_id."""
    return login(req.email, req.password)


@app.post("/api/auth/refresh")
def api_refresh(req: RefreshRequest):
    """Exchange a refresh token for a fresh access token."""
    return refresh(req.refresh_token)


@app.post("/api/auth/logout")
def api_logout(authorization: str | None = Header(default=None)):
    """Log out: invalidate the access token from the Authorization header."""
    if authorization and authorization.startswith("Bearer "):
        logout(authorization[len("Bearer ") :].strip())
    return {"ok": True}


# --- Master CV endpoints --------------------------------------------------------
# NOTE the recurring pattern below:
#   `_sv: Annotated[dict, Depends(require_service_user)]`
# This is FastAPI dependency injection. Depends(...) says "before running this
# endpoint, call require_service_user". That call verifies the caller's token
# and returns {"id": ..., "name": ...}. `_sv["id"]` is then used to scope every
# data access to that user. `_sv` (service user) is named with a leading
# underscore to signal "internal plumbing, not a real parameter".

@app.get("/api/master-cvs")
def api_list_cvs(_sv: Annotated[dict, Depends(require_service_user)]):
    """List the caller's master CVs."""
    return list_cvs(_sv["id"])


@app.post("/api/master-cvs")
def api_upload_cv(
    _sv: Annotated[dict, Depends(require_service_user)],
    file: Annotated[UploadFile, File(...)],   # File(...) = a required file upload
):
    """Upload a new master CV. Only .tex files are allowed."""
    if not file.filename or not file.filename.lower().endswith(".tex"):
        raise HTTPException(400, "Master CVs must be .tex (LaTeX) files.")
    return upload_cv(file.filename, file.file.read(), _sv["id"])


@app.delete("/api/master-cvs/{cv_id}")
def api_delete_cv(cv_id: int, _sv: Annotated[dict, Depends(require_service_user)]):
    """Delete one master CV. `{cv_id}` in the URL is passed as an int."""
    delete_cv(cv_id, _sv["id"])
    return {"ok": True}


@app.put("/api/master-cvs/{cv_id}/preferred")
def api_cv_preferred(cv_id: int, _sv: Annotated[dict, Depends(require_service_user)]):
    """Mark a CV as the preferred default."""
    set_cv_preferred(cv_id, _sv["id"])
    return {"ok": True}


# --- Brag document endpoints ----------------------------------------------------

@app.get("/api/brag-doc")
def api_get_brag(_sv: Annotated[dict, Depends(require_service_user)]):
    """Return the caller's brag doc row (or null)."""
    return get_brag(_sv["id"])


@app.post("/api/brag-doc")
def api_upload_brag(
    _sv: Annotated[dict, Depends(require_service_user)],
    file: Annotated[UploadFile, File(...)],
):
    """Upload/replace the caller's brag document. Only .md allowed."""
    if not file.filename or not file.filename.lower().endswith(".md"):
        raise HTTPException(400, "The brag document must be a Markdown (.md) file.")
    return upload_brag(file.filename, file.file.read(), _sv["id"])


@app.delete("/api/brag-doc")
def api_delete_brag(_sv: Annotated[dict, Depends(require_service_user)]):
    """Delete the caller's brag document."""
    delete_brag(_sv["id"])
    return {"ok": True}


# --- Settings & links endpoints ---------------------------------------------------

@app.get("/api/settings")
def api_get_settings(_sv: Annotated[dict, Depends(require_service_user)]):
    """Report which LLM provider is active and which keys the user has saved.

    bool(x) turns a value into True/False, so the dashboard can show
    "Gemini key: set ✓" or "not set".
    """
    return {
        "provider": active_provider(),
        "openrouter_key_set": bool(get_openrouter_key()),
        "gemini_key_set": bool(get_gemini_key()),
    }


class SettingsUpdate(BaseModel):
    """Payload for saving user keys. Default "" = "don't change / clear"."""
    openrouter_api_key: str = ""
    gemini_api_key: str = ""


class LinksUpdate(BaseModel):
    """Payload for saving the user's profile links."""
    links: list[str] = []


@app.put("/api/settings")
def api_put_settings(req: SettingsUpdate, _sv: Annotated[dict, Depends(require_service_user)]):
    """Save the user's own LLM API keys to the DB (BYOK)."""
    set_openrouter_key(req.openrouter_api_key)
    set_gemini_key(req.gemini_api_key)
    return {"ok": True}


@app.get("/api/links")
def api_get_links(_sv: Annotated[dict, Depends(require_service_user)]):
    """Return the user's saved profile links."""
    return {"links": get_links()}


@app.put("/api/links")
def api_put_links(req: LinksUpdate, _sv: Annotated[dict, Depends(require_service_user)]):
    """Save the user's profile links (sanitized by _clamp_links)."""
    links = _clamp_links(req.links)
    set_links(links)
    return {"links": links}


# ============================================================================
# THE MAIN EVENT: /api/generate
#
# The flow:
#   1. Validate the request (JD present, a master CV exists).
#   2. Auto-pick the best master CV for this job (AI scores the candidates).
#   3. Kick off resume / cover-letter / feedback jobs CONCURRENTLY.
#   4. Stream each finished artifact back as an SSE "event" the instant it's
#      ready, so the dashboard can show things appearing one by one.
#
# SSE (Server-Sent Events) in one line: the server opens a long-lived response
# and writes plain-text lines like  event: <name>  /  data: <json>  down it.
# The browser reads them as they arrive — progress without polling.
# ============================================================================

@app.post("/api/generate")
def api_generate(
    req: GenerateRequest, _sv: Annotated[dict, Depends(require_service_user)]
) -> StreamingResponse:
    """Stream each generated artifact as an SSE event the moment it's ready."""
    jd = _clamp(req.job_description, 6000)   # cap the JD length (input guard)
    if not jd.strip():                        # .strip() removes spaces; empty = error
        raise HTTPException(400, "A job description is required.")
    answers = _clamp_answers(req.answers)     # cap each answer's length
    cvs = list_cvs(_sv["id"])
    if not cvs:
        raise HTTPException(400, "Upload at least one master CV in Settings first.")

    cv = _pick_cv(cvs, jd)   # pick the master CV best suited to this JD

    # Feedback always runs, so the master CV is always needed even if the user
    # only asked for a cover letter. Decode the .tex bytes to text.
    master_tex = cv_content(cv).decode("utf-8", errors="replace")
    # Guard: the resume job needs the model to swallow the whole CV. On Groq's
    # free tier a CV over ~18KB won't fit the token budget → explain up front.
    if "resume" in req.parts and active_provider() == "groq" and len(master_tex) > 18000:
        raise HTTPException(
            400,
            "Master CV is too large to fine-tune on the free tier (over 18KB). "
            "Split or simplify the .tex file, or add an OpenRouter key in Settings for no limits.",
        )

    # Load the brag document text too (optional grounding material).
    brag_text = ""
    brag = get_brag(_sv["id"])
    if brag:
        brag_text = brag_content(brag)

    # Return a StreamingResponse wrapping the async generator _generate_stream.
    # The response is sent back immediately; _generate_stream then yields
    # events over time. media_type "text/event-stream" is the SSE MIME type.
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
    """Format one SSE event as the wire format:
       event: <name>\n
       data: <json>\n
       \n
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_error(exc: Exception) -> str:
    """Turn any exception into a short, human-readable error string for SSE."""
    if isinstance(exc, HTTPException):      # a deliberate API error → use its message
        return str(exc.detail)
    if isinstance(exc, httpx.HTTPStatusError):   # an AI provider error
        return f"LLM provider error ({exc.response.status_code}). {exc.response.text[:300]}"
    return f"Generation failed: {exc}"      # anything else → generic message


async def _generate_stream(
    req: GenerateRequest,
    jd: str,
    answers: list[Answer],
    cv_name: str,
    name: str,
    links: list[str],
    brag_text: str,
    master_tex: str,
):
    """Emit each requested artifact as an SSE event; a failed part doesn't kill the rest.

    `async def` + `yield` = an ASYNC GENERATOR: a function you can pause and
    read from gradually. FastAPI streams it. Every `yield` pushes one SSE
    event to the browser.

    The resume, cover letter, and feedback jobs are INDEPENDENT, so they run
    CONCURRENTLY: we start all of them as "tasks" with asyncio.create_task,
    then as_completed gives us each task's result the moment it finishes.
    `await asyncio.to_thread(...)` runs the blocking (CPU/network-heavy)
    function in a worker thread so one job never blocks another.
    """
    # First event: tell the browser which master CV was auto-picked.
    yield _sse("used_master_cv", {"used_master_cv": cv_name})

    # --- The three jobs, each defined as a nested async function -------------

    async def _run_resume() -> list[tuple[str, dict]]:
        """Build the tailored resume PDF. Returns a list of (event, data) pairs."""
        try:
            resume_pdf = await asyncio.to_thread(_build_resume, master_tex, brag_text, jd)
            return [
                (
                    "resume",
                    {"name": "custom-resume.pdf", "kind": "pdf", "url": f"/out/{resume_pdf.name}"},
                )
            ]
        except Exception as exc:
            # Any failure → one "error" event for THIS part only.
            return [("error", {"part": "resume", "message": _stream_error(exc)})]

    async def _run_cover_letter() -> list[tuple[str, dict]]:
        """Write the cover letter; emit text and/or PDF events as requested."""
        try:
            letter_text = await asyncio.to_thread(
                _cover_letter, jd, answers, cv_name, name, links
            )
            events: list[tuple[str, dict]] = [("cover_letter_text", {"text": letter_text})]
            if "text" in req.cover_letter_formats:
                events.append(
                    (
                        "cover_letter_txt",
                        {"name": "cover-letter.txt", "kind": "text", "text": letter_text},
                    )
                )
            if "pdf" in req.cover_letter_formats:
                letter_pdf = await asyncio.to_thread(
                    _compile, _letter_to_tex(letter_text), "cover-letter"
                )
                events.append(
                    (
                        "cover_letter_pdf",
                        {
                            "name": "cover-letter.pdf",
                            "kind": "pdf",
                            "url": f"/out/{letter_pdf.name}",
                        },
                    )
                )
            return events
        except Exception as exc:
            return [("error", {"part": "cover_letter", "message": _stream_error(exc)})]

    async def _run_feedback() -> list[tuple[str, dict]]:
        """Score the user's fit against the JD. ALWAYS runs (it's not optional)."""
        try:
            rating, feedback_text = await asyncio.to_thread(_feedback, jd, master_tex, brag_text)
            return [("feedback", {"rating": rating, "text": feedback_text})]
        except Exception as exc:
            return [("error", {"part": "feedback", "message": _stream_error(exc)})]

    # --- Kick off the requested jobs -----------------------------------------
    tasks: list[asyncio.Task] = []
    if "resume" in req.parts:
        tasks.append(asyncio.create_task(_run_resume()))
    if "cover_letter" in req.parts:
        tasks.append(asyncio.create_task(_run_cover_letter()))
    tasks.append(asyncio.create_task(_run_feedback()))   # feedback is always included

    # as_completed: yields tasks in the order they FINISH (not start order).
    for task in asyncio.as_completed(tasks):
        for event, data in await task:   # unpack the (event, data) pairs we built above
            yield _sse(event, data)

    # Final event: the stream is complete.
    yield _sse("done", {})


# ============================================================================
# /api/screenshot-questions — read form questions off images and answer them.
#
# The user is filling out an application form with free-text questions ("Why
# this company?", "Tell us about your experience with X"). They screenshot
# the questions, upload them here, and the VISION model reads the images and
# drafts answers grounded in their resume + brag doc.
#
# Privacy note: the images are read into memory, base64-encoded into the API
# request, and NEVER written to disk or the database.
# ============================================================================

MAX_SCREENSHOTS = 6             # hard cap on number of images per call
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024   # 5 MB per image


@app.post("/api/screenshot-questions")
def api_screenshot_questions(
    files: Annotated[list[UploadFile], File(...)],   # MANY file uploads
    _sv: Annotated[dict, Depends(require_service_user)],
) -> list[Answer]:
    """Read questions off uploaded screenshots and answer them from resume + brag doc."""
    if not files:
        raise HTTPException(400, "Upload at least one screenshot.")
    if len(files) > MAX_SCREENSHOTS:
        raise HTTPException(400, f"At most {MAX_SCREENSHOTS} screenshots per request.")
    cvs = list_cvs(_sv["id"])
    if not cvs:
        raise HTTPException(400, "Upload at least one master CV in Settings first.")

    # Validate each uploaded file: must be an image, under 5MB, with bytes.
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

    # Gather the grounding material: brag doc (optional) + preferred master CV.
    brag_text = ""
    brag = get_brag(_sv["id"])
    if brag:
        brag_text = brag_content(brag)
    cv = next((c for c in cvs if c["preferred"]), cvs[0])  # preferred CV, else first
    master_tex = cv_content(cv).decode("utf-8", errors="replace")

    system, user = _screenshot_questions_prompt(master_tex, brag_text)
    try:
        # Ask the vision model. Low temperature → grounded, consistent answers.
        raw = vision_chat(system, user, images, temperature=0.3, max_tokens=2500)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    out = _parse_question_answers(raw)
    if not out:
        raise HTTPException(
            502, "Model returned no usable questions/answers. Try clearer screenshots."
        )
    return out


# The system prompt for the screenshot-reading model. Stored as a constant so
# it's easy to review/tune. Note the grounding rules — never invent anything.
SCREENSHOT_SYSTEM = (
    "You read application-form questions from screenshots and answer them for a job "
    "candidate. Extract EVERY question you can see, in order. Answer each one in the "
    "candidate's voice, grounded ONLY in the candidate's resume and brag document below — "
    "never invent experience, skills, or metrics. Keep answers to 1-4 specific, honest "
    "sentences. "
    'Reply with ONLY JSON: an array of objects, each {"question": "...", "answer": "..."}. '
    "No markdown fences, no commentary."
)


def _screenshot_questions_prompt(master_tex: str, brag_text: str) -> tuple[str, str]:
    """Build the (system, user) prompt pair for the screenshot reader."""
    user = (
        f"RESUME:\n{master_tex}\n\n"
        + (f"BRAG DOCUMENT:\n{brag_text}\n\n" if brag_text else "")
        + "Answer the questions visible in the attached screenshots."
    )
    return SCREENSHOT_SYSTEM, user


def _parse_question_answers(raw: str) -> list[Answer]:
    """Parse the model's raw text into a list of Answer objects. Returns [] on garbage.

    The model is asked for strict JSON, but models are chatty — they may wrap
    it in ``` fences or add prose. This untangles that:
    1. Strip ``` code fences if present.
    2. json.loads the result.
    3. Handle a bare array OR a {"questions": [...]} object.
    4. Drop any items missing a question or answer, then clamp lengths.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:])      # drop the opening ``` line
        if text.rstrip().endswith("```"):
            text = "\n".join(text.splitlines()[:-1])  # drop the closing ``` line
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []   # not JSON at all → no usable answers
    if isinstance(data, dict):      # {"questions": [...]} wrapper?
        data = data.get("questions") or data.get("answers") or []
    if not isinstance(data, list):
        return []
    rows = []
    for item in data:
        if isinstance(item, dict) and item.get("question") and item.get("answer"):
            rows.append(Answer(question=str(item["question"]), answer=str(item["answer"])))
    return _clamp_answers(rows)     # enforce length caps


# ============================================================================
# Shared helpers (the rest of the file)
# ============================================================================

def _out_name(base: str) -> str:
    """Give generated files unique names: base-<8 random hex chars>."""
    return f"{base}-{uuid4().hex[:8]}"


def _compile(tex: str, base: str) -> Path:
    """Compile LaTeX to PDF; surface tectonic failures as a readable 502, not a traceback."""
    try:
        return compile_tex(tex, _out_name(base))
    except RuntimeError as exc:
        raise HTTPException(502, f"LaTeX compile failed. {exc}") from exc


# --- Input guards: everything the user sends gets length-capped -----------------
# Trust-boundary rule: never let a user (or a hostile client) send us a
# megabyte of text. These clamp helpers keep every input within sane limits.

def _clamp(text: str, max_chars: int) -> str:
    """Cut a string down to at most max_chars."""
    return text[:max_chars]


def _clamp_answers(answers: list[Answer]) -> list[Answer]:
    """Trim answers: drop blank ones, cap question/answer length, cap count at 20."""
    out = []
    for a in answers:
        q = a.question.strip()
        ans = a.answer.strip()
        if q and ans:
            out.append(Answer(question=q[:500], answer=ans[:2000]))
    return out[:20]


def _clamp_links(links: list[str]) -> list[str]:
    """Trim links: drop blanks, cap each at 2048 chars, cap count at 50."""
    out = []
    for link in links:
        s = link.strip()
        if s:
            out.append(s[:2048])
    return out[:50]


# ============================================================================
# Token-budget math for the Groq free tier.
#
# Groq's free llama-3.3-70b model is capped at 12,000 "tokens per minute"
# (roughly word-parts). A request counts its INPUT length + the max_tokens we
# ask for as OUTPUT against that rolling budget. So we compute how many output
# tokens we can afford given the input size, and fail loudly if the input
# alone is already too big. This guard only applies to Groq — BYOK OpenRouter
# and local Ollama have no such ceiling.
# ============================================================================

TPM_BUDGET = 11000          # leave a little headroom under the 12,000 cap
MAX_OUT_TOKENS = 5000       # biggest output we'll ever request


def _fit_max_tokens(system: str, user: str, floor: int = 800) -> int:
    """How many output tokens may we request for this prompt?

    Rough input estimate: English is ~4 chars per token, so len(text)//4.
    * Non-Groq providers: no TPM ceiling — but OpenRouter RESERVES max_tokens
      worth of credits per call, so request only the floor (what the task
      needs), not the 5000 cap.
    * Groq: fit output within the budget left after the input, never below
      `floor`; if input alone busts the budget, raise a clear 400 error.
    """
    est_input = (len(system) + len(user)) // 4
    if active_provider() != "groq":
        return floor
    max_out = max(floor, min(MAX_OUT_TOKENS, TPM_BUDGET - est_input))
    if est_input + max_out > TPM_BUDGET + 500:   # +500 slack for estimate error
        raise HTTPException(
            400,
            "Input is too large for the model's free-tier token budget. "
            "Shorten the job description or simplify the master CV "
            "(or add an OpenRouter key in Settings for no limits).",
        )
    return max_out


# ============================================================================
# FEEDBACK job — rate the candidate's fit against the job description.
# ============================================================================

FEEDBACK_SYSTEM = (
    "You are a career advisor reviewing a candidate against a job description. "
    "Base your assessment ONLY on the candidate's resume and brag document below — "
    "never invent skills, experience, or metrics. "
    "Reply with ONLY JSON with exactly two fields: "
    '"rating": an integer 1-10 rating how well the candidate matches this job, and '
    "\"feedback\": a concise bullet-point list (each line starting with '- '), at most "
    "6 bullets, covering strengths that fit the job, gaps or weak spots relative to it, "
    "and one practical piece of advice for this application or interview. "
    "Be specific and honest. No preamble, no markdown fences."
    "Be pragmatic and realistic with the rating."
)


def _feedback_prompt(job_description: str, master_tex: str, brag_text: str) -> tuple[str, str]:
    """Build the (system, user) prompt for the feedback job."""
    user = (
        f"JOB DESCRIPTION:\n{job_description}\n\n"
        + (f"BRAG DOCUMENT:\n{brag_text}\n\n" if brag_text else "")
        + f"RESUME:\n{master_tex}"
    )
    return FEEDBACK_SYSTEM, user


def _strip_json_fence(raw: str) -> str:
    """Remove ```json ... ``` fences if the model wrapped its JSON in them."""
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:])
        if text.rstrip().endswith("```"):
            text = "\n".join(text.splitlines()[:-1])
    return text.strip()


def _first_json_object(text: str) -> dict | None:
    """Pull the first {...} block out of the model output, ignoring prose around it."""
    start, end = text.find("{"), text.rfind("}")   # first { to last }
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _clamp_rating(rating: object) -> int | None:
    """Turn whatever the model returned into a clean 1-10 int (None if unusable)."""
    if isinstance(rating, str):
        rating = rating.strip()
    try:
        rating = int(float(rating))   # handles "8", 8, "8.0", 8.0 ...
    except (TypeError, ValueError):
        return None
    return max(1, min(10, rating))   # clamp into 1..10


def _parse_feedback(raw: str) -> tuple[int | None, str]:
    """Parse the model's JSON into (rating 1-10, feedback text); fall back on failure."""
    text = _strip_json_fence(raw)
    data = _first_json_object(text)
    if data is not None:
        fb = data.get("feedback")
        if isinstance(fb, str) and fb.strip():
            return _clamp_rating(data.get("rating")), fb.strip()
        if isinstance(fb, list):   # feedback as a list of bullet strings
            lines = [str(x).strip() for x in fb if str(x).strip()]
            if lines:
                return _clamp_rating(data.get("rating")), "\n".join(lines)
    # Parsing failed → salvage a rating from the raw text, else return text as-is.
    return _clamp_rating(_rating_in_text(text)), text


def _rating_in_text(text: str) -> object:
    """Regex-scrape a "rating": <number> out of raw text (fallback parsing)."""
    m = re.search(r'"rating"\s*:\s*"?(\d{1,2})"?', text)
    return m.group(1) if m else None


def _feedback(job_description: str, master_tex: str, brag_text: str) -> tuple[int | None, str]:
    """Run the feedback job end-to-end: prompt → model call → parse. Returns (rating, text)."""
    system, user = _feedback_prompt(job_description, master_tex, brag_text)
    max_tokens = _fit_max_tokens(system, user, floor=800)
    return _parse_feedback(chat(system, user, temperature=0.3, max_tokens=max_tokens).strip())


# ============================================================================
# Master-CV auto-picking — which CV is the best starting point for this JD?
# ============================================================================

def _pick_cv(cvs: list[dict], job_description: str) -> dict:
    """Auto-pick the best master CV for the JD. LLM scores candidates; preferred breaks ties."""
    if len(cvs) == 1:
        return cvs[0]   # only one option — no need to ask the model
    # List the candidates for the model, flagging the user's preferred one.
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
            temperature=0.0,    # deterministic pick
            max_tokens=200,
        ).strip()
        # Match the model's chosen filename against our real list (case-insensitive).
        for c in cvs:
            if c["file_name"].lower() in choice.lower():
                return c
    except Exception:
        pass  # model failed → fall through to the safe default below
    # Fallback: preferred CV, else the first one.
    return next((c for c in cvs if c["preferred"]), cvs[0])


# ============================================================================
# RESUME job — the "fine-tune" (per-job tailoring) of the master CV.
#
# The master CV is a LaTeX .tex file. We ask the model to make MINIMAL,
# keyword-level edits so it matches the JD's terminology — surfacing keywords
# already present, honest synonym swaps only, NEVER invented facts. The model
# replies with edited .tex, which we compile to PDF. Since LLM-produced LaTeX
# is unreliable, a failed compile earns ONE retry with the error fed back as a
# hint, then we fail loudly.
# ============================================================================

FINE_TUNE_SYSTEM = (
    "You are a resume editor. Your only goal: maximize the chance this resume gets an "
    "interview call for the job description. "
    "KEEP the document structure and almost all existing content intact — keep every section, "
    "bullet, and metric exactly as written; never delete, condense, summarize, or rewrite a line. "
    "Make only minimal keyword-level edits to better match the job description: "
    "surface relevant keywords that are already in the resume (matching the job's terminology), "
    "and swap a generic phrase for the job's keyword when it is an honest fit (e.g. "
    "'built services' -> 'designed REST APIs'). You may add a skill ONLY if it appears in the "
    "brag document. "
    "NEVER invent experience, skills, or metrics that appear in neither the resume nor the "
    "brag document. Every number must appear EXACTLY as written in the source. "
    "Escape special characters in text (use \\& not &, \\% not %, \\_ not _, \\# not #). "
    "Keep the LaTeX valid. "
    "Respond with ONLY the .tex source code — no markdown fences, no commentary."
)


def _extract_latex_document(text: str) -> str:
    """Cut any prose the model added before \\documentclass or after \\end{document}."""
    m = re.search(r"\\documentclass", text, re.IGNORECASE)
    if not m:
        return text   # no document marker → return as-is (caller handles it)
    body = text[m.start() :]                      # everything from \\documentclass on
    end = re.search(r"\\end\{document\}", body, re.IGNORECASE)
    if end:
        body = body[: end.end()]                  # stop right after \\end{document}
    return body


def _repair_missing_preamble(model_output: str, master_tex: str) -> str:
    """If the model dropped the preamble (no \\documentclass), splice the master's back in.

    The fine-tune prompt asks for keyword-level edits, so a model occasionally
    returns just the body it changed. The master preamble is the one grounded
    preamble we have — reuse it (its commands like \\resumeItem define the
    body anyway). Returns the model output unchanged if it already has a
    documentclass.
    """
    if "documentclass" in model_output.lower():
        return model_output
    # Find where the master document body starts, to cut the preamble off it.
    master_begin = re.search(r"\\begin\{document\}", master_tex, re.IGNORECASE)
    if not master_begin:
        return model_output
    # The model output may itself contain a body marker; take from there (or all of it).
    body_begin = re.search(r"\\begin\{document\}", model_output, re.IGNORECASE)
    body = model_output[body_begin.start() :] if body_begin else model_output
    repaired = master_tex[: master_begin.end()] + body   # master preamble + model body
    # If the spliced result lacks a closing \\end{document}, borrow the master's.
    if "\\end{document}" not in repaired.lower():
        master_end = re.search(r"\\end\{document\}", master_tex, re.IGNORECASE)
        if master_end:
            repaired += master_tex[master_end.start() :]
    return repaired


def _fine_tune(
    master_tex: str,
    brag_text: str,
    job_description: str,
    error_hint: str = "",
) -> str:
    """Ask the model to keyword-tailor the master CV; return the edited .tex.

    If error_hint is non-empty (a previous compile failed), it's appended so
    the model gets a chance to fix the exact LaTeX error.
    """
    user = (
        f"JOB DESCRIPTION:\n{job_description}\n\n"
        + (f"BRAG DOCUMENT:\n{brag_text}\n\n" if brag_text else "")
        + f"MASTER RESUME (.tex):\n{master_tex}"
    )
    if error_hint:
        user += (
            "\n\nThe previous compile attempt failed with:\n"
            f"{error_hint[:1200]}\n\n"
            "Fix this LaTeX error. Output the complete corrected .tex source."
        )
    max_tokens = _fit_max_tokens(FINE_TUNE_SYSTEM, user, floor=3000)
    edited = _clean_model_latex(
        chat(FINE_TUNE_SYSTEM, user, temperature=0.3, max_tokens=max_tokens).strip()
    )
    # ponytail: LLM LaTeX may not compile — splice a dropped preamble, then fail loud.
    if "documentclass" not in edited.lower():
        edited = _repair_missing_preamble(edited, master_tex)
        if "documentclass" not in edited.lower():
            raise HTTPException(502, "Model produced invalid LaTeX (no documentclass). Try again.")
    return edited


def _clean_model_latex(text: str) -> str:
    """Clean the model's output: strip code fences, then any prose around the document."""
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:])
        if text.rstrip().endswith("```"):
            text = "\n".join(text.splitlines()[:-1])
    return _extract_latex_document(text.strip())


def _build_resume(master_tex: str, brag_text: str, job_description: str) -> Path:
    """Fine-tune + compile the resume; regenerate once if the LLM's LaTeX fails to compile."""
    error_hint = ""
    last_error: Exception | None = None
    for _ in range(2):   # at most 2 attempts: first try, then one repair try
        edited = _fine_tune(master_tex, brag_text, job_description, error_hint)
        try:
            return _compile(edited, "custom-resume")
        except Exception as exc:
            last_error = exc
            error_hint = str(exc)   # feed the error back so the next try can fix it
    raise last_error if last_error else RuntimeError("resume generation failed")


# ============================================================================
# COVER LETTER job
# ============================================================================

def _cover_letter(
    job_description: str,
    answers: list[Answer],
    cv_name: str,
    name: str = "",
    links: list[str] | None = None,
) -> str:
    """Write the cover letter: prompt → model call → return the letter text."""
    system, user = _cover_letter_prompt(job_description, answers, cv_name, name, links or [])
    return chat(system, user, temperature=0.4, max_tokens=1500).strip()


def _cover_letter_prompt(
    job_description: str,
    answers: list[Answer],
    cv_name: str,
    name: str,
    links: list[str],
) -> tuple[str, str]:
    """Build the (system, user) prompt for the cover-letter writer.

    The system prompt is built conditionally: the signature uses the real name
    if provided, else a placeholder; links are listed only if the user has any.
    """
    # Answers to application-form questions, formatted Q:/A: per line.
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
        "Optimize for recruiter attractiveness and recruiter ease to read"
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


# ============================================================================
# LaTeX escaping — making plain text safe to embed in a .tex document.
#
# In LaTeX, characters like & % _ # $ ~ ^ { } are RESERVED (they mean things:
# & aligns a table, % starts a comment, _ makes a subscript). If a cover
# letter contains "50%", writing it raw would break the document. So we escape
# each reserved char into its safe LaTeX form. This is exactly like escaping
# HTML in a web page.
# ============================================================================

_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",   # raw backslash
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
    """Replace every reserved LaTeX character in s with its escaped form."""
    return re.sub(r"[\\{}%$&#_~^]", lambda m: _LATEX_SPECIALS[m.group(0)], s)


def _letter_to_tex(letter_text: str) -> str:
    """Wrap a plain-text cover letter into a minimal compilable LaTeX document.

    Splits the letter into paragraphs (separated by blank lines), escapes each
    paragraph, and joins them with \\par\\medskip (a paragraph break with some
    vertical space). Then wraps everything in a tiny article template.
    """
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