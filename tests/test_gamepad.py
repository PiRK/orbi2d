# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

"""Game controller support, tested with SDL virtual controllers (no real
hardware needed; a real controller that happens to be plugged in is never
read, the tests open their virtual one explicitly)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("sdl2")

from PySide6.QtWidgets import QApplication  # noqa: E402

from orbi2d import game as g  # noqa: E402
from orbi2d.gamepad import Gamepad, VirtualPad  # noqa: E402
from orbi2d.menu import MenuWidget  # noqa: E402
from orbi2d.view import GameWidget  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def pad():
    gp = Gamepad()
    assert gp.available
    vp = VirtualPad()
    assert gp.open(vp.index)
    yield gp, vp
    gp.close()
    vp.unplug()


@pytest.fixture
def game(app, pad):
    gp, vp = pad
    w = GameWidget(seed=1, mode=g.SINGLE)
    w.timer.stop()
    w.pad = gp
    w.apply_pad(gp.poll())   # a first frame with nothing pressed, as in play
    return w, gp, vp


def test_buttons_report_held_and_newly_pressed(pad):
    gp, vp = pad
    assert gp.connected and gp.name == "orbi2d virtual pad"
    vp.set("a", True)
    s = gp.poll()
    assert "a" in s.held and "a" in s.pressed
    s = gp.poll()
    assert "a" in s.held and "a" not in s.pressed   # still down, not new
    vp.set("a", False)
    assert "a" not in gp.poll().held


def test_left_stick_counts_as_directions(pad):
    gp, vp = pad
    vp.stick(-0.8)
    assert "left" in gp.poll().held
    vp.stick(0.3)          # small deflection: nothing
    assert not gp.poll().held
    vp.stick(0.0, -0.9)    # stick up
    assert "up" in gp.poll().held


def _press(w, gp, vp, *buttons, down=True):
    for b in buttons:
        vp.set(b, down)
    w.apply_pad(gp.poll())


def test_a_full_thrust_b_fine_thrust(game):
    w, gp, vp = game
    _press(w, gp, vp, "a")
    assert w.controls.thrust and not w.controls.fine
    _press(w, gp, vp, "a", down=False)
    _press(w, gp, vp, "b")
    assert w.controls.thrust and w.controls.fine
    _press(w, gp, vp, "a")              # A and B: full thrust wins
    assert w.controls.thrust and not w.controls.fine
    _press(w, gp, vp, "a", "b", down=False)
    assert not w.controls.thrust
    # The engine really fires.
    _press(w, gp, vp, "a")
    w.game.update(1 / 60, w.controls)
    assert w.game.thrusting and w.game.burn_dv > 0


def test_dpad_rotates(game):
    w, gp, vp = game
    _press(w, gp, vp, "left")
    assert w.controls.left and not w.controls.right
    heading = w.game.heading
    w.game.update(1 / 60, w.controls)
    assert w.game.heading > heading   # counter-clockwise


def test_shoulders_change_time_warp(game):
    w, gp, vp = game
    w.game.set_warp(1.0)
    _press(w, gp, vp, "rb")
    assert w.game.time_warp == pytest.approx(1.25)
    _press(w, gp, vp, "rb", down=False)
    _press(w, gp, vp, "lb")
    _press(w, gp, vp, "lb", down=False)
    _press(w, gp, vp, "lb")
    assert w.game.time_warp == pytest.approx(0.8)


def test_start_pauses_and_back_returns_to_menu(game):
    w, gp, vp = game
    left = []
    w.exit_requested.connect(lambda: left.append(True))
    _press(w, gp, vp, "start")
    assert w.paused
    _press(w, gp, vp, "start", down=False)
    _press(w, gp, vp, "back")
    assert left == [True]


def test_button_held_from_the_menu_does_not_fire_the_engine(game):
    w, gp, vp = game
    vp.set("a", True)        # A pressed on the start screen...
    gp.poll()
    w.start_game(g.SINGLE)   # ...starts the game while still held
    _press(w, gp, vp, "a")
    assert not w.controls.thrust
    _press(w, gp, vp, "a", down=False)
    _press(w, gp, vp, "a")   # pressed again: now it counts
    assert w.controls.thrust


def test_a_after_a_game_ends_starts_a_new_level(game):
    w, gp, vp = game
    w.game.status = "won"
    old_target = w.game.target
    _press(w, gp, vp, "a")
    assert w.game.status == "playing" and w.game.target != old_target
    assert not w.controls.thrust   # the same press doesn't fire the engine


def test_keyboard_and_controller_combine(game):
    w, gp, vp = game
    w.key_controls.left = True
    _press(w, gp, vp, "a")
    assert w.controls.left and w.controls.thrust


def test_menu_choose_and_start(app, pad):
    gp, vp = pad
    m = MenuWidget()
    m.timer.stop()
    started = []
    m.start_requested.connect(started.append)
    _press(m, gp, vp, "down")
    assert m.selected == 1
    _press(m, gp, vp, "down", down=False)
    _press(m, gp, vp, "a")
    assert started == [g.MOON_MODE]


def test_unplug_and_plug_back_in(app):
    gp = Gamepad()
    vp = VirtualPad()
    assert gp.open(vp.index)
    vp.unplug()
    gp.poll()
    assert not gp.connected or gp.name != "orbi2d virtual pad"
    vp2 = VirtualPad("orbi2d second pad")
    gp.close()
    for _ in range(3):
        gp.poll()   # finds a controller again on its own
    assert gp.connected
    gp.close()
    vp2.unplug()
