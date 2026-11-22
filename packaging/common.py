# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

"""Helpers shared by the standalone build scripts."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
BUILD = ROOT / "build"
DIST = ROOT / "dist"


def version() -> str:
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def run(cmd: list[str], **kwargs) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kwargs)


def pyinstaller(name: str, *, onefile: bool, icon: Path, distpath: Path) -> None:
    """Bundle the game with PyInstaller (windowed: no console window)."""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("PyInstaller is missing: pip install -r packaging/requirements.txt")
    work = BUILD / "pyinstaller"
    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed",
        "--onefile" if onefile else "--onedir",
        "--name", name,
        "--icon", icon,
        "--paths", ROOT,                 # import orbi2d from the source tree
        "--exclude-module", "tkinter",
        # PySDL2 loads the SDL2 library at run time: bundle pysdl2-dll's copy.
        "--collect-all", "sdl2dll",
        "--distpath", distpath,
        "--workpath", work,
        "--specpath", work,
        PACKAGING / "launcher.py",
    ])
