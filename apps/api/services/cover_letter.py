# ============================================================================
# services/cover_letter.py — the cover-letter writer.
# ============================================================================

from __future__ import annotations

import re

from llm import chat


def cover_letter(
    job_description: str,
    cv_name: str,
    name: str = "",
    links: list[str] | None = None,
) -> str:
    """Write the cover letter: prompt → model call → return the letter text."""
    system, user = cover_letter_prompt(job_description, cv_name, name, links or [])
    return chat(system, user, temperature=0.4, max_tokens=1500).strip()


def cover_letter_prompt(
    job_description: str,
    cv_name: str,
    name: str,
    links: list[str],
) -> tuple[str, str]:
    """Build the (system, user) prompt for the cover-letter writer.

    The system prompt is built conditionally: the signature uses the real name
    if provided, else a placeholder; links are listed only if the user has any.
    """
    user = (
        f"JOB DESCRIPTION:\n{job_description}\n\n"
        + f"RESUME FILENAME: {cv_name}"
    )
    if name:
        user += f"\n\nCANDIDATE NAME: {name}"
    if links:
        user += "\n\nCANDIDATE LINKS:\n" + "\n".join(f"- {link}" for link in links)
    system = (
        "You write concise, specific cover letters (about 250 words)"
        "Short sentences, one idea per sentence, simple "
        "unambiguous vocabulary. Ground every claim in the job description and the candidate's "
        "resume; never invent experience or numbers. "
        "Optimize for recruiter attractiveness and recruiter ease to read"
    )
    if name:
        system += (
            f"Sign the letter with the candidate's real name ('{name}') "
            "— do not use a placeholder. "
        )
    else:
        system += "Leave the signature as '[Your Name]'. "
    if links:
        system += (
            "List the candidate's links at the bottom of the letter under a 'Links:' heading, "
            "one per line. "
        )
    system += "Output plain text only, with blank lines between paragraphs."
    return system, user


# ============================================================================
# LaTeX escaping — making plain text safe to embed in a .tex document.
#
# In LaTeX, characters like & % _ # $ ~ ^ { } are RESERVED (they mean things:
# & aligns a table, % starts a comment, _ makes a subscript). If a cover
# letter contains "50%", writing it raw would break the document. So we escape
# each reserved char into its safe LaTeX form. This is exactly like escaping
# HTML in a web page.
# ============================================================================

_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",   # raw backslash
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "%": r"\%",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def _escape_latex(s: str) -> str:
    """Replace every reserved LaTeX character in s with its escaped form."""
    return re.sub(r"[\\{}%$&#_~^]", lambda m: _LATEX_SPECIALS[m.group(0)], s)


def letter_to_tex(letter_text: str) -> str:
    """Wrap a plain-text cover letter into a minimal compilable LaTeX document.

    Splits the letter into paragraphs (separated by blank lines), escapes each
    paragraph, and joins them with \par\medskip (a paragraph break with some
    vertical space). Then wraps everything in a tiny article template.
    """
    paragraphs = [_escape_latex(p.strip()) for p in letter_text.split("\n\n") if p.strip()]
    body = "\n\\par\\medskip\n".join(f"\\noindent {p}" for p in paragraphs)
    return (
        "\\documentclass[11pt]{article}\n"
        "\\usepackage[a4paper,margin=1in]{geometry}\n"
        "\\pagestyle{empty}\n"
        "\\begin{document}\n"
        f"{body}\n"
        "\\end{document}"
    )