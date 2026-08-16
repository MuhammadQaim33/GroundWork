# ============================================================================
# compile.py — turning LaTeX (.tex) source into a PDF document.
#
# Why LaTeX? The user's master CV is a .tex file. The AI rewrites it (still
# .tex), and to hand the user a real resume we must COMPILE that .tex into a
# PDF. This file does that, using a tool called "tectonic" — a self-contained
# LaTeX compiler (no giant LaTeX install needed; it's one .exe in /bin).
#
# The only real job here is: take text, write it to a .tex file, run tectonic,
# and return the produced .pdf path. Anything that goes wrong becomes a clear
# RuntimeError with the tail of tectonic's log.
# ============================================================================

from __future__ import annotations

import subprocess  # lets Python run external programs (like tectonic.exe)
from pathlib import Path  # pathlib.Path = a friendlier way to handle file paths
from uuid import uuid4  # unique IDs for naming generated files

from fastapi import HTTPException

# This file lives at apps/api/compile.py, so:
#   __file__ = "apps/api/compile.py"
#   .parent  = "apps/api/"
#   / "bin"  = "apps/api/bin/"  → where tectonic.exe lives
#   / "data" / "out"            → where generated PDFs are written
BIN_DIR = Path(__file__).resolve().parent / "bin"
OUT_DIR = Path(__file__).resolve().parent / "data" / "out"

# A chunk of LaTeX spliced on top of every document before compiling.
# WHY: many resume templates were written for pdfTeX, the "classic" engine,
# and call two special commands (\pdfglyphtounicode / \pdfgentounicode) that
# tectonic's engine (XeTeX) doesn't understand. These lines say "if the command
# isn't defined, define it as a harmless no-op" — so those templates compile
# unchanged. Deliberately narrow: we add shims only as real failures show up.
XETEX_SHIM = (
    "\\ifdefined\\pdfglyphtounicode\\else\\def\\pdfglyphtounicode#1#2{}\\fi\n"
    "\\ifdefined\\pdfgentounicode\\else\\newcount\\pdfgentounicode\\fi\n"
)


def compile_tex(tex: str, output_name: str, out_dir: Path | None = None) -> Path:
    """Compile a .tex document to PDF with tectonic. Returns the PDF path.

    Raises RuntimeError (with the useful tail of tectonic's log) on failure.
    """
    # Allow the caller to override the output directory (tests use a temp dir).
    out_dir = out_dir or OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)   # create the folder if missing

    # 1) Write the shim + the document to a temp .tex file.
    tex_path = out_dir / f"{output_name}.tex"
    tex_path.write_text(XETEX_SHIM + tex, encoding="utf-8")

    # 2) Make sure the compiler binary exists; if not, tell the user how to fix it.
    exe = BIN_DIR / "tectonic.exe"
    if not exe.exists():
        raise RuntimeError(
            f"tectonic not found at {exe} — download the Windows binary into apps/api/bin/"
        )

    # 3) Run:  tectonic -X compile <file.tex> --outdir <folder>
    #    capture_output=True → grab its printed logs instead of showing them.
    #    timeout=180          → give up after 3 minutes (a hung compiler is a bug).
    result = subprocess.run(
        [str(exe), "-X", "compile", str(tex_path), "--outdir", str(out_dir)],
        capture_output=True,
        text=True,
        timeout=180,
    )

    # 4) Success means: exit code 0 AND a .pdf file appeared.
    pdf = out_dir / f"{output_name}.pdf"
    if result.returncode != 0 or not pdf.exists():
        log = f"{result.stdout or ''}\n{result.stderr or ''}"
        tail = "\n".join(log.splitlines()[-25:])   # keep the last 25 log lines — the useful part
        raise RuntimeError(f"tectonic failed for {output_name}:\n{tail}")
    return pdf


def _out_name(base: str) -> str:
    """Give generated files unique names: base-<8 random hex chars>."""
    return f"{base}-{uuid4().hex[:8]}"


def _compile(tex: str, base: str) -> Path:
    """Compile LaTeX to PDF; surface tectonic failures as a readable 502, not a traceback."""
    try:
        return compile_tex(tex, _out_name(base))
    except RuntimeError as exc:
        raise HTTPException(502, f"LaTeX compile failed. {exc}") from exc