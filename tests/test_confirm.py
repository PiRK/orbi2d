# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

"""Leaving a game or starting a new orbit mid-flight asks first, with time
stopped (keyboard; the controller's Back/A/B are in test_gamepad.py)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from orbi2d import game as g  # noqa: E402
from orbi2d.view import GameWidget  # noqa: E402

K = Qt.Key


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def w(app):
    w = GameWidget(seed=3, mode=g.SOLAR)
    w.resize(800, 600)
    w.timer.stop()
    w.show()
    left = []
    w.exit_requested.connect(lambda: left.append(True))
    w.left = left
    return w


def tick(w, n=5):
    for _ in range(n):
        w.clock.restart()
        w._tick()


def test_esc_asks_and_stops_time(w):
    QTest.keyClick(w, K.Key_Escape)
    assert w.confirm == "leave" and w.left == []
    t = w.game.elapsed
    QTest.keyPress(w, K.Key_Space)   # engine key while asking: ignored
    tick(w)
    QTest.keyRelease(w, K.Key_Space)
    assert w.game.elapsed == t and w.game.burn_dv == 0


def test_enter_confirms_leaving(w):
    QTest.keyClick(w, K.Key_Escape)
    QTest.keyClick(w, K.Key_Return)
    assert w.left == [True] and w.confirm is None


def test_second_esc_cancels_and_time_resumes(w):
    QTest.keyClick(w, K.Key_Escape)
    QTest.keyClick(w, K.Key_Escape)
    assert w.confirm is None and w.left == []
    t = w.game.elapsed
    w.clock.restart()
    QTest.qWait(20)
    w._tick()
    assert w.game.elapsed > t


@pytest.mark.parametrize("key", [K.Key_R, K.Key_N])
def test_new_orbit_asks_first(w, key):
    target = w.game.target
    QTest.keyClick(w, key)
    assert w.confirm == "new" and w.game.target is target
    QTest.keyClick(w, K.Key_Escape)   # no
    assert w.game.target is target
    QTest.keyClick(w, key)
    QTest.keyClick(w, K.Key_Enter)    # yes
    assert w.game.target is not target and w.confirm is None


def test_no_question_once_the_game_is_over(w):
    w.game.status = "crashed"
    QTest.keyClick(w, K.Key_R)
    assert w.confirm is None and w.game.status == "playing"
    w.game.status = "won"
    QTest.keyClick(w, K.Key_Escape)
    assert w.confirm is None and w.left == [True]


def test_pause_state_is_kept_after_cancelling(w):
    QTest.keyClick(w, K.Key_P)
    assert w.paused
    QTest.keyClick(w, K.Key_Escape)
    QTest.keyClick(w, K.Key_Escape)
    assert w.paused and w.confirm is None
