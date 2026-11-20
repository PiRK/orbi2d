# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

"""Game state and rules (no Qt dependency, so it can be unit-tested).

Two modes:

* ``single``: one planet; start and target orbits are both around it.
* ``moon``: a planet and a moon on a circular orbit around it.  The start
  orbit is around one body and the target orbit around the other.  Gravity
  uses *patched conics*: inside the moon's sphere of influence (SOI) only the
  moon pulls on the rocket, outside it only the planet does.  Each leg is
  therefore an exact Kepler conic around a single body, and the state vector
  is converted between the two frames when the rocket crosses the SOI.
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

SINGLE = "single"
MOON_MODE = "moon"
MODES = (SINGLE, MOON_MODE)
PLANET = "planet"
MOON = "moon"


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


@dataclass(frozen=True)
class Moon:
    """A moon on a circular, counter-clockwise orbit around the planet."""

    distance: float
    mu: float
    radius: float
    soi: float
    phase0: float
    rate: float  # angular velocity (rad / s)

    @staticmethod
    def create(planet_mu: float, phase0: float) -> "Moon":
        d = MOON_DISTANCE
        return Moon(
            distance=d,
            mu=planet_mu * MOON_MASS_RATIO,
            radius=MOON_RADIUS,
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
        a = self.angle(t)
        return self.distance * math.cos(a), self.distance * math.sin(a)

    def velocity(self, t: float) -> Vec:
        a = self.angle(t)
        return -self.speed * math.sin(a), self.speed * math.cos(a)


@dataclass(frozen=True)
class Transition:
    """Predicted crossing of the moon's sphere of influence."""

    time: float          # game time of the crossing
    body: str            # primary body after the crossing
    orbit: Orbit         # orbit around ``body`` after the crossing
    point: Vec           # world position of the rocket at the crossing
    moon_pos: Vec        # world position of the moon at the crossing


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
    moon: Moon | None = None
    status: str = "playing"        # playing | won | crashed | escaped
    thrusting: bool = False
    rotating: int = 0              # -1 right (cw), +1 left (ccw), 0 none
    time_warp: float = DEFAULT_WARP  # game seconds per real second
    elapsed: float = 0.0
    burn_dv: float = 0.0           # total delta-v spent
    deviation: float = math.inf
    transition: Transition | None = None   # next predicted SOI crossing
    _predicted_at: float = -math.inf

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"unknown mode {self.mode!r}")
        self.reset(self.seed)

    # ---- bodies -------------------------------------------------------
    def mu_of(self, body: str) -> float:
        return self.moon.mu if body == MOON else self.mu

    def radius_of(self, body: str) -> float:
        return self.moon.radius if body == MOON else self.planet_radius

    def body_position(self, body: str, t: float | None = None) -> Vec:
        if body == MOON:
            return self.moon.position(self.elapsed if t is None else t)
        return 0.0, 0.0

    def body_velocity(self, body: str, t: float | None = None) -> Vec:
        if body == MOON:
            return self.moon.velocity(self.elapsed if t is None else t)
        return 0.0, 0.0

    @property
    def world_r(self) -> Vec:
        """Rocket position relative to the planet (screen world frame)."""
        return _add(self.r, self.body_position(self.primary))

    # ------------------------------------------------------------------
    def reset(self, seed: int | None = None) -> None:
        rng = random.Random(seed)
        if self.mode == SINGLE:
            self.moon = None
            start_body = PLANET
            start = random_orbit(rng)
            target = random_orbit(rng)
            # Make sure there is actually something to do.
            while target.deviation_from(start) < 0.3 or start.deviation_from(target) < 0.3:
                target = random_orbit(rng)
            self.target_body = PLANET
        else:
            self.moon = Moon.create(self.mu, rng.uniform(0, 2 * math.pi))
            start_body = rng.choice((PLANET, MOON))
            self.target_body = MOON if start_body == PLANET else PLANET
            orbits = {PLANET: random_orbit(rng), MOON: self._random_moon_orbit(rng)}
            start, target = orbits[start_body], orbits[self.target_body]
        self.target = target
        self.primary = start_body
        self.r, self.v = state_on_orbit(start, rng.uniform(0, 2 * math.pi), self.mu_of(start_body))
        self.heading = math.atan2(self.v[1], self.v[0])  # start pointing prograde
        self.status = "playing"
        self.thrusting = False
        self.rotating = 0
        self.elapsed = 0.0
        self.burn_dv = 0.0
        self._refresh_orbit()
        self._predict()

    def _random_moon_orbit(self, rng: random.Random) -> Orbit:
        max_ra = self.moon.soi * MOON_MAX_APOAPSIS_FRACTION
        rp = rng.uniform(MOON_MIN_PERIAPSIS, max_ra * 0.7)
        ra = rng.uniform(rp, max_ra)
        return Orbit.from_apsides(rp, ra, rng.uniform(0, 2 * math.pi))

    def set_warp(self, warp: float) -> None:
        # Snap to 3 significant digits so repeated +/- steps don't drift
        # (0.5 * 1.25 / 1.25 lands back on exactly 0.5).
        warp = float(f"{warp:.3g}")
        self.time_warp = max(MIN_WARP, min(MAX_WARP, warp))

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
        if self.moon is None:
            return False
        if self.primary == PLANET:
            if math.dist(self.r, self.moon.position(t)) < self.moon.soi:
                self._switch_primary(MOON, t)
                return True
        elif math.hypot(*self.r) > self.moon.soi:
            self._switch_primary(PLANET, t)
            return True
        return False

    def _predict(self) -> None:
        """Find the next SOI crossing of the current coasting trajectory."""
        self._predicted_at = self.elapsed
        self.transition = None
        moon = self.moon
        if moon is None or self.status != "playing":
            return
        o = self.orbit
        if self.primary == PLANET:
            # Quick reject: the conic never reaches the moon's orbit band.
            if o.periapsis > moon.distance + moon.soi:
                return
            if o.bound and o.apoapsis < moon.distance - moon.soi:
                return
            inside = lambda r, t: math.dist(r, moon.position(t)) < moon.soi  # noqa: E731
        else:
            if o.bound and o.apoapsis < moon.soi:
                return
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
                rel_r = _sub(world_r, self.body_position(new, tc))
                rel_v = _sub(world_v, self.body_velocity(new, tc))
                self.transition = Transition(
                    time=tc, body=new, orbit=Orbit.from_state(rel_r, rel_v, self.mu_of(new)),
                    point=world_r, moon_pos=moon.position(tc),
                )
                return
            r, v, t = r2, v2, t + dt
            if math.hypot(*r) <= self.radius_of(self.primary):
                return  # impact before any crossing

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

        sim_dt = dt * self.time_warp
        t = self.elapsed
        self.elapsed += sim_dt
        speed = math.hypot(*self.v) + (self.moon.speed if self.moon else 0.0)
        n = max(1, math.ceil(speed * sim_dt / MAX_STEP_DISTANCE))
        h = sim_dt / n
        ux, uy = math.cos(self.heading), math.sin(self.heading)
        switched = False
        for _ in range(n):
            mu = self.mu_of(self.primary)
            if accel:
                # Kick-drift-kick: half an impulse, exact Kepler coast, half
                # an impulse.  Second order accurate for finite burns.
                dv = 0.5 * accel * h
                self.v = (self.v[0] + dv * ux, self.v[1] + dv * uy)
                self.r, self.v = propagate(self.r, self.v, h, mu)
                self.v = (self.v[0] + dv * ux, self.v[1] + dv * uy)
                self.burn_dv += accel * h
            else:
                self.r, self.v = propagate(self.r, self.v, h, mu)
            t += h
            switched |= self._check_soi(t)
            if math.hypot(*self.r) <= self.radius_of(self.primary):
                self.status = "crashed"
                break

        self._refresh_orbit()
        if self.status != "playing":
            self.transition = None
            return
        if math.hypot(*self.world_r) > ESCAPE_RADIUS:
            self.status = "escaped"
            self.transition = None
        elif not self.thrusting and self.deviation <= self.tolerance:
            self.status = "won"
            self.transition = None
        elif self.moon is not None and (
            self.thrusting or switched or self.elapsed - self._predicted_at > 0.5
        ):
            self._predict()
