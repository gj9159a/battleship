# Test Strategy Baseline

- Unit tests first for `engine`: placement, shot outcomes, game completion.
- Golden scenarios for deterministic fixed sequences.
- Contract tests for `api`: REST routes (`rulesets`, `game sessions`, `training jobs`) + WS event smoke.
- Future stages add integration (`engine<->bot`, `trainer<->storage`, `league<->ratings`) and UI smoke e2e.
