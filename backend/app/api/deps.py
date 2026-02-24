from fastapi import Request

from app.services import EventBus, GameSessionService, TrainingJobService


def get_game_sessions(request: Request) -> GameSessionService:
    return request.app.state.game_sessions


def get_training_jobs(request: Request) -> TrainingJobService:
    return request.app.state.training_jobs


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus
