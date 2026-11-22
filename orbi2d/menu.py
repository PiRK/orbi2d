# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

"""The main menu: mode selection over an animated planet + moon scene."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

from . import game as g
from .gamepad import Gamepad, PadState
from .graphics import (
    BG,
    CURRENT_COLOR,
    DIM_TEXT,
    FAINT,
    TARGET_COLOR,
    TEXT_COLOR,
    draw_moon,
    draw_planet,
    draw_ship,
    draw_stars,
    make_stars,
)
from .physics import Orbit, propagate


@dataclass(frozen=True)
class MenuItem:
    title: str
    subtitle: str
    mode: str | None  # None = quit


ITEMS = (
    MenuItem("Planetary Orbit", "Match a target orbit around the planet", g.SINGLE),
    MenuItem("Lunar Transfer", "Fly between the planet and its moon", g.MOON_MODE),
    MenuItem("Solar System", "Fly from the blue planet to the gas giant", g.SOLAR),
    MenuItem("Quit", "Close the game", None),
)

# Background scene, in the game's world units (planet radius 40, same MU).
SHIP_ORBIT = Orbit.from_apsides(95.0, 190.0, math.radians(140))
SHIP_TIME_SCALE = 0.5            # the ship orbits at half speed (~17 s)
MOON_DISTANCE = 300.0            # visual only: closer than in the game
MOON_RADIUS = 13.0
MOON_PERIOD = 60.0               # seconds per revolution
MOON_TARGET_RADIUS = 34.0        # dashed "target" orbit around the moon


class MenuWidget(QWidget):
    start_requested = Signal(str)  # game mode
    quit_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(640, 480)
        self.selected = 0
        self.t = 0.0
        self.stars = make_stars()
        self._item_rects: list[QRectF] = []
        self.pad: Gamepad | None = None   # set by the main window
        self._ship_state = g.state_on_orbit(SHIP_ORBIT, math.radians(200), g.MU)
        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    # ---- animation -------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802
        self.clock.restart()
        self.timer.start(16)
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self.timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        self.t += min(self.clock.restart() / 1000.0, 0.05)
        self.apply_pad(self.pad.poll() if self.pad else PadState())
        self.update()

    # ---- input -----------------------------------------------------------
    def activate(self, index: int) -> None:
        item = ITEMS[index]
        if item.mode is None:
            self.quit_requested.emit()
        else:
            self.start_requested.emit(item.mode)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        n = len(ITEMS)
        if key in (Qt.Key.Key_Up, Qt.Key.Key_W):
            self.selected = (self.selected - 1) % n
        elif key in (Qt.Key.Key_Down, Qt.Key.Key_S, Qt.Key.Key_Tab):
            self.selected = (self.selected + 1) % n
        elif event.isAutoRepeat():
            return
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activate(self.selected)
        elif Qt.Key.Key_1 <= key < Qt.Key.Key_1 + n:
            self.selected = key - Qt.Key.Key_1
            self.activate(self.selected)
        elif key == Qt.Key.Key_Escape:
            self.quit_requested.emit()
        else:
            super().keyPressEvent(event)
            return
        self.update()

    def apply_pad(self, pad: PadState) -> None:
        """Controller: up/down to choose, A or Start to select."""
        n = len(ITEMS)
        if "up" in pad.pressed:
            self.selected = (self.selected - 1) % n
        if "down" in pad.pressed:
            self.selected = (self.selected + 1) % n
        if pad.pressed & {"a", "start"}:
            self.activate(self.selected)

    def _item_at(self, pos: QPointF) -> int | None:
        for i, rect in enumerate(self._item_rects):
            if rect.contains(pos):
                return i
        return None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        i = self._item_at(event.position())
        if i is not None and i != self.selected:
            self.selected = i
            self.update()
        self.setCursor(Qt.CursorShape.PointingHandCursor if i is not None
                       else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            i = self._item_at(event.position())
            if i is not None:
                self.selected = i
                self.activate(i)

    # ---- painting --------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), BG)
        draw_stars(p, self.stars, w, h)
        self._draw_scene(p)
        self._draw_text_backdrop(p)
        self._draw_title(p)
        self._draw_items(p)
        self._draw_footer(p)
        p.end()

    def _scene_geometry(self) -> tuple[QPointF, float]:
        """Planet centre on screen and pixels per world unit."""
        w, h = self.width(), self.height()
        center = QPointF(w * 0.66, h * 0.5)
        moon_orbit_px = min(h * 0.42, w * 0.31)
        return center, moon_orbit_px / MOON_DISTANCE

    def _draw_scene(self, p: QPainter) -> None:
        c, s = self._scene_geometry()

        def at(x: float, y: float) -> QPointF:
            return QPointF(c.x() + x * s, c.y() - y * s)

        # Moon orbit and moon (counter-clockwise, slow).
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(FAINT, 1))
        p.drawEllipse(c, MOON_DISTANCE * s, MOON_DISTANCE * s)
        a = 2 * math.pi * self.t / MOON_PERIOD + math.radians(25)
        mx, my = MOON_DISTANCE * math.cos(a), MOON_DISTANCE * math.sin(a)
        target_pen = QPen(TARGET_COLOR, 1.4)
        target_pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(target_pen)
        p.drawEllipse(at(mx, my), MOON_TARGET_RADIUS * s, MOON_TARGET_RADIUS * s)

        # Ship orbit (exact Kepler motion, like in the game).
        path = QPainterPath()
        pts = SHIP_ORBIT.sample(240)
        path.moveTo(at(*pts[0]))
        for x, y in pts[1:]:
            path.lineTo(at(x, y))
        orbit_color = QColor(CURRENT_COLOR)
        orbit_color.setAlpha(150)
        p.setPen(QPen(orbit_color, 1.4))
        p.drawPath(path)

        draw_planet(p, c, g.PLANET_RADIUS * s)
        draw_moon(p, at(mx, my), MOON_RADIUS * s)

        r0, v0 = self._ship_state
        r, v = propagate(r0, v0, self.t * SHIP_TIME_SCALE, g.MU)
        draw_ship(p, at(*r), math.atan2(v[1], v[0]), size=1.2)

    def _draw_text_backdrop(self, p: QPainter) -> None:
        """Darken the left side so the menu stays readable over the scene."""
        w = self.width()
        grad = QLinearGradient(0, 0, w * 0.5, 0)
        dark = QColor(BG)
        dark.setAlpha(225)
        clear = QColor(BG)
        clear.setAlpha(0)
        grad.setColorAt(0.0, dark)
        grad.setColorAt(0.55, dark)
        grad.setColorAt(1.0, clear)
        p.fillRect(QRectF(0, 0, w * 0.5, self.height()), grad)

    def _left(self) -> float:
        return max(28.0, self.width() * 0.07)

    def _draw_title(self, p: QPainter) -> None:
        h = self.height()
        x = self._left()
        font = QFont("sans-serif")
        font.setPixelSize(int(h * 0.085))
        font.setWeight(QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 104)
        p.setFont(font)
        p.setPen(TEXT_COLOR)
        base = h * 0.24
        p.drawText(QPointF(x, base), "orbi")
        orbi_w = p.fontMetrics().horizontalAdvance("orbi")
        p.setPen(CURRENT_COLOR)
        p.drawText(QPointF(x + orbi_w, base), "2d")

        sub = QFont("sans-serif")
        sub.setPixelSize(max(12, int(h * 0.024)))
        sub.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        p.setFont(sub)
        p.setPen(DIM_TEXT)
        p.drawText(QPointF(x + 2, base + h * 0.05), "A GAME OF ORBITAL MECHANICS")

    def _draw_items(self, p: QPainter) -> None:
        h = self.height()
        x = self._left()
        title_font = QFont("sans-serif")
        title_font.setPixelSize(max(16, int(h * 0.036)))
        title_font.setWeight(QFont.Weight.DemiBold)
        sub_font = QFont("sans-serif")
        sub_font.setPixelSize(max(11, int(h * 0.018)))
        step = h * 0.115
        top = h * 0.42
        width = max(260.0, self.width() * 0.34)
        self._item_rects = []
        for i, item in enumerate(ITEMS):
            y = top + i * step
            rect = QRectF(x - 14, y - step * 0.42, width, step * 0.86)
            self._item_rects.append(rect)
            selected = i == self.selected
            if selected:
                fill = QColor(TARGET_COLOR)
                fill.setAlpha(22)
                p.fillRect(rect, fill)
                p.fillRect(QRectF(rect.x(), rect.y(), 3, rect.height()), TARGET_COLOR)
            p.setFont(title_font)
            p.setPen(TARGET_COLOR if selected else TEXT_COLOR)
            p.drawText(QPointF(x + 6, y), item.title)
            p.setFont(sub_font)
            p.setPen(DIM_TEXT if selected else QColor(110, 118, 138))
            p.drawText(QPointF(x + 6, y + h * 0.032), item.subtitle)

    def _draw_footer(self, p: QPainter) -> None:
        font = QFont("monospace")
        font.setPixelSize(12)
        p.setFont(font)
        p.setPen(DIM_TEXT)
        p.drawText(QPointF(self._left(), self.height() - 18),
                   "↑/↓ choose    Enter start    Esc quit")
        if self.pad is not None and self.pad.connected:
            text = f"{self.pad.name} connected: ↑/↓ choose, A start"
            w = p.fontMetrics().horizontalAdvance(text)
            p.drawText(QPointF(self.width() - w - 18, self.height() - 18), text)
