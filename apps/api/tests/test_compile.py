# ============================================================================
# test_compile.py — checks that the LaTeX→PDF compiler actually works.
#
# These tests need a real tectonic.exe in apps/api/bin/ (the compiler binary).
# Each test writes a tiny LaTeX document, compiles it, and asserts the result
# is a genuine PDF. A PDF always starts with the 5 magic bytes "%PDF-", so
# reading the first 5 bytes is a solid "yes this is a PDF" check.
#
# WHY these three specific tests:
#   1. Basic compile — does the pipeline work at all?
#   2. Special characters + unicode — our cover-letter escaping (%, &, _, é)
#      must not break the compile.
#   3. The XeTeX shim — the most important one: popular resume templates use
#      pdfTeX-only commands that tectonic's engine lacks; the shim must
#      neutralize them or every real resume would fail to compile.
# ============================================================================

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # import path to apps/api/

from compile import compile_tex  # noqa: E402


def test_compile_minimal_document() -> None:
    """The simplest possible document must compile to a valid PDF."""
    pdf = compile_tex(
        "\\documentclass{article}\n\\begin{document}\nHello world.\n\\end{document}",
        "test-minimal",
    )
    assert pdf.read_bytes()[:5] == b"%PDF-"   # first 5 bytes are the PDF magic marker


def test_compile_unicode_and_specials() -> None:
    """Escaped special chars (\\& \\% \\_) and unicode (é, —) must survive
    compilation — this is exactly what cover letters contain."""
    tex = (
        "\\documentclass{article}\n"
        "\\usepackage[a4paper]{geometry}\n"
        "\\begin{document}\n"
        "\\noindent Costs \\& \\% margin \\_ and unicode: café — done.\n"
        "\\end{document}"
    )
    pdf = compile_tex(tex, "test-specials")
    assert pdf.read_bytes()[:5] == b"%PDF-"


def test_compile_pdftex_template_shim() -> None:
    """Jake's-Resume-style templates \\input glyphtounicode.tex, which uses the
    pdfTeX-only primitives \\pdfglyphtounicode and \\pdfgentounicode. The shim
    must neutralize them under tectonic's XeTeX engine."""
    tex = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\input glyphtounicode\n"
        "\\noindent Resume template.\\end{document}"
    )
    pdf = compile_tex(tex, "test-pdftex-shim")
    assert pdf.read_bytes()[:5] == b"%PDF-"