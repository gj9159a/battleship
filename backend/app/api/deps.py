from fastapi import Request

from app.services import (
    BotCatalogService,
    EventBus,
    FrozenBenchmarkService,
    GameSessionService,
    LeagueService,
    PlacementDiagnosticsService,
    TrainingJobService,
)


def get_game_sessions(request: Request) -> GameSessionService:
    return request.app.state.game_sessions


def get_training_jobs(request: Request) -> TrainingJobService:
    return request.app.state.training_jobs


def get_bot_catalog(request: Request) -> BotCatalogService:
    return request.app.state.bot_catalog


def get_league_service(request: Request) -> LeagueService:
    return request.app.state.league_service


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus


def get_frozen_benchmarks(request: Request) -> FrozenBenchmarkService:
    return request.app.state.frozen_benchmarks


def get_placement_diagnostics(request: Request) -> PlacementDiagnosticsService:
    return request.app.state.placement_diagnostics
