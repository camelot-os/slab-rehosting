#!/usr/bin/env python3
"""
Generate PNG diagrams from TikZ/LaTeX sources.

Called by ``make images`` in the docs Makefile.  Requires ``pdflatex``
and ``pdftoppm`` (from poppler-utils) on the system PATH.

Usage:
    python3 generate_diagrams.py            # build all diagrams
    python3 generate_diagrams.py --force    # rebuild even if up-to-date

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import os
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
DIAGRAMS_DIR = SCRIPT_DIR / "diagrams"
IMAGES_DIR = SCRIPT_DIR / "source" / "images"

DPI = 200  # PNG resolution


def find_tex_files():
    """Find all .tex files in the diagrams directory."""
    if not DIAGRAMS_DIR.exists():
        return []
    return sorted(DIAGRAMS_DIR.glob("*.tex"))


def needs_rebuild(tex_path: Path, png_path: Path) -> bool:
    """Check if PNG needs to be rebuilt from its TeX source."""
    if not png_path.exists():
        return True
    return tex_path.stat().st_mtime > png_path.stat().st_mtime


def build_diagram(tex_path: Path, force: bool = False) -> bool:
    """Compile a single TikZ diagram to PNG.

    Pipeline: pdflatex → pdftoppm -png -r DPI → copy to images/
    """
    stem = tex_path.stem
    png_path = IMAGES_DIR / f"{stem}.png"

    if not force and not needs_rebuild(tex_path, png_path):
        print(f"  [skip] {stem}.png (up-to-date)")
        return True

    with tempfile.TemporaryDirectory(prefix="tikz_") as tmpdir:
        tmpdir = Path(tmpdir)

        # Step 1: pdflatex
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode",
             f"-output-directory={tmpdir}", str(tex_path)],
            capture_output=True, text=True, timeout=30,
        )
        pdf_path = tmpdir / f"{stem}.pdf"
        if result.returncode != 0 or not pdf_path.exists():
            print(f"  [FAIL] {stem}.tex — pdflatex error")
            for line in result.stdout.splitlines():
                if line.startswith("!"):
                    print(f"         {line}")
            return False

        # Step 2: pdftoppm → PNG
        png_prefix = tmpdir / stem
        result = subprocess.run(
            ["pdftoppm", "-png", "-r", str(DPI), "-singlefile",
             str(pdf_path), str(png_prefix)],
            capture_output=True, text=True, timeout=15,
        )
        tmp_png = tmpdir / f"{stem}.png"
        if result.returncode != 0 or not tmp_png.exists():
            print(f"  [FAIL] {stem}.pdf — pdftoppm error")
            return False

        # Step 3: Copy to images/
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tmp_png, png_path)
        size_kb = png_path.stat().st_size / 1024
        print(f"  [ OK ] {stem}.png ({size_kb:.0f} KB, {DPI} DPI)")
        return True


def main():
    force = "--force" in sys.argv

    # Check prerequisites
    for tool in ("pdflatex", "pdftoppm"):
        if not shutil.which(tool):
            print(f"WARNING: {tool} not found — skipping diagram generation")
            print(f"Install with: sudo apt-get install texlive-latex-base poppler-utils")
            return

    tex_files = find_tex_files()
    if not tex_files:
        print("No .tex files found in diagrams/")
        return

    print(f"Building {len(tex_files)} diagram(s) at {DPI} DPI...")
    ok = 0
    fail = 0
    for tex_path in tex_files:
        if build_diagram(tex_path, force=force):
            ok += 1
        else:
            fail += 1

    print(f"\nDone: {ok} built, {fail} failed")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
