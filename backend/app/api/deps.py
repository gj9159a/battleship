from fastapi import Request

from app.services import EventBus, GameSessionService, LeagueService, TrainingJobService


def get_game_sessions(request: Request) -> GameSessionService:
    return request.app.state.game_sessions


def get_training_jobs(request: Request) -> TrainingJobService:
    return request.app.state.training_jobs


def get_league_service(request: Request) -> LeagueService:
    return request.app.state.league_service


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus
