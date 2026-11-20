# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

import math

import pytest

from orbi2d import game as g
from orbi2d.game import MOON, MOON_MODE, PLANET, Controls, Game, state_on_orbit
from orbi2d.physics import Orbit


def games(n=40):
    return [Game(seed=s, mode=MOON_MODE) for s in range(n)]


def test_single_mode_has_no_moon():
    gm = Game(seed=3)
    assert gm.mode == g.SINGLE and gm.moon is None
    assert gm.primary == PLANET and gm.target_body == PLANET


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        Game(mode="mars")


def test_levels_put_start_and_target_on_different_bodies():
    starts = set()
    for gm in games():
        assert gm.primary != gm.target_body
        starts.add(gm.primary)
        moon = gm.moon
        for body, orbit in ((gm.primary, gm.orbit), (gm.target_body, gm.target)):
            if body == MOON:
                assert orbit.periapsis > moon.radius
                assert orbit.apoapsis < moon.soi
            else:
                # Planet orbits stay clear of the moon's sphere of influence.
                assert orbit.apoapsis < moon.distance - moon.soi
    assert starts == {PLANET, MOON}  # both directions occur


def test_moon_motion_is_circular_and_consistent():
    moon = Game(seed=1, mode=MOON_MODE).moon
    for t in (0.0, 10.0, 37.0):
        assert math.hypot(*moon.position(t)) == pytest.approx(moon.distance)
        # Velocity is the time derivative of position.
        h = 1e-5
        p1, p2 = moon.position(t - h), moon.position(t + h)
        num = ((p2[0] - p1[0]) / (2 * h), (p2[1] - p1[1]) / (2 * h))
        assert moon.velocity(t) == pytest.approx(num, rel=1e-6)
    # Circular orbit speed around the planet.
    assert moon.speed == pytest.approx(math.sqrt(g.MU / moon.distance))


def test_soi_switch_preserves_world_state():
    gm = Game(seed=1, mode=MOON_MODE)
    t = 12.3
    gm.elapsed = t
    moon_pos = gm.moon.position(t)
    gm.primary = PLANET
    gm.r = (moon_pos[0] + 50.0, moon_pos[1] - 20.0)
    gm.v = (3.0, 70.0)
    world_r, world_v = gm.r, gm.v
    gm._switch_primary(MOON, t)
    assert gm.r == pytest.approx((50.0, -20.0))
    mv = gm.moon.velocity(t)
    assert gm.v == pytest.approx((world_v[0] - mv[0], world_v[1] - mv[1]))
    gm._switch_primary(PLANET, t)
    assert gm.r == pytest.approx(world_r)
    assert gm.v == pytest.approx(world_v)


def _planet_start(seed_range=range(100)):
    for s in seed_range:
        gm = Game(seed=s, mode=MOON_MODE)
        if gm.primary == PLANET:
            return gm
    raise AssertionError("no planet start found")


def test_predicted_encounter_matches_simulation():
    gm = _planet_start()
    r0, v0 = gm.r, gm.v
    sp = math.hypot(*v0)
    for dv in [x * 0.5 for x in range(10, 120)]:
        gm.r, gm.v = r0, (v0[0] * (1 + dv / sp), v0[1] * (1 + dv / sp))
        gm._refresh_orbit()
        gm._predict()
        if gm.transition and gm.transition.body == MOON:
            break
    tr = gm.transition
    assert tr is not None and tr.body == MOON
    gm.set_warp(1.0)
    while gm.primary == PLANET and gm.status == "playing":
        gm.update(1 / 60, Controls())
    assert gm.primary == MOON
    assert gm.elapsed == pytest.approx(tr.time, abs=1 / 60)
    assert gm.orbit.e == pytest.approx(tr.orbit.e, rel=1e-2)
    assert gm.orbit.periapsis == pytest.approx(tr.orbit.periapsis, rel=1e-2)


def test_deviation_only_counts_around_target_body():
    for gm in games(10):
        assert gm.deviation == math.inf  # always start around the other body


def test_win_around_the_moon():
    gm = _planet_start()
    assert gm.target_body == MOON
    # Teleport onto the target orbit around the moon.
    gm.primary = MOON
    gm.r, gm.v = state_on_orbit(gm.target, 0.3, gm.moon.mu)
    gm.update(1 / 60, Controls())
    assert gm.status == "won"


def test_crash_into_the_moon():
    gm = _planet_start()
    gm.primary = MOON
    gm.r = (gm.moon.radius + 5.0, 0.0)
    gm.v = (-60.0, 0.0)
    gm.set_warp(1.0)
    for _ in range(60):
        gm.update(1 / 60, Controls())
    assert gm.status == "crashed"


def test_orbit_around_moon_is_stable_while_coasting():
    for gm in games(20):
        if gm.primary != MOON:
            continue
        o0 = gm.orbit
        gm.set_warp(8.0)
        for _ in range(600):
            gm.update(1 / 60, Controls())
        assert gm.primary == MOON
        assert gm.orbit.p == pytest.approx(o0.p, rel=1e-9)
        assert gm.orbit.e == pytest.approx(o0.e, abs=1e-9)
        assert isinstance(gm.orbit, Orbit)
