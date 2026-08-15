from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import (  # noqa: E402
    FINE_TUNE_SYSTEM,
    Answer,
    GenerateRequest,
    _clamp,
    _clamp_answers,
    _clamp_links,
    _cover_letter_prompt,
    _feedback_prompt,
    _generate_stream,
    _parse_feedback,
    _parse_question_answers,
    _screenshot_questions_prompt,
)


def test_clamp_limits_length() -> None:
    assert len(_clamp("x" * 5000, 100)) == 100
    assert _clamp("short", 100) == "short"


def test_clamp_answers_filters_blanks_and_caps() -> None:
    out = _clamp_answers(
        [
            Answer(question="   ", answer="ignored"),
            Answer(question="q", answer="a" * 5000),
            Answer(question="q2", answer="b"),
        ]
    )
    assert len(out) == 2
    assert out[0].answer == "a" * 2000
    assert out[1].answer == "b"


def test_clamp_answers_limits_count() -> None:
    many = [Answer(question=f"q{i}", answer="a") for i in range(50)]
    assert len(_clamp_answers(many)) == 20


def test_clamp_links_filters_blanks_caps_count_and_length() -> None:
    assert _clamp_links(["  https://a.example  ", "", "   "]) == ["https://a.example"]
    assert len(_clamp_links(["x" * 5000])) == 1
    assert len(_clamp_links(["x" * 5000])[0]) == 2048
    assert len(_clamp_links([f"l{i}" for i in range(80)])) == 50


def test_cover_letter_prompt_includes_name_and_links() -> None:
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
    assert "ASD-STE100" in system


def test_cover_letter_prompt_without_name_or_links_keeps_placeholder() -> None:
    system, _ = _cover_letter_prompt("Job desc", [], "cv.tex", "", [])
    assert "[Your Name]" in system
    assert "CANDIDATE LINKS" not in system


def test_fine_tune_prompt_never_trims_content_or_metrics() -> None:
    lower = FINE_TUNE_SYSTEM.lower()
    assert "never delete, condense, summarize, or shorten anything" in lower
    assert "exactly as written" in lower
    assert "at least as detailed as the master" in lower


def test_feedback_prompt_grounded_in_resume_and_brag_and_bullets() -> None:
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
    rating, text = _parse_feedback('{"rating": 8, "feedback": "- strong fit\\n- one gap"}')
    assert rating == 8
    assert text == "- strong fit\n- one gap"

    rating, text = _parse_feedback('```json\n{"rating": "10", "feedback": "- great"}\n```')
    assert rating == 10
    assert text == "- great"

    rating, _ = _parse_feedback('{"rating": 99, "feedback": "- way too high"}')
    assert rating == 10
    rating, _ = _parse_feedback('{"rating": 0, "feedback": "- way too low"}')
    assert rating == 1

    rating, text = _parse_feedback("not json")
    assert rating is None
    assert text == "not json"


def _parse_sse(stream: str) -> list[tuple[str, dict]]:
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


def test_generate_stream_emits_each_part_in_order(monkeypatch) -> None:
    monkeypatch.setattr("main._fine_tune", lambda *a, **k: "\\documentclass{article}")
    monkeypatch.setattr("main._compile", lambda *a, **k: Path("custom-resume.pdf"))
    monkeypatch.setattr("main._cover_letter", lambda *a, **k: "Dear team,")
    monkeypatch.setattr("main._feedback", lambda *a, **k: (8, "- strong fit"))
    req = GenerateRequest(
        job_description="JD",
        cover_letter_formats=["pdf", "text"],
        parts=["resume", "cover_letter"],
    )
    events = _parse_sse(
        "".join(_generate_stream(req, "JD", [], "cv.tex", "Jane", [], "brag", "tex"))
    )
    assert [e for e, _ in events] == [
        "used_master_cv",
        "resume",
        "cover_letter_text",
        "cover_letter_txt",
        "cover_letter_pdf",
        "feedback",
        "done",
    ]
    assert events[0][1] == {"used_master_cv": "cv.tex"}
    assert events[3][1]["kind"] == "text"
    assert "Dear team," in events[3][1]["text"]
    assert events[5][1] == {"rating": 8, "text": "- strong fit"}


def test_generate_stream_always_emits_feedback_even_when_not_requested(monkeypatch) -> None:
    monkeypatch.setattr("main._cover_letter", lambda *a, **k: "Dear team,")
    monkeypatch.setattr("main._feedback", lambda *a, **k: (6, "- ok"))
    req = GenerateRequest(
        job_description="JD", cover_letter_formats=["text"], parts=["cover_letter"]
    )
    events = _parse_sse(
        "".join(_generate_stream(req, "JD", [], "cv.tex", "", [], "", ""))
    )
    assert [e for e, _ in events] == [
        "used_master_cv",
        "cover_letter_text",
        "cover_letter_txt",
        "feedback",
        "done",
    ]


def test_generate_stream_partial_failure_isolates_the_part(monkeypatch) -> None:
    def boom(*a, **k):
        raise RuntimeError("model down")

    monkeypatch.setattr("main._fine_tune", boom)
    monkeypatch.setattr("main._compile", lambda *a, **k: Path("cover-letter.pdf"))
    monkeypatch.setattr("main._cover_letter", lambda *a, **k: "Dear team,")
    monkeypatch.setattr("main._feedback", lambda *a, **k: (7, "- ok"))
    req = GenerateRequest(
        job_description="JD", cover_letter_formats=["text"], parts=["resume", "cover_letter"]
    )
    events = _parse_sse(
        "".join(_generate_stream(req, "JD", [], "cv.tex", "", [], "", ""))
    )
    assert [e for e, _ in events] == [
        "used_master_cv",
        "error",
        "cover_letter_text",
        "cover_letter_txt",
        "feedback",
        "done",
    ]
    assert events[1][1]["part"] == "resume"
    assert "model down" in events[1][1]["message"]


def test_screenshot_questions_prompt_grounded_in_resume_and_brag() -> None:
    system, user = _screenshot_questions_prompt("resume.tex content", "brag content")
    assert "resume.tex content" in user
    assert "brag content" in user
    assert "never invent" in system.lower()


def test_parse_question_answers_handles_array_dict_fences_and_garbage() -> None:
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
