import hashlib
import inspect
import random
import threading
from datetime import UTC, datetime
from uuid import uuid4

from app.bots.selfplay import generate_random_placements
from app.rulesets import get_ruleset


class PlacementDiagnosticsService:
    _SEED_DERIVATION_SCHEME = "anchor_plus_index_mul_1009_v1"
    _DEFAULT_SEED_ANCHOR = 17_711
    _MAX_SAMPLES = 100_000

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last_reports: dict[str, dict[str, object]] = {}

    def analyze_bias(
        self,
        *,
        ruleset_id: str,
        sample_count: int,
        seed_anchor: int | None = None,
    ) -> dict[str, object]:
        if sample_count <= 0:
            raise ValueError("sample_count must be > 0")
        if sample_count > self._MAX_SAMPLES:
            raise ValueError(f"sample_count must be <= {self._MAX_SAMPLES}")

        ruleset = get_ruleset(ruleset_id)
        size = ruleset.board_size
        resolved_seed_anchor = self._DEFAULT_SEED_ANCHOR if seed_anchor is None else int(seed_anchor)

        occupancy = self._empty_heatmap(size)
        occupancy_by_len: dict[int, list[list[int]]] = {
            ship_len: self._empty_heatmap(size)
            for ship_len in sorted(set(ruleset.fleet))
        }
        orientation_counts: dict[int, dict[str, int]] = {
            ship_len: {"horizontal": 0, "vertical": 0, "total": 0}
            for ship_len in sorted(set(ruleset.fleet))
        }

        total_occupied_cells = 0
        edge_hits = 0
        center_hits = 0
        corner_hits = 0
        corners = {
            (0, 0),
            (0, size - 1),
            (size - 1, 0),
            (size - 1, size - 1),
        }

        for sample_index in range(sample_count):
            sample_seed = self._derive_seed(resolved_seed_anchor, sample_index)
            placements = generate_random_placements(ruleset, random.Random(sample_seed))
            for placement in placements:
                ship_len = placement.length
                orientation_key = "horizontal" if placement.orientation == "H" else "vertical"
                orientation_counts[ship_len][orientation_key] += 1
                orientation_counts[ship_len]["total"] += 1

                for row, col in placement.cells():
                    occupancy[row][col] += 1
                    occupancy_by_len[ship_len][row][col] += 1
                    total_occupied_cells += 1
                    if self._is_edge(row, col, size):
                        edge_hits += 1
                    else:
                        center_hits += 1
                    if (row, col) in corners:
                        corner_hits += 1

        occupancy_heatmap = self._normalize_heatmap(occupancy, sample_count)
        occupancy_by_ship_len = {
            str(ship_len): self._normalize_heatmap(heatmap, sample_count)
            for ship_len, heatmap in occupancy_by_len.items()
        }
        orientation_stats_by_len: dict[str, dict[str, float | int]] = {}
        for ship_len, counters in orientation_counts.items():
            total = max(1, counters["total"])
            orientation_stats_by_len[str(ship_len)] = {
                "horizontal": counters["horizontal"],
                "vertical": counters["vertical"],
                "total": counters["total"],
                "horizontal_share": round(counters["horizontal"] / total, 6),
                "vertical_share": round(counters["vertical"] / total, 6),
            }

        total_cells = size * size
        edge_cells = total_cells - max(0, size - 2) * max(0, size - 2)
        center_cells = max(0, total_cells - edge_cells)
        occupied = max(1, total_occupied_cells)

        observed_edge_share = edge_hits / occupied
        observed_center_share = center_hits / occupied
        expected_edge_share = edge_cells / total_cells
        expected_center_share = center_cells / total_cells

        edge_center_bias = {
            "edge_cells": float(edge_cells),
            "center_cells": float(center_cells),
            "observed_edge_share": round(observed_edge_share, 6),
            "observed_center_share": round(observed_center_share, 6),
            "expected_edge_share": round(expected_edge_share, 6),
            "expected_center_share": round(expected_center_share, 6),
            "edge_over_expected": round(observed_edge_share / max(expected_edge_share, 1e-9), 6),
            "center_over_expected": round(observed_center_share / max(expected_center_share, 1e-9), 6),
            "edge_center_ratio_over_expected": round(
                (observed_edge_share / max(observed_center_share, 1e-9))
                / (expected_edge_share / max(expected_center_share, 1e-9)),
                6,
            ),
        }

        observed_corner_share = corner_hits / occupied
        expected_corner_share = 4 / total_cells
        corner_bias = {
            "observed_corner_share": round(observed_corner_share, 6),
            "expected_corner_share": round(expected_corner_share, 6),
            "corner_over_expected": round(observed_corner_share / max(expected_corner_share, 1e-9), 6),
        }

        reproducibility = self._seed_reproducibility_check(
            ruleset_id=ruleset_id,
            seed_anchor=resolved_seed_anchor,
            sample_count=sample_count,
        )

        report = {
            "report_id": str(uuid4()),
            "ruleset_id": ruleset_id,
            "sample_count": sample_count,
            "seed_anchor": resolved_seed_anchor,
            "seed_derivation_scheme": self._SEED_DERIVATION_SCHEME,
            "generator_version": self._generator_version(),
            "created_at": datetime.now(tz=UTC).isoformat(),
            "occupancy_heatmap": occupancy_heatmap,
            "occupancy_by_ship_len": occupancy_by_ship_len,
            "orientation_stats_by_len": orientation_stats_by_len,
            "edge_center_bias": edge_center_bias,
            "corner_bias": corner_bias,
            "retry_stats": {
                "available": False,
                "reason": "unavailable_without_generator_instrumentation",
            },
            "seed_reproducibility_check": reproducibility,
        }

        with self._lock:
            self._last_reports[ruleset_id] = report
        return report

    def get_last_report(self, ruleset_id: str) -> dict[str, object] | None:
        with self._lock:
            report = self._last_reports.get(ruleset_id)
            if report is None:
                return None
            return dict(report)

    @classmethod
    def _derive_seed(cls, seed_anchor: int, seed_index: int) -> int:
        return seed_anchor + seed_index * 1009

    @staticmethod
    def _empty_heatmap(size: int) -> list[list[int]]:
        return [[0 for _ in range(size)] for _ in range(size)]

    @staticmethod
    def _normalize_heatmap(matrix: list[list[int]], sample_count: int) -> list[list[float]]:
        denominator = max(1, sample_count)
        return [[round(value / denominator, 6) for value in row] for row in matrix]

    @staticmethod
    def _is_edge(row: int, col: int, size: int) -> bool:
        return row == 0 or col == 0 or row == size - 1 or col == size - 1

    def _seed_reproducibility_check(self, *, ruleset_id: str, seed_anchor: int, sample_count: int) -> dict[str, object]:
        ruleset = get_ruleset(ruleset_id)
        checked_seed_count = min(max(1, sample_count), 5)
        checked_seeds: list[int] = []
        deterministic = True
        for seed_index in range(checked_seed_count):
            seed = self._derive_seed(seed_anchor, seed_index)
            checked_seeds.append(seed)
            left = generate_random_placements(ruleset, random.Random(seed))
            right = generate_random_placements(ruleset, random.Random(seed))
            if self._placement_signature(left) != self._placement_signature(right):
                deterministic = False
                break

        return {
            "checked_seed_count": checked_seed_count,
            "checked_seeds": checked_seeds,
            "deterministic": deterministic,
        }

    @staticmethod
    def _placement_signature(placements) -> tuple[tuple[int, int, int, str], ...]:
        return tuple((item.row, item.col, item.length, item.orientation) for item in placements)

    @staticmethod
    def _generator_version() -> str:
        source = inspect.getsource(generate_random_placements)
        return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
