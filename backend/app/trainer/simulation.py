import math
import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WindowMetrics:
    wr_baseline: float
    wr_active: float
    avg_turns_win: float
    score: float


def compute_score(wr_baseline: float, wr_active: float, avg_turns_win: float) -> float:
    turn_efficiency = max(0.0, min(1.0, 1 - (avg_turns_win - 20.0) / 60.0))
    return 0.6 * wr_baseline + 0.3 * wr_active + 0.1 * turn_efficiency


class DeterministicSimulator:
    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def next_window(self, windows_done: int) -> WindowMetrics:
        # Smooth saturating curve to make plateau detection testable.
        trend = 0.38 + 0.40 * (1 - math.exp(-(windows_done + 1) / 6.0))
        wr_baseline = min(0.97, max(0.05, trend + self._rng.uniform(-0.01, 0.01)))
        wr_active = min(0.95, max(0.05, trend - 0.05 + self._rng.uniform(-0.015, 0.015)))
        avg_turns_win = max(20.0, 68.0 - windows_done * 0.9 + self._rng.uniform(-1.2, 1.2))
        score = compute_score(wr_baseline, wr_active, avg_turns_win)
        return WindowMetrics(
            wr_baseline=round(wr_baseline, 6),
            wr_active=round(wr_active, 6),
            avg_turns_win=round(avg_turns_win, 6),
            score=round(score, 6),
        )
