# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

import math

import pytest

from orbi2d import game as g
from orbi2d.game import GIANT, MOON, PLANET, RED, SOLAR, SUN, Controls, Game, state_on_orbit


def solar(seed=0):
    return Game(seed=seed, mode=SOLAR)


def test_bodies_nest_inside_each_other():
    gm = solar()
    sun, home, moon, red, giant = (gm.bodies[n] for n in (SUN, PLANET, MOON, RED, GIANT))
    assert sun.parent is None and gm.root == SUN
    assert {b.parent for b in (home, red, giant)} == {SUN}
    assert moon.parent == PLANET
    # The moon's whole SOI fits inside the blue planet's SOI.
    assert moon.distance + moon.soi < home.soi
    # Planets' SOIs don't overlap each other or the Sun.
    assert home.distance + home.soi < red.distance - red.soi
    assert red.distance + red.soi < giant.distance - giant.soi
    assert sun.radius < home.distance - home.soi


def test_world_positions_follow_the_tree():
    gm = solar(3)
    t = 123.4
    home = gm.body_position(PLANET, t)
    local = gm.bodies[MOON].position(t)
    assert gm.body_position(MOON, t) == pytest.approx((home[0] + local[0], home[1] + local[1]))
    assert math.hypot(*home) == pytest.approx(g.HOME_DISTANCE)
    # Circular orbit speed around the Sun.
    assert math.hypot(*gm.body_velocity(PLANET, t)) == pytest.approx(math.sqrt(g.SUN_MU / g.HOME_DISTANCE))


def test_levels_start_home_and_target_sun_or_giant():
    targets = set()
    for seed in range(30):
        gm = solar(seed)
        assert gm.primary == PLANET
        assert gm.orbit.apoapsis < gm.bodies[MOON].distance - gm.bodies[MOON].soi
        targets.add(gm.target_body)
        body = gm.bodies[gm.target_body]
        assert gm.target.periapsis > body.radius
        if gm.target_body == GIANT:
            assert gm.target.apoapsis < body.soi
    assert targets == {SUN, GIANT}


def _burn_prograde(gm, until, max_dv=400.0):
    gm.set_warp(1.0)
    while gm.status == "playing" and gm.burn_dv < max_dv:
        gm.heading = math.atan2(gm.v[1], gm.v[0])
        gm.update(1 / 60, Controls(thrust=True))
        if until(gm):
            return True
    return False


def _coast_and_record(gm, n_crossings, max_frames=60 * 600):
    crossings, last = [], gm.primary
    gm.set_warp(1000.0)
    for _ in range(max_frames):
        gm.update(1 / 60, Controls())
        if gm.primary != last:
            crossings.append((last, gm.primary, gm.elapsed))
            last = gm.primary
        if len(crossings) >= n_crossings or gm.status != "playing":
            break
    return crossings


def test_escape_from_home_matches_prediction():
    gm = solar(3)
    assert _burn_prograde(gm, lambda gm: gm.transition is not None and gm.transition.body == SUN)
    tr = gm.transition
    (old, new, t), = _coast_and_record(gm, 1)
    assert (old, new) == (PLANET, SUN)
    assert t == pytest.approx(tr.time, abs=0.1)


def test_chained_prediction_to_the_gas_giant():
    gm = solar(0)
    assert _burn_prograde(gm, lambda gm: any(tr.body == GIANT for tr in gm.transitions))
    predicted = [(tr.from_body, tr.body, tr.time) for tr in gm.transitions]
    n = next(i for i, p in enumerate(predicted) if p[1] == GIANT) + 1
    actual = _coast_and_record(gm, n)
    assert [(a, b) for a, b, _ in actual] == [(a, b) for a, b, _ in predicted[:n]]
    for (_, _, t_act), (_, _, t_pred) in zip(actual, predicted):
        assert t_act == pytest.approx(t_pred, abs=0.5)


def test_automatic_warp_limits():
    gm = solar(0)
    gm.set_warp(1000.0)
    gm.update(1 / 60, Controls())
    # Around the blue planet: at most a few orbits per real second.
    period = gm.orbit.period(gm.mu_of(gm.primary))
    assert gm.effective_warp == pytest.approx(min(1000.0, g.ORBITS_PER_SECOND * period))
    # Burning: low warp.
    gm.update(1 / 60, Controls(thrust=True))
    assert gm.effective_warp <= g.THRUST_MAX_WARP
    # Approaching a predicted SOI crossing: slows down.
    assert _burn_prograde(gm, lambda gm: gm.transition is not None)
    gm.set_warp(1000.0)
    remaining = gm.transition.time - gm.elapsed   # the warp is chosen from this
    gm.update(1 / 60, Controls())
    assert gm.effective_warp <= max(1.0, remaining / 1.5) + 1e-9
    assert gm.effective_warp < 1000.0


def test_requested_warp_is_a_ceiling():
    gm = solar(0)
    gm.set_warp(2.0)
    gm.update(1 / 60, Controls())
    assert gm.effective_warp == 2.0
    gm.set_warp(5000.0)
    assert gm.time_warp == g.SOLAR_MAX_WARP


@pytest.mark.parametrize("target", [SUN, GIANT])
def test_win_around_the_target_body(target):
    seed = next(s for s in range(50) if solar(s).target_body == target)
    gm = solar(seed)
    gm.primary = target
    gm.r, gm.v = state_on_orbit(gm.target, 1.0, gm.mu_of(target))
    gm.update(1 / 60, Controls())
    assert gm.status == "won"


def test_wrong_body_never_counts():
    gm = solar(0)
    assert gm.deviation == math.inf


def test_coasting_at_high_warp_takes_few_steps(monkeypatch):
    gm = solar(0)
    # Put the rocket on a circular orbit around the Sun, far from any planet.
    gm.primary = SUN
    r = 100_000.0
    gm.r, gm.v = (0.0, -r), (math.sqrt(g.SUN_MU / r), 0.0)
    gm._refresh_orbit()
    gm._predict()
    calls = {"n": 0}
    real = g.propagate

    def counting(*args):
        calls["n"] += 1
        return real(*args)

    monkeypatch.setattr(g, "propagate", counting)
    gm.set_warp(1000.0)
    gm.update(1 / 60, Controls())
    assert gm.effective_warp > 100
    assert calls["n"] < 50


def test_reached_tolerates_rounding():
    end = 12345.678
    assert g._reached(end - 1e-12, end)
    assert not g._reached(end - 1e-3, end)


def test_no_frame_gets_stuck_in_tiny_steps(monkeypatch):
    # Regression: a search window ending at a large game time used to be
    # "never quite reached" because of rounding, and burned 20000 tiny steps.
    calls = {"n": 0}
    real = g.propagate

    def counting(*args):
        calls["n"] += 1
        return real(*args)

    monkeypatch.setattr(g, "propagate", counting)
    gm = solar(0)
    gm.set_warp(1.0)
    worst = 0
    for _ in range(60 * 20):
        gm.heading = math.atan2(gm.v[1], gm.v[0])
        calls["n"] = 0
        gm.update(1 / 60, Controls(thrust=True))
        worst = max(worst, calls["n"])
        if any(tr.body == GIANT for tr in gm.transitions):
            break
    assert worst < 5000
