# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

"""Qt rendering and input handling."""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from . import game as g
from .physics import Orbit

BG = QColor(6, 8, 18)
CURRENT_COLOR = QColor(80, 190, 255)
TARGET_COLOR = QColor(110, 255, 140)
WARN_COLOR = QColor(255, 200, 80)
BAD_COLOR = QColor(255, 90, 90)
TEXT_COLOR = QColor(220, 225, 235)
DIM_TEXT = QColor(140, 150, 170)

MIN_VIEW_EXTENT = 380.0


class GameWidget(QWidget):
    def __init__(self, seed: int | None = None) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(640, 480)
        self.game = g.Game(seed=seed)
        self.controls = g.Controls()
        self.paused = False
        self.show_help = True
        self.view_extent = self._desired_extent()

        rng = random.Random(1234)
        self.stars = [(rng.random(), rng.random(), rng.uniform(0.3, 1.0)) for _ in range(220)]

        self.clock = QElapsedTimer()
        self.clock.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    # ---- loop ------------------------------------------------------------
    def _tick(self) -> None:
        dt = min(self.clock.restart() / 1000.0, 0.05)
        if not self.paused:
            self.game.update(dt, self.controls)
        desired = self._desired_extent()
        self.view_extent += (desired - self.view_extent) * min(1.0, dt * 2.5)
        self.update()

    def _desired_extent(self) -> float:
        gm = self.game
        rn = math.hypot(*gm.r)
        far = max(gm.target.apoapsis, rn)
        if gm.orbit.bound:
            far = max(far, min(gm.orbit.apoapsis, g.ESCAPE_RADIUS))
        return max(MIN_VIEW_EXTENT, 1.12 * far)

    # ---- input -----------------------------------------------------------
    def _set_key(self, event: QKeyEvent, pressed: bool) -> bool:
        key = event.key()
        if key == Qt.Key.Key_Left:
            self.controls.left = pressed
        elif key == Qt.Key.Key_Right:
            self.controls.right = pressed
        elif key == Qt.Key.Key_Up:
            self.controls.thrust = pressed
        elif key == Qt.Key.Key_Shift:
            self.controls.fine = pressed
        else:
            return False
        return True

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self._set_key(event, True):
            return
        if event.isAutoRepeat():
            return
        key = event.key()
        gm = self.game
        if key in (Qt.Key.Key_R, Qt.Key.Key_N) or (
            key in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and gm.status != "playing"
        ):
            gm.reset()
            self.paused = False
        elif key == Qt.Key.Key_P:
            self.paused = not self.paused
        elif key == Qt.Key.Key_H:
            self.show_help = not self.show_help
        elif Qt.Key.Key_1 <= key <= Qt.Key.Key_4:
            gm.set_warp(key - Qt.Key.Key_1)
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            gm.set_warp(gm.warp_index + 1)
        elif key == Qt.Key.Key_Minus:
            gm.set_warp(gm.warp_index - 1)
        elif key in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
            self.window().close()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.isAutoRepeat():
            return
        if not self._set_key(event, False):
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        # Don't leave the engine stuck on when the window loses focus.
        self.controls = g.Controls()
        super().focusOutEvent(event)

    # ---- coordinates -------------------------------------------------------
    @property
    def scale(self) -> float:
        return 0.5 * min(self.width(), self.height()) / self.view_extent

    def to_screen(self, x: float, y: float) -> QPointF:
        s = self.scale
        return QPointF(self.width() / 2 + x * s, self.height() / 2 - y * s)

    # ---- painting ----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), BG)
        self._draw_stars(p)

        gm = self.game
        matched = gm.deviation <= gm.tolerance
        self._draw_orbit(p, gm.target, TARGET_COLOR, dashed=True, width=2.0 if not matched else 3.0)
        cur_color = TARGET_COLOR if matched else (BAD_COLOR if not gm.orbit.bound else CURRENT_COLOR)
        self._draw_orbit(p, gm.orbit, cur_color, dashed=False, width=1.6)
        self._draw_planet(p)
        self._draw_apsides(p, gm.target, TARGET_COLOR)
        self._draw_apsides(p, gm.orbit, cur_color)
        self._draw_rocket(p)
        self._draw_hud(p)
        self._draw_banner(p)
        p.end()

    def _draw_stars(self, p: QPainter) -> None:
        w, h = self.width(), self.height()
        for sx, sy, b in self.stars:
            c = int(90 + 120 * b)
            p.setPen(QColor(c, c, c + 20 if c < 235 else 255))
            p.drawPoint(QPointF(sx * w, sy * h))

    def _draw_planet(self, p: QPainter) -> None:
        c = self.to_screen(0, 0)
        r = self.game.planet_radius * self.scale
        grad = QRadialGradient(c + QPointF(-0.35 * r, -0.35 * r), 1.3 * r)
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

    def _draw_orbit(self, p: QPainter, orbit: Orbit, color: QColor, dashed: bool, width: float) -> None:
        pts = orbit.sample(480, r_max=g.ESCAPE_RADIUS)
        path = QPainterPath(self.to_screen(*pts[0]))
        for x, y in pts[1:]:
            path.lineTo(self.to_screen(x, y))
        pen = QPen(color, width)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _draw_apsides(self, p: QPainter, orbit: Orbit, color: QColor) -> None:
        if orbit.e < 1e-3:
            return  # circular: apsides undefined
        p.setFont(QFont("monospace", 8))
        marks = [("Pe", 0.0)]
        if orbit.bound:
            marks.append(("Ap", math.pi))
        for label, nu in marks:
            pt = self.to_screen(*orbit.point_at(nu))
            p.setPen(QPen(color, 1.5))
            p.setBrush(QBrush(BG))
            p.drawEllipse(pt, 3.5, 3.5)
            p.setPen(color)
            p.drawText(pt + QPointF(6, -6), label)

    def _draw_rocket(self, p: QPainter) -> None:
        gm = self.game
        pos = self.to_screen(*gm.r)
        # Screen y is flipped, so negate the angle for Qt's rotation.
        p.save()
        p.translate(pos)

        # Prograde / retrograde markers around the ship.
        vx, vy = gm.v
        vang = -math.atan2(vy, vx)
        ring = 26.0
        pro = QPointF(ring * math.cos(vang), ring * math.sin(vang))
        p.setPen(QPen(QColor(230, 230, 100), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(pro, 3.5, 3.5)
        p.drawLine(pro + QPointF(0, -3.5), pro + QPointF(0, -7))
        retro = -pro
        p.setPen(QPen(QColor(230, 120, 100), 1.4))
        p.drawLine(retro + QPointF(-3.5, -3.5), retro + QPointF(3.5, 3.5))
        p.drawLine(retro + QPointF(-3.5, 3.5), retro + QPointF(3.5, -3.5))

        p.rotate(-math.degrees(gm.heading))
        p.scale(1.4, 1.4)
        # Ship body pointing along +x.
        body = QPolygonF([
            QPointF(13, 0), QPointF(4, -5), QPointF(-9, -5),
            QPointF(-9, 5), QPointF(4, 5),
        ])
        if gm.thrusting:
            flame_len = (10 + 8 * random.random()) * (0.5 if self.controls.fine else 1.0)
            flame = QPolygonF([QPointF(-9, -3.5), QPointF(-9 - flame_len, 0), QPointF(-9, 3.5)])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 160, 40))
            p.drawPolygon(flame)
            p.setBrush(QColor(255, 240, 160))
            p.drawPolygon(QPolygonF([QPointF(-9, -2), QPointF(-9 - flame_len * 0.5, 0), QPointF(-9, 2)]))
        if gm.rotating:
            # Side thrusters at the nose: firing left side pushes nose right.
            side = 1 if gm.rotating > 0 else -1  # +1 = ccw (nose turns up/left)
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

    def _draw_hud(self, p: QPainter) -> None:
        gm = self.game
        o, t = gm.orbit, gm.target
        rn = math.hypot(*gm.r)
        speed = math.hypot(*gm.v)

        def fmt(x: float) -> str:
            return "  ∞  " if not math.isfinite(x) else f"{x:7.1f}"

        lines = [
            (TEXT_COLOR, f"Altitude {rn - gm.planet_radius:7.1f}   Speed {speed:6.1f}"),
            (TEXT_COLOR, f"Δv used  {gm.burn_dv:7.1f}   Time  {gm.elapsed:6.1f}s"),
            (TEXT_COLOR, ""),
            (DIM_TEXT, "            Periapsis  Apoapsis  Ecc."),
            (CURRENT_COLOR, f"Current      {fmt(o.periapsis)}   {fmt(o.apoapsis)}  {o.e:5.3f}"),
            (TARGET_COLOR, f"Target       {fmt(t.periapsis)}   {fmt(t.apoapsis)}  {t.e:5.3f}"),
        ]
        p.setFont(QFont("monospace", 10))
        y = 22
        for color, text in lines:
            p.setPen(color)
            p.drawText(14, y, text)
            y += 17

        # Deviation gauge (log scale, tolerance marked).
        dev = gm.deviation
        y += 6
        p.setPen(DIM_TEXT)
        dev_txt = "escape" if not math.isfinite(dev) else f"{100 * dev:6.2f}%"
        p.drawText(14, y + 11, f"Deviation {dev_txt}  (win ≤ {100 * gm.tolerance:.1f}%)")
        bar = QRectF(14, y + 18, 300, 10)
        p.setPen(QPen(DIM_TEXT, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(bar)
        lo, hi = math.log10(gm.tolerance / 4), math.log10(2.0)

        def frac(x: float) -> float:
            return max(0.0, min(1.0, (math.log10(max(x, 1e-9)) - lo) / (hi - lo)))

        fill = 1.0 - frac(dev) if math.isfinite(dev) else 0.0
        color = TARGET_COLOR if dev <= gm.tolerance else (WARN_COLOR if dev <= 5 * gm.tolerance else BAD_COLOR)
        p.fillRect(QRectF(bar.x() + 1, bar.y() + 1, (bar.width() - 2) * fill, bar.height() - 2), color)
        tx = bar.x() + bar.width() * (1.0 - frac(gm.tolerance))
        p.setPen(QPen(TEXT_COLOR, 2))
        p.drawLine(QPointF(tx, bar.y() - 3), QPointF(tx, bar.bottom() + 3))

        # Top-right status.
        p.setFont(QFont("monospace", 10))
        right = []
        right.append((TEXT_COLOR, f"Time warp x{gm.time_warp}"))
        if self.paused:
            right.append((WARN_COLOR, "PAUSED"))
        if gm.thrusting:
            right.append((WARN_COLOR, "ENGINE " + ("FINE" if self.controls.fine else "FULL")))
        if not o.bound and gm.status == "playing":
            right.append((BAD_COLOR, "ESCAPE TRAJECTORY"))
        elif o.periapsis < gm.planet_radius and gm.status == "playing":
            right.append((BAD_COLOR, "IMPACT TRAJECTORY"))
        y = 22
        for color, text in right:
            p.setPen(color)
            w = p.fontMetrics().horizontalAdvance(text)
            p.drawText(self.width() - 14 - w, y, text)
            y += 17

        if self.show_help:
            help_lines = [
                "←/→ rotate   ↑ main engine   Shift fine control",
                "1-4 or +/- time warp   P pause   R new orbit   H hide help   Esc quit",
            ]
            p.setFont(QFont("monospace", 9))
            p.setPen(DIM_TEXT)
            y = self.height() - 12 - 15 * (len(help_lines) - 1)
            for text in help_lines:
                p.drawText(14, y, text)
                y += 15

    def _draw_banner(self, p: QPainter) -> None:
        gm = self.game
        if gm.status == "playing":
            return
        title, color = {
            "won": ("ORBIT ACHIEVED", TARGET_COLOR),
            "crashed": ("CRASHED", BAD_COLOR),
            "escaped": ("LOST IN SPACE", BAD_COLOR),
        }[gm.status]
        sub = (
            f"Δv {gm.burn_dv:.1f}   time {gm.elapsed:.1f}s   deviation {100 * gm.deviation:.2f}%"
            if gm.status == "won" else ""
        )
        rect = QRectF(0, self.height() * 0.18, self.width(), 50)
        p.setFont(QFont("sans-serif", 28, QFont.Weight.Bold))
        p.setPen(color)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, title)
        p.setFont(QFont("monospace", 11))
        p.setPen(TEXT_COLOR)
        rect2 = QRectF(0, rect.bottom() + 4, self.width(), 22)
        if sub:
            p.drawText(rect2, Qt.AlignmentFlag.AlignCenter, sub)
            rect2.translate(0, 22)
        p.drawText(rect2, Qt.AlignmentFlag.AlignCenter, "Press Space / Enter for a new orbit")
