# ============================================================================
# services/feedback.py — rate the candidate's fit against the job description.
# ============================================================================

from __future__ import annotations

import re

from llm import chat, fit_max_tokens
from services.text import first_json_object, strip_json_fence

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


def feedback_prompt(job_description: str, master_tex: str, brag_text: str) -> tuple[str, str]:
    """Build the (system, user) prompt for the feedback job."""
    user = (
        f"JOB DESCRIPTION:\n{job_description}\n\n"
        + (f"BRAG DOCUMENT:\n{brag_text}\n\n" if brag_text else "")
        + f"RESUME:\n{master_tex}"
    )
    return FEEDBACK_SYSTEM, user


def _clamp_rating(rating: object) -> int | None:
    """Turn whatever the model returned into a clean 1-10 int (None if unusable)."""
    if isinstance(rating, str):
        rating = rating.strip()
    try:
        rating = int(float(rating))   # handles "8", 8, "8.0", 8.0 ...
    except (TypeError, ValueError):
        return None
    return max(1, min(10, rating))   # clamp into 1..10


def parse_feedback(raw: str) -> tuple[int | None, str]:
    """Parse the model's JSON into (rating 1-10, feedback text); fall back on failure."""
    text = strip_json_fence(raw)
    data = first_json_object(text)
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


def feedback(job_description: str, master_tex: str, brag_text: str) -> tuple[int | None, str]:
    """Run the feedback job end-to-end: prompt → model call → parse. Returns (rating, text)."""
    system, user = feedback_prompt(job_description, master_tex, brag_text)
    max_tokens = fit_max_tokens(system, user, floor=800)
    return parse_feedback(chat(system, user, temperature=0.3, max_tokens=max_tokens).strip())