# Test Strategy Baseline

- Unit tests first for `engine`: placement, shot outcomes, game completion.
- Golden scenarios for deterministic fixed sequences.
- Contract tests for `api`: REST routes (`rulesets`, `game sessions`, `training jobs`) + WS event smoke.
- Trainer tests:
- unit (`simulator` determinism, checkpoint save/load).
- integration (`training service <-> checkpoint storage`, pause/resume/stop flow).
- UI tests: component tests (`vitest` + `testing-library`) and e2e smoke (`playwright`).
- Future stages add integration (`engine<->bot`, `trainer<->storage`, `league<->ratings`) and UI smoke e2e.
