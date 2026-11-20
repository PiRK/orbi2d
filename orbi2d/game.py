"""Game state and rules (no Qt dependency, so it can be unit-tested)."""

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
TIME_WARPS = (1, 2, 4, 8)


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


@dataclass
class Game:
    seed: int | None = None
    mu: float = MU
    planet_radius: float = PLANET_RADIUS
    tolerance: float = TOLERANCE

    r: Vec = (0.0, 0.0)
    v: Vec = (0.0, 0.0)
    heading: float = 0.0           # direction the nose points (rad)
    orbit: Orbit = field(default=None)  # type: ignore[assignment]
    target: Orbit = field(default=None)  # type: ignore[assignment]
    status: str = "playing"        # playing | won | crashed | escaped
    thrusting: bool = False
    rotating: int = 0              # -1 right (cw), +1 left (ccw), 0 none
    warp_index: int = 0
    elapsed: float = 0.0
    burn_dv: float = 0.0           # total delta-v spent
    deviation: float = math.inf

    def __post_init__(self) -> None:
        self.reset(self.seed)

    # ------------------------------------------------------------------
    def reset(self, seed: int | None = None) -> None:
        rng = random.Random(seed)
        start = random_orbit(rng)
        target = random_orbit(rng)
        # Make sure there is actually something to do.
        while target.deviation_from(start) < 0.3 or start.deviation_from(target) < 0.3:
            target = random_orbit(rng)
        self.target = target
        self.r, self.v = state_on_orbit(start, rng.uniform(0, 2 * math.pi), self.mu)
        self.heading = math.atan2(self.v[1], self.v[0])  # start pointing prograde
        self.status = "playing"
        self.thrusting = False
        self.rotating = 0
        self.elapsed = 0.0
        self.burn_dv = 0.0
        self._refresh_orbit()

    @property
    def time_warp(self) -> int:
        return TIME_WARPS[self.warp_index]

    def set_warp(self, index: int) -> None:
        self.warp_index = max(0, min(len(TIME_WARPS) - 1, index))

    def _refresh_orbit(self) -> None:
        self.orbit = Orbit.from_state(self.r, self.v, self.mu)
        self.deviation = self.orbit.deviation_from(self.target)

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
        self.elapsed += sim_dt
        speed = math.hypot(*self.v)
        n = max(1, math.ceil(speed * sim_dt / MAX_STEP_DISTANCE))
        h = sim_dt / n
        ux, uy = math.cos(self.heading), math.sin(self.heading)
        for _ in range(n):
            if accel:
                # Kick-drift-kick: half an impulse, exact Kepler coast, half
                # an impulse.  Second order accurate for finite burns.
                dv = 0.5 * accel * h
                self.v = (self.v[0] + dv * ux, self.v[1] + dv * uy)
                self.r, self.v = propagate(self.r, self.v, h, self.mu)
                self.v = (self.v[0] + dv * ux, self.v[1] + dv * uy)
                self.burn_dv += accel * h
            else:
                self.r, self.v = propagate(self.r, self.v, h, self.mu)
            if math.hypot(*self.r) <= self.planet_radius:
                self.status = "crashed"
                break

        self._refresh_orbit()
        if self.status != "playing":
            return
        if math.hypot(*self.r) > ESCAPE_RADIUS:
            self.status = "escaped"
        elif not self.thrusting and self.deviation <= self.tolerance:
            self.status = "won"
