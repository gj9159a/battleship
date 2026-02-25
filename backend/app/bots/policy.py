from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

from app.engine.types import Coord, ShotOutcome
from app.rulesets.models import Ruleset

LookaheadMode = Literal["off", "depth1", "depth2", "adaptive"]


@dataclass(frozen=True, slots=True)
class StrongBotConfig:
    lookahead_mode: LookaheadMode = "adaptive"
    lookahead_policy_version: str = "adaptive_v1"


DEFAULT_WEIGHTS: dict[str, float] = {
    "hunt_heat": 1.0,
    "hunt_parity": 0.24,
    "hunt_center": 0.16,
    "target_adjacent": 1.05,
    "target_line": 0.48,
    "target_heat": 0.82,
    "lookahead_hit": 0.72,
    "lookahead_depth2": 0.44,
}


def normalize_weights(weights: dict[str, float] | None) -> dict[str, float]:
    merged = dict(DEFAULT_WEIGHTS)
    if weights:
        for key, value in weights.items():
            if key in merged:
                merged[key] = float(value)
    return merged


class RandomBotPolicy:
    def __init__(self, ruleset: Ruleset, rng: random.Random) -> None:
        self._size = ruleset.board_size
        self._rng = rng
        self._fired: set[Coord] = set()

    def select_shot(self) -> Coord:
        options = [
            (row, col)
            for row in range(self._size)
            for col in range(self._size)
            if (row, col) not in self._fired
        ]
        if not options:
            raise RuntimeError("No valid shots left")
        shot = self._rng.choice(options)
        self._fired.add(shot)
        return shot

    def observe_shot(self, coord: Coord, outcome: ShotOutcome) -> None:
        if coord not in self._fired:
            self._fired.add(coord)


class StrongBotPolicy:
    def __init__(
        self,
        ruleset: Ruleset,
        rng: random.Random,
        *,
        weights: dict[str, float] | None = None,
        config: StrongBotConfig | None = None,
    ) -> None:
        self._ruleset = ruleset
        self._size = ruleset.board_size
        self._rng = rng
        self._weights = normalize_weights(weights)
        self._config = config or StrongBotConfig()

        self._fired: set[Coord] = set()
        self._misses: set[Coord] = set()
        self._hits_pending: set[Coord] = set()
        self._hits_sunk: set[Coord] = set()
        self._remaining_fleet: list[int] = sorted(ruleset.fleet)

    def select_shot(self) -> Coord:
        available = [
            (row, col)
            for row in range(self._size)
            for col in range(self._size)
            if (row, col) not in self._fired
        ]
        if not available:
            raise RuntimeError("No valid shots left")

        target_mode = bool(self._hits_pending)
        heat = self._build_heat(target_mode=target_mode)
        total_heat = sum(max(0.0, value) for value in heat.values())
        max_prob = max((value for value in heat.values()), default=0.0)
        candidates = self._candidate_cells(available, target_mode)

        depth = self._resolve_depth(
            target_mode=target_mode,
            max_prob=max_prob,
            remaining_cells=len(available),
            target_candidates=len(candidates),
            target_hits=len(self._hits_pending),
        )

        scored: list[tuple[float, Coord]] = []
        for cell in candidates:
            base_score = self._base_score(cell, heat=heat, target_mode=target_mode)
            probability = 0.0
            if total_heat > 0:
                probability = max(0.0, heat.get(cell, 0.0)) / total_heat

            if depth >= 1:
                base_score += self._weights["lookahead_hit"] * probability

            if depth >= 2:
                neighborhood = self._neighbor_average_heat(cell, heat)
                frontier_focus = 1.0 / max(1, len(candidates))
                base_score += self._weights["lookahead_depth2"] * probability * neighborhood * (1.0 + frontier_focus)

            tie_noise = self._rng.random() * 1e-9
            scored.append((base_score + tie_noise, cell))

        scored.sort(key=lambda item: item[0], reverse=True)
        shot = scored[0][1]
        self._fired.add(shot)
        return shot

    def observe_shot(self, coord: Coord, outcome: ShotOutcome) -> None:
        self._fired.add(coord)
        if outcome == "miss":
            self._misses.add(coord)
            return

        if outcome == "hit":
            self._hits_pending.add(coord)
            return

        # sunk
        self._hits_pending.add(coord)
        sunk_cluster = self._collect_cluster(coord, self._hits_pending)
        self._hits_pending.difference_update(sunk_cluster)
        self._hits_sunk.update(sunk_cluster)
        self._consume_remaining_ship(len(sunk_cluster))

    def _candidate_cells(self, available: list[Coord], target_mode: bool) -> list[Coord]:
        if not target_mode:
            return available

        frontier: set[Coord] = set()
        for cell in self._hits_pending:
            for neighbor in self._orthogonal_neighbors(cell):
                if neighbor in self._fired:
                    continue
                frontier.add(neighbor)
        return list(frontier) if frontier else available

    def _base_score(self, cell: Coord, *, heat: dict[Coord, float], target_mode: bool) -> float:
        row, col = cell
        center = (self._size - 1) / 2
        dist_center = abs(row - center) + abs(col - center)
        center_score = 1.0 - (dist_center / max(1.0, self._size - 1))
        parity = 1.0 if (row + col) % 2 == 0 else 0.0

        if not target_mode:
            return (
                self._weights["hunt_heat"] * heat.get(cell, 0.0)
                + self._weights["hunt_parity"] * parity
                + self._weights["hunt_center"] * center_score
            )

        adjacent_hits = sum(1 for n in self._orthogonal_neighbors(cell) if n in self._hits_pending)
        line_bonus = self._line_bonus(cell)
        return (
            self._weights["target_adjacent"] * adjacent_hits
            + self._weights["target_line"] * line_bonus
            + self._weights["target_heat"] * heat.get(cell, 0.0)
        )

    def _resolve_depth(
        self,
        *,
        target_mode: bool,
        max_prob: float,
        remaining_cells: int,
        target_candidates: int,
        target_hits: int,
    ) -> int:
        mode = self._config.lookahead_mode
        if mode == "off":
            return 0
        if mode == "depth1":
            return 1
        if mode == "depth2":
            return 2

        # adaptive_v1: deterministic policy
        if self._config.lookahead_policy_version != "adaptive_v1":
            return 1

        aligned = self._has_alignment()
        if target_mode and (target_hits >= 2 or aligned):
            return 2

        if target_mode and target_hits >= 1 and target_candidates <= max(6, self._size // 2):
            return 2

        if remaining_cells <= max(40, self._size * self._size // 2) and max_prob >= 0.12:
            return 2

        if max_prob >= 0.24:
            return 2

        return 1

    def _build_heat(self, *, target_mode: bool) -> dict[Coord, float]:
        heat: dict[Coord, float] = {}
        target_hits = set(self._hits_pending)
        for length in self._remaining_fleet:
            for orientation in ("H", "V"):
                row_limit = self._size if orientation == "H" else self._size - length + 1
                col_limit = self._size - length + 1 if orientation == "H" else self._size
                for row in range(row_limit):
                    for col in range(col_limit):
                        cells = self._placement_cells(row, col, length, orientation)
                        if any(cell in self._misses for cell in cells):
                            continue
                        if any(cell in self._hits_sunk for cell in cells):
                            continue
                        if target_mode and target_hits and not any(cell in target_hits for cell in cells):
                            continue

                        for cell in cells:
                            if cell in self._fired:
                                continue
                            heat[cell] = heat.get(cell, 0.0) + 1.0

        if not heat:
            for row in range(self._size):
                for col in range(self._size):
                    cell = (row, col)
                    if cell not in self._fired:
                        heat[cell] = 1e-6

        max_value = max(heat.values())
        if max_value > 0:
            for key in list(heat.keys()):
                heat[key] = heat[key] / max_value
        return heat

    def _line_bonus(self, cell: Coord) -> float:
        if len(self._hits_pending) < 2:
            return 0.0

        rows = {row for row, _ in self._hits_pending}
        cols = {col for _, col in self._hits_pending}
        if len(rows) == 1:
            return 1.0 if cell[0] in rows else 0.0
        if len(cols) == 1:
            return 1.0 if cell[1] in cols else 0.0
        return 0.0

    def _has_alignment(self) -> bool:
        if len(self._hits_pending) < 2:
            return False
        rows = {row for row, _ in self._hits_pending}
        cols = {col for _, col in self._hits_pending}
        return len(rows) == 1 or len(cols) == 1

    def _neighbor_average_heat(self, cell: Coord, heat: dict[Coord, float]) -> float:
        values = [heat.get(neighbor, 0.0) for neighbor in self._orthogonal_neighbors(cell)]
        if not values:
            return 0.0
        return sum(values) / len(values)

    def _consume_remaining_ship(self, length: int) -> None:
        for idx, ship_len in enumerate(self._remaining_fleet):
            if ship_len == length:
                self._remaining_fleet.pop(idx)
                return
        if self._remaining_fleet:
            self._remaining_fleet.pop()

    def _collect_cluster(self, start: Coord, source: set[Coord]) -> set[Coord]:
        stack = [start]
        visited: set[Coord] = set()
        while stack:
            cell = stack.pop()
            if cell in visited or cell not in source:
                continue
            visited.add(cell)
            for neighbor in self._orthogonal_neighbors(cell):
                if neighbor in source and neighbor not in visited:
                    stack.append(neighbor)
        return visited

    def _placement_cells(self, row: int, col: int, length: int, orientation: str) -> tuple[Coord, ...]:
        if orientation == "H":
            return tuple((row, col + offset) for offset in range(length))
        return tuple((row + offset, col) for offset in range(length))

    def _orthogonal_neighbors(self, cell: Coord) -> tuple[Coord, ...]:
        row, col = cell
        result: list[Coord] = []
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = row + dr, col + dc
            if 0 <= nr < self._size and 0 <= nc < self._size:
                result.append((nr, nc))
        return tuple(result)
