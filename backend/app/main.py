import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.services import (
    BotCatalogService,
    EventBus,
    FrozenBenchmarkService,
    GameSessionService,
    LeagueService,
    PlacementDiagnosticsService,
    TrainingJobService,
)
from app.storage import SQLiteStore

ALLOWED_ORIGINS = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'tauri://localhost',
    'http://tauri.localhost',
    'https://tauri.localhost',
]


def _resolve_data_root(data_root: Path | None = None) -> Path:
    if data_root is not None:
        return data_root
    from_env = os.getenv("BATTLESHIP_DATA_DIR")
    if from_env:
        return Path(from_env)
    return Path.cwd() / ".data"


def create_app(*, data_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="Battleship API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    resolved_data_root = _resolve_data_root(data_root)
    store = SQLiteStore(resolved_data_root / "app.sqlite3")

    event_bus = EventBus()
    app.state.event_bus = event_bus
    app.state.store = store
    app.state.game_sessions = GameSessionService()
    app.state.bot_catalog = BotCatalogService(store=store)
    app.state.league_service = LeagueService(event_bus=event_bus, store=store, bot_catalog=app.state.bot_catalog)
    app.state.frozen_benchmarks = FrozenBenchmarkService(store=store, bot_catalog=app.state.bot_catalog)
    app.state.placement_diagnostics = PlacementDiagnosticsService()
    app.state.frozen_benchmarks.ensure_frozen_suites("classic_v1", suite_tier="canonical")
    app.state.training_jobs = TrainingJobService(
        event_bus=event_bus,
        checkpoint_root=resolved_data_root / "training_checkpoints",
        bot_catalog=app.state.bot_catalog,
        league_service=app.state.league_service,
        frozen_benchmarks=app.state.frozen_benchmarks,
        store=store,
    )

    app.include_router(api_router)
    return app


app = create_app()
