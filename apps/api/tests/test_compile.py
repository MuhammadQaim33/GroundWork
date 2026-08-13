from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compile import compile_tex  # noqa: E402


def test_compile_minimal_document() -> None:
    pdf = compile_tex(
        "\\documentclass{article}\n\\begin{document}\nHello world.\n\\end{document}",
        "test-minimal",
    )
    assert pdf.read_bytes()[:5] == b"%PDF-"


def test_compile_unicode_and_specials() -> None:
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
    # Jake's-Resume-style templates \input glyphtounicode.tex, which uses the
    # pdfTeX-only primitives \pdfglyphtounicode and \pdfgentounicode. The shim
    # must neutralize them under tectonic's XeTeX engine.
    tex = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\input glyphtounicode\n"
        "\\noindent Resume template.\\end{document}"
    )
    pdf = compile_tex(tex, "test-pdftex-shim")
    assert pdf.read_bytes()[:5] == b"%PDF-"
