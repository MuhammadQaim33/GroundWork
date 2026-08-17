# ============================================================================
# services/pipeline.py — the generation pipeline: run the resume / cover-letter
# / feedback jobs CONCURRENTLY and emit each finished artifact as an SSE event.
#
# This is ORCHESTRATION, not HTTP: the only transport it touches is the SSE
# wire format (services/sse.py), which the web layer and the future Coach
# (mock interviews) both reuse. `_generate_stream` is an ASYNC GENERATOR —
# a function you can pause and read from gradually; FastAPI streams it, and a
# failed part never kills the others.
# ============================================================================

from __future__ import annotations

import asyncio  # concurrency toolkit (run several jobs at once)

from compile import _compile
from schemas import Answer, GenerateRequest
from services.cover_letter import _cover_letter, _letter_to_tex
from services.feedback import _feedback
from services.resume import _build_resume
from services.sse import _sse, _stream_error


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