# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

"""Drawing helpers shared by the game view and the main menu."""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
)

BG = QColor(6, 8, 18)
CURRENT_COLOR = QColor(80, 190, 255)
TARGET_COLOR = QColor(110, 255, 140)
PREDICT_COLOR = QColor(215, 140, 255)
WARN_COLOR = QColor(255, 200, 80)
BAD_COLOR = QColor(255, 90, 90)
TEXT_COLOR = QColor(220, 225, 235)
DIM_TEXT = QColor(140, 150, 170)
FAINT = QColor(120, 130, 160, 90)

Star = tuple[float, float, float]  # x, y (fractions of the widget size), brightness


def make_stars(n: int = 220, seed: int = 1234) -> list[Star]:
    rng = random.Random(seed)
    return [(rng.random(), rng.random(), rng.uniform(0.3, 1.0)) for _ in range(n)]


def draw_stars(p: QPainter, stars: list[Star], width: int, height: int) -> None:
    for sx, sy, b in stars:
        c = int(90 + 120 * b)
        p.setPen(QColor(c, c, c + 20 if c < 235 else 255))
        p.drawPoint(QPointF(sx * width, sy * height))


Light = tuple[float, float]  # unit vector (screen coordinates) towards the light


def _highlight(c: QPointF, r: float, light: Light | None) -> QPointF:
    """Brightest point of a lit sphere: towards the light, or the classic
    top-left when there's no light source (no Sun on screen)."""
    if light is None:
        return c + QPointF(-0.35 * r, -0.35 * r)
    return c + QPointF(0.45 * r * light[0], 0.45 * r * light[1])


def _night_side(p: QPainter, c: QPointF, r: float, light: Light | None) -> None:
    """Shade the half of a sphere facing away from the light."""
    if light is None or r < 1.5:
        return
    lx, ly = light
    grad = QLinearGradient(c + QPointF(0.15 * r * lx, 0.15 * r * ly), c - QPointF(r * lx, r * ly))
    grad.setColorAt(0.0, QColor(2, 3, 10, 0))
    grad.setColorAt(0.35, QColor(2, 3, 10, 150))
    grad.setColorAt(1.0, QColor(2, 3, 10, 235))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawEllipse(c, r, r)


def draw_planet(p: QPainter, c: QPointF, r: float, light: Light | None = None) -> None:
    """Blue planet of screen radius ``r`` centred on ``c``, lit from
    ``light`` (a unit vector towards the light source) if given."""
    grad = QRadialGradient(_highlight(c, r, light), 1.3 * r)
    grad.setColorAt(0.0, QColor(120, 170, 255))
    grad.setColorAt(0.6, QColor(40, 90, 190))
    grad.setColorAt(1.0, QColor(10, 25, 70))
    # Thin atmosphere glow.
    glow = QRadialGradient(c, r * 1.25)
    glow.setColorAt(0.75, QColor(100, 160, 255, 90))
    glow.setColorAt(1.0, QColor(100, 160, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(glow))
    p.drawEllipse(c, r * 1.25, r * 1.25)
    p.setBrush(QBrush(grad))
    p.drawEllipse(c, r, r)
    _night_side(p, c, r, light)


def draw_moon(p: QPainter, c: QPointF, r: float, light: Light | None = None) -> None:
    """Grey moon of screen radius ``r`` centred on ``c``."""
    grad = QRadialGradient(_highlight(c, r, light), 1.3 * r)
    grad.setColorAt(0.0, QColor(225, 222, 210))
    grad.setColorAt(0.6, QColor(150, 146, 138))
    grad.setColorAt(1.0, QColor(55, 54, 52))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawEllipse(c, r, r)
    _night_side(p, c, r, light)


def _draw_ball(p: QPainter, c: QPointF, r: float, bright: QColor, mid: QColor,
               dark: QColor, light: Light | None) -> None:
    grad = QRadialGradient(_highlight(c, r, light), 1.3 * r)
    grad.setColorAt(0.0, bright)
    grad.setColorAt(0.6, mid)
    grad.setColorAt(1.0, dark)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawEllipse(c, r, r)


def draw_sun(p: QPainter, c: QPointF, r: float, light: Light | None = None) -> None:
    """Yellow-white star with a soft corona."""
    glow = QRadialGradient(c, r * 2.2)
    glow.setColorAt(0.4, QColor(255, 210, 120, 120))
    glow.setColorAt(1.0, QColor(255, 180, 80, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(glow))
    p.drawEllipse(c, r * 2.2, r * 2.2)
    grad = QRadialGradient(c, r)
    grad.setColorAt(0.0, QColor(255, 255, 235))
    grad.setColorAt(0.7, QColor(255, 225, 120))
    grad.setColorAt(1.0, QColor(255, 170, 50))
    p.setBrush(QBrush(grad))
    p.drawEllipse(c, r, r)


def draw_red_planet(p: QPainter, c: QPointF, r: float, light: Light | None = None) -> None:
    _draw_ball(p, c, r, QColor(240, 150, 110), QColor(180, 75, 45), QColor(60, 20, 12), light)
    _night_side(p, c, r, light)


def draw_gas_giant(p: QPainter, c: QPointF, r: float, light: Light | None = None) -> None:
    """Banded tan giant."""
    _draw_ball(p, c, r, QColor(245, 225, 190), QColor(200, 155, 105), QColor(70, 45, 30), light)
    if r < 6:
        _night_side(p, c, r, light)
        return
    p.save()
    clip = QPainterPath()
    clip.addEllipse(c, r, r)
    p.setClipPath(clip)
    for i, (dy, w) in enumerate(((-0.45, 0.10), (-0.12, 0.14), (0.22, 0.09), (0.5, 0.07))):
        band = QColor(150, 100, 65, 110) if i % 2 == 0 else QColor(235, 205, 160, 90)
        p.fillRect(QRectF(c.x() - r, c.y() + dy * r, 2 * r, w * r), band)
    p.restore()
    _night_side(p, c, r, light)   # over the bands


def draw_body(p: QPainter, name: str, c: QPointF, r: float, light: Light | None = None) -> None:
    """Draw the body called ``name`` (see game.py) with radius ``r`` px, lit
    from ``light`` (unit vector towards the light) if given."""
    {
        "sun": draw_sun,
        "planet": draw_planet,
        "moon": draw_moon,
        "red": draw_red_planet,
        "giant": draw_gas_giant,
    }.get(name, draw_moon)(p, c, r, light)


def draw_ship(p: QPainter, pos: QPointF, heading: float, *, thrust: str | None = None,
              rotating: int = 0, size: float = 1.4) -> None:
    """Rocket at screen position ``pos`` with its nose along ``heading``
    (world angle, radians, counter-clockwise).  ``thrust`` is None, "fine" or
    "full"; ``rotating`` is +1 (ccw), -1 (cw) or 0 to show side thrusters."""
    p.save()
    p.translate(pos)
    # Screen y is flipped, so negate the angle for Qt's rotation.
    p.rotate(-math.degrees(heading))
    p.scale(size, size)
    # Ship body pointing along +x.
    body = QPolygonF([
        QPointF(13, 0), QPointF(4, -5), QPointF(-9, -5),
        QPointF(-9, 5), QPointF(4, 5),
    ])
    if thrust:
        flame_len = (10 + 8 * random.random()) * (0.5 if thrust == "fine" else 1.0)
        flame = QPolygonF([QPointF(-9, -3.5), QPointF(-9 - flame_len, 0), QPointF(-9, 3.5)])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 160, 40))
        p.drawPolygon(flame)
        p.setBrush(QColor(255, 240, 160))
        p.drawPolygon(QPolygonF([QPointF(-9, -2), QPointF(-9 - flame_len * 0.5, 0), QPointF(-9, 2)]))
    if rotating:
        # Side thrusters at the nose: firing left side pushes nose right.
        side = 1 if rotating > 0 else -1  # +1 = ccw (nose turns up/left)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(200, 220, 255))
        y0 = 5 * side
        p.drawPolygon(QPolygonF([
            QPointF(6, y0), QPointF(8, y0 + 6 * side), QPointF(4, y0 + 6 * side),
        ]))
        p.drawPolygon(QPolygonF([
            QPointF(-6, -y0), QPointF(-4, -y0 - 6 * side), QPointF(-8, -y0 - 6 * side),
        ]))
    p.setPen(QPen(QColor(30, 30, 40), 1))
    p.setBrush(QColor(235, 235, 245))
    p.drawPolygon(body)
    p.setBrush(QColor(200, 60, 60))
    p.drawPolygon(QPolygonF([QPointF(13, 0), QPointF(4, -5), QPointF(4, 5)]))
    p.restore()
