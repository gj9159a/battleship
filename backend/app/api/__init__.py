from fastapi import APIRouter

from .routes_game import router as game_router
from .routes_league import router as league_router
from .routes_rulesets import router as rulesets_router
from .routes_training import router as training_router
from .ws import router as ws_router

api_router = APIRouter()
api_router.include_router(rulesets_router)
api_router.include_router(game_router)
api_router.include_router(training_router)
api_router.include_router(league_router)
api_router.include_router(ws_router)
