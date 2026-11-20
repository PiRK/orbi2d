# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

"""Two-body orbital mechanics in 2D.

The rocket is a point mass orbiting a planet of gravitational parameter ``mu``.
Coasting is propagated *analytically* with the universal-variable Kepler
solution, so the rocket follows its conic exactly (no integrator drift) and
the drawn orbit always matches the actual trajectory.  Thrust is applied as a
sequence of small velocity kicks; after every kick the osculating orbit is
recomputed from the new state vector.  That makes every manoeuvre - prograde,
retrograde, radial, or any arbitrary direction at any point of the orbit -
behave according to real orbital mechanics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Vec = tuple[float, float]


def _stumpff(z: float) -> tuple[float, float]:
    """Stumpff functions C(z), S(z)."""
    if z > 1e-4:
        s = math.sqrt(z)
        return (1.0 - math.cos(s)) / z, (s - math.sin(s)) / (s * s * s)
    if z < -1e-4:
        s = math.sqrt(-z)
        return (math.cosh(s) - 1.0) / (-z), (math.sinh(s) - s) / (s * s * s)
    # Series expansion around z = 0 (parabolic / very short arcs).
    return (
        1.0 / 2 - z / 24 + z * z / 720 - z ** 3 / 40320,
        1.0 / 6 - z / 120 + z * z / 5040 - z ** 3 / 362880,
    )


def propagate(r0: Vec, v0: Vec, dt: float, mu: float) -> tuple[Vec, Vec]:
    """Advance a Keplerian state (r0, v0) by ``dt`` (any conic: ellipse,
    parabola or hyperbola) using the universal-variable formulation."""
    if dt == 0.0:
        return r0, v0
    x0, y0 = r0
    vx0, vy0 = v0
    rn = math.hypot(x0, y0)
    v2 = vx0 * vx0 + vy0 * vy0
    vr = (x0 * vx0 + y0 * vy0) / rn
    sqmu = math.sqrt(mu)
    alpha = 2.0 / rn - v2 / mu  # 1/a (negative for hyperbolas)

    # Newton iteration on the universal anomaly chi.
    if alpha > 1e-9:
        chi = sqmu * dt * alpha
    else:
        chi = sqmu * dt / rn
    k1 = rn * vr / sqmu
    k2 = 1.0 - alpha * rn
    for _ in range(50):
        z = alpha * chi * chi
        c, s = _stumpff(z)
        chi2 = chi * chi
        f = k1 * chi2 * c + k2 * chi2 * chi * s + rn * chi - sqmu * dt
        fp = k1 * chi * (1.0 - z * s) + k2 * chi2 * c + rn
        step = f / fp
        chi -= step
        if abs(step) < 1e-12 * max(1.0, abs(chi)):
            break

    z = alpha * chi * chi
    c, s = _stumpff(z)
    chi2 = chi * chi
    f = 1.0 - chi2 / rn * c
    g = dt - chi2 * chi / sqmu * s
    x = f * x0 + g * vx0
    y = f * y0 + g * vy0
    r = math.hypot(x, y)
    fdot = sqmu / (r * rn) * (alpha * chi2 * chi * s - chi)
    gdot = 1.0 - chi2 / r * c
    return (x, y), (fdot * x0 + gdot * vx0, fdot * y0 + gdot * vy0)


@dataclass(frozen=True)
class Orbit:
    """Shape of a conic orbit around the planet (focus at the origin).

    Defined by the semi-latus rectum ``p``, eccentricity ``e`` and argument of
    periapsis ``omega`` (angle of the periapsis direction).  ``h_sign`` is +1
    for counter-clockwise motion and -1 for clockwise motion.
    """

    p: float
    e: float
    omega: float
    h_sign: float = 1.0

    # ---- construction -------------------------------------------------
    @staticmethod
    def from_apsides(rp: float, ra: float, omega: float, h_sign: float = 1.0) -> "Orbit":
        e = (ra - rp) / (ra + rp)
        return Orbit(p=rp * (1.0 + e), e=e, omega=omega, h_sign=h_sign)

    @staticmethod
    def from_state(r: Vec, v: Vec, mu: float) -> "Orbit":
        x, y = r
        vx, vy = v
        rn = math.hypot(x, y)
        v2 = vx * vx + vy * vy
        h = x * vy - y * vx
        rv = x * vx + y * vy
        ex = ((v2 - mu / rn) * x - rv * vx) / mu
        ey = ((v2 - mu / rn) * y - rv * vy) / mu
        e = math.hypot(ex, ey)
        omega = math.atan2(ey, ex) if e > 1e-12 else 0.0
        return Orbit(p=h * h / mu, e=e, omega=omega, h_sign=1.0 if h >= 0 else -1.0)

    # ---- derived quantities -------------------------------------------
    @property
    def bound(self) -> bool:
        return self.e < 1.0

    @property
    def periapsis(self) -> float:
        return self.p / (1.0 + self.e)

    @property
    def apoapsis(self) -> float:
        return self.p / (1.0 - self.e) if self.e < 1.0 else math.inf

    @property
    def semi_major_axis(self) -> float:
        return self.p / (1.0 - self.e * self.e) if self.e != 1.0 else math.inf

    def period(self, mu: float) -> float:
        if not self.bound:
            return math.inf
        a = self.semi_major_axis
        return 2.0 * math.pi * math.sqrt(a ** 3 / mu)

    def radius_at(self, true_anomaly: float) -> float:
        denom = 1.0 + self.e * math.cos(true_anomaly)
        return self.p / denom if denom > 1e-12 else math.inf

    def radius_at_angle(self, theta: float) -> float:
        """Radius of the orbit curve along polar direction ``theta``."""
        return self.radius_at(theta - self.omega)

    def point_at(self, true_anomaly: float) -> Vec:
        r = self.radius_at(true_anomaly)
        ang = self.omega + true_anomaly
        return r * math.cos(ang), r * math.sin(ang)

    def sample(self, n: int = 360, r_max: float = math.inf) -> list[Vec]:
        """Points along the orbit curve (closed loop for ellipses, a single
        clipped branch for parabolas / hyperbolas)."""
        if self.bound:
            return [self.point_at(2.0 * math.pi * i / n) for i in range(n + 1)]
        # Asymptote true anomaly; clip the branch at r_max.
        nu_inf = math.acos(-1.0 / self.e)
        nu_lim = nu_inf - 1e-3
        if math.isfinite(r_max):
            # r(nu) = r_max  ->  cos(nu) = (p / r_max - 1) / e
            c = (self.p / r_max - 1.0) / self.e
            if -1.0 <= c <= 1.0:
                nu_lim = min(nu_lim, math.acos(c))
        return [self.point_at(-nu_lim + 2.0 * nu_lim * i / n) for i in range(n + 1)]

    def deviation_from(self, target: "Orbit", samples: int = 360) -> float:
        """Maximum relative radial distance between this orbit's curve and
        ``target``'s curve, over all polar directions.  0 means identical.

        This is a purely geometric comparison: it is well defined for
        near-circular orbits (where the argument of periapsis is meaningless)
        and treats any combination of size, shape and orientation errors."""
        if not self.bound:
            return math.inf
        worst = 0.0
        for i in range(samples):
            th = 2.0 * math.pi * i / samples
            rt = target.radius_at_angle(th)
            worst = max(worst, abs(self.radius_at_angle(th) - rt) / rt)
        return worst
