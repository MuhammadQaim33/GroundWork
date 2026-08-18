# ============================================================================
# services/resume.py — the "fine-tune" (per-job tailoring) of the master CV.
#
# The master CV is a LaTeX .tex file. We ask the model to make MINIMAL,
# keyword-level edits so it matches the JD's terminology — surfacing keywords
# already present, honest synonym swaps only, NEVER invented facts. The model
# replies with edited .tex, which we compile to PDF. Since LLM-produced LaTeX
# is unreliable, a failed compile earns ONE retry with the error fed back as a
# hint, then we fail loudly.
# ============================================================================

from __future__ import annotations

import re
from pathlib import Path

from compile import compile_pdf
from errors import CompileError
from llm import MAX_OUT_TOKENS, active_provider, chat, fit_max_tokens

FINE_TUNE_SYSTEM = (
    "You are a resume editor. Your only goal: maximize the chance this resume gets an "
    "interview call for the job description. "
    "KEEP the document structure and almost all existing content intact — keep every section, "
    "bullet, and metric exactly as written; never delete, condense, summarize, or rewrite a line. "
    "Make only minimal keyword-level edits to better match the job description: "
    "surface relevant keywords that are already in the resume (matching the job's terminology), "
    "and swap a generic phrase for the job's keyword when it is an honest fit (e.g. "
    "'built services' -> 'designed REST APIs'). "
    "EVERY technology keyword in the job description (e.g. Angular, React, PostgreSQL) must be "
    "added to the resume even if the resume lacks it: always add it to the Skills section, and "
    "add it to the Projects section by lightly editing ONE existing project line so the "
    "technology is mentioned there naturally. "
    "Mention each keyword only where it is genuinely relevant: a frontend framework belongs in "
    "a frontend or full-stack project line, never in a backend description; a backend "
    "technology belongs in a backend line. Never write react.js into a backend-only bullet. "
    "Edits must read like the candidate's own writing — no stilted keyword stacking, no "
    "unrelated pairings a recruiter would spot as machine-tailored. If no project line "
    "plausibly fits the keyword, still add it to Skills but do not force it into an "
    "irrelevant bullet. "
    "NEVER invent experience, skills, metrics, or projects; the ONLY addition allowed is the "
    "JD's technology keyword itself. Every number must appear EXACTLY as written in the source. "
    "Escape special characters in text (use \\& not &, \\% not %, \\_ not _, \\# not #). "
    "Keep the LaTeX valid. "
    "Respond with ONLY the .tex source code — no markdown fences, no commentary."
)


def extract_latex_document(text: str) -> str:
    """Cut any prose the model added before \\documentclass or after \\end{document}."""
    m = re.search(r"\\documentclass", text, re.IGNORECASE)
    if not m:
        return text   # no document marker → return as-is (caller handles it)
    body = text[m.start() :]                      # everything from \\documentclass on
    end = re.search(r"\\end\{document\}", body, re.IGNORECASE)
    if end:
        body = body[: end.end()]                  # stop right after \\end{document}
    return body


def _ensure_documentclass(edited: str, master_tex: str) -> str:
    """Make sure the model's output has a \\documentclass (splice the master's
    preamble if it was dropped), else raise a clear error."""
    if "documentclass" not in edited.lower():
        edited = repair_missing_preamble(edited, master_tex)
    if "documentclass" not in edited.lower():
        raise CompileError("Model produced invalid LaTeX (no documentclass). Try again.")
    return edited


def repair_missing_preamble(model_output: str, master_tex: str) -> str:
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


def fine_tune(
    master_tex: str,
    brag_text: str,
    job_description: str,
    error_hint: str = "",
) -> str:
    """Ask the model to keyword-tailor the master CV; return the edited .tex.

    If error_hint is non-empty (a previous compile failed), it's appended so
    the model gets a chance to fix the exact LaTeX error.

    Truncation guard: a fine-tuned resume is ~as long as the input, so it is
    prone to being cut off at the token cap. An output with no \\end{document}
    means truncation — we regenerate ONCE with a nudge and a bigger budget,
    then fall back to splicing the master's closing tag (deterministic last
    resort) so the compile step at least has a complete document.
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
    # match_input=True: the answer is the resume itself (output ≈ input size),
    # so on non-Groq providers ask for up to the input's length, not the floor.
    max_tokens = fit_max_tokens(FINE_TUNE_SYSTEM, user, floor=3000, match_input=True)
    edited = clean_model_latex(
        chat(FINE_TUNE_SYSTEM, user, temperature=0.3, max_tokens=max_tokens).strip()
    )
    edited = _ensure_documentclass(edited, master_tex)

    if "\\end{document}" not in edited.lower():
        # The answer was cut off before the closing tag — regenerate once with
        # a nudge and (on non-Groq providers) the full output budget.
        user += (
            "\n\nYour previous answer was cut off before \\end{document}.\n"
            "Output the COMPLETE corrected document, ending with \\end{document}."
        )
        if active_provider() == "groq":
            bumped = fit_max_tokens(FINE_TUNE_SYSTEM, user, floor=max_tokens)
        else:   # no TPM ceiling — give the regen the full cap so dense LaTeX fits
            bumped = MAX_OUT_TOKENS
        edited = clean_model_latex(
            chat(FINE_TUNE_SYSTEM, user, temperature=0.3, max_tokens=bumped).strip()
        )
        edited = _ensure_documentclass(edited, master_tex)
        if "\\end{document}" not in edited.lower():
            # Last resort: borrow the master's closing tag. Compiles only if the
            # cut happened after all environments closed; otherwise build_resume's
            # compile-retry feeds the real error back to the model.
            end_tag = re.search(r"\\end\{document\}", master_tex, re.IGNORECASE)
            if end_tag:
                edited += master_tex[end_tag.start():]
    return edited


def clean_model_latex(text: str) -> str:
    """Clean the model's output: strip code fences, then any prose around the document."""
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:])
        if text.rstrip().endswith("```"):
            text = "\n".join(text.splitlines()[:-1])
    return extract_latex_document(text.strip())


def build_resume(master_tex: str, brag_text: str, job_description: str) -> Path:
    """Fine-tune + compile the resume; regenerate once if the LLM's LaTeX fails to compile."""
    error_hint = ""
    last_error: Exception | None = None
    for _ in range(2):   # at most 2 attempts: first try, then one repair try
        edited = fine_tune(master_tex, brag_text, job_description, error_hint)
        try:
            return compile_pdf(edited, "custom-resume")
        except Exception as exc:
            last_error = exc
            error_hint = str(exc)   # feed the error back so the next try can fix it
    raise last_error if last_error else RuntimeError("resume generation failed")


# ============================================================================
# Master-CV auto-picking — which CV is the best starting point for this JD?
# ============================================================================

def pick_cv(cvs: list[dict], job_description: str) -> dict:
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