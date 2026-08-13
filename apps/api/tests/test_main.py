from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import Answer, _clamp, _clamp_answers  # noqa: E402


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
