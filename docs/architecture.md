# Architecture Baseline

- `backend/app/rulesets`: ruleset declarations and lookup.
- `backend/app/engine`: pure game domain logic (board, placement validation, shot processing, game flow).
- `backend/app/services`: in-memory services for game sessions, training jobs, and WS event bus.
- `backend/app/trainer`: trainer domain (`TrainingParams`, deterministic simulation, checkpoint store).
- `backend/app/league`: league domain entities (`ratings`, `season`, `pool` models).
- `backend/app/api`: FastAPI routes for REST + WebSocket contracts.
- `backend/app/schemas`: pydantic request/response contracts for API.
- `backend/tests`: unit + golden tests for deterministic core behavior.
- `frontend`: React + TypeScript web UI, MVP game screen via HTTP API.
