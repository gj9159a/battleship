import time

import pytest

from app.rulesets import catalog
from app.rulesets.models import Ruleset
from app.services import EventBus
from app.services.league import LeagueService


@pytest.fixture
def service() -> LeagueService:
    return LeagueService(event_bus=EventBus())


@pytest.fixture
def second_ruleset(monkeypatch):
    ruleset = Ruleset(
        id="classic_alt_v1",
        name="Classic Alt v1",
        board_size=10,
        fleet=(5, 4, 3, 3, 2),
        placement_no_touch=False,
        extra_turn_on_hit=True,
    )
    monkeypatch.setitem(catalog._RULESETS, ruleset.id, ruleset)
    return ruleset.id


def test_trueskill_update_and_sorting(service: LeagueService) -> None:
    service.register_bot("classic_v1", "bot-a", "active")
    service.register_bot("classic_v1", "bot-b", "active")

    before = {row.bot_version_id: (row.mu, row.sigma) for row in service.list_table("classic_v1")}
    service.record_match(
        ruleset_id="classic_v1",
        bot_a_id="bot-a",
        bot_b_id="bot-b",
        winner_id="bot-a",
    )
    table = service.list_table("classic_v1")

    assert table[0].bot_version_id == "bot-a"
    assert table[0].conservative_score >= table[1].conservative_score
    assert table[0].mu > before["bot-a"][0]
    assert table[1].mu < before["bot-b"][0]


def test_top16_active_baseline_pools(service: LeagueService) -> None:
    for i in range(2):
        service.register_bot("classic_v1", f"baseline-{i}", "baseline")

    for i in range(20):
        service.register_bot("classic_v1", f"candidate-{i:02d}", "active")

    table = service.list_table("classic_v1")
    pool_counts: dict[str, int] = {}
    for row in table:
        pool_counts[row.pool_type] = pool_counts.get(row.pool_type, 0) + 1

    assert pool_counts.get("baseline", 0) == 2
    assert pool_counts.get("league", 0) == 16
    assert pool_counts.get("active", 0) == 4


def test_ruleset_isolation(service: LeagueService, second_ruleset: str) -> None:
    service.register_bot("classic_v1", "same-a", "active")
    service.register_bot("classic_v1", "same-b", "active")
    service.register_bot(second_ruleset, "same-a", "active")
    service.register_bot(second_ruleset, "same-b", "active")

    service.record_match(
        ruleset_id="classic_v1",
        bot_a_id="same-a",
        bot_b_id="same-b",
        winner_id="same-a",
    )

    classic = {row.bot_version_id: row for row in service.list_table("classic_v1")}
    alt = {row.bot_version_id: row for row in service.list_table(second_ruleset)}

    assert classic["same-a"].matches_played == 1
    assert classic["same-b"].matches_played == 1
    assert alt["same-a"].matches_played == 0
    assert alt["same-b"].matches_played == 0


def test_season_lifecycle_pause_resume_stop(service: LeagueService) -> None:
    service.register_bot("classic_v1", "bot-a", "active")
    service.register_bot("classic_v1", "bot-b", "active")
    service.register_bot("classic_v1", "bot-c", "active")

    season = service.create_season(
        ruleset_id="classic_v1",
        seed=1,
        max_matches=500,
        microbatch_size=5,
    )

    import asyncio

    asyncio.run(service.command_season(season.id, "start"))
    asyncio.run(service.command_season(season.id, "pause"))

    deadline = time.time() + 2.0
    while time.time() < deadline:
        current = service.get_season(season.id)
        if current.lifecycle_state == "Paused":
            break
        time.sleep(0.02)
    assert service.get_season(season.id).lifecycle_state == "Paused"
    assert service.get_season(season.id).matches_done % 5 == 0

    asyncio.run(service.command_season(season.id, "resume"))
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if service.get_season(season.id).matches_done > 0:
            break
        time.sleep(0.02)

    asyncio.run(service.command_season(season.id, "stop"))
    deadline = time.time() + 2.0
    while time.time() < deadline:
        current = service.get_season(season.id)
        if current.lifecycle_state == "Stopped":
            break
        time.sleep(0.02)

    assert service.get_season(season.id).lifecycle_state == "Stopped"
    assert service.get_season(season.id).stop_reason == "stopped_by_user"
