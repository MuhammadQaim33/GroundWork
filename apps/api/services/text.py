# ============================================================================
# services/text.py — shared input guards and text helpers.
#
# Trust-boundary rule: never let a user (or a hostile client) send us a
# megabyte of text. These clamp helpers keep every input within sane limits.
# The JSON-from-LLM helpers are generic enough that every future pillar
# (Screener, Armory validator, Coach) will want them too.
# ============================================================================

from __future__ import annotations

import json

from schemas import Answer


def clamp(text: str, max_chars: int) -> str:
    """Cut a string down to at most max_chars."""
    return text[:max_chars]


def clamp_answers(answers: list[Answer]) -> list[Answer]:
    """Trim answers: drop blank ones, cap question/answer length, cap count at 20."""
    out = []
    for a in answers:
        q = a.question.strip()
        ans = a.answer.strip()
        if q and ans:
            out.append(Answer(question=q[:500], answer=ans[:2000]))
    return out[:20]


def clamp_questions(questions: list[str]) -> list[str]:
    """Trim form questions: drop blanks, cap each at 500 chars, cap count at 20."""
    return [q.strip()[:500] for q in questions if q.strip()][:20]


def clamp_links(links: list[str]) -> list[str]:
    """Trim links: drop blanks, cap each at 2048 chars, cap count at 50."""
    out = []
    for link in links:
        s = link.strip()
        if s:
            out.append(s[:2048])
    return out[:50]


def strip_json_fence(raw: str) -> str:
    """Remove ```json ... ``` fences if the model wrapped its JSON in them."""
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:])
        if text.rstrip().endswith("```"):
            text = "\n".join(text.splitlines()[:-1])
    return text.strip()


def first_json_object(text: str) -> dict | None:
    """Pull the first {...} block out of the model output, ignoring prose around it."""
    start, end = text.find("{"), text.rfind("}")   # first { to last }
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None