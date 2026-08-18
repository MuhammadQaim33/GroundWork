# ============================================================================
# routes/generate.py — /api/generate + /api/screenshot-questions.
#
# These routes only handle HTTP: validate the request, gather the user's
# grounding material, and hand off to the logic in services/. The generation
# orchestration (the SSE streaming pipeline) lives in services/pipeline.py.
# ============================================================================

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from auth import require_service_user
from llm import active_provider, vision_chat
from schemas import Answer, GenerateRequest
from services.pipeline import generate_stream
from services.questions import parse_question_answers, screenshot_questions_prompt
from services.resume import pick_cv
from services.text import clamp, clamp_questions
from store import brag_content, cv_content, get_brag, list_cvs
from user_settings import get_links

router = APIRouter(tags=["generate"])

MAX_SCREENSHOTS = 6             # hard cap on number of images per call
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024   # 5 MB per image


@router.post("/api/generate")
async def api_generate(
    req: GenerateRequest, _sv: Annotated[dict, Depends(require_service_user)]
) -> StreamingResponse:
    """Stream each generated artifact as an SSE event the moment it's ready."""
    jd = clamp(req.job_description, 6000)   # cap the JD length (input guard)
    if not jd.strip():                        # .strip() removes spaces; empty = error
        raise HTTPException(400, "A job description is required.")
    questions = clamp_questions(req.questions)   # trim the form questions

    # The storage reads are independent (all key off the same user), so fetch
    # them concurrently: CV list, brag doc, and profile links.
    cvs_task = asyncio.create_task(asyncio.to_thread(list_cvs, _sv["id"]))
    brag_task = asyncio.create_task(asyncio.to_thread(get_brag, _sv["id"]))
    links_task = asyncio.create_task(asyncio.to_thread(get_links))

    cvs = await cvs_task
    if not cvs:
        raise HTTPException(400, "Upload at least one master CV in Settings first.")

    cv = pick_cv(cvs, jd)   # pick the master CV best suited to this JD

    # Feedback always runs, so the master CV is always needed even if the user
    # only asked for a cover letter. Decode the .tex bytes to text.
    master_tex = (await asyncio.to_thread(cv_content, cv)).decode("utf-8", errors="replace")
    # Guard: the resume job needs the model to swallow the whole CV. On Groq's
    # free tier a CV over ~18KB won't fit the token budget → explain up front.
    if "resume" in req.parts and active_provider() == "groq" and len(master_tex) > 18000:
        raise HTTPException(
            400,
            "Master CV is too large to fine-tune on the free tier (over 18KB). "
            "Split or simplify the .tex file, or add an OpenRouter key in Settings for no limits.",
        )

    # Collect the remaining reads that were already running concurrently.
    brag = await brag_task
    brag_text = brag_content(brag) if brag else ""
    links = await links_task

    # Return a StreamingResponse wrapping the async generator generate_stream.
    # The response is sent back immediately; generate_stream then yields
    # events over time. media_type "text/event-stream" is the SSE MIME type.
    return StreamingResponse(
        generate_stream(
            req,
            jd,
            questions,
            cv["file_name"],
            _sv.get("name") or "",
            links,
            brag_text,
            master_tex,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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

    system, user = screenshot_questions_prompt(master_tex, brag_text)
    try:
        # Ask the vision model. Low temperature → grounded, consistent answers.
        raw = vision_chat(system, user, images, temperature=0.3, max_tokens=2500)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    out = parse_question_answers(raw)
    if not out:
        raise HTTPException(
            502, "Model returned no usable questions/answers. Try clearer screenshots."
        )
    return out