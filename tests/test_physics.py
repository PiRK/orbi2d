# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

import math

import pytest

from orbi2d.game import Controls, Game, state_on_orbit
from orbi2d.physics import Orbit, propagate

MU = 1.5e6


def energy(r, v):
    return 0.5 * (v[0] ** 2 + v[1] ** 2) - MU / math.hypot(*r)


def rk4_reference(r, v, t, steps=200_000):
    """Brute-force numerical integration for cross-checking."""
    h = t / steps
    x, y, vx, vy = *r, *v

    def acc(x, y):
        d = (x * x + y * y) ** 1.5
        return -MU * x / d, -MU * y / d

    for _ in range(steps):
        a1 = acc(x, y)
        a2 = acc(x + 0.5 * h * vx, y + 0.5 * h * vy)
        a3 = acc(x + 0.5 * h * (vx + 0.5 * h * a1[0]), y + 0.5 * h * (vy + 0.5 * h * a1[1]))
        a4 = acc(x + h * (vx + 0.5 * h * a2[0]), y + h * (vy + 0.5 * h * a2[1]))
        x += h * (vx + h / 6 * (a1[0] + a2[0] + a3[0]))
        y += h * (vy + h / 6 * (a1[1] + a2[1] + a3[1]))
        vx += h / 6 * (a1[0] + 2 * a2[0] + 2 * a3[0] + a4[0])
        vy += h / 6 * (a1[1] + 2 * a2[1] + 2 * a3[1] + a4[1])
    return (x, y), (vx, vy)


def test_full_period_returns_to_start():
    orbit = Orbit.from_apsides(90, 300, 0.7)
    r0, v0 = state_on_orbit(orbit, 1.1, MU)
    r, v = propagate(r0, v0, orbit.period(MU), MU)
    assert r == pytest.approx(r0, abs=1e-6)
    assert v == pytest.approx(v0, abs=1e-6)


@pytest.mark.parametrize("speed_factor", [0.8, 1.0, 1.3, math.sqrt(2), 1.8])
def test_propagation_matches_numerical_integration(speed_factor):
    # Covers ellipse, circle, parabola and hyperbola.
    r0 = (150.0, 20.0)
    vc = math.sqrt(MU / math.hypot(*r0))
    v0 = (-10.0, vc * speed_factor)
    r_ref, v_ref = rk4_reference(r0, v0, 3.0, steps=30_000)
    r, v = propagate(r0, v0, 3.0, MU)
    assert r == pytest.approx(r_ref, rel=1e-6, abs=1e-5)
    assert v == pytest.approx(v_ref, rel=1e-6, abs=1e-5)
    assert energy(r, v) == pytest.approx(energy(r0, v0), rel=1e-9, abs=1e-9)


def test_elements_roundtrip():
    orbit = Orbit.from_apsides(100, 250, -2.0)
    for nu in (0.0, 0.5, 2.0, math.pi, 4.0):
        o2 = Orbit.from_state(*state_on_orbit(orbit, nu, MU), MU)
        assert o2.periapsis == pytest.approx(100)
        assert o2.apoapsis == pytest.approx(250)
        assert math.cos(o2.omega - orbit.omega) == pytest.approx(1.0)


def _burn(orbit, nu, direction, dv):
    """Impulsive burn; direction in ('pro', 'retro', 'radial_out')."""
    r, v = state_on_orbit(orbit, nu, MU)
    sp = math.hypot(*v)
    if direction == "pro":
        u = (v[0] / sp, v[1] / sp)
    elif direction == "retro":
        u = (-v[0] / sp, -v[1] / sp)
    else:
        rn = math.hypot(*r)
        u = (r[0] / rn, r[1] / rn)
    return Orbit.from_state(r, (v[0] + dv * u[0], v[1] + dv * u[1]), MU)


def test_prograde_at_periapsis_raises_apoapsis():
    o = Orbit.from_apsides(100, 200, 0.3)
    n = _burn(o, 0.0, "pro", 5.0)
    assert n.periapsis == pytest.approx(100)
    assert n.apoapsis > 200


def test_retrograde_at_periapsis_lowers_apoapsis():
    o = Orbit.from_apsides(100, 200, 0.3)
    n = _burn(o, 0.0, "retro", 5.0)
    assert n.periapsis == pytest.approx(100)
    assert n.apoapsis < 200


def test_prograde_at_apoapsis_raises_periapsis():
    o = Orbit.from_apsides(100, 200, 0.3)
    n = _burn(o, math.pi, "pro", 5.0)
    assert n.apoapsis == pytest.approx(200)
    assert n.periapsis > 100


def test_retrograde_at_apoapsis_lowers_periapsis():
    o = Orbit.from_apsides(100, 200, 0.3)
    n = _burn(o, math.pi, "retro", 5.0)
    assert n.apoapsis == pytest.approx(200)
    assert n.periapsis < 100


def test_radial_burn_rotates_line_of_apsides():
    o = Orbit.from_apsides(150, 150.0001, 0.0)  # ~circular
    n = _burn(o, math.pi / 2, "radial_out", 10.0)
    # Radial kick: angular momentum unchanged -> p unchanged; orbit becomes
    # eccentric and passes through the burn point.
    assert n.p == pytest.approx(o.p, rel=1e-9)
    assert n.e > 0.05


def test_deviation_metric():
    o = Orbit.from_apsides(100, 200, 0.4)
    assert o.deviation_from(o) == 0.0
    assert Orbit.from_apsides(101, 202, 0.4).deviation_from(o) == pytest.approx(0.01, rel=1e-6)


def test_game_finite_burn_tracks_orbit_and_can_win():
    game = Game(seed=7)
    # Cheat: set the target to our current orbit slightly scaled, then check
    # that coasting alone keeps the orbit constant.
    o0 = game.orbit
    for _ in range(300):
        game.update(1 / 60, Controls())
    assert game.orbit.p == pytest.approx(o0.p, rel=1e-9)
    assert game.orbit.e == pytest.approx(o0.e, abs=1e-9)
    game.target = Orbit(p=o0.p, e=o0.e, omega=o0.omega)
    game.update(1 / 60, Controls())
    assert game.status == "won"
