# ============================================================================
# test_main.py â€” automated checks for the generation pipeline in main.py.
#
# These tests cover the tricky, pure-logic pieces:
#   * input clamping (length caps on JD, answers, links)
#   * prompt builders (feedback, cover letter, screenshot questions)
#   * parsing the model's messy output into clean structures
#     (feedback JSON, question/answer JSON, LaTeX documents)
#   * LaTeX repair (dropped preamble â†’ splice master's back in)
#   * the SSE streaming pipeline â€” events emitted, ordering, and that a failed
#     part doesn't kill the others
#
# The tests run WITHOUT the real LLM or real compilation: the functions that
# touch the network or the filesystem are monkeypatched (swapped for fakes).
# ============================================================================

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # import path to apps/api/

from fastapi import HTTPException  # noqa: E402

from llm import _fit_max_tokens  # noqa: E402
from schemas import Answer, GenerateRequest  # noqa: E402
from services.cover_letter import _cover_letter_prompt  # noqa: E402
from services.feedback import _feedback_prompt, _parse_feedback  # noqa: E402
from services.pipeline import _generate_stream  # noqa: E402
from services.questions import (  # noqa: E402
    _parse_question_answers,
    _screenshot_questions_prompt,
)
from services.resume import (  # noqa: E402
    FINE_TUNE_SYSTEM,
    _build_resume,
    _clean_model_latex,
    _extract_latex_document,
    _fine_tune,
    _repair_missing_preamble,
)
from services.text import _clamp, _clamp_answers, _clamp_links  # noqa: E402

# --- Input-guard tests -----------------------------------------------------------

def test_clamp_limits_length() -> None:
    """_clamp must cut strings down to max_chars and leave short ones alone."""
    assert len(_clamp("x" * 5000, 100)) == 100
    assert _clamp("short", 100) == "short"


def test_clamp_answers_filters_blanks_and_caps() -> None:
    """Blank answers are dropped; long answers are cut to 2000 chars."""
    out = _clamp_answers(
        [
            Answer(question="   ", answer="ignored"),   # blank question â†’ dropped
            Answer(question="q", answer="a" * 5000),    # too-long answer â†’ trimmed
            Answer(question="q2", answer="b"),
        ]
    )
    assert len(out) == 2
    assert out[0].answer == "a" * 2000
    assert out[1].answer == "b"


def test_clamp_answers_limits_count() -> None:
    """More than 20 answers â†’ only the first 20 are kept."""
    many = [Answer(question=f"q{i}", answer="a") for i in range(50)]
    assert len(_clamp_answers(many)) == 20


def test_clamp_links_filters_blanks_caps_count_and_length() -> None:
    """Links are trimmed of spaces, blank entries dropped, length â‰¤ 2048, â‰¤ 50 total."""
    assert _clamp_links(["  https://a.example  ", "", "   "]) == ["https://a.example"]
    assert len(_clamp_links(["x" * 5000])) == 1
    assert len(_clamp_links(["x" * 5000])[0]) == 2048
    assert len(_clamp_links([f"l{i}" for i in range(80)])) == 50


# --- Cover-letter prompt tests ----------------------------------------------------

def test_cover_letter_prompt_includes_name_and_links() -> None:
    """When the user has a name and links, the prompt must carry both into the
    system (instructions) and user (context) parts."""
    system, user = _cover_letter_prompt(
        "Job desc",
        [Answer(question="q", answer="a")],
        "cv.tex",
        "Jane Doe",
        ["https://github.com/jane", "https://linkedin.com/in/jane"],
    )
    assert "Jane Doe" in system
    assert "Jane Doe" in user
    assert "github.com/jane" in user and "linkedin.com/in/jane" in user
    assert "Links:" in system
    assert "ASD-STE100" in system   # the "simple unambiguous vocabulary" instruction


def test_cover_letter_prompt_without_name_or_links_keeps_placeholder() -> None:
    """No name â†’ the signature stays '[Your Name]'; no links â†’ no Links section."""
    system, _ = _cover_letter_prompt("Job desc", [], "cv.tex", "", [])
    assert "[Your Name]" in system
    assert "CANDIDATE LINKS" not in system


# --- LaTeX cleaning tests -----------------------------------------------------------

def test_extract_latex_document_drops_prose_and_trailing_commentary() -> None:
    """Models often wrap the .tex in human prose. Extraction must keep ONLY
    the document, from \\documentclass to \\end{document}."""
    raw = (
        "Here is the modified LaTeX resume tailored to the job description:\n"
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\noindent Hi\n"
        "\\end{document}\n"
        "Hope this helps!"
    )
    out = _extract_latex_document(raw)
    assert out.startswith("\\documentclass{article}")
    assert out.endswith("\\end{document}")
    assert "Here is the modified" not in out
    assert "Hope this helps" not in out
    assert "\\begin{document}" in out


def test_extract_latex_document_returns_input_without_documentclass() -> None:
    """No \\documentclass marker â†’ return the text untouched (caller decides what to do)."""
    assert _extract_latex_document("just prose") == "just prose"


def test_clean_model_latex_strips_fences_and_prose() -> None:
    """The full cleanup: drop ``` fences AND any prose around the document."""
    out = _clean_model_latex(
        "```latex\nHere is my resume:\n\\documentclass{article}\n"
        "\\begin{document}x\\end{document}\n```"
    )
    assert out.startswith("\\documentclass{article}")
    assert out.endswith("\\end{document}")
    assert "```" not in out
    assert "Here is my resume" not in out


def test_fine_tune_prompt_keyword_only_edits() -> None:
    """The resume-editor system prompt must contain the grounding promises
    that make this a "keyword-only, never-fabricate" edit."""
    lower = FINE_TUNE_SYSTEM.lower()
    assert "never delete, condense, summarize, or rewrite a line" in lower
    assert "exactly as written" in lower
    assert "keyword-level edits" in lower
    assert "interview call" in lower
    assert "never invent" in lower
    assert "escape special characters" in lower


# --- Token-budget & retry tests ------------------------------------------------------

def test_fit_max_tokens_non_groq_returns_floor_not_ceiling(monkeypatch) -> None:
    """Non-Groq providers have no TPM ceiling, so we ask for only the floor â€”
    OpenRouter reserves max_tokens of credits per call."""
    monkeypatch.setattr("llm.active_provider", lambda: "openrouter")
    assert _fit_max_tokens("system", "user", floor=800) == 800
    assert _fit_max_tokens("system", "user", floor=3000) == 3000


def test_fine_tune_appends_compile_error_hint(monkeypatch) -> None:
    """When a previous compile failed, the error must be fed back into the
    prompt so the retry can fix the exact LaTeX error."""
    captured: dict[str, str] = {}

    def fake_chat(system, user, temperature, max_tokens):
        captured["user"] = user   # capture what the fake LLM "saw"
        return "\\documentclass{article}\n\\begin{document}x\n\\end{document}"

    monkeypatch.setattr("services.resume.chat", fake_chat)
    monkeypatch.setattr("services.resume._fit_max_tokens", lambda *a, **k: 3000)
    _fine_tune("master", "brag", "JD", error_hint="Forbidden control sequence")
    assert "Forbidden control sequence" in captured["user"]
    assert "previous compile attempt failed" in captured["user"].lower()
    assert "Fix this LaTeX error" in captured["user"]


def test_repair_missing_preamble_splices_master_when_body_only() -> None:
    """If the model returns only a body (no \\documentclass), the master's
    preamble must be spliced in front, keeping the model's body."""
    master = (
        "\\documentclass{article}\n"
        "\\newcommand{\\resumeItem}[1]{#1}\n"
        "\\begin{document}\n\\section{Master}\n\\end{document}"
    )
    body_only = "\\section{Edited}\n\\resumeItem{new bullet}"
    out = _repair_missing_preamble(body_only, master)
    assert out.startswith("\\documentclass{article}")
    assert "\\resumeItem" in out           # the master's macro definition survived
    assert "\\section{Edited}" in out      # the model's body is kept
    assert "\\section{Master}" not in out  # the master's original body is NOT kept


def test_repair_missing_preamble_passthrough_when_documentclass_present() -> None:
    """If the output already has a \\documentclass, leave it untouched."""
    master = "\\documentclass{article}\n\\begin{document}x\\end{document}"
    good = "\\documentclass{article}\n\\begin{document}y\\end{document}"
    assert _repair_missing_preamble(good, master) == good


def test_fine_tune_splices_master_preamble_when_documentclass_missing(monkeypatch) -> None:
    """End-to-end: model returns pure prose â†’ fine-tune still produces a
    compilable-looking document by splicing the master preamble."""
    def fake_chat(system, user, temperature, max_tokens):
        return "just prose, no latex here"

    monkeypatch.setattr("services.resume.chat", fake_chat)
    monkeypatch.setattr("services.resume._fit_max_tokens", lambda *a, **k: 3000)
    master = (
        "\\documentclass{article}\n"
        "\\newcommand{\\resumeItem}[1]{#1}\n"
        "\\begin{document}\n\\section{Experience}\n\\end{document}"
    )
    out = _fine_tune(master, "brag", "JD")
    assert out.startswith("\\documentclass{article}")
    assert "\\resumeItem" in out
    assert "\\begin{document}" in out
    assert out.endswith("\\end{document}")
    assert "just prose" in out


def test_build_resume_regenerates_once_on_compile_failure(monkeypatch) -> None:
    """If the first compile fails, _build_resume must retry ONCE with a fresh
    fine-tune, then return the PDF from the successful second attempt."""
    calls = {"fine_tune": 0, "compile": 0}

    def fake_fine_tune(master, brag, jd, error_hint=""):
        calls["fine_tune"] += 1
        return f"tex-{calls['fine_tune']}"

    def fake_compile(tex, base):
        calls["compile"] += 1
        if calls["compile"] == 1:
            raise HTTPException(502, "LaTeX compile failed. broken")   # first try fails
        return Path("custom-resume.pdf")                                # second try works

    monkeypatch.setattr("services.resume._fine_tune", fake_fine_tune)
    monkeypatch.setattr("services.resume._compile", fake_compile)
    pdf = _build_resume("master", "brag", "JD")
    assert pdf == Path("custom-resume.pdf")
    assert calls["fine_tune"] == 2   # exactly two attempts, no more
    assert calls["compile"] == 2


# --- Feedback tests -------------------------------------------------------------------

def test_feedback_prompt_grounded_in_resume_and_brag_and_bullets() -> None:
    """The feedback prompt must include the JD, resume, and brag doc, and its
    system instructions must demand honesty + bullet output."""
    system, user = _feedback_prompt(
        "Job description", "resume.tex content", "brag document content"
    )
    assert "resume.tex content" in user
    assert "brag document content" in user
    assert "JOB DESCRIPTION" in user
    lower = system.lower()
    assert "only" in lower and "never invent" in lower
    assert "- " in system
    assert "rating" in lower


def test_parse_feedback_returns_rating_and_text() -> None:
    """The model's JSON (possibly wrapped in fences or prose) must parse into
    a (rating, text) tuple, with ratings clamped to 1-10."""
    # Plain JSON
    rating, text = _parse_feedback('{"rating": 8, "feedback": "- strong fit\\n- one gap"}')
    assert rating == 8
    assert text == "- strong fit\n- one gap"

    # Wrapped in ```json fences, rating as a string
    rating, text = _parse_feedback('```json\n{"rating": "10", "feedback": "- great"}\n```')
    assert rating == 10
    assert text == "- great"

    # Prose before the JSON
    rating, text = _parse_feedback(
        'Here is the feedback:\n{"rating": 9, "feedback": "- matches well"}'
    )
    assert rating == 9
    assert text == "- matches well"

    # feedback as a list of bullet strings
    rating, text = _parse_feedback('{"rating": 6, "feedback": ["- a", "- b"]}')
    assert rating == 6
    assert text == "- a\n- b"

    # Out-of-range ratings are clamped
    rating, _ = _parse_feedback('{"rating": 99, "feedback": "- way too high"}')
    assert rating == 10
    rating, _ = _parse_feedback('{"rating": 0, "feedback": "- way too low"}')
    assert rating == 1

    # Not JSON at all â†’ rating None, text passed through
    rating, text = _parse_feedback("not json")
    assert rating is None
    assert text == "not json"


# --- SSE stream helper + tests ---------------------------------------------------------

def _parse_sse(stream: str) -> list[tuple[str, dict]]:
    """Parse a raw SSE stream into [(event_name, data_dict), ...].

    SSE wire format is blocks separated by blank lines:
        event: resume
        data: {"name": ...}
        <blank line>
    """
    events = []
    for block in stream.split("\n\n"):
        event, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if event and data is not None:
            events.append((event, data))
    return events


async def _collect_sse(ag) -> str:
    """Drain an async generator into one big string (consumes the whole stream)."""
    return "".join([chunk async for chunk in ag])


def _sse_by_event(events: list[tuple[str, dict]]) -> dict[str, list[dict]]:
    """Group events by name: {"resume": [data1], "feedback": [data1], ...}."""
    by: dict[str, list[dict]] = {}
    for event, data in events:
        by.setdefault(event, []).append(data)
    return by


async def test_generate_stream_emits_each_expected_artifact(monkeypatch) -> None:
    """A full request (resume + cover letter in pdf and text + feedback) must
    emit exactly the expected SSE events, with the right payloads."""
    # Fake every heavy operation so no LLM or compile actually runs.
    monkeypatch.setattr("services.resume._fine_tune", lambda *a, **k: "\\documentclass{article}")
    monkeypatch.setattr("services.resume._compile", lambda *a, **k: Path("custom-resume.pdf"))
    monkeypatch.setattr("services.pipeline._compile", lambda *a, **k: Path("cover-letter.pdf"))
    monkeypatch.setattr("services.pipeline._cover_letter", lambda *a, **k: "Dear team,")
    monkeypatch.setattr("services.pipeline._feedback", lambda *a, **k: (8, "- strong fit"))
    req = GenerateRequest(
        job_description="JD",
        cover_letter_formats=["pdf", "text"],
        parts=["resume", "cover_letter"],
    )
    stream = _generate_stream(req, "JD", [], "cv.tex", "Jane", [], "brag", "tex")
    events = _parse_sse(await _collect_sse(stream))
    by = _sse_by_event(events)
    assert set(by) == {   # exactly these events, no more no fewer
        "used_master_cv",
        "resume",
        "cover_letter_text",
        "cover_letter_txt",
        "cover_letter_pdf",
        "feedback",
        "done",
    }
    assert by["used_master_cv"][0] == {"used_master_cv": "cv.tex"}
    assert by["cover_letter_txt"][0]["kind"] == "text"
    assert "Dear team," in by["cover_letter_txt"][0]["text"]
    assert by["feedback"][0] == {"rating": 8, "text": "- strong fit"}


async def test_generate_stream_always_emits_feedback_even_when_not_requested(monkeypatch) -> None:
    """Feedback is non-optional â€” even if the user only asked for a cover
    letter, the feedback event must still appear."""
    monkeypatch.setattr("services.pipeline._cover_letter", lambda *a, **k: "Dear team,")
    monkeypatch.setattr("services.pipeline._feedback", lambda *a, **k: (6, "- ok"))
    req = GenerateRequest(
        job_description="JD", cover_letter_formats=["text"], parts=["cover_letter"]
    )
    stream = _generate_stream(req, "JD", [], "cv.tex", "", [], "", "")
    events = _parse_sse(await _collect_sse(stream))
    assert set(_sse_by_event(events)) == {
        "used_master_cv",
        "cover_letter_text",
        "cover_letter_txt",
        "feedback",          # â† present despite not being requested
        "done",
    }


async def test_generate_stream_partial_failure_isolates_the_part(monkeypatch) -> None:
    """If the resume job explodes, its error must be an 'error' event and the
    OTHER parts (cover letter, feedback) must still complete normally."""
    def boom(*a, **k):
        raise RuntimeError("model down")

    monkeypatch.setattr("services.resume._fine_tune", boom)   # resume generation dies
    monkeypatch.setattr("services.resume._compile", lambda *a, **k: Path("cover-letter.pdf"))
    monkeypatch.setattr("services.pipeline._cover_letter", lambda *a, **k: "Dear team,")
    monkeypatch.setattr("services.pipeline._feedback", lambda *a, **k: (7, "- ok"))
    req = GenerateRequest(
        job_description="JD", cover_letter_formats=["text"], parts=["resume", "cover_letter"]
    )
    stream = _generate_stream(req, "JD", [], "cv.tex", "", [], "", "")
    events = _parse_sse(await _collect_sse(stream))
    by = _sse_by_event(events)
    assert set(by) == {
        "used_master_cv",
        "error",                    # the resume failure event
        "cover_letter_text",        # ... but cover letter still produced
        "cover_letter_txt",
        "feedback",                 # ... and feedback still produced
        "done",
    }
    assert by["error"][0]["part"] == "resume"       # which part failed
    assert "model down" in by["error"][0]["message"]


# --- Screenshot-questions tests --------------------------------------------------------

def test_screenshot_questions_prompt_grounded_in_resume_and_brag() -> None:
    """The screenshot-reading prompt must include resume + brag as grounding,
    and demand honesty in its system instructions."""
    system, user = _screenshot_questions_prompt("resume.tex content", "brag content")
    assert "resume.tex content" in user
    assert "brag content" in user
    assert "never invent" in system.lower()


def test_parse_question_answers_handles_array_dict_fences_and_garbage() -> None:
    """Question/answer parsing must handle: a bare JSON array, a {"questions": [...]}
    wrapper, ``` fences, and outright garbage (which yields [])."""
    rows = _parse_question_answers(
        '[{"question": "Why us?", "answer": "Because."},'
        '{"question": "Salary?", "answer": "Negotiable."}]'
    )
    assert [r.question for r in rows] == ["Why us?", "Salary?"]
    assert rows[0].answer == "Because."

    rows = _parse_question_answers(
        '```json\n{"questions": [{"question": "Q", "answer": "A"}]}\n```'
    )
    assert len(rows) == 1 and rows[0].question == "Q"

    assert _parse_question_answers("not json at all") == []
    assert _parse_question_answers('[{"question": "no answer"}]') == []
