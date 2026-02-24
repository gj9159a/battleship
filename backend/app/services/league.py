import threading
import time
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import combinations
from typing import TYPE_CHECKING
from uuid import uuid4

import trueskill

from app.bots.selfplay import play_policy_vs
from app.league import LeagueRating, LeagueSeason, MatchRecord, PoolType, SeasonState
from app.rulesets import get_ruleset
from app.services.events import EventBus
from app.storage import SQLiteStore

if TYPE_CHECKING:
    from app.services.bot_catalog import BotCatalogService


@dataclass(slots=True)
class _SeasonRuntime:
    thread: threading.Thread | None = None
    run_gate: threading.Event = field(default_factory=threading.Event)
    pause_requested: bool = False
    stop_requested: bool = False
    pair_cursor: int = 0
    in_microbatch: bool = False


class LeagueService:
    def __init__(
        self,
        event_bus: EventBus,
        *,
        store: SQLiteStore | None = None,
        bot_catalog: "BotCatalogService | None" = None,
    ) -> None:
        self._event_bus = event_bus
        self._env = trueskill.TrueSkill(draw_probability=0.0)
        self._ratings: dict[str, dict[str, LeagueRating]] = {}
        self._seasons: dict[str, LeagueSeason] = {}
        self._season_runtime: dict[str, _SeasonRuntime] = {}
        self._matches_by_ruleset: dict[str, list[MatchRecord]] = {}
        self._wins: dict[str, dict[tuple[str, str], int]] = {}
        self._store = store
        self._bot_catalog = bot_catalog
        self._lock = threading.RLock()
        self._restore_from_store()

    def _restore_from_store(self) -> None:
        if self._store is None:
            return

        with self._lock:
            for rating in self._store.load_league_ratings():
                self._ratings.setdefault(rating.ruleset_id, {})[rating.bot_version_id] = rating
                self._matches_by_ruleset.setdefault(rating.ruleset_id, [])
                self._wins.setdefault(rating.ruleset_id, {})

            for match in self._store.load_league_matches():
                self._matches_by_ruleset.setdefault(match.ruleset_id, []).append(match)
                self._wins.setdefault(match.ruleset_id, {})
                if match.winner_id is None:
                    continue
                loser_id = match.bot_b_id if match.winner_id == match.bot_a_id else match.bot_a_id
                self._wins[match.ruleset_id][(match.winner_id, loser_id)] = (
                    self._wins[match.ruleset_id].get((match.winner_id, loser_id), 0) + 1
                )

            for season_row in self._store.load_league_seasons():
                state = season_row["lifecycle_state"]
                if state in {"Running", "Pausing"}:
                    state = "Paused"
                elif state == "Stopping":
                    state = "Stopped"

                season = LeagueSeason(
                    id=season_row["id"],
                    ruleset_id=season_row["ruleset_id"],
                    lifecycle_state=state,
                    seed=season_row["seed"],
                    max_matches=season_row["max_matches"],
                    microbatch_size=season_row["microbatch_size"],
                    matches_done=season_row["matches_done"],
                    stop_reason=season_row["stop_reason"],
                )
                runtime = _SeasonRuntime(
                    pair_cursor=season_row["pair_cursor"],
                    pause_requested=season_row["pause_requested"],
                    stop_requested=season_row["stop_requested"],
                )
                self._seasons[season.id] = season
                self._season_runtime[season.id] = runtime
                self._persist_season_locked(season.id)

    def _persist_ratings_locked(self, ruleset_id: str) -> None:
        if self._store is None:
            return
        for rating in self._ratings.get(ruleset_id, {}).values():
            self._store.upsert_league_rating(rating)

    def _persist_match_locked(self, match: MatchRecord) -> None:
        if self._store is None:
            return
        self._store.insert_league_match(match)

    def _persist_season_locked(self, season_id: str) -> None:
        if self._store is None:
            return
        season = self._seasons[season_id]
        runtime = self._season_runtime[season_id]
        self._store.upsert_league_season(
            season,
            pair_cursor=runtime.pair_cursor,
            pause_requested=runtime.pause_requested,
            stop_requested=runtime.stop_requested,
        )

    def register_bot(self, ruleset_id: str, bot_version_id: str, pool_type: PoolType) -> LeagueRating:
        get_ruleset(ruleset_id)
        with self._lock:
            by_ruleset = self._ratings.setdefault(ruleset_id, {})
            rating = by_ruleset.get(bot_version_id)
            if rating is None:
                rating = LeagueRating(
                    ruleset_id=ruleset_id,
                    bot_version_id=bot_version_id,
                    pool_type=pool_type,
                    mu=self._env.mu,
                    sigma=self._env.sigma,
                )
                by_ruleset[bot_version_id] = rating
            else:
                rating.pool_type = pool_type
                rating.updated_at = datetime.now(tz=UTC).isoformat()

            self._matches_by_ruleset.setdefault(ruleset_id, [])
            self._wins.setdefault(ruleset_id, {})
            self._rebalance_top16_locked(ruleset_id)
            self._persist_ratings_locked(ruleset_id)
            return rating

    def list_table(self, ruleset_id: str) -> list[LeagueRating]:
        get_ruleset(ruleset_id)
        with self._lock:
            rows = list(self._ratings.get(ruleset_id, {}).values())
            return self._sort_rows(rows)

    def get_matchup_matrix(self, ruleset_id: str) -> list[dict]:
        get_ruleset(ruleset_id)
        with self._lock:
            rows = []
            wins = self._wins.get(ruleset_id, {})
            bot_ids = sorted(self._ratings.get(ruleset_id, {}).keys())
            for bot_a, bot_b in combinations(bot_ids, 2):
                wins_a = wins.get((bot_a, bot_b), 0)
                wins_b = wins.get((bot_b, bot_a), 0)
                rows.append(
                    {
                        "bot_a_id": bot_a,
                        "bot_b_id": bot_b,
                        "wins_a": wins_a,
                        "wins_b": wins_b,
                        "total": wins_a + wins_b,
                    }
                )
            return rows

    def record_match(
        self,
        *,
        ruleset_id: str,
        bot_a_id: str,
        bot_b_id: str,
        winner_id: str | None,
        season_id: str | None = None,
    ) -> MatchRecord:
        get_ruleset(ruleset_id)
        with self._lock:
            if bot_a_id == bot_b_id:
                raise ValueError("bot_a_id and bot_b_id must be different")

            by_ruleset = self._ratings.get(ruleset_id, {})
            rating_a = by_ruleset.get(bot_a_id)
            rating_b = by_ruleset.get(bot_b_id)
            if rating_a is None or rating_b is None:
                raise KeyError("Both bots must be registered in the ruleset pool")

            if winner_id not in {None, bot_a_id, bot_b_id}:
                raise ValueError("winner_id must be null, bot_a_id, or bot_b_id")

            tr_a = trueskill.Rating(mu=rating_a.mu, sigma=rating_a.sigma)
            tr_b = trueskill.Rating(mu=rating_b.mu, sigma=rating_b.sigma)

            if winner_id is None:
                new_a, new_b = trueskill.rate_1vs1(tr_a, tr_b, drawn=True, env=self._env)
                rating_a.draws += 1
                rating_b.draws += 1
            elif winner_id == bot_a_id:
                new_a, new_b = trueskill.rate_1vs1(tr_a, tr_b, env=self._env)
                rating_a.wins += 1
                rating_b.losses += 1
                self._wins.setdefault(ruleset_id, {})[(bot_a_id, bot_b_id)] = (
                    self._wins.setdefault(ruleset_id, {}).get((bot_a_id, bot_b_id), 0) + 1
                )
            else:
                new_b, new_a = trueskill.rate_1vs1(tr_b, tr_a, env=self._env)
                rating_b.wins += 1
                rating_a.losses += 1
                self._wins.setdefault(ruleset_id, {})[(bot_b_id, bot_a_id)] = (
                    self._wins.setdefault(ruleset_id, {}).get((bot_b_id, bot_a_id), 0) + 1
                )

            rating_a.mu = new_a.mu
            rating_a.sigma = new_a.sigma
            rating_a.matches_played += 1
            rating_a.updated_at = datetime.now(tz=UTC).isoformat()

            rating_b.mu = new_b.mu
            rating_b.sigma = new_b.sigma
            rating_b.matches_played += 1
            rating_b.updated_at = datetime.now(tz=UTC).isoformat()

            match = MatchRecord(
                id=str(uuid4()),
                ruleset_id=ruleset_id,
                season_id=season_id,
                bot_a_id=bot_a_id,
                bot_b_id=bot_b_id,
                winner_id=winner_id,
                played_at=datetime.now(tz=UTC).isoformat(),
            )
            self._matches_by_ruleset.setdefault(ruleset_id, []).append(match)
            self._rebalance_top16_locked(ruleset_id)
            self._persist_match_locked(match)
            self._persist_ratings_locked(ruleset_id)

            self._event_bus.publish_sync(
                event_type="league.match_finished",
                entity_id=match.id,
                ruleset_id=ruleset_id,
                payload={
                    "season_id": season_id,
                    "bot_a_id": bot_a_id,
                    "bot_b_id": bot_b_id,
                    "winner_id": winner_id,
                },
            )
            self._event_bus.publish_sync(
                event_type="league.rating_updated",
                entity_id=bot_a_id,
                ruleset_id=ruleset_id,
                payload={
                    "mu": rating_a.mu,
                    "sigma": rating_a.sigma,
                    "conservative_score": rating_a.conservative_score,
                },
            )
            self._event_bus.publish_sync(
                event_type="league.rating_updated",
                entity_id=bot_b_id,
                ruleset_id=ruleset_id,
                payload={
                    "mu": rating_b.mu,
                    "sigma": rating_b.sigma,
                    "conservative_score": rating_b.conservative_score,
                },
            )
            return match

    def create_season(
        self,
        *,
        ruleset_id: str,
        seed: int,
        max_matches: int,
        microbatch_size: int,
    ) -> LeagueSeason:
        get_ruleset(ruleset_id)
        if max_matches <= 0:
            raise ValueError("max_matches must be > 0")
        if microbatch_size <= 0:
            raise ValueError("microbatch_size must be > 0")

        with self._lock:
            if len(self._ratings.get(ruleset_id, {})) < 2:
                raise ValueError("At least two bots are required for season")

            season = LeagueSeason(
                id=str(uuid4()),
                ruleset_id=ruleset_id,
                lifecycle_state="Idle",
                seed=seed,
                max_matches=max_matches,
                microbatch_size=microbatch_size,
            )
            self._seasons[season.id] = season
            self._season_runtime[season.id] = _SeasonRuntime(pair_cursor=max(0, seed))
            self._persist_season_locked(season.id)
            return season

    def get_season(self, season_id: str) -> LeagueSeason:
        with self._lock:
            season = self._seasons.get(season_id)
            if season is None:
                raise KeyError(f"Unknown season_id={season_id}")
            return season

    async def command_season(self, season_id: str, command: str) -> LeagueSeason:
        with self._lock:
            season = self._seasons.get(season_id)
            if season is None:
                raise KeyError(f"Unknown season_id={season_id}")
            runtime = self._season_runtime[season_id]

            if command == "start":
                self._ensure_state(season, {"Idle"}, command)
                old = season.lifecycle_state
                season.lifecycle_state = "Running"
                runtime.pause_requested = False
                runtime.stop_requested = False
                runtime.run_gate.set()
                if runtime.thread is None or not runtime.thread.is_alive():
                    runtime.thread = threading.Thread(
                        target=self._season_loop,
                        args=(season.id,),
                        daemon=True,
                        name=f"league-{season.id[:8]}",
                    )
                    runtime.thread.start()
                self._persist_season_locked(season.id)
                self._event_bus.publish_sync(
                    event_type="league.lifecycle_changed",
                    entity_id=season.id,
                    ruleset_id=season.ruleset_id,
                    payload={"old_state": old, "new_state": season.lifecycle_state},
                )
                return season

            if command == "pause":
                self._ensure_state(season, {"Running"}, command)
                runtime.pause_requested = True
                old = season.lifecycle_state
                if runtime.in_microbatch:
                    season.lifecycle_state = "Pausing"
                else:
                    season.lifecycle_state = "Paused"
                    runtime.run_gate.clear()
                self._persist_season_locked(season.id)
                self._event_bus.publish_sync(
                    event_type="league.lifecycle_changed",
                    entity_id=season.id,
                    ruleset_id=season.ruleset_id,
                    payload={"old_state": old, "new_state": season.lifecycle_state},
                )
                return season

            if command == "resume":
                self._ensure_state(season, {"Paused"}, command)
                runtime.pause_requested = False
                old = season.lifecycle_state
                season.lifecycle_state = "Running"
                runtime.run_gate.set()
                self._persist_season_locked(season.id)
                self._event_bus.publish_sync(
                    event_type="league.lifecycle_changed",
                    entity_id=season.id,
                    ruleset_id=season.ruleset_id,
                    payload={"old_state": old, "new_state": season.lifecycle_state},
                )
                return season

            if command == "stop":
                self._ensure_state(season, {"Running", "Pausing", "Paused"}, command)
                runtime.stop_requested = True
                season.stop_reason = "stopped_by_user"
                old = season.lifecycle_state
                season.lifecycle_state = "Stopping"
                self._persist_season_locked(season.id)
                self._event_bus.publish_sync(
                    event_type="league.lifecycle_changed",
                    entity_id=season.id,
                    ruleset_id=season.ruleset_id,
                    payload={"old_state": old, "new_state": season.lifecycle_state},
                )
                if old == "Paused":
                    season.lifecycle_state = "Stopped"
                    self._persist_season_locked(season.id)
                    self._event_bus.publish_sync(
                        event_type="league.lifecycle_changed",
                        entity_id=season.id,
                        ruleset_id=season.ruleset_id,
                        payload={"old_state": "Stopping", "new_state": "Stopped"},
                    )
                else:
                    runtime.run_gate.set()
                return season

        raise ValueError(f"Unknown command: {command}")

    def _season_loop(self, season_id: str) -> None:
        while True:
            with self._lock:
                season = self._seasons[season_id]
                runtime = self._season_runtime[season_id]
                if season.lifecycle_state in {"Stopped", "Completed", "Error"}:
                    return

            runtime.run_gate.wait()

            with self._lock:
                season = self._seasons[season_id]
                runtime = self._season_runtime[season_id]

                if runtime.stop_requested and season.lifecycle_state == "Stopping":
                    old = season.lifecycle_state
                    season.lifecycle_state = "Stopped"
                    self._persist_season_locked(season.id)
                    self._event_bus.publish_sync(
                        event_type="league.lifecycle_changed",
                        entity_id=season.id,
                        ruleset_id=season.ruleset_id,
                        payload={"old_state": old, "new_state": "Stopped"},
                    )
                    runtime.run_gate.clear()
                    return

                if season.lifecycle_state == "Pausing":
                    old = season.lifecycle_state
                    season.lifecycle_state = "Paused"
                    self._persist_season_locked(season.id)
                    self._event_bus.publish_sync(
                        event_type="league.lifecycle_changed",
                        entity_id=season.id,
                        ruleset_id=season.ruleset_id,
                        payload={"old_state": old, "new_state": "Paused"},
                    )
                    runtime.run_gate.clear()
                    continue

                if season.lifecycle_state != "Running":
                    continue
                microbatch_size = season.microbatch_size
                runtime.in_microbatch = True

            for _ in range(microbatch_size):
                with self._lock:
                    season = self._seasons[season_id]
                    runtime = self._season_runtime[season_id]
                    if season.lifecycle_state not in {"Running", "Pausing"}:
                        break
                    # If pause was requested at a microbatch boundary, do not start
                    # a new match; pause should take effect immediately.
                    if season.lifecycle_state == "Pausing" and (season.matches_done % season.microbatch_size == 0):
                        break
                    if season.matches_done >= season.max_matches:
                        break

                    pair = self._pick_pair_locked(season.ruleset_id, runtime.pair_cursor)
                    runtime.pair_cursor += 1
                    if pair is None:
                        season.stop_reason = "insufficient_participants"
                        self._persist_season_locked(season.id)
                        break

                    bot_a_id, bot_b_id = pair
                    seed = season.seed + runtime.pair_cursor * 1_003 + season.matches_done * 9_973

                try:
                    winner_id = self._play_match(
                        ruleset_id=season.ruleset_id,
                        bot_a_id=bot_a_id,
                        bot_b_id=bot_b_id,
                        seed=seed,
                    )
                    self.record_match(
                        ruleset_id=season.ruleset_id,
                        bot_a_id=bot_a_id,
                        bot_b_id=bot_b_id,
                        winner_id=winner_id,
                        season_id=season.id,
                    )
                except Exception as exc:
                    with self._lock:
                        season = self._seasons[season_id]
                        runtime = self._season_runtime[season_id]
                        runtime.in_microbatch = False
                        season.stop_reason = f"season_runtime_error: {exc}"
                        old = season.lifecycle_state
                        season.lifecycle_state = "Error"
                        self._persist_season_locked(season.id)
                        self._event_bus.publish_sync(
                            event_type="league.lifecycle_changed",
                            entity_id=season.id,
                            ruleset_id=season.ruleset_id,
                            payload={"old_state": old, "new_state": "Error"},
                        )
                        runtime.run_gate.clear()
                    return

                with self._lock:
                    season = self._seasons[season_id]
                    runtime = self._season_runtime[season_id]
                    season.matches_done += 1
                    self._persist_season_locked(season.id)
                    if runtime.stop_requested:
                        break

            with self._lock:
                season = self._seasons[season_id]
                runtime = self._season_runtime[season_id]
                runtime.in_microbatch = False
                if runtime.stop_requested:
                    continue

                if runtime.pause_requested:
                    continue

                if season.matches_done >= season.max_matches or season.stop_reason == "insufficient_participants":
                    if season.stop_reason is None:
                        season.stop_reason = "max_matches_reached"
                    old = season.lifecycle_state
                    season.lifecycle_state = "Completed"
                    self._persist_season_locked(season.id)
                    self._event_bus.publish_sync(
                        event_type="league.lifecycle_changed",
                        entity_id=season.id,
                        ruleset_id=season.ruleset_id,
                        payload={"old_state": old, "new_state": "Completed"},
                    )
                    runtime.run_gate.clear()
                    return

            time.sleep(0.001)

    def _pick_pair_locked(self, ruleset_id: str, cursor: int) -> tuple[str, str] | None:
        by_ruleset = self._ratings.get(ruleset_id, {})
        if len(by_ruleset) < 2:
            return None

        league_ids = sorted(
            rating.bot_version_id for rating in by_ruleset.values() if rating.pool_type == "league"
        )
        active_ids = sorted(
            rating.bot_version_id for rating in by_ruleset.values() if rating.pool_type == "active"
        )
        baseline_ids = sorted(
            rating.bot_version_id for rating in by_ruleset.values() if rating.pool_type == "baseline"
        )

        candidates: list[tuple[str, str]] = []
        if active_ids and league_ids:
            candidates.extend((a, l) for a in active_ids for l in league_ids if a != l)
        if active_ids and baseline_ids:
            candidates.extend((a, b) for a in active_ids for b in baseline_ids if a != b)
        if league_ids and baseline_ids:
            candidates.extend((l, b) for l in league_ids for b in baseline_ids if l != b)

        all_ids = sorted(by_ruleset.keys())
        candidates.extend((a, b) for a, b in combinations(all_ids, 2))

        unique: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for pair in candidates:
            ordered = tuple(sorted(pair))
            if ordered[0] == ordered[1]:
                continue
            if ordered not in seen:
                seen.add(ordered)
                unique.append(ordered)

        if not unique:
            return None
        return unique[cursor % len(unique)]

    def _play_match(self, *, ruleset_id: str, bot_a_id: str, bot_b_id: str, seed: int) -> str:
        if not (self._is_known_bot(bot_a_id) and self._is_known_bot(bot_b_id)):
            return bot_a_id if seed % 2 == 0 else bot_b_id

        ruleset = get_ruleset(ruleset_id)
        rng = random.Random(seed)
        kind_a, weights_a = self._resolve_bot_policy(bot_a_id)
        kind_b, weights_b = self._resolve_bot_policy(bot_b_id)
        result = play_policy_vs(
            ruleset,
            rng,
            bot_a_kind=kind_a,
            bot_a_weights=weights_a,
            bot_b_kind=kind_b,
            bot_b_weights=weights_b,
            first_player=seed % 2,
        )
        return bot_a_id if result.winner == 0 else bot_b_id

    def _is_known_bot(self, bot_version_id: str) -> bool:
        if self._bot_catalog is None:
            return False
        try:
            self._bot_catalog.get_bot(bot_version_id)
        except KeyError:
            return False
        return True

    def _resolve_bot_policy(self, bot_version_id: str) -> tuple[str, dict[str, float] | None]:
        if self._bot_catalog is None:
            return "random", None

        try:
            bot = self._bot_catalog.get_bot(bot_version_id)
        except KeyError:
            return "random", None

        if bot.policy_type == "random":
            return "random", None
        return "strong", dict(bot.weights)

    def _rebalance_top16_locked(self, ruleset_id: str) -> None:
        rows = list(self._ratings.get(ruleset_id, {}).values())
        baseline_ids = {row.bot_version_id for row in rows if row.pool_type == "baseline"}
        non_baseline = [row for row in rows if row.bot_version_id not in baseline_ids]
        sorted_non_baseline = self._sort_rows(non_baseline)
        top16 = {row.bot_version_id for row in sorted_non_baseline[:16]}

        for row in non_baseline:
            row.pool_type = "league" if row.bot_version_id in top16 else "active"

    @staticmethod
    def _sort_rows(rows: list[LeagueRating]) -> list[LeagueRating]:
        return sorted(
            rows,
            key=lambda row: (
                -row.conservative_score,
                -row.mu,
                row.sigma,
                row.bot_version_id,
            ),
        )

    @staticmethod
    def _ensure_state(season: LeagueSeason, allowed: set[SeasonState], command: str) -> None:
        if season.lifecycle_state not in allowed:
            raise ValueError(
                f"Invalid command '{command}' for state '{season.lifecycle_state}'. Allowed: {sorted(allowed)}"
            )
