# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

"""The game screen: rendering and input handling."""

from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QWidget

from . import game as g
from .gamepad import Gamepad, PadState
from .graphics import (
    BAD_COLOR,
    BG,
    CURRENT_COLOR,
    DIM_TEXT,
    FAINT,
    PREDICT_COLOR,
    TARGET_COLOR,
    TEXT_COLOR,
    WARN_COLOR,
    draw_body,
    draw_moon,
    draw_planet,
    draw_ship,
    draw_stars,
    make_stars,
)
from .physics import Orbit, Vec

MIN_VIEW_EXTENT = 380.0
THRUST_KEYS = (Qt.Key.Key_Space, Qt.Key.Key_Up)
MIN_MOON_VIEW_EXTENT = 110.0


def fmt_dist(d: float) -> str:
    """Compact distance: 850, 4.2k, 51k."""
    if d >= 10_000:
        return f"{d / 1000:.0f}k"
    if d >= 1000:
        return f"{d / 1000:.1f}k"
    return f"{d:.0f}"


def approach_hint(a: g.ClosestApproach) -> str:
    """Early or late, and the burn that the game found brings it closer."""
    if a.receding and a.fix == 0:
        return "moving away from it: try the next window"
    when = f"{abs(a.lead):.0f} s {'early' if a.lead > 0 else 'late'}"
    if a.fix > 0:
        return f"{when}: burn prograde to close in"
    if a.fix < 0:
        return f"{when}: burn retrograde to close in"
    return f"{when}: no single burn helps (next window?)"


class GameWidget(QWidget):
    exit_requested = Signal()  # Esc: back to the main menu

    def __init__(self, seed: int | None = None, mode: str = g.SINGLE) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(640, 480)
        self.show_help = True
        self.stars = make_stars()
        self.pad: Gamepad | None = None   # set by the main window
        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.start_game(mode, seed)

    def start_game(self, mode: str, seed: int | None = None) -> None:
        """Start a new level in ``mode``, keeping the player's time warp."""
        warp = self.game.time_warp if hasattr(self, "game") else g.DEFAULT_WARP
        self.game = g.Game(seed=seed, mode=mode)
        self.game.set_warp(warp)
        self.controls = g.Controls()       # what the game gets: keyboard + controller
        self.key_controls = g.Controls()   # from the keyboard
        self.thrust_keys: set[int] = set()  # held engine keys (Space, Up)
        # Controller buttons still held from the menu (A starts a game) must
        # be released once before they count, or the engine would fire.
        self.pad_blocked = {"a", "b"}
        self.paused = False
        self.system_view = False   # moon mode: force the whole-system camera
        # Camera: ``focus`` blends the view centre from the planet (0) to the
        # moon (1); ``view_extent`` is the half-size of the view in world units.
        # Solar mode instead follows a body: centre = body position + an
        # offset that decays to zero after switching bodies.
        self.focus, self.view_extent = 0.0, 1.0
        if self.game.mode == g.SOLAR:
            self.cam_body, self.view_extent = self._desired_solar_view()
            self.cam_offset: Vec = (0.0, 0.0)
        else:
            self.focus, self.view_extent = self._desired_view()
        self.clock.restart()

    # Only animate while visible (the menu and the game share one window).
    def showEvent(self, event) -> None:  # noqa: N802
        self.clock.restart()
        self.timer.start(16)
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self.timer.stop()
        super().hideEvent(event)

    # ---- loop ------------------------------------------------------------
    def _tick(self) -> None:
        dt = min(self.clock.restart() / 1000.0, 0.05)
        self.apply_pad(self.pad.poll() if self.pad else PadState())
        if not self.paused:
            self.game.update(dt, self.controls)
        self.step_camera(dt)
        self.update()

    def step_camera(self, dt: float) -> None:
        if self.game.mode == g.SOLAR:
            self._step_solar_camera(dt)
            return
        focus, extent = self._desired_view()
        k = min(1.0, dt * 2.5)
        self.focus += (focus - self.focus) * k
        self.view_extent += (extent - self.view_extent) * k

    def _planet_view(self) -> tuple[float, float]:
        """Frame the current orbit and the target around the planet."""
        gm = self.game
        rn = math.hypot(*gm.r)
        far = max(gm.target.apoapsis, rn)
        if gm.orbit.bound:
            far = max(far, min(gm.orbit.apoapsis, g.ESCAPE_RADIUS))
        return 0.0, max(MIN_VIEW_EXTENT, 1.12 * far)

    def _desired_view(self) -> tuple[float, float]:
        gm = self.game
        if gm.moon is None:
            return self._planet_view()

        moon, o = gm.moon, gm.orbit
        if (not self.system_view and gm.primary == g.MOON
                and o.bound and o.apoapsis < moon.soi):
            far = max(o.apoapsis, math.hypot(*gm.r))
            if gm.target_body == g.MOON:
                far = max(far, gm.target.apoapsis)
            return 1.0, max(MIN_MOON_VIEW_EXTENT, 1.3 * far)
        # Back around the planet for a planet target, on an orbit that can't
        # reach the moon: zoom on the planet as in Planetary Orbit mode, so
        # the final adjustments aren't made from the whole-system view.
        if (not self.system_view and gm.primary == g.PLANET
                and gm.target_body == g.PLANET and o.bound
                and o.apoapsis < moon.distance - moon.soi and gm.transition is None):
            return self._planet_view()
        far = max(moon.distance + moon.soi, math.hypot(*gm.world_r))
        if gm.primary == g.PLANET and o.bound:
            far = max(far, min(o.apoapsis, g.ESCAPE_RADIUS))
        return 0.0, max(MIN_VIEW_EXTENT, 1.05 * far)

    def _step_solar_camera(self, dt: float) -> None:
        body, extent = self._desired_solar_view()
        if body != self.cam_body:
            # Keep the current centre, then glide to the new body.
            cx, cy = self.camera_center
            bx, by = self.game.body_position(body)
            self.cam_body, self.cam_offset = body, (cx - bx, cy - by)
        decay = math.exp(-3.0 * dt)
        self.cam_offset = (self.cam_offset[0] * decay, self.cam_offset[1] * decay)
        # Zoom on a log scale: the extent spans orders of magnitude.
        k = min(1.0, dt * 2.5)
        self.view_extent *= (extent / self.view_extent) ** k

    def _desired_solar_view(self) -> tuple[str, float]:
        """Body to centre on and view half-size, in solar mode."""
        gm = self.game
        if self.system_view:
            giant = gm.bodies[g.GIANT]
            return gm.root, 1.08 * (giant.distance + giant.soi)
        body = gm.bodies[gm.primary]
        o = gm.orbit
        rn = math.hypot(*gm.r)
        if body.parent is None:   # around the Sun
            far = rn
            if o.bound:
                far = max(far, min(o.apoapsis, gm.escape_radius))
            if gm.target_body == body.name:
                far = max(far, gm.target.apoapsis)
            return body.name, max(5_000.0, 1.12 * far)
        if o.bound and o.apoapsis < body.soi:
            far = max(o.apoapsis, rn)
            if gm.target_body == body.name:
                far = max(far, gm.target.apoapsis)
            return body.name, max(4.0 * body.radius, 1.3 * far)
        return body.name, 1.15 * body.soi   # leaving: show the whole SOI

    # ---- input -----------------------------------------------------------
    def apply_pad(self, pad: PadState) -> None:
        """Controller: held buttons steer and fire the engine (combined with
        the keyboard), pressed buttons trigger actions."""
        # Actions first: a new level blocks the button that started it.
        gm = self.game
        pressed = pad.pressed
        if "a" in pressed and gm.status != "playing":
            self.new_level()
        if "x" in pressed:
            self.new_level()
        if "lb" in pressed:
            gm.slower()
        if "rb" in pressed:
            gm.faster()
        if pressed & {"up", "down"} and len(gm.targets) > 1:
            gm.cycle_target()
        if "y" in pressed:
            self.system_view = not self.system_view
        if "start" in pressed:
            self.paused = not self.paused
        if "back" in pressed:
            self.leave()
        self.pad_blocked &= pad.held   # released once: usable again
        held = pad.held - self.pad_blocked
        k = self.key_controls
        full, fine = "a" in held, "b" in held
        self.controls = g.Controls(
            left=k.left or "left" in held,
            right=k.right or "right" in held,
            thrust=k.thrust or full or fine,
            # B: 10% thrust (and fine turning, like Shift); A wins over B.
            fine=k.fine or (fine and not full),
        )

    def new_level(self) -> None:
        self.game.reset()
        self.paused = False
        self.pad_blocked = {"a", "b"}

    def leave(self) -> None:
        """Back to the main menu."""
        self.key_controls = g.Controls()
        self.controls = g.Controls()
        self.thrust_keys.clear()
        self.exit_requested.emit()

    def _set_key(self, event: QKeyEvent, pressed: bool) -> bool:
        key = event.key()
        k = self.key_controls
        if key == Qt.Key.Key_Left:
            k.left = pressed
        elif key == Qt.Key.Key_Right:
            k.right = pressed
        elif key in THRUST_KEYS:
            # Either key fires the engine; it stays on while any is held.
            if pressed:
                self.thrust_keys.add(key)
            else:
                self.thrust_keys.discard(key)
            k.thrust = bool(self.thrust_keys)
        elif key == Qt.Key.Key_Shift:
            k.fine = pressed
        else:
            return False
        # Keyboard-only play still works when no timer tick merges inputs.
        self.controls = g.Controls(k.left, k.right, k.thrust, k.fine)
        return True

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self._set_key(event, True):
            return
        if event.isAutoRepeat():
            return
        key = event.key()
        gm = self.game
        if key in (Qt.Key.Key_R, Qt.Key.Key_N) or (
            key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and gm.status != "playing"
        ):
            self.new_level()
        elif key in (Qt.Key.Key_Tab, Qt.Key.Key_T) and len(gm.targets) > 1:
            gm.cycle_target()
        elif key == Qt.Key.Key_V:
            self.system_view = not self.system_view
        elif key == Qt.Key.Key_P:
            self.paused = not self.paused
        elif key == Qt.Key.Key_H:
            self.show_help = not self.show_help
        elif Qt.Key.Key_1 <= key < Qt.Key.Key_1 + len(gm.warp_presets):
            gm.set_warp(gm.warp_presets[key - Qt.Key.Key_1])
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            gm.faster()
        elif key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            gm.slower()
        elif key == Qt.Key.Key_Escape:
            self.leave()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.isAutoRepeat():
            return
        if not self._set_key(event, False):
            super().keyReleaseEvent(event)

    def focusNextPrevChild(self, next: bool) -> bool:  # noqa: N802
        return False   # Tab switches targets instead of moving the focus

    def focusOutEvent(self, event) -> None:  # noqa: N802
        # Don't leave the engine stuck on when the window loses focus.
        self.key_controls = g.Controls()
        self.controls = g.Controls()
        self.thrust_keys.clear()
        super().focusOutEvent(event)

    # ---- coordinates -------------------------------------------------------
    @property
    def scale(self) -> float:
        return 0.5 * min(self.width(), self.height()) / self.view_extent

    @property
    def camera_center(self) -> Vec:
        gm = self.game
        if gm.mode == g.SOLAR:
            bx, by = gm.body_position(self.cam_body)
            return bx + self.cam_offset[0], by + self.cam_offset[1]
        if gm.moon is None or self.focus == 0.0:
            return 0.0, 0.0
        mx, my = gm.moon.position(gm.elapsed)
        return self.focus * mx, self.focus * my

    def to_screen(self, x: float, y: float) -> QPointF:
        s = self.scale
        cx, cy = self.camera_center
        return QPointF(self.width() / 2 + (x - cx) * s, self.height() / 2 - (y - cy) * s)

    # ---- painting ----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), BG)
        draw_stars(p, self.stars, self.width(), self.height())

        gm = self.game
        if gm.mode == g.SOLAR:
            self._paint_solar(p)
            p.end()
            return
        moon = gm.moon
        soi = moon.soi if moon else None
        if moon:
            self._draw_moon_path(p)
        matched = gm.deviation <= gm.tolerance
        target_center = gm.body_position(gm.target_body)
        primary_center = gm.body_position(gm.primary)
        self._draw_orbit(p, gm.target, TARGET_COLOR, dashed=True,
                         width=2.0 if not matched else 3.0, center=target_center)
        tr = gm.transition
        if tr is not None:
            self._draw_transition(p, tr)
        # Unbound around the moon is just a flyby; unbound around the planet
        # means leaving the system.
        escaping = not gm.orbit.bound and gm.primary == g.PLANET
        cur_color = TARGET_COLOR if matched else (BAD_COLOR if escaping else CURRENT_COLOR)
        clip = soi if gm.primary == g.MOON else None
        self._draw_orbit(p, gm.orbit, cur_color, dashed=False, width=1.6,
                         center=primary_center, clip=clip)
        self._draw_planet(p)
        if moon:
            self._draw_moon(p, moon.position(gm.elapsed))
        self._draw_apsides(p, gm.target, TARGET_COLOR, target_center)
        self._draw_apsides(p, gm.orbit, cur_color, primary_center, clip)
        self._draw_rocket(p)
        self._draw_hud(p)
        self._draw_banner(p)
        p.end()

    def _paint_solar(self, p: QPainter) -> None:
        gm = self.game
        s = self.scale
        # Orbits of the bodies and their spheres of influence.
        for b in gm.bodies.values():
            if b.parent is None:
                continue
            r_px = b.distance * s
            if 3 < r_px < 5e5:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(FAINT, 1))
                p.drawEllipse(self.to_screen(*gm.body_position(b.parent)), r_px, r_px)
            soi_px = b.soi * s
            if 6 < soi_px < 5e5:
                pen = QPen(QColor(170, 170, 200, 90), 1)
                pen.setStyle(Qt.PenStyle.DotLine)
                p.setPen(pen)
                p.drawEllipse(self.to_screen(*gm.body_position(b.name)), soi_px, soi_px)

        matched = gm.deviation <= gm.tolerance
        target_center = gm.body_position(gm.target_body)
        other = QColor(TARGET_COLOR)
        other.setAlpha(110)
        for body, orbit in gm.targets.items():
            selected = body == gm.target_body
            self._draw_orbit(p, orbit, TARGET_COLOR if selected else other, dashed=True,
                             width=(3.0 if matched else 2.0) if selected else 1.3,
                             center=gm.body_position(body), clip=self._clip_for(body))
        for i, tr in enumerate(gm.transitions):
            self._draw_solar_transition(p, tr, alpha=255 - 60 * i)
        self._draw_approaches(p)
        primary_center = gm.body_position(gm.primary)
        escaping = self._solar_escaping()
        cur_color = TARGET_COLOR if matched else (BAD_COLOR if escaping else CURRENT_COLOR)
        clip = self._clip_for(gm.primary)
        self._draw_orbit(p, gm.orbit, cur_color, dashed=False, width=1.6,
                         center=primary_center, clip=clip)
        self._draw_solar_bodies(p)
        self._draw_apsides(p, gm.target, TARGET_COLOR, target_center, self._clip_for(gm.target_body))
        self._draw_apsides(p, gm.orbit, cur_color, primary_center, clip)
        self._draw_rocket(p)
        self._draw_hud(p)
        self._draw_banner(p)

    def _solar_escaping(self) -> bool:
        """Around the Sun on an orbit that leaves the play area (open, or
        reaching past the escape radius, e.g. after a big slingshot)."""
        gm = self.game
        o = gm.orbit
        return gm.primary == gm.root and (not o.bound or o.apoapsis > gm.escape_radius)

    def _clip_for(self, body: str) -> float | None:
        b = self.game.bodies[body]
        return b.soi if b.parent is not None else None

    def _draw_solar_bodies(self, p: QPainter) -> None:
        gm = self.game
        s = self.scale
        font = QFont("sans-serif")
        font.setPixelSize(11)
        for b in gm.bodies.values():
            c = self.to_screen(*gm.body_position(b.name))
            min_px = 6.0 if b.parent is None else 2.5
            r_px = max(b.radius * s, min_px)
            draw_body(p, b.name, c, r_px)
            # Label small bodies, unless they sit on top of their parent.
            if r_px < 30 and (b.parent is None or b.distance * s > 14):
                p.setFont(font)
                p.setPen(DIM_TEXT)
                p.drawText(c + QPointF(r_px + 5, -r_px - 3), b.label)

    def _draw_solar_transition(self, p: QPainter, tr: g.Transition, alpha: int) -> None:
        """Predicted SOI crossing: ghost of the body entered, crossing
        point, and the orbit after the crossing."""
        gm = self.game
        s = self.scale
        color = QColor(PREDICT_COLOR)
        color.setAlpha(max(80, alpha))
        body = gm.bodies[tr.body]
        if body.parent == tr.from_body:   # entering: where the body will be
            c = self.to_screen(*tr.body_pos)
            pen = QPen(color, 1)
            pen.setStyle(Qt.PenStyle.DotLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, body.soi * s, body.soi * s)
            p.setPen(QPen(color, 1.2))
            r_px = max(body.radius * s, 2.5)
            p.drawEllipse(c, r_px, r_px)
        self._draw_orbit(p, tr.orbit, color, dashed=True, width=1.3,
                         center=tr.body_pos, clip=self._clip_for(tr.body))
        if body.parent is not None and tr.orbit.periapsis < body.soi:
            # Where the flyby passes closest, and how high above the surface.
            x, y = tr.orbit.point_at(0.0)
            pe = self.to_screen(tr.body_pos[0] + x, tr.body_pos[1] + y)
            p.setPen(QPen(color, 1.5))
            p.setBrush(QBrush(BG))
            p.drawEllipse(pe, 3.5, 3.5)
            p.setFont(QFont("monospace", 8))
            p.setPen(color)
            alt = tr.orbit.periapsis - body.radius
            p.drawText(pe + QPointF(6, -6), "IMPACT" if alt <= 0 else f"Pe alt {fmt_dist(alt)}")
        pt = self.to_screen(*tr.point)
        p.setPen(QPen(color, 1.5))
        p.setBrush(QBrush(BG))
        p.drawPolygon(QPolygonF([pt + QPointF(0, -5), pt + QPointF(5, 0),
                                 pt + QPointF(0, 5), pt + QPointF(-5, 0)]))

    def _draw_approaches(self, p: QPainter) -> None:
        """Closest approaches to the target's planet, and to other planets
        passed nearby: where the rocket and the planet will be, how far."""
        gm = self.game
        s = self.scale
        entered = {tr.body for tr in gm.transitions}
        color = QColor(WARN_COLOR)
        for a in gm.approaches:
            body = gm.bodies[a.body]
            if a.body in entered or body.parent is None:
                continue
            if a.body != gm.target_body and a.distance > 4 * body.soi:
                continue
            rocket = self.to_screen(*a.point)
            planet = self.to_screen(*a.body_pos)
            pen = QPen(color, 1)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(rocket, planet)
            pen.setStyle(Qt.PenStyle.DotLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(planet, body.soi * s, body.soi * s)
            p.setPen(QPen(color, 1.3))
            r_px = max(body.radius * s, 3.0)
            p.drawEllipse(planet, r_px, r_px)
            p.drawLine(rocket + QPointF(-4, -4), rocket + QPointF(4, 4))
            p.drawLine(rocket + QPointF(-4, 4), rocket + QPointF(4, -4))
            p.setFont(QFont("monospace", 8))
            p.setPen(color)
            mid = (rocket + planet) / 2
            p.drawText(mid + QPointF(6, -4),
                       f"closest {fmt_dist(a.distance)} (SOI {fmt_dist(body.soi)})")
            if a.body == gm.target_body:   # the hint is about reaching the target
                p.drawText(mid + QPointF(6, 8), approach_hint(a))

    def _draw_planet(self, p: QPainter) -> None:
        draw_planet(p, self.to_screen(0, 0), self.game.planet_radius * self.scale)

    def _draw_moon(self, p: QPainter, pos: Vec) -> None:
        draw_moon(p, self.to_screen(*pos), self.game.moon.radius * self.scale)

    def _draw_moon_path(self, p: QPainter) -> None:
        """Moon's orbit around the planet and its sphere of influence."""
        gm = self.game
        moon = gm.moon
        s = self.scale
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(FAINT, 1))
        p.drawEllipse(self.to_screen(0, 0), moon.distance * s, moon.distance * s)
        pen = QPen(QColor(170, 170, 200, 110), 1)
        pen.setStyle(Qt.PenStyle.DotLine)
        p.setPen(pen)
        p.drawEllipse(self.to_screen(*moon.position(gm.elapsed)), moon.soi * s, moon.soi * s)

    def _draw_transition(self, p: QPainter, tr: g.Transition) -> None:
        """Predicted SOI crossing: ghost moon, crossing point, next orbit."""
        gm = self.game
        moon = gm.moon
        s = self.scale
        if tr.body == g.MOON:
            # Where the moon will be when the rocket arrives.
            c = self.to_screen(*tr.moon_pos)
            pen = QPen(PREDICT_COLOR, 1)
            pen.setStyle(Qt.PenStyle.DotLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, moon.soi * s, moon.soi * s)
            p.setPen(QPen(PREDICT_COLOR, 1.2))
            p.drawEllipse(c, moon.radius * s, moon.radius * s)
            center, clip = tr.moon_pos, moon.soi
        else:
            center, clip = (0.0, 0.0), None
        self._draw_orbit(p, tr.orbit, PREDICT_COLOR, dashed=True, width=1.3,
                         center=center, clip=clip)
        pt = self.to_screen(*tr.point)
        p.setPen(QPen(PREDICT_COLOR, 1.5))
        p.setBrush(QBrush(BG))
        p.drawPolygon(QPolygonF([pt + QPointF(0, -5), pt + QPointF(5, 0),
                                 pt + QPointF(0, 5), pt + QPointF(-5, 0)]))

    def _draw_orbit(self, p: QPainter, orbit: Orbit, color: QColor, dashed: bool,
                    width: float, center: Vec = (0.0, 0.0), clip: float | None = None) -> None:
        """Draw ``orbit`` around ``center``; parts farther than ``clip`` from
        the centre (outside a sphere of influence) are left out."""
        cx, cy = center
        pts = orbit.sample(480, r_max=clip if clip is not None else self.game.escape_radius)
        path = QPainterPath()
        pen_down = False
        for x, y in pts:
            if clip is not None and math.hypot(x, y) > clip * 1.0001:
                pen_down = False
                continue
            q = self.to_screen(cx + x, cy + y)
            if pen_down:
                path.lineTo(q)
            else:
                path.moveTo(q)
                pen_down = True
        pen = QPen(color, width)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _draw_apsides(self, p: QPainter, orbit: Orbit, color: QColor,
                      center: Vec = (0.0, 0.0), clip: float | None = None) -> None:
        if orbit.e < 1e-3:
            return  # circular: apsides undefined
        p.setFont(QFont("monospace", 8))
        marks = [("Pe", 0.0)]
        if orbit.bound:
            marks.append(("Ap", math.pi))
        for label, nu in marks:
            x, y = orbit.point_at(nu)
            if clip is not None and math.hypot(x, y) > clip:
                continue
            pt = self.to_screen(center[0] + x, center[1] + y)
            p.setPen(QPen(color, 1.5))
            p.setBrush(QBrush(BG))
            p.drawEllipse(pt, 3.5, 3.5)
            p.setPen(color)
            p.drawText(pt + QPointF(6, -6), label)

    def _draw_rocket(self, p: QPainter) -> None:
        gm = self.game
        pos = self.to_screen(*gm.world_r)
        p.save()
        p.translate(pos)
        # Prograde / retrograde markers (velocity relative to the body being
        # orbited) around the ship.  Screen y is flipped, hence the minus.
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
        p.restore()
        thrust = ("fine" if self.controls.fine else "full") if gm.thrusting else None
        draw_ship(p, pos, gm.heading, thrust=thrust, rotating=gm.rotating)

    def _draw_hud(self, p: QPainter) -> None:
        gm = self.game
        o, t = gm.orbit, gm.target
        rn = math.hypot(*gm.r)
        speed = math.hypot(*gm.v)
        moon_mode = gm.moon is not None
        solar = gm.mode == g.SOLAR

        def fmt(x: float) -> str:
            return "  ∞  " if not math.isfinite(x) else f"{x:7.1f}"

        lines = [
            (TEXT_COLOR, f"Altitude {rn - gm.radius_of(gm.primary):7.1f}   Speed {speed:6.1f}"),
            (TEXT_COLOR, f"Δv used  {gm.burn_dv:7.1f}   Time  {gm.elapsed:6.1f}s"),
            (TEXT_COLOR, ""),
        ]
        if solar:   # the selected target has its own line below
            lines.insert(2, (TEXT_COLOR, f"Orbiting {gm.label(gm.primary)}"))
        elif moon_mode:
            lines.insert(2, (TEXT_COLOR, f"Orbiting {gm.label(gm.primary):7}   "
                                         f"Target around {gm.label(gm.target_body)}"))
        if solar:
            extra = []
            if len(gm.targets) > 1:
                others = [gm.label(b) for b in gm.targets if b != gm.target_body]
                extra.append((TARGET_COLOR, f"Selected target: {gm.label(gm.target_body)}   "
                                            f"(Tab: {', '.join(others)})"))
            window = gm.transfer_window()
            if window is not None and gm.primary == g.PLANET:
                phase, ideal, wait = window
                name = gm.label(gm.target_body)
                if abs((phase - ideal + 180) % 360 - 180) < 3:
                    extra.append((TARGET_COLOR, f"Window to {name}: NOW ({phase:.0f}° ahead)"))
                else:
                    extra.append((TEXT_COLOR, f"Window to {name}: {phase:.0f}° ahead, "
                                              f"best {ideal:.0f}° (in {wait:.0f}s)"))
            if gm.assists:
                names = ", ".join(gm.label(a.body) for a in gm.assists)
                extra.append((PREDICT_COLOR, f"Gravity assists: +{gm.assist_dv:.1f} Δv ({names})"))
            lines[3:3] = extra
        lines += [
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
        if math.isfinite(dev):
            dev_txt = f"{100 * dev:6.2f}%"
        elif solar and gm.primary != gm.target_body:
            dev_txt = f"  --  (orbit the {gm.label(gm.target_body)} first)"
        elif moon_mode and gm.primary != gm.target_body:
            dev_txt = f"  --  (get to the {gm.target_body} first)"
        else:
            dev_txt = "escape"
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
        if solar and gm.effective_warp < gm.time_warp:
            right.append((TEXT_COLOR, f"Time warp x{gm.time_warp:g} (auto x{gm.effective_warp:.3g})"))
        else:
            right.append((TEXT_COLOR, f"Time warp x{gm.time_warp:g}"))
        if moon_mode and self.system_view:
            right.append((DIM_TEXT, "System view"))
        if self.paused:
            right.append((WARN_COLOR, "PAUSED"))
        if gm.thrusting:
            right.append((WARN_COLOR, "ENGINE " + ("FINE" if self.controls.fine else "FULL")))
        if gm.status == "playing":
            tr = gm.transition
            if tr is not None and solar:
                if gm.bodies[tr.body].parent == tr.from_body:
                    what = f"{gm.label(tr.body).upper()} ENCOUNTER"
                else:
                    what = f"LEAVING {gm.label(tr.from_body).upper()} SOI"
                assist = gm.predicted_assist(0)
                more = f" (assist +{assist:.0f})" if assist is not None else ""
                right.append((PREDICT_COLOR, f"{what} in {tr.time - gm.elapsed:6.1f}s{more}"))
            elif tr is not None:
                what = "MOON ENCOUNTER" if tr.body == g.MOON else "LEAVING MOON SOI"
                right.append((PREDICT_COLOR, f"{what} in {tr.time - gm.elapsed:5.1f}s"))
            if (self._solar_escaping() if solar else not o.bound and gm.primary == gm.root):
                right.append((BAD_COLOR, "ESCAPE TRAJECTORY"))
            elif o.periapsis < gm.radius_of(gm.primary) and tr is None:
                right.append((BAD_COLOR, "IMPACT TRAJECTORY"))
        y = 22
        for color, text in right:
            p.setPen(color)
            w = p.fontMetrics().horizontalAdvance(text)
            p.drawText(self.width() - 14 - w, y, text)
            y += 17

        if self.show_help:
            help_lines = [
                "←/→ rotate   Space (or ↑) main engine   Shift fine control",
                f"1-{len(gm.warp_presets)} or +/- time warp   P pause   R new orbit"
                + ("   V system view" if moon_mode else "")
                + ("   Tab switch target" if len(gm.targets) > 1 else ""),
                "H hide help   Esc main menu",
            ]
            if self.pad is not None and self.pad.connected:
                help_lines.append(
                    f"{self.pad.name}: ◀▶ rotate   A thrust   B fine thrust   LB/RB warp   "
                    + ("Y system view   " if moon_mode else "")
                    + ("▲▼ switch target   " if len(gm.targets) > 1 else "")
                    + "X new orbit   Start pause   Back menu")
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
        if sub and gm.mode == g.SOLAR and gm.reached:
            sub = f"Orbit around the {gm.label(gm.reached)}   " + sub
        if sub and gm.mode == g.SOLAR and gm.assists:
            sub += f"   gravity assists +{gm.assist_dv:.1f} Δv"
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
        p.drawText(rect2, Qt.AlignmentFlag.AlignCenter, "Enter: new orbit     Esc: main menu")
