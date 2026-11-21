# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

"""Game state and rules (no Qt dependency, so it can be unit-tested).

Three modes:

* ``single``: one planet; start and target orbits are both around it.
* ``moon``: a planet and a moon on a circular orbit around it.  The start
  orbit is around one body and the target orbit around the other.
* ``solar``: a compressed solar system (Sun, the blue planet and its moon, a
  red planet, a gas giant).  The start orbit is around the blue planet and
  the target orbit around the Sun or the gas giant.

Bodies form a tree (Sun -> planets -> moons); every body except the root
moves on a circular, counter-clockwise orbit around its parent.  Gravity uses
*patched conics*: each body has a sphere of influence (SOI), and only the
body whose SOI the rocket is in (the deepest one) pulls on it.  Each leg is
therefore an exact Kepler conic around a single body, and the state vector is
converted between frames when the rocket crosses an SOI boundary.  Gravity
assists (slingshots) fall out of this naturally.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .physics import Orbit, Vec, propagate

# ---- tuning --------------------------------------------------------------
MU = 1.5e6                 # gravitational parameter (world units^3 / s^2)
PLANET_RADIUS = 40.0       # world units
MIN_PERIAPSIS = 80.0       # random orbits never come closer than this
MAX_APOAPSIS = 330.0       # ... nor farther than this
MAIN_THRUST = 15.0         # main engine acceleration (units / s^2)
FINE_THRUST = 1.5          # with Shift held
ROTATION_SPEED = math.radians(180)       # rad / s
FINE_ROTATION_SPEED = math.radians(40)   # with Shift held
TOLERANCE = 0.02           # max relative radial deviation to win (2 %)
ESCAPE_RADIUS = 3000.0     # beyond this the rocket is lost
MAX_STEP_DISTANCE = 4.0    # sub-step size used for collision / thrust
WARP_PRESETS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)  # keys 1-6
DEFAULT_WARP = 0.5
MIN_WARP = 0.1
MAX_WARP = 16.0
WARP_STEP = 1.25           # +/- multiply / divide the warp by this

# Moon mode.
MOON_DISTANCE = 600.0      # radius of the moon's circular orbit
MOON_MASS_RATIO = 0.05     # moon mass / planet mass
MOON_RADIUS = 18.0
MOON_MIN_PERIAPSIS = 35.0
MOON_MAX_APOAPSIS_FRACTION = 0.6   # of the SOI radius

# Solar system mode (compressed scale: distances ~70-270x the planet-moon one).
SUN_MU = 1.2e10
SUN_RADIUS = 2500.0
HOME_DISTANCE = 40_000.0           # blue planet: period ~460 s
RED_DISTANCE = 62_000.0            # red planet: period ~880 s
RED_MASS_RATIO = 0.12              # of the blue planet
RED_RADIUS = 24.0
GIANT_DISTANCE = 150_000.0         # gas giant: period ~3300 s
GIANT_MASS_RATIO = 300.0           # of the blue planet
GIANT_RADIUS = 420.0
SOLAR_ESCAPE_RADIUS = 400_000.0
SOLAR_WARP_PRESETS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 32.0, 128.0, 1000.0)  # keys 1-9
SOLAR_MAX_WARP = 1000.0
THRUST_MAX_WARP = 8.0              # automatic warp limit while the engine fires
ORBITS_PER_SECOND = 3.0            # automatic warp limit: orbits per real second
PREDICTED_PATCHES = 3              # SOI crossings shown ahead in solar mode

SINGLE = "single"
MOON_MODE = "moon"
SOLAR = "solar"
MODES = (SINGLE, MOON_MODE, SOLAR)
PLANET = "planet"                  # the blue planet (root in single/moon mode)
MOON = "moon"
SUN = "sun"
RED = "red"
GIANT = "giant"


@dataclass
class Controls:
    left: bool = False
    right: bool = False
    thrust: bool = False
    fine: bool = False


def state_on_orbit(orbit: Orbit, true_anomaly: float, mu: float) -> tuple[Vec, Vec]:
    """Position and velocity of a body at ``true_anomaly`` on ``orbit``."""
    r = orbit.point_at(true_anomaly)
    k = math.sqrt(mu / orbit.p) * orbit.h_sign
    # Perifocal velocity, then rotate by omega.
    vpx = -k * math.sin(true_anomaly)
    vpy = k * (orbit.e + math.cos(true_anomaly))
    c, s = math.cos(orbit.omega), math.sin(orbit.omega)
    return r, (c * vpx - s * vpy, s * vpx + c * vpy)


def random_orbit(rng: random.Random) -> Orbit:
    rp = rng.uniform(MIN_PERIAPSIS, MAX_APOAPSIS * 0.7)
    ra = rng.uniform(rp, MAX_APOAPSIS)
    return Orbit.from_apsides(rp, ra, rng.uniform(0, 2 * math.pi))


def _orbit_between(rng: random.Random, rp_min: float, rp_max: float, ra_max: float) -> Orbit:
    rp = rng.uniform(rp_min, rp_max)
    ra = rng.uniform(rp, ra_max)
    return Orbit.from_apsides(rp, ra, rng.uniform(0, 2 * math.pi))


@dataclass(frozen=True)
class Body:
    """A celestial body.  Except for the root, it moves on a circular,
    counter-clockwise orbit of radius ``distance`` around ``parent``.
    ``position``/``velocity`` are relative to the parent."""

    name: str
    label: str
    mu: float
    radius: float
    parent: str | None = None
    distance: float = 0.0
    soi: float = math.inf
    phase0: float = 0.0
    rate: float = 0.0  # angular velocity around the parent (rad / s)

    @staticmethod
    def orbiting(name: str, label: str, mu: float, radius: float, parent: str,
                 parent_mu: float, distance: float, phase0: float) -> "Body":
        return Body(
            name=name, label=label, mu=mu, radius=radius, parent=parent,
            distance=distance,
            soi=distance * (mu / parent_mu) ** 0.4,  # Laplace sphere of influence
            phase0=phase0,
            rate=math.sqrt(parent_mu / distance ** 3),
        )

    @staticmethod
    def create(planet_mu: float, phase0: float) -> "Body":
        """The moon of the planet + moon mode."""
        d = MOON_DISTANCE
        return Body(
            name=MOON, label="Moon",
            distance=d,
            mu=planet_mu * MOON_MASS_RATIO,
            radius=MOON_RADIUS,
            parent=PLANET,
            soi=d * MOON_MASS_RATIO ** 0.4,  # Laplace sphere of influence
            phase0=phase0,
            rate=math.sqrt(planet_mu / d ** 3),
        )

    @property
    def speed(self) -> float:
        return self.distance * self.rate

    def angle(self, t: float) -> float:
        return self.phase0 + self.rate * t

    def position(self, t: float) -> Vec:
        if self.parent is None:
            return 0.0, 0.0
        a = self.angle(t)
        return self.distance * math.cos(a), self.distance * math.sin(a)

    def velocity(self, t: float) -> Vec:
        if self.parent is None:
            return 0.0, 0.0
        a = self.angle(t)
        return -self.speed * math.sin(a), self.speed * math.cos(a)


Moon = Body  # backwards-compatible name


@dataclass(frozen=True)
class Transition:
    """Predicted crossing of a sphere-of-influence boundary."""

    time: float          # game time of the crossing
    body: str            # primary body after the crossing
    orbit: Orbit         # orbit around ``body`` after the crossing
    point: Vec           # world position of the rocket at the crossing
    moon_pos: Vec | None  # world position of the moon at the crossing (if any)
    body_pos: Vec = (0.0, 0.0)   # world position of ``body`` at the crossing
    from_body: str = ""          # primary body before the crossing


def _periapsis_speed(o: Orbit, mu: float) -> float:
    """Speed at periapsis (the fastest point) of any conic, from vis-viva:
    v^2 = mu (2/r - 1/a), with a < 0 for hyperbolas."""
    a = o.semi_major_axis
    inv_a = 1.0 / a if math.isfinite(a) else 0.0
    return math.sqrt(max(0.0, mu * (2.0 / max(o.periapsis, 1e-9) - inv_a)))


def _reached(t: float, end: float) -> bool:
    """True once ``t`` is at ``end``, up to floating-point rounding (a step
    of ``end - t`` may land a few ulps short when the times are large)."""
    return end - t <= 1e-9 * max(1.0, abs(end))


def _add(a: Vec, b: Vec) -> Vec:
    return a[0] + b[0], a[1] + b[1]


def _sub(a: Vec, b: Vec) -> Vec:
    return a[0] - b[0], a[1] - b[1]


@dataclass
class Game:
    seed: int | None = None
    mode: str = SINGLE
    mu: float = MU
    planet_radius: float = PLANET_RADIUS
    tolerance: float = TOLERANCE

    # Rocket state, relative to the current primary body.
    r: Vec = (0.0, 0.0)
    v: Vec = (0.0, 0.0)
    primary: str = PLANET
    heading: float = 0.0           # direction the nose points (rad)
    orbit: Orbit = field(default=None)  # type: ignore[assignment]
    target: Orbit = field(default=None)  # type: ignore[assignment]
    target_body: str = PLANET
    bodies: dict[str, Body] = field(default_factory=dict)
    root: str = PLANET
    moon: Body | None = None
    status: str = "playing"        # playing | won | crashed | escaped
    thrusting: bool = False
    rotating: int = 0              # -1 right (cw), +1 left (ccw), 0 none
    time_warp: float = DEFAULT_WARP  # requested warp (game seconds per real second)
    effective_warp: float = DEFAULT_WARP  # warp actually used (solar mode limits it)
    elapsed: float = 0.0
    burn_dv: float = 0.0           # total delta-v spent
    deviation: float = math.inf
    transitions: list[Transition] = field(default_factory=list)  # predicted SOI crossings
    _predicted_at: float = -math.inf
    _predict_valid_until: float = math.inf
    _real_since_predict: float = 0.0

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"unknown mode {self.mode!r}")
        self.reset(self.seed)

    # ---- bodies -------------------------------------------------------
    @property
    def transition(self) -> Transition | None:
        """Next predicted SOI crossing."""
        return self.transitions[0] if self.transitions else None

    def mu_of(self, body: str) -> float:
        return self.bodies[body].mu

    def radius_of(self, body: str) -> float:
        return self.bodies[body].radius

    def label(self, body: str) -> str:
        return self.bodies[body].label

    def children(self, body: str) -> list[Body]:
        return [b for b in self.bodies.values() if b.parent == body]

    def body_position(self, body: str, t: float | None = None) -> Vec:
        """World position (relative to the root body) of ``body``."""
        t = self.elapsed if t is None else t
        b = self.bodies[body]
        if b.parent is None:
            return 0.0, 0.0
        return _add(self.body_position(b.parent, t), b.position(t))

    def body_velocity(self, body: str, t: float | None = None) -> Vec:
        t = self.elapsed if t is None else t
        b = self.bodies[body]
        if b.parent is None:
            return 0.0, 0.0
        return _add(self.body_velocity(b.parent, t), b.velocity(t))

    @property
    def world_r(self) -> Vec:
        """Rocket position relative to the root body (screen world frame)."""
        return _add(self.r, self.body_position(self.primary))

    @property
    def max_warp(self) -> float:
        return SOLAR_MAX_WARP if self.mode == SOLAR else MAX_WARP

    @property
    def warp_presets(self) -> tuple[float, ...]:
        return SOLAR_WARP_PRESETS if self.mode == SOLAR else WARP_PRESETS

    @property
    def escape_radius(self) -> float:
        return SOLAR_ESCAPE_RADIUS if self.mode == SOLAR else ESCAPE_RADIUS

    # ------------------------------------------------------------------
    def reset(self, seed: int | None = None) -> None:
        rng = random.Random(seed)
        planet = Body(name=PLANET, label="Planet", mu=self.mu, radius=self.planet_radius)
        if self.mode == SINGLE:
            self.bodies = {PLANET: planet}
            self.root = PLANET
            self.moon = None
            start_body = PLANET
            start = random_orbit(rng)
            target = random_orbit(rng)
            # Make sure there is actually something to do.
            while target.deviation_from(start) < 0.3 or start.deviation_from(target) < 0.3:
                target = random_orbit(rng)
            self.target_body = PLANET
        elif self.mode == MOON_MODE:
            self.moon = Body.create(self.mu, rng.uniform(0, 2 * math.pi))
            self.bodies = {PLANET: planet, MOON: self.moon}
            self.root = PLANET
            start_body = rng.choice((PLANET, MOON))
            self.target_body = MOON if start_body == PLANET else PLANET
            orbits = {PLANET: random_orbit(rng), MOON: self._random_moon_orbit(rng)}
            start, target = orbits[start_body], orbits[self.target_body]
        else:
            self._make_solar_system(rng)
            start_body = PLANET
            start = random_orbit(rng)
            self.target_body = rng.choice((SUN, GIANT))
            if self.target_body == GIANT:
                g = self.bodies[GIANT]
                target = _orbit_between(rng, 1.6 * g.radius, 0.08 * g.soi, 0.2 * g.soi)
            elif rng.random() < 0.5:   # outside the blue planet's orbit
                target = _orbit_between(rng, 55_000.0, 100_000.0, 130_000.0)
            else:                      # inside it, towards the Sun
                target = _orbit_between(rng, 12_000.0, 25_000.0, 32_000.0)
        self.target = target
        self.primary = start_body
        self.r, self.v = state_on_orbit(start, rng.uniform(0, 2 * math.pi), self.mu_of(start_body))
        self.heading = math.atan2(self.v[1], self.v[0])  # start pointing prograde
        self.status = "playing"
        self.thrusting = False
        self.rotating = 0
        self.elapsed = 0.0
        self.burn_dv = 0.0
        self.effective_warp = self.time_warp
        self._refresh_orbit()
        self._predict()

    def _make_solar_system(self, rng: random.Random) -> None:
        sun = Body(name=SUN, label="Sun", mu=SUN_MU, radius=SUN_RADIUS)
        home = Body.orbiting(PLANET, "Blue planet", self.mu, self.planet_radius, SUN, SUN_MU,
                             HOME_DISTANCE, rng.uniform(0, 2 * math.pi))
        moon = Body.create(self.mu, rng.uniform(0, 2 * math.pi))
        red = Body.orbiting(RED, "Red planet", self.mu * RED_MASS_RATIO, RED_RADIUS, SUN, SUN_MU,
                            RED_DISTANCE, rng.uniform(0, 2 * math.pi))
        giant = Body.orbiting(GIANT, "Gas giant", self.mu * GIANT_MASS_RATIO, GIANT_RADIUS, SUN,
                              SUN_MU, GIANT_DISTANCE, rng.uniform(0, 2 * math.pi))
        self.bodies = {b.name: b for b in (sun, home, moon, red, giant)}
        self.root = SUN
        self.moon = moon

    def _random_moon_orbit(self, rng: random.Random) -> Orbit:
        max_ra = self.moon.soi * MOON_MAX_APOAPSIS_FRACTION
        rp = rng.uniform(MOON_MIN_PERIAPSIS, max_ra * 0.7)
        ra = rng.uniform(rp, max_ra)
        return Orbit.from_apsides(rp, ra, rng.uniform(0, 2 * math.pi))

    def set_warp(self, warp: float) -> None:
        # Snap to 3 significant digits so repeated +/- steps don't drift
        # (0.5 * 1.25 / 1.25 lands back on exactly 0.5).
        warp = float(f"{warp:.3g}")
        self.time_warp = max(MIN_WARP, min(self.max_warp, warp))

    def faster(self) -> None:
        self.set_warp(self.time_warp * WARP_STEP)

    def slower(self) -> None:
        self.set_warp(self.time_warp / WARP_STEP)

    def _refresh_orbit(self) -> None:
        self.orbit = Orbit.from_state(self.r, self.v, self.mu_of(self.primary))
        if self.primary == self.target_body:
            self.deviation = self.orbit.deviation_from(self.target)
        else:
            self.deviation = math.inf

    # ---- automatic time warp (solar mode) -----------------------------
    def warp_limit(self) -> float:
        """Highest sensible warp right now: at most a few orbits per real
        second, slower as the next SOI crossing approaches (so it isn't
        skipped past in a blur), and low while the engine fires."""
        limit = self.max_warp
        if self.orbit.bound:
            limit = min(limit, ORBITS_PER_SECOND * self.orbit.period(self.mu_of(self.primary)))
        tr = self.transition
        if tr is not None:
            limit = min(limit, max(1.0, (tr.time - self.elapsed) / 1.5))
        if self.thrusting:
            limit = min(limit, THRUST_MAX_WARP)
        return max(MIN_WARP, limit)

    # ---- sphere of influence ------------------------------------------
    def _switch_primary(self, new: str, t: float) -> None:
        """Re-express the rocket state relative to ``new`` at game time t."""
        old = self.primary
        r_world = _add(self.r, self.body_position(old, t))
        v_world = _add(self.v, self.body_velocity(old, t))
        self.r = _sub(r_world, self.body_position(new, t))
        self.v = _sub(v_world, self.body_velocity(new, t))
        self.primary = new

    def _check_soi(self, t: float) -> bool:
        p = self.bodies[self.primary]
        if p.parent is not None and math.hypot(*self.r) > p.soi:
            self._switch_primary(p.parent, t)
            return True
        for c in self.children(self.primary):
            if math.dist(self.r, c.position(t)) < c.soi:
                self._switch_primary(c.name, t)
                return True
        return False

    def _soi_gap(self, body: str, r: Vec, t: float, children: list[Body]) -> float:
        """Distance from ``r`` (relative to ``body``) to the nearest SOI
        boundary or surface: positive while inside the same frame."""
        p = self.bodies[body]
        gap = math.hypot(*r) - p.radius
        if p.parent is not None:
            gap = min(gap, p.soi - math.hypot(*r))
        for c in children:
            gap = min(gap, math.dist(r, c.position(t)) - c.soi)
        return gap

    # ---- prediction ---------------------------------------------------
    def _predict(self) -> None:
        """Predict the next SOI crossings of the coasting trajectory."""
        self._predicted_at = self.elapsed
        self._real_since_predict = 0.0
        self.transitions = []
        if self.moon is None or self.status != "playing":
            return
        if self.mode == MOON_MODE:
            tr = self._predict_moon()
            self.transitions = [tr] if tr else []
            return
        body, r, v, t = self.primary, self.r, self.v, self.elapsed
        horizon_end = t
        for _ in range(PREDICTED_PATCHES):
            tr, v, horizon_end = self._predict_patch(body, r, v, t)
            if tr is None:
                break
            self.transitions.append(tr)
            # Continue from the crossing, in the new body's frame.
            body, t, r = tr.body, tr.time, _sub(tr.point, tr.body_pos)
        # Re-predict once the first crossing has happened (or the horizon of
        # the last search has been used up).
        first = self.transition
        self._predict_valid_until = first.time if first else horizon_end

    def _predict_patch(self, body: str, r: Vec, v: Vec,
                       t0: float) -> tuple[Transition | None, Vec, float]:
        """Next SOI crossing from state (r, v) around ``body`` at time t0.
        Returns the transition (or None), the rocket velocity relative to the
        new body, and the end of the searched time span."""
        p = self.bodies[body]
        mu = p.mu
        o = Orbit.from_state(r, v, mu)
        # Only children whose orbit band the conic can reach.
        children = [c for c in self.children(body)
                    if o.periapsis < c.distance + c.soi
                    and not (o.bound and o.apoapsis < c.distance - c.soi)]
        can_exit = p.parent is not None and not (o.bound and o.apoapsis < p.soi)
        horizon = o.period(mu) if o.bound else math.inf
        horizon = min(horizon, 4000.0)
        if not children and not can_exit:
            return None, v, t0 + horizon
        # Upper bound on how fast the gap to any boundary can shrink: the
        # rocket's fastest speed on this conic plus the fastest child.
        vmax = max(_periapsis_speed(o, mu), math.hypot(*v)) + max((c.speed for c in children), default=0.0)
        scales = [c.soi for c in children] + ([p.soi] if can_exit else [])
        h_min = 0.002 * min(scales) / vmax

        def crossing(rr: Vec, tt: float) -> str | None:
            if can_exit and math.hypot(*rr) > p.soi:
                return p.parent
            for c in children:
                if math.dist(rr, c.position(tt)) < c.soi:
                    return c.name
            return None

        t = t0
        end = t0 + horizon
        for _ in range(20000):
            if _reached(t, end):
                break
            gap = self._soi_gap(body, r, t, children) if children or can_exit else math.inf
            if math.hypot(*r) <= p.radius:
                return None, v, t   # impact before any crossing
            h = min(max(gap / vmax, h_min), end - t)
            r2, v2 = propagate(r, v, h, mu)
            new = crossing(r2, t + h)
            if new is not None:
                lo, hi = 0.0, h
                for _ in range(40):
                    mid = 0.5 * (lo + hi)
                    if crossing(propagate(r, v, mid, mu)[0], t + mid) is not None:
                        hi = mid
                    else:
                        lo = mid
                rc, vc = propagate(r, v, hi, mu)
                tc = t + hi
                new = crossing(rc, tc) or new
                world_r = _add(rc, self.body_position(body, tc))
                world_v = _add(vc, self.body_velocity(body, tc))
                body_pos = self.body_position(new, tc)
                rel_r = _sub(world_r, body_pos)
                rel_v = _sub(world_v, self.body_velocity(new, tc))
                return Transition(
                    time=tc, body=new, orbit=Orbit.from_state(rel_r, rel_v, self.mu_of(new)),
                    point=world_r, moon_pos=self.body_position(MOON, tc),
                    body_pos=body_pos, from_body=body,
                ), rel_v, tc
            r, v, t = r2, v2, t + h
        return None, v, t

    def _predict_moon(self) -> Transition | None:
        """Planet + moon mode: the original fixed-step search (unchanged)."""
        moon = self.moon
        o = self.orbit
        if self.primary == PLANET:
            # Quick reject: the conic never reaches the moon's orbit band.
            if o.periapsis > moon.distance + moon.soi:
                return None
            if o.bound and o.apoapsis < moon.distance - moon.soi:
                return None
            inside = lambda r, t: math.dist(r, moon.position(t)) < moon.soi  # noqa: E731
        else:
            if o.bound and o.apoapsis < moon.soi:
                return None
            inside = lambda r, t: math.hypot(*r) > moon.soi  # noqa: E731

        mu = self.mu_of(self.primary)
        horizon = min(o.period(mu), 200.0)
        steps = int(min(800, max(200, horizon / 0.25)))
        dt = horizon / steps
        r, v, t = self.r, self.v, self.elapsed
        for _ in range(steps):
            r2, v2 = propagate(r, v, dt, mu)
            if inside(r2, t + dt):
                # Bisect for the crossing time.
                lo, hi = 0.0, dt
                for _ in range(30):
                    mid = 0.5 * (lo + hi)
                    if inside(propagate(r, v, mid, mu)[0], t + mid):
                        hi = mid
                    else:
                        lo = mid
                rc, vc = propagate(r, v, hi, mu)
                tc = t + hi
                world_r = _add(rc, self.body_position(self.primary, tc))
                world_v = _add(vc, self.body_velocity(self.primary, tc))
                new = MOON if self.primary == PLANET else PLANET
                body_pos = self.body_position(new, tc)
                rel_r = _sub(world_r, body_pos)
                rel_v = _sub(world_v, self.body_velocity(new, tc))
                return Transition(
                    time=tc, body=new, orbit=Orbit.from_state(rel_r, rel_v, self.mu_of(new)),
                    point=world_r, moon_pos=moon.position(tc),
                    body_pos=body_pos, from_body=self.primary,
                )
            r, v, t = r2, v2, t + dt
            if math.hypot(*r) <= self.radius_of(self.primary):
                return None  # impact before any crossing
        return None

    def _needs_prediction(self, switched: bool) -> bool:
        if self.moon is None:
            return False
        if self.mode == MOON_MODE:
            return self.thrusting or switched or self.elapsed - self._predicted_at > 0.5
        if switched:
            return True
        if self.thrusting:
            return self._real_since_predict >= 0.1   # throttle while burning
        return self.elapsed >= self._predict_valid_until

    # ------------------------------------------------------------------
    def update(self, dt: float, controls: Controls) -> None:
        if self.status != "playing":
            self.thrusting = False
            self.rotating = 0
            return

        # Side thrusters: orientation only, real time (not warped).
        self.rotating = int(controls.left) - int(controls.right)
        rot = FINE_ROTATION_SPEED if controls.fine else ROTATION_SPEED
        self.heading = (self.heading + self.rotating * rot * dt) % (2 * math.pi)

        self.thrusting = controls.thrust
        accel = (FINE_THRUST if controls.fine else MAIN_THRUST) if self.thrusting else 0.0

        if self.mode == SOLAR:
            self.effective_warp = min(self.time_warp, self.warp_limit())
            self._real_since_predict += dt
        else:
            self.effective_warp = self.time_warp
        sim_dt = dt * self.effective_warp
        t = self.elapsed
        self.elapsed += sim_dt
        if self.mode == SOLAR:
            switched = self._advance_solar(t, sim_dt, accel)
        else:
            switched = self._advance(t, sim_dt, accel)

        self._refresh_orbit()
        if self.status != "playing":
            self.transitions = []
            return
        if math.hypot(*self.world_r) > self.escape_radius:
            self.status = "escaped"
            self.transitions = []
        elif not self.thrusting and self.deviation <= self.tolerance:
            self.status = "won"
            self.transitions = []
        elif self._needs_prediction(switched):
            self._predict()

    def _kick_drift(self, h: float, accel: float, mu: float) -> None:
        if accel:
            # Kick-drift-kick: half an impulse, exact Kepler coast, half an
            # impulse.  Second order accurate for finite burns.
            ux, uy = math.cos(self.heading), math.sin(self.heading)
            dv = 0.5 * accel * h
            self.v = (self.v[0] + dv * ux, self.v[1] + dv * uy)
            self.r, self.v = propagate(self.r, self.v, h, mu)
            self.v = (self.v[0] + dv * ux, self.v[1] + dv * uy)
            self.burn_dv += accel * h
        else:
            self.r, self.v = propagate(self.r, self.v, h, mu)

    def _advance(self, t: float, sim_dt: float, accel: float) -> bool:
        """Single / moon modes: fixed sub-steps of at most MAX_STEP_DISTANCE."""
        extra = max((b.speed for b in self.bodies.values()), default=0.0)
        speed = math.hypot(*self.v) + extra
        n = max(1, math.ceil(speed * sim_dt / MAX_STEP_DISTANCE))
        h = sim_dt / n
        switched = False
        for _ in range(n):
            self._kick_drift(h, accel, self.mu_of(self.primary))
            t += h
            switched |= self._check_soi(t)
            if math.hypot(*self.r) <= self.radius_of(self.primary):
                self.status = "crashed"
                break
        return switched

    def _advance_solar(self, t: float, sim_dt: float, accel: float) -> bool:
        """Solar mode: while coasting, jump as far as the nearest SOI
        boundary or surface allows (exact Kepler motion makes long jumps
        free); while burning, small fixed sub-steps."""
        end = t + sim_dt
        switched = False
        for _ in range(100_000):
            if _reached(t, end):
                break
            children = self.children(self.primary)
            p = self.bodies[self.primary]
            child_speed = max((c.speed for c in children), default=0.0)
            speed = math.hypot(*self.v) + child_speed
            h_small = MAX_STEP_DISTANCE / max(speed, 1e-9)
            if accel:
                h = h_small
            else:
                # The rocket is fastest at periapsis: use that speed as the
                # bound so a long jump can't skip a boundary or the surface.
                o = Orbit.from_state(self.r, self.v, p.mu)
                vmax = max(math.hypot(*self.v), _periapsis_speed(o, p.mu)) + child_speed
                gap = self._soi_gap(self.primary, self.r, t, children)
                h = max(0.5 * gap / vmax, h_small)
            h = min(h, end - t)
            self._kick_drift(h, accel, p.mu)
            t += h
            switched |= self._check_soi(t)
            if math.hypot(*self.r) <= self.radius_of(self.primary):
                self.status = "crashed"
                break
        return switched
