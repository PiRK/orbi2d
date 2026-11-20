# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

"""Render the application icon with the game's own graphics.

Writes packaging/orbi2d.png (256x256, Linux/AppImage) and packaging/orbi2d.ico
(multi-size, Windows). Needs PySide6 and Pillow. Run from the repository root:

    python packaging/make_icon.py
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen  # noqa: E402

from orbi2d.graphics import BG, CURRENT_COLOR, TARGET_COLOR, draw_moon, draw_planet, draw_ship  # noqa: E402

HERE = Path(__file__).resolve().parent
SIZE = 256


def render(size: int = SIZE) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256.0

    # Rounded dark tile.
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 48 * s, 48 * s)
    p.fillPath(tile, BG)
    p.setClipPath(tile)

    c = QPointF(118 * s, 138 * s)
    # Target orbit (dashed green) and current orbit (blue ellipse).
    pen = QPen(TARGET_COLOR, 6 * s)
    pen.setStyle(Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.drawEllipse(c, 96 * s, 96 * s)
    p.save()
    p.translate(c)
    p.rotate(-28)
    p.setPen(QPen(CURRENT_COLOR, 6 * s))
    p.drawEllipse(QPointF(14 * s, 0), 72 * s, 52 * s)
    p.restore()

    draw_planet(p, c, 38 * s)
    draw_moon(p, QPointF(206 * s, 52 * s), 20 * s)
    # Ship on the blue orbit, nose up-left (prograde, counter-clockwise).
    draw_ship(p, QPointF(186 * s, 120 * s), math.radians(100), thrust=None, size=2.6 * s)
    p.end()
    return img


def main() -> None:
    QGuiApplication([])
    png = HERE / "orbi2d.png"
    render().save(str(png))
    # Multi-resolution .ico for Windows (Explorer, taskbar, title bar).
    sizes = [16, 24, 32, 48, 64, 128, 256]
    Image.open(png).save(HERE / "orbi2d.ico", sizes=[(n, n) for n in sizes])
    print(f"wrote {png} and {HERE / 'orbi2d.ico'}")


if __name__ == "__main__":
    main()
