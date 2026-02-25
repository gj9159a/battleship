import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.bots.policy import normalize_weights
from app.bots.selfplay import FrozenSuiteAggregate, run_frozen_suite
from app.rulesets import get_ruleset
from app.storage import SQLiteStore
from app.trainer import FrozenSuite, FrozenSuiteRun, SuiteSubjectType, SuiteTier

from .bot_catalog import BotCatalogService


@dataclass(frozen=True, slots=True)
class _SuiteTierConfig:
    tier: SuiteTier
    random_suite_id_suffix: str
    strong_suite_id_suffix: str
    random_name: str
    strong_name: str
    random_seed_anchor: int
    strong_seed_anchor: int
    seed_count: int
    games_per_seed: int


class FrozenBenchmarkService:
    _RANDOM_SUITE_KIND = "random"
    _STRONG_SUITE_KIND = "strong"
    _CANONICAL_TIER: SuiteTier = "canonical"
    _CI_SMOKE_TIER: SuiteTier = "ci_smoke"
    _SEED_DERIVATION_SCHEME = "anchor_plus_index_mul_1009_v1"

    _TIER_CONFIGS: dict[SuiteTier, _SuiteTierConfig] = {
        "canonical": _SuiteTierConfig(
            tier="canonical",
            random_suite_id_suffix="frozen-random-suite-v1",
            strong_suite_id_suffix="frozen-strong-suite-v1",
            random_name="Frozen Random Suite v1",
            strong_name="Frozen Strong Suite v1",
            random_seed_anchor=104_729,
            strong_seed_anchor=130_363,
            seed_count=2,
            games_per_seed=2,
        ),
        "ci_smoke": _SuiteTierConfig(
            tier="ci_smoke",
            random_suite_id_suffix="frozen-random-suite-ci-smoke-v1",
            strong_suite_id_suffix="frozen-strong-suite-ci-smoke-v1",
            random_name="Frozen Random Suite CI Smoke v1",
            strong_name="Frozen Strong Suite CI Smoke v1",
            random_seed_anchor=1_009,
            strong_seed_anchor=3_007,
            seed_count=1,
            games_per_seed=1,
        ),
    }

    def __init__(self, *, store: SQLiteStore | None = None, bot_catalog: BotCatalogService | None = None) -> None:
        self._store = store
        self._bot_catalog = bot_catalog
        self._suites: dict[str, FrozenSuite] = {}
        self._runs_by_suite: dict[str, list[FrozenSuiteRun]] = {}
        self._lock = threading.RLock()
        self._restore_from_store()

    def _restore_from_store(self) -> None:
        if self._store is None:
            return
        with self._lock:
            for suite in self._store.load_frozen_suites():
                self._suites[suite.suite_id] = suite
                self._runs_by_suite.setdefault(suite.suite_id, [])
            for run in self._store.load_frozen_suite_runs():
                self._runs_by_suite.setdefault(run.suite_id, []).append(run)
            for runs in self._runs_by_suite.values():
                runs.sort(key=lambda item: item.created_at, reverse=True)

    def list_suites(self, ruleset_id: str | None = None, suite_tier: SuiteTier | None = None) -> list[FrozenSuite]:
        with self._lock:
            suites = list(self._suites.values())
        if ruleset_id is not None:
            suites = [suite for suite in suites if suite.ruleset_id == ruleset_id]
        if suite_tier is not None:
            suites = [suite for suite in suites if suite.suite_tier == suite_tier]
        suites.sort(key=lambda item: item.created_at)
        return suites

    def list_suite_runs(self, suite_id: str) -> list[FrozenSuiteRun]:
        with self._lock:
            if suite_id not in self._suites:
                raise KeyError(f"Unknown suite_id={suite_id}")
            return list(self._runs_by_suite.get(suite_id, []))

    def ensure_frozen_suites(
        self,
        ruleset_id: str,
        *,
        suite_tier: SuiteTier = "canonical",
    ) -> dict[str, FrozenSuite]:
        get_ruleset(ruleset_id)
        config = self._tier_config(suite_tier)
        strong_snapshot = self._ensure_strong_snapshot_bot(ruleset_id)
        with self._lock:
            existing_by_kind = {
                suite.suite_kind: suite
                for suite in self._suites.values()
                if suite.ruleset_id == ruleset_id
                and suite.suite_tier == suite_tier
                and suite.suite_kind in {self._RANDOM_SUITE_KIND, self._STRONG_SUITE_KIND}
            }

            if self._RANDOM_SUITE_KIND not in existing_by_kind:
                random_suite = self._build_suite(
                    suite_id=f"{ruleset_id}-{config.random_suite_id_suffix}",
                    name=config.random_name,
                    ruleset_id=ruleset_id,
                    suite_kind=self._RANDOM_SUITE_KIND,
                    suite_tier=suite_tier,
                    seed_anchor=config.random_seed_anchor,
                    seed_count=config.seed_count,
                    games_per_seed=config.games_per_seed,
                    opponent_policy_type="random",
                    opponent_bot_version_id=None,
                    opponent_weights={},
                    opponent_lookahead_policy_version="off",
                )
                existing_by_kind[self._RANDOM_SUITE_KIND] = self._insert_suite_locked(random_suite)

            if self._STRONG_SUITE_KIND not in existing_by_kind:
                strong_suite = self._build_suite(
                    suite_id=f"{ruleset_id}-{config.strong_suite_id_suffix}",
                    name=config.strong_name,
                    ruleset_id=ruleset_id,
                    suite_kind=self._STRONG_SUITE_KIND,
                    suite_tier=suite_tier,
                    seed_anchor=config.strong_seed_anchor,
                    seed_count=config.seed_count,
                    games_per_seed=config.games_per_seed,
                    opponent_policy_type="strong",
                    opponent_bot_version_id=strong_snapshot.bot_version_id,
                    opponent_weights=dict(strong_snapshot.weights),
                    opponent_lookahead_policy_version=strong_snapshot.lookahead_policy_version,
                )
                existing_by_kind[self._STRONG_SUITE_KIND] = self._insert_suite_locked(strong_suite)

            return dict(existing_by_kind)

    def run_suite_for_bot_version(self, suite_id: str, bot_version_id: str) -> FrozenSuiteRun:
        if self._bot_catalog is None:
            raise ValueError("run_suite_for_bot_version requires bot catalog service")
        try:
            bot = self._bot_catalog.get_bot(bot_version_id)
        except KeyError as exc:
            raise KeyError(f"Unknown bot_version_id={bot_version_id}") from exc
        return self._run_suite_for_weights(
            suite_id=suite_id,
            subject_type="bot_version",
            subject_ref=bot.bot_version_id,
            ruleset_id=bot.ruleset_id,
            subject_weights=bot.weights,
        )

    def run_suite_for_checkpoint(self, suite_id: str, *, checkpoint_id: str, ruleset_id: str, weights: dict[str, float]) -> FrozenSuiteRun:
        return self._run_suite_for_weights(
            suite_id=suite_id,
            subject_type="checkpoint",
            subject_ref=checkpoint_id,
            ruleset_id=ruleset_id,
            subject_weights=weights,
        )

    def run_default_suites_for_checkpoint(
        self,
        *,
        ruleset_id: str,
        checkpoint_id: str,
        weights: dict[str, float],
    ) -> dict[str, dict[str, object]]:
        with self._lock:
            suites = sorted(
                (
                    suite
                    for suite in self._suites.values()
                    if suite.ruleset_id == ruleset_id
                    and suite.suite_tier == self._CANONICAL_TIER
                    and suite.suite_kind in {self._RANDOM_SUITE_KIND, self._STRONG_SUITE_KIND}
                ),
                key=lambda item: item.suite_kind,
            )

        summaries: dict[str, dict[str, object]] = {}
        for suite in suites:
            run = self.run_suite_for_checkpoint(
                suite.suite_id,
                checkpoint_id=checkpoint_id,
                ruleset_id=ruleset_id,
                weights=weights,
            )
            summaries[suite.suite_kind] = self._run_to_summary(run, suite)
        return summaries

    def _run_suite_for_weights(
        self,
        *,
        suite_id: str,
        subject_type: SuiteSubjectType,
        subject_ref: str,
        ruleset_id: str,
        subject_weights: dict[str, float],
    ) -> FrozenSuiteRun:
        with self._lock:
            suite = self._suites.get(suite_id)
            if suite is None:
                raise KeyError(f"Unknown suite_id={suite_id}")
        if suite.ruleset_id != ruleset_id:
            raise ValueError(f"Suite ruleset mismatch: {suite.ruleset_id} != {ruleset_id}")

        ruleset = get_ruleset(suite.ruleset_id)
        aggregate = run_frozen_suite(
            ruleset=ruleset,
            subject_weights=normalize_weights(subject_weights),
            opponent_kind=suite.opponent_policy_type,
            opponent_weights=suite.opponent_weights if suite.opponent_policy_type == "strong" else None,
            seed_anchor=suite.seed_anchor,
            seed_count=suite.seed_count,
            seed_derivation_scheme=suite.seed_derivation_scheme,
            games_per_seed=suite.games_per_seed,
            mirrored_first_player=suite.mirrored_first_player,
        )
        run = self._build_run(suite, aggregate, subject_type=subject_type, subject_ref=subject_ref)
        with self._lock:
            self._runs_by_suite.setdefault(suite.suite_id, []).insert(0, run)
            if self._store is not None:
                self._store.insert_frozen_suite_run(run)
        return run

    def _ensure_strong_snapshot_bot(self, ruleset_id: str):
        if self._bot_catalog is None:
            raise ValueError("Frozen suite bootstrap requires bot catalog service")
        strong_snapshot_id = f"{ruleset_id}-baseline-strong"
        strong_snapshot = self._bot_catalog.ensure_bot(
            bot_version_id=strong_snapshot_id,
            ruleset_id=ruleset_id,
            policy_type="probability_strong",
            feature_schema_version="classic_features_v1",
            lookahead_policy_version="adaptive_v1",
            weights=normalize_weights(None),
            tags={"baseline"},
        )
        if strong_snapshot.ruleset_id != ruleset_id:
            raise ValueError(
                f"Strong suite bootstrap failed: bot ruleset mismatch {strong_snapshot.ruleset_id} != {ruleset_id}"
            )
        return strong_snapshot

    def _insert_suite_locked(self, suite: FrozenSuite) -> FrozenSuite:
        existing = self._suites.get(suite.suite_id)
        if existing is not None:
            if existing.suite_tier != suite.suite_tier:
                raise ValueError(
                    f"Frozen suite drift detected for suite_id={suite.suite_id}: "
                    f"tier {existing.suite_tier} != {suite.suite_tier}"
                )
            if existing.suite_protocol_hash != suite.suite_protocol_hash:
                raise ValueError(
                    f"Frozen suite drift detected for suite_id={suite.suite_id}: "
                    f"{existing.suite_protocol_hash} != {suite.suite_protocol_hash}"
                )
            return existing

        self._suites[suite.suite_id] = suite
        self._runs_by_suite.setdefault(suite.suite_id, [])
        if self._store is not None:
            self._store.insert_frozen_suite(suite)
        return suite

    def _build_suite(
        self,
        *,
        suite_id: str,
        name: str,
        ruleset_id: str,
        suite_kind: str,
        suite_tier: SuiteTier,
        seed_anchor: int,
        seed_count: int,
        games_per_seed: int,
        opponent_policy_type: str,
        opponent_bot_version_id: str | None,
        opponent_weights: dict[str, float],
        opponent_lookahead_policy_version: str,
    ) -> FrozenSuite:
        spec_payload = {
            "suite_id": suite_id,
            "name": name,
            "ruleset_id": ruleset_id,
            "suite_kind": suite_kind,
            "seed_anchor": seed_anchor,
            "seed_count": seed_count,
            "seed_derivation_scheme": self._SEED_DERIVATION_SCHEME,
            "games_per_seed": games_per_seed,
            "series_count": seed_count,
            "mirrored_first_player": True,
            "opponent_policy_type": opponent_policy_type,
            "opponent_bot_version_id": opponent_bot_version_id,
            "opponent_weights": normalize_weights(opponent_weights) if opponent_policy_type == "strong" else {},
            "opponent_lookahead_policy_version": opponent_lookahead_policy_version,
        }
        protocol_hash = self._compute_suite_protocol_hash(spec_payload)
        return FrozenSuite(
            suite_id=suite_id,
            name=name,
            ruleset_id=ruleset_id,
            suite_kind=suite_kind,
            suite_tier=suite_tier,
            created_at=datetime.now(tz=UTC).isoformat(),
            suite_protocol_hash=protocol_hash,
            seed_anchor=seed_anchor,
            seed_count=seed_count,
            seed_derivation_scheme=self._SEED_DERIVATION_SCHEME,
            games_per_seed=games_per_seed,
            series_count=seed_count,
            mirrored_first_player=True,
            opponent_policy_type=opponent_policy_type,
            opponent_bot_version_id=opponent_bot_version_id,
            opponent_weights=dict(spec_payload["opponent_weights"]),
            opponent_lookahead_policy_version=opponent_lookahead_policy_version,
        )

    def _build_run(
        self,
        suite: FrozenSuite,
        aggregate: FrozenSuiteAggregate,
        *,
        subject_type: SuiteSubjectType,
        subject_ref: str,
    ) -> FrozenSuiteRun:
        raw_metrics = {
            "wins": aggregate.wins,
            "total_games": aggregate.total_games,
            "suite_id": suite.suite_id,
            "suite_kind": suite.suite_kind,
            "suite_tier": suite.suite_tier,
            "suite_protocol_hash": suite.suite_protocol_hash,
            "seed_anchor": suite.seed_anchor,
            "seed_count": suite.seed_count,
            "seed_derivation_scheme": suite.seed_derivation_scheme,
            "games_per_seed": suite.games_per_seed,
            "mirrored_first_player": suite.mirrored_first_player,
            "opponent_policy_type": suite.opponent_policy_type,
            "opponent_bot_version_id": suite.opponent_bot_version_id,
        }
        return FrozenSuiteRun(
            run_id=str(uuid4()),
            suite_id=suite.suite_id,
            created_at=datetime.now(tz=UTC).isoformat(),
            subject_type=subject_type,
            subject_ref=subject_ref,
            suite_protocol_hash=suite.suite_protocol_hash,
            eval_seed_anchor=aggregate.eval_seed_anchor,
            seed_count=aggregate.seed_count,
            games_per_seed=aggregate.games_per_seed,
            paired_eval=aggregate.paired_eval,
            mirrored_first_player=aggregate.mirrored_first_player,
            winrate=aggregate.winrate,
            lcb=aggregate.lcb,
            avg_shots_to_sink_all=aggregate.avg_shots_to_sink_all,
            p95_shots_to_sink_all=aggregate.p95_shots_to_sink_all,
            avg_shots_to_first_hit=aggregate.avg_shots_to_first_hit,
            avg_shots_after_first_hit_to_sink_all=aggregate.avg_shots_after_first_hit_to_sink_all,
            avg_misses_before_first_hit=aggregate.avg_misses_before_first_hit,
            raw_metrics=raw_metrics,
        )

    @staticmethod
    def _compute_suite_protocol_hash(spec_payload: dict) -> str:
        serialized = json.dumps(spec_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _run_to_summary(
        run: FrozenSuiteRun,
        suite: FrozenSuite,
    ) -> dict[str, object]:
        payload = asdict(run)
        payload["suite_kind"] = suite.suite_kind
        payload["suite_tier"] = suite.suite_tier
        return payload

    def _tier_config(self, suite_tier: SuiteTier) -> _SuiteTierConfig:
        try:
            return self._TIER_CONFIGS[suite_tier]
        except KeyError as exc:
            raise ValueError(f"Unsupported suite_tier={suite_tier}") from exc
