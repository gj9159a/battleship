from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.services import BotCatalogService, EventBus, GameSessionService, LeagueService, TrainingJobService

ALLOWED_ORIGINS = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'tauri://localhost',
    'http://tauri.localhost',
    'https://tauri.localhost',
]


def create_app() -> FastAPI:
    app = FastAPI(title="Battleship API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    event_bus = EventBus()
    app.state.event_bus = event_bus
    app.state.game_sessions = GameSessionService()
    app.state.bot_catalog = BotCatalogService()
    app.state.league_service = LeagueService(event_bus=event_bus)
    app.state.training_jobs = TrainingJobService(
        event_bus=event_bus,
        bot_catalog=app.state.bot_catalog,
        league_service=app.state.league_service,
    )

    app.include_router(api_router)
    return app


app = create_app()
