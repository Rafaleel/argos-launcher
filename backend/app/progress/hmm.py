"""Pure-NumPy exact discrete Hidden Markov Model (Bayesian filter) for game progress.

Progress is modeled as a latent discrete state s in {0, 1, ..., N}:
- s = 0 is the start of the game (0%).
- s = k (1 <= k <= N) means the furthest story milestone reached is milestone k.
- Any milestone typed `win_condition` maps to 100%, so completing the story
  locks progress to 100% even when earlier optional milestones were skipped.
- Games without milestones use a generic N-state grid (default 20 states, 0%..100%).
"""

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class FilterParams:
    ram_error: float = 0.001
    ach_false_pos: float = 0.0001
    playtime_dispersion: float = 0.55
    min_sigma: float = 0.35
    default_ttb_hours: float = 12.0
    generic_states: int = 20
    reset_prob_threshold: float = 0.95
    prior_floor: float = 0.02


@dataclass(frozen=True)
class Estimate:
    mean: float
    lower: float
    upper: float
    margin: float
    distribution: list[float]


class DiscreteProgressFilter:
    """Exact discrete Bayesian filter over ordered completion states."""

    def __init__(
        self,
        state_values: np.ndarray,
        win_indices: set[int] | None = None,
        params: FilterParams | None = None,
    ) -> None:
        if state_values.ndim != 1 or len(state_values) < 2:
            raise ValueError("state_values must be a 1D array with at least 2 states")
        self.state_values = np.asarray(state_values, dtype=np.float64)
        self.k = len(self.state_values)
        self.win_indices = set(win_indices or ())
        self.params = params or FilterParams()
        self.belief = np.zeros(self.k, dtype=np.float64)
        self.belief[0] = 1.0
        self.last_ram_idx: int | None = None
        self.resets: int = 0

    @classmethod
    def for_milestones(cls, kinds: list[str], params: FilterParams | None = None) -> "DiscreteProgressFilter":
        """Build a filter for an ordered list of milestones (each 'progression' or 'win_condition')."""
        n = len(kinds)
        if n < 1:
            raise ValueError("At least one milestone is required")
        values = np.zeros(n + 1, dtype=np.float64)
        win_indices: set[int] = set()
        for idx, kind in enumerate(kinds, start=1):
            if kind == "win_condition":
                values[idx] = 100.0
                win_indices.add(idx)
            else:
                values[idx] = 100.0 * idx / n
        # Guarantee monotonic non-decreasing values so CDF quantiles never invert and winning stays at 100%.
        values = np.maximum.accumulate(values)
        return cls(values, win_indices=win_indices, params=params)

    @classmethod
    def generic(cls, params: FilterParams | None = None) -> "DiscreteProgressFilter":
        """Build a filter on a generic 0%..100% grid when no milestones exist."""
        p = params or FilterParams()
        values = np.linspace(0.0, 100.0, p.generic_states + 1, dtype=np.float64)
        return cls(values, win_indices={p.generic_states}, params=p)

    def predict(self, dt_hours: float, ttb_hours: float | None = None) -> None:
        """Advance belief monotonically according to elapsed playtime and expected time-to-beat."""
        if dt_hours <= 0.0:
            return
        ttb = ttb_hours if (ttb_hours is not None and ttb_hours > 0.0) else self.params.default_ttb_hours
        n = self.k - 1
        mu = (dt_hours / ttb) * n
        sigma = max(self.params.min_sigma, self.params.playtime_dispersion * math.sqrt(mu + 0.25))

        trans = np.zeros((self.k, self.k), dtype=np.float64)
        for i in range(self.k):
            deltas = np.arange(self.k - i, dtype=np.float64)
            weights = np.exp(-0.5 * ((deltas - mu) / sigma) ** 2)
            total = float(weights.sum())
            if total > 0.0:
                trans[i, i:] = weights / total
            else:
                # Extreme mu/sigma underflow fallback: jump to the closest reachable state
                target = min(self.k - 1, i + int(round(mu)))
                trans[i, target] = 1.0

        nxt = self.belief @ trans
        total = float(nxt.sum())
        if total > 0.0:
            self.belief = nxt / total

    def _ram_likelihood(self, target: int) -> np.ndarray:
        eps = min(max(self.params.ram_error, 1e-6), 0.5)
        like = np.full(self.k, eps / max(1, self.k - 1), dtype=np.float64)
        like[target] = 1.0 - eps
        return like

    def update_ram(self, furthest_idx: int, win_reached: bool = False) -> bool:
        """Apply a high-reliability live RAM milestone observation. Returns True if a reset occurred."""
        if win_reached:
            target = self.k - 1  # absorbing 100% terminal state
        else:
            target = min(max(int(furthest_idx), 0), self.k - 1)

        like = self._ram_likelihood(target)
        prob_above = float(self.belief[target + 2 :].sum()) if (target + 2) < self.k else 0.0
        if (
            self.last_ram_idx is not None
            and target < self.last_ram_idx - 1
            and prob_above > self.params.reset_prob_threshold
        ):
            # Sharp drop in RAM milestones (e.g. older save loaded or New Game+): reset belief cleanly.
            self.belief = like / float(like.sum())
            self.resets += 1
            self.last_ram_idx = target
            return True

        # Mix a tiny uniform floor before Bayes update so strong evidence (RAM / achievements)
        # can override a playtime-only prior even when the player moves much faster than TTB.
        prior = (1.0 - self.params.prior_floor) * self.belief + (self.params.prior_floor / self.k)
        posterior = prior * like
        total = float(posterior.sum())
        if total <= 1e-15:
            self.belief = like / float(like.sum())
            self.resets += 1
            self.last_ram_idx = target
            return True

        self.belief = posterior / total
        self.last_ram_idx = target
        return False

    def update_achievements(self, furthest_idx: int, win_reached: bool = False) -> None:
        """Apply an achievement lower-bound ('at least up to furthest_idx')."""
        if furthest_idx <= 0 and not win_reached:
            return
        if win_reached:
            target = self.k - 1  # absorbing 100% terminal state
        else:
            target = min(max(int(furthest_idx), 0), self.k - 1)

        like = np.ones(self.k, dtype=np.float64)
        fp = min(max(self.params.ach_false_pos, 1e-6), 0.5)
        like[:target] = min(fp, 1e-5) if win_reached else fp
        prior = (1.0 - self.params.prior_floor) * self.belief + (self.params.prior_floor / self.k)
        posterior = prior * like
        total = float(posterior.sum())
        if total > 1e-15:
            self.belief = posterior / total

    def estimate(self) -> Estimate:
        """Return mean completion %, 90% credible interval [lower, upper], and half-width margin."""
        mean = float(np.dot(self.belief, self.state_values))
        cdf = np.cumsum(self.belief)
        lower_idx = int(np.searchsorted(cdf, 0.05))
        upper_idx = int(np.searchsorted(cdf, 0.95))
        lower = float(self.state_values[min(lower_idx, self.k - 1)])
        upper = float(self.state_values[min(upper_idx, self.k - 1)])

        mean = round(min(100.0, max(0.0, mean)), 1)
        lower = round(min(mean, max(0.0, lower)), 1)
        upper = round(min(100.0, max(mean, upper)), 1)
        margin = round(max(0.0, (upper - lower) / 2.0), 1)
        return Estimate(
            mean=mean,
            lower=lower,
            upper=upper,
            margin=margin,
            distribution=[round(float(p), 5) for p in self.belief],
        )
