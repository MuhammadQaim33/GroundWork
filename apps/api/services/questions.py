# ============================================================================
# services/questions.py — read application-form questions off screenshots and
# draft answers grounded in the resume + brag doc.
# ============================================================================

from __future__ import annotations

import json

from schemas import Answer
from services.text import _clamp_answers

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