from fastapi import FastAPI

from app.api import api_router
from app.services import EventBus, GameSessionService, TrainingJobService


def create_app() -> FastAPI:
    app = FastAPI(title="Battleship API", version="0.1.0")

    event_bus = EventBus()
    app.state.event_bus = event_bus
    app.state.game_sessions = GameSessionService()
    app.state.training_jobs = TrainingJobService(event_bus=event_bus)

    app.include_router(api_router)
    return app


app = create_app()
