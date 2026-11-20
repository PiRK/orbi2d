# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

"""Build a single-file Windows executable: dist/orbi2d-<version>-windows-x64.exe

Run on Windows (PyInstaller cannot cross-compile), from the repository root:

    pip install -r requirements.txt -r packaging/requirements.txt
    python packaging/build_exe.py
"""

from __future__ import annotations

import sys

from common import DIST, PACKAGING, pyinstaller, version


def main() -> None:
    if sys.platform != "win32":
        sys.exit("build_exe.py must run on Windows: PyInstaller cannot cross-compile.\n"
                 "Use the 'Standalone builds' GitHub workflow to build it from Linux.")
    name = f"orbi2d-{version()}-windows-x64"
    pyinstaller(name, onefile=True, icon=PACKAGING / "orbi2d.ico", distpath=DIST)
    print(f"\nBuilt {DIST / (name + '.exe')}")


if __name__ == "__main__":
    main()
