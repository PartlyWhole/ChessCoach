"""Glicko-2 (Mark Glickman, "Example of the Glicko-2 system", 2013), implemented from the paper.
Used for game, drill and (v2) concept ratings (docs/06 §1)."""
from __future__ import annotations

import math
from dataclasses import dataclass

SCALE = 173.7178
TAU = 0.5
EPS = 1e-6


@dataclass
class Glicko:
    rating: float = 1500.0
    rd: float = 350.0
    vol: float = 0.06


def _g(phi: float) -> float:
    return 1 / math.sqrt(1 + 3 * phi * phi / math.pi ** 2)


def _e(mu: float, mu_j: float, phi_j: float) -> float:
    return 1 / (1 + math.exp(-_g(phi_j) * (mu - mu_j)))


def expected(a: Glicko, b: Glicko) -> float:
    """Expected score of `a` against `b`."""
    return _e((a.rating - 1500) / SCALE, (b.rating - 1500) / SCALE, b.rd / SCALE)


def update(player: Glicko, results: list[tuple[Glicko, float]], tau: float = TAU) -> Glicko:
    """One rating period. `results`: (opponent, score) with score 1 win / 0.5 draw / 0 loss."""
    mu, phi, sigma = (player.rating - 1500) / SCALE, player.rd / SCALE, player.vol
    if not results:
        phi_star = math.sqrt(phi * phi + sigma * sigma)
        return Glicko(player.rating, min(350.0, phi_star * SCALE), sigma)
    v_inv, delta_sum = 0.0, 0.0
    for opp, s in results:
        mu_j, phi_j = (opp.rating - 1500) / SCALE, opp.rd / SCALE
        g, e = _g(phi_j), _e(mu, mu_j, phi_j)
        v_inv += g * g * e * (1 - e)
        delta_sum += g * (s - e)
    v = 1 / v_inv
    delta = v * delta_sum

    # Step 5: new volatility (Illinois algorithm).
    a = math.log(sigma * sigma)

    def f(x: float) -> float:
        ex = math.exp(x)
        return ex * (delta * delta - phi * phi - v - ex) / (2 * (phi * phi + v + ex) ** 2) - (x - a) / (tau * tau)

    A = a
    if delta * delta > phi * phi + v:
        B = math.log(delta * delta - phi * phi - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        B = a - k * tau
    fa, fb = f(A), f(B)
    while abs(B - A) > EPS:
        C = A + (A - B) * fa / (fb - fa)
        fc = f(C)
        if fc * fb <= 0:
            A, fa = B, fb
        else:
            fa /= 2
        B, fb = C, fc
    sigma_new = math.exp(A / 2)

    phi_star = math.sqrt(phi * phi + sigma_new * sigma_new)
    phi_new = 1 / math.sqrt(1 / (phi_star * phi_star) + 1 / v)
    mu_new = mu + phi_new * phi_new * delta_sum
    return Glicko(mu_new * SCALE + 1500, phi_new * SCALE, sigma_new)


def update_pair(a: Glicko, b: Glicko, score_a: float) -> tuple[Glicko, Glicko]:
    """Single game between two rated entities (player vs drill: a failed drill is a win for the drill)."""
    return update(a, [(b, score_a)]), update(b, [(a, 1 - score_a)])
