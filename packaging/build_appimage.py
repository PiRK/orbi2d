# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

"""Build a Linux AppImage: dist/orbi2d-<version>-x86_64.AppImage

Run on Linux, from the repository root:

    pip install -r requirements.txt -r packaging/requirements.txt
    python packaging/build_appimage.py

Steps: PyInstaller bundles the game and its Qt libraries into a folder, the
folder goes into an AppDir (AppRun launcher, .desktop entry, icon), and
appimagetool packs the AppDir into a single executable file.

An AppImage only runs on distributions whose glibc is at least as new as the
build machine's, so release builds are made on an old distro (the GitHub
workflow uses Ubuntu 22.04).

appimagetool is taken from $APPIMAGETOOL or PATH, or downloaded (pinned
release, checked against its SHA-256) into build/tools/.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import sys
import urllib.request
from pathlib import Path

from common import BUILD, DIST, PACKAGING, pyinstaller, run, version

APPIMAGETOOL_VERSION = "1.9.1"
APPIMAGETOOL_URL = (
    "https://github.com/AppImage/appimagetool/releases/download/"
    f"{APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage"
)
APPIMAGETOOL_SHA256 = "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"

APPRUN = """#!/bin/sh
# AppImage entry point: start the bundled game.
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/orbi2d/orbi2d" "$@"
"""


def appimagetool() -> Path:
    env = os.environ.get("APPIMAGETOOL")
    if env:
        return Path(env)
    found = shutil.which("appimagetool")
    if found:
        return Path(found)
    tool = BUILD / "tools" / f"appimagetool-{APPIMAGETOOL_VERSION}-x86_64.AppImage"
    if not tool.exists():
        tool.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {APPIMAGETOOL_URL}")
        data = urllib.request.urlopen(APPIMAGETOOL_URL).read()
        digest = hashlib.sha256(data).hexdigest()
        if digest != APPIMAGETOOL_SHA256:
            sys.exit(f"appimagetool checksum mismatch: got {digest}")
        tool.write_bytes(data)
        tool.chmod(0o755)
    return tool


def main() -> None:
    if sys.platform != "linux" or platform.machine() != "x86_64":
        sys.exit("build_appimage.py must run on x86_64 Linux.")
    ver = version()

    # 1. Bundle with PyInstaller (folder mode: AppImage is the single file).
    bundle_dist = BUILD / "appimage" / "bundle"
    pyinstaller("orbi2d", onefile=False, icon=PACKAGING / "orbi2d.png", distpath=bundle_dist)

    # 2. Assemble the AppDir.
    appdir = BUILD / "appimage" / "orbi2d.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    shutil.copytree(bundle_dist / "orbi2d", appdir / "usr" / "lib" / "orbi2d", symlinks=True)
    apprun = appdir / "AppRun"
    apprun.write_text(APPRUN)
    apprun.chmod(0o755)
    shutil.copy(PACKAGING / "orbi2d.desktop", appdir / "orbi2d.desktop")
    shutil.copy(PACKAGING / "orbi2d.png", appdir / "orbi2d.png")
    icons = appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    icons.mkdir(parents=True)
    shutil.copy(PACKAGING / "orbi2d.png", icons / "orbi2d.png")
    (appdir / ".DirIcon").symlink_to("orbi2d.png")

    # 3. Pack it. Extract-and-run avoids needing FUSE for appimagetool itself.
    DIST.mkdir(exist_ok=True)
    out = DIST / f"orbi2d-{ver}-x86_64.AppImage"
    env = dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1")
    run([appimagetool(), "--no-appstream", appdir, out], env=env)
    print(f"\nBuilt {out}")


if __name__ == "__main__":
    main()
