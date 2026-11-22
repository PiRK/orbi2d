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


def test_levels_go_from_home_to_the_gas_giant():
    giant = solar().bodies[GIANT]
    for seed in range(30):
        gm = solar(seed)
        assert gm.primary == PLANET and gm.target_body == GIANT
        assert gm.orbit.apoapsis < gm.bodies[MOON].distance - gm.bodies[MOON].soi
        assert giant.radius < gm.target.periapsis <= gm.target.apoapsis < giant.soi


def _helio(gm):
    """Orbit around the Sun: the current one, or the one after leaving the
    blue planet (as predicted)."""
    if gm.primary == SUN:
        return gm.orbit
    tr = gm.transition
    return tr.orbit if tr and tr.body == SUN else None


def _window_departure(seed, offset=0.0):
    """Fly like a player using the aids: wait for the transfer window (plus
    ``offset`` seconds), leave moving along the blue planet's own motion,
    burn prograde until the orbit around the Sun reaches the gas giant's
    distance, then coast until out of the blue planet's SOI."""
    gm = solar(seed)
    gm.set_warp(32.0)
    _, _, wait = gm.transfer_window()
    while gm.elapsed < wait + offset:
        gm.update(1 / 30, Controls())
    for _ in range(30 * 60):
        hv = gm.body_velocity(PLANET)
        if (gm.v[0] * hv[0] + gm.v[1] * hv[1]) / (math.hypot(*gm.v) * math.hypot(*hv)) > 0.9:
            break
        gm.update(1 / 30, Controls())
    gm.set_warp(1.0)
    for _ in range(30 * 60):
        o = _helio(gm)
        if o and o.bound and o.apoapsis >= g.GIANT_DISTANCE:
            break
        gm.heading = math.atan2(gm.v[1], gm.v[0])
        gm.update(1 / 30, Controls(thrust=True))
    gm.set_warp(1000.0)
    for _ in range(30 * 600):
        if gm.primary == SUN or gm.status != "playing":
            break
        gm.update(1 / 30, Controls())
    gm.set_warp(1.0)
    return gm


def _encounter(gm):
    return any(tr.body == GIANT for tr in gm.transitions)


def _window_flight_with_encounter():
    """A level where a departure at the window gives a direct encounter."""
    for seed in range(10):
        gm = _window_departure(seed)
        if _encounter(gm):
            return gm
    raise AssertionError("no level gave a direct encounter at its window")


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
    gm = _window_flight_with_encounter()
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


def test_win_around_the_gas_giant():
    gm = solar(4)
    gm.primary = GIANT
    gm.r, gm.v = state_on_orbit(gm.target, 1.0, gm.mu_of(GIANT))
    gm.update(1 / 60, Controls())
    assert gm.status == "won"


def test_same_orbit_around_the_sun_does_not_win():
    gm = solar(4)
    gm.primary = SUN   # right shape, wrong body
    gm.r, gm.v = state_on_orbit(gm.target, 1.0, g.SUN_MU)
    gm.update(1 / 60, Controls())
    assert gm.status != "won"


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


# ---- step 2: gravity-assist aids ------------------------------------------

from orbi2d.physics import propagate  # noqa: E402


def _sun_orbit(gm, r, speed_factor):
    gm.primary = SUN
    gm.r, gm.v = (r, 0.0), (0.0, speed_factor * math.sqrt(g.SUN_MU / r))
    gm._refresh_orbit()
    gm._predict()


def test_closest_approach_matches_brute_force():
    gm = solar(0)
    _sun_orbit(gm, 60_000.0, 1.25)
    assert gm.approaches
    for a in gm.approaches:
        c = gm.bodies[a.body]
        brute = min(
            math.dist(propagate(gm.r, gm.v, k * 0.05, g.SUN_MU)[0], c.position(gm.elapsed + k * 0.05))
            for k in range(int((a.time - gm.elapsed + 50) / 0.05))
        )
        assert a.distance == pytest.approx(brute, rel=1e-6, abs=0.01)
        assert math.dist(a.point, a.body_pos) == pytest.approx(a.distance, rel=1e-9)


def test_no_closest_approach_to_a_body_just_left():
    gm = solar(0)
    giant = gm.bodies[GIANT]
    # Inside the giant's SOI, near its edge, flying straight out.
    gm.primary = GIANT
    gm.r, gm.v = (giant.soi - 5.0, 0.0), (400.0, 0.0)
    gm._refresh_orbit()
    gm.set_warp(1.0)
    gm.update(1 / 60, Controls())
    assert gm.primary == SUN
    assert gm._left == GIANT
    first = [a for a in gm.approaches if a.body == GIANT and a.time < gm.elapsed + 10]
    assert not first


def test_transfer_window_lines_up_the_target():
    gm = solar(1)
    phase, ideal, wait = gm.transfer_window()
    assert 0 <= phase < 360 and ideal == pytest.approx(89.3, abs=0.5)
    gm.elapsed += wait
    phase2, _, wait2 = gm.transfer_window()
    assert phase2 == pytest.approx(ideal, abs=1e-6)
    assert wait2 == pytest.approx(0.0, abs=1e-6) or wait2 == pytest.approx(
        360.0 / abs(math.degrees(gm.bodies[GIANT].rate - gm.bodies[PLANET].rate)), rel=1e-6)


def test_no_transfer_window_outside_solar_mode():
    assert Game(seed=1, mode=g.MOON_MODE).transfer_window() is None


def test_gravity_assist_is_predicted_and_recorded():
    gm = _window_flight_with_encounter()
    i = next(k for k, tr in enumerate(gm.transitions) if tr.body == GIANT)
    predicted = gm.predicted_assist(i)
    assert predicted is not None and predicted > 50
    gm.set_warp(1000.0)
    for _ in range(60 * 600):
        gm.update(1 / 60, Controls())
        if gm.assists or gm.status != "playing":
            break
    assert [a.body for a in gm.assists] == [GIANT]
    assert gm.assists[0].dv == pytest.approx(predicted, rel=1e-3)
    assert gm.assist_dv == gm.assists[0].dv


def test_radial_trajectory_does_not_break_the_step_logic():
    # Zero angular momentum: a degenerate conic with no finite top speed.
    gm = solar(0)
    giant = gm.bodies[GIANT]
    gm.primary = GIANT
    gm.r, gm.v = (giant.soi * 0.5, 0.0), (-50.0, 0.0)   # falling straight in
    gm._refresh_orbit()
    gm.set_warp(8.0)
    for _ in range(60 * 60):
        gm.update(1 / 60, Controls())
        if gm.status != "playing":
            break
    assert gm.status == "crashed"


def test_hint_burn_direction_leads_to_an_encounter():
    # Depart late, after the ideal window: the path misses the gas giant, and
    # the marker's burn direction (found by re-predicting) must close the gap.
    for seed, offset in [(s, o) for s in range(6) for o in (40.0, 80.0, 150.0)]:
        gm = _window_departure(seed, offset)
        ca = next((a for a in gm.approaches if a.body == GIANT), None)
        if not _encounter(gm) and ca is not None and ca.fix != 0:
            break
    else:
        raise AssertionError("no late departure with a hint to follow")
    for _ in range(600):
        if _encounter(gm):
            break
        ca = next(a for a in gm.approaches if a.body == GIANT)
        assert ca.fix != 0
        pro = math.atan2(gm.v[1], gm.v[0])
        gm.heading = pro if ca.fix > 0 else pro + math.pi
        for _ in range(6):
            gm.update(1 / 30, Controls(thrust=True, fine=True))
    assert _encounter(gm)


# ---- two targets: the gas giant (easy) or the red planet (hard) ----------

def test_every_level_has_both_targets():
    red = solar().bodies[RED]
    for seed in range(20):
        gm = solar(seed)
        assert set(gm.targets) == {GIANT, RED}
        assert gm.target_body == GIANT and gm.target is gm.targets[GIANT]
        t = gm.targets[RED]
        assert red.radius < t.periapsis <= t.apoapsis < red.soi


def test_other_modes_have_a_single_target():
    for mode in (g.SINGLE, g.MOON_MODE):
        gm = Game(seed=1, mode=mode)
        assert list(gm.targets) == [gm.target_body]


def test_switching_target_moves_the_aids():
    gm = solar(1)
    giant_window = gm.transfer_window()
    gm.cycle_target()
    assert gm.target_body == RED and gm.target is gm.targets[RED]
    phase, ideal, wait = gm.transfer_window()
    assert ideal != pytest.approx(giant_window[1])        # Hohmann angle for the red planet
    r1, r2 = g.HOME_DISTANCE, g.RED_DISTANCE
    assert ideal == pytest.approx(180 * (1 - ((r1 + r2) / (2 * r2)) ** 1.5))
    gm.cycle_target()
    assert gm.target_body == GIANT


@pytest.mark.parametrize("body", [GIANT, RED])
def test_either_target_wins_whichever_is_selected(body):
    gm = solar(4)
    gm.select_target(GIANT)
    gm.primary = body
    gm.r, gm.v = state_on_orbit(gm.targets[body], 1.0, gm.mu_of(body))
    gm.update(1 / 60, Controls())
    assert gm.status == "won" and gm.reached == body


def test_arriving_at_the_other_target_selects_it():
    gm = solar(4)
    red = gm.bodies[RED]
    assert gm.target_body == GIANT
    # Just outside the red planet's SOI, heading straight in.
    rx, ry = gm.body_position(RED)
    vx, vy = gm.body_velocity(RED)
    gm.primary = SUN
    gm.r = (rx + red.soi + 2.0, ry)
    gm.v = (vx - 40.0, vy)
    gm._refresh_orbit()
    gm.set_warp(1.0)
    for _ in range(60):
        gm.update(1 / 60, Controls())
        if gm.primary == RED:
            break
    assert gm.primary == RED and gm.target_body == RED
    assert gm.target is gm.targets[RED]   # HUD and aids now follow the red target
