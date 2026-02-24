# Architecture Baseline

- `backend/app/rulesets`: ruleset declarations and lookup.
- `backend/app/engine`: pure game domain logic (board, placement validation, shot processing, game flow).
- `backend/app/bots`: bot policies (`random`, `strong probability HUNT/TARGET`, adaptive lookahead) and self-play simulation.
- `backend/app/services`: in-memory services for game sessions, training jobs, bot catalog, league, and WS event bus.
- `backend/app/trainer`: trainer domain (`TrainingParams`, checkpoint store, lifecycle/stage control).
- `backend/app/league`: league domain entities (`ratings`, `season`, `pool` models).
- `backend/app/api`: FastAPI routes for REST + WebSocket contracts.
- `backend/app/schemas`: pydantic request/response contracts for API.
- `backend/tests`: unit + golden tests for deterministic core behavior.
- `frontend`: React + TypeScript web UI (`Game`, `Training`, `League`) via HTTP + WS API.
