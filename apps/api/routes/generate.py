# ============================================================================
# routes/generate.py — THE MAIN EVENT: /api/generate + /api/screenshot-questions.
#
# The generate flow:
#   1. Validate the request (JD present, a master CV exists).
#   2. Auto-pick the best master CV for this job (AI scores the candidates).
#   3. Kick off resume / cover-letter / feedback jobs CONCURRENTLY.
#   4. Stream each finished artifact back as an SSE "event" the instant it's
#      ready, so the dashboard can show things appearing one by one.
#
# SSE (Server-Sent Events) in one line: the server opens a long-lived response
# and writes plain-text lines like  event: <name>  /  data: <json>  down it.
# The browser reads them as they arrive — progress without polling.
#
# The heavy lifting (prompts, fine-tuning, parsing) lives in services/*.
# ============================================================================

from __future__ import annotations

import asyncio  # concurrency toolkit (run several jobs at once)
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from auth import require_service_user
from compile import _compile
from llm import active_provider, vision_chat
from schemas import Answer, GenerateRequest
from services.cover_letter import _cover_letter, _letter_to_tex
from services.feedback import _feedback
from services.questions import _parse_question_answers, _screenshot_questions_prompt
from services.resume import _build_resume, _pick_cv
from services.sse import _sse, _stream_error
from services.text import _clamp, _clamp_answers
from store import brag_content, cv_content, get_brag, list_cvs
from user_settings import get_links

router = APIRouter(tags=["generate"])

MAX_SCREENSHOTS = 6             # hard cap on number of images per call
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024   # 5 MB per image


@router.post("/api/generate")
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

@router.post("/api/screenshot-questions")
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