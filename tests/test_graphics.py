# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

"""Sun lighting of the bodies (drawn offscreen, measured pixel by pixel)."""

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from orbi2d import game as g  # noqa: E402
from orbi2d.graphics import draw_body  # noqa: E402

SIZE = 200


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


def render(name, light):
    img = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.black)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_body(p, name, QPointF(SIZE / 2, SIZE / 2), 60.0, light)
    p.end()
    return img


def brightness_towards(img, direction):
    """Mean brightness of the disc's half facing ``direction`` minus the
    half facing away (positive: that side is the lit one)."""
    dx, dy = direction
    lit = dark = 0.0
    n = m = 0
    for y in range(SIZE):
        for x in range(SIZE):
            px, py = x - SIZE / 2, y - SIZE / 2
            if px * px + py * py > 55 * 55:
                continue
            v = QColor(img.pixel(x, y)).lightnessF()
            if px * dx + py * dy > 0:
                lit, n = lit + v, n + 1
            else:
                dark, m = dark + v, m + 1
    return lit / n - dark / m


@pytest.mark.parametrize("name", ["planet", "moon", "red", "giant"])
@pytest.mark.parametrize("angle", [0, 90, 200, 300])
def test_lit_side_faces_the_light(name, angle):
    a = math.radians(angle)
    light = (math.cos(a), math.sin(a))
    img = render(name, light)
    assert brightness_towards(img, light) > 0.15


def test_without_a_light_the_classic_top_left_highlight_stays():
    img = render("planet", None)
    up_left = (-math.sqrt(0.5), -math.sqrt(0.5))
    assert brightness_towards(img, up_left) > 0.05
    # No night side drawn: the bottom-right half isn't darkened like a lit one.
    lit = render("planet", up_left)
    assert brightness_towards(lit, up_left) > brightness_towards(img, up_left)


def test_game_lights_planets_from_the_sun():
    from orbi2d.view import GameWidget

    for seed in (4, 7):
        w = GameWidget(seed=seed, mode=g.SOLAR)
        w.resize(1100, 850)
        w.timer.stop()
        w.show_help = False
        for _ in range(300):
            w.step_camera(1 / 30)
        img = w.grab().toImage()
        gm = w.game
        c = w.to_screen(*gm.body_position(g.PLANET))
        sun = w.to_screen(*gm.body_position(gm.root))
        d = (sun.x() - c.x(), sun.y() - c.y())
        n = math.hypot(*d)
        d = (d[0] / n, d[1] / n)
        r = gm.radius_of(g.PLANET) * w.scale * 0.8
        # Brightness just inside the disc, on the Sun's side vs the far side.
        near = QColor(img.pixel(int(c.x() + d[0] * r), int(c.y() + d[1] * r))).lightnessF()
        far = QColor(img.pixel(int(c.x() - d[0] * r), int(c.y() - d[1] * r))).lightnessF()
        assert near > far + 0.2
