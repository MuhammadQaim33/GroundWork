from __future__ import annotations

import subprocess
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent / "bin"
OUT_DIR = Path(__file__).resolve().parent / "data" / "out"

# tectonic compiles with XeTeX, which lacks pdfTeX-only primitives. Resume
# templates (e.g. Jake's-Resume forks) \input glyphtounicode.tex, which calls
# \pdfglyphtounicode and sets \pdfgentounicode; define both as no-ops if
# undefined so those templates compile unchanged. Deliberately narrow: add
# primitives only as real failures show up. (\newcount is part of latex.ltx,
# already in the format before \documentclass runs.)
XETEX_SHIM = (
    "\\ifdefined\\pdfglyphtounicode\\else\\def\\pdfglyphtounicode#1#2{}\\fi\n"
    "\\ifdefined\\pdfgentounicode\\else\\newcount\\pdfgentounicode\\fi\n"
)


def compile_tex(tex: str, output_name: str, out_dir: Path | None = None) -> Path:
    """Compile a .tex document to PDF with tectonic. Raises RuntimeError (log tail) on failure."""
    out_dir = out_dir or OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    tex_path = out_dir / f"{output_name}.tex"
    tex_path.write_text(XETEX_SHIM + tex, encoding="utf-8")

    exe = BIN_DIR / "tectonic.exe"
    if not exe.exists():
        raise RuntimeError(
            f"tectonic not found at {exe} — download the Windows binary into apps/api/bin/"
        )

    result = subprocess.run(
        [str(exe), "-X", "compile", str(tex_path), "--outdir", str(out_dir)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    pdf = out_dir / f"{output_name}.pdf"
    if result.returncode != 0 or not pdf.exists():
        log = f"{result.stdout or ''}\n{result.stderr or ''}"
        tail = "\n".join(log.splitlines()[-25:])
        raise RuntimeError(f"tectonic failed for {output_name}:\n{tail}")
    return pdf
