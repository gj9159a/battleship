export type Orientation = 'H' | 'V';

export type Placement = {
  row: number;
  col: number;
  length: number;
  orientation: Orientation;
};

export type RulesetDTO = {
  id: string;
  name: string;
  board_size: number;
  fleet: number[];
  placement_no_touch: boolean;
  extra_turn_on_hit: boolean;
  is_active?: boolean;
  is_archived?: boolean;
};

export type ShotOutcome = 'miss' | 'hit' | 'sunk';

export type ShotDTO = {
  shooter: number;
  target: number;
  row: number;
  col: number;
  outcome: ShotOutcome;
  game_over: boolean;
  winner: number | null;
  next_player: number;
};

export type GameSessionDTO = {
  id: string;
  ruleset_id: string;
  lifecycle_state: 'running' | 'completed';
  current_player: number;
  winner: number | null;
  shots: ShotDTO[];
};

export type TrainingLifecycleState =
  | 'Idle'
  | 'Running'
  | 'Pausing'
  | 'Paused'
  | 'Stopping'
  | 'Stopped'
  | 'Completed'
  | 'Error';

export type TrainingParamsDTO = {
  microbatch_size: number;
  eval_window_batches: number;
  checkpoint_interval_batches: number;
  population_size: number;
  train_split: number;
  worker_count: number;
  quality_gate_games: number;
  quality_gate_min_winrate: number;
  quality_gate_min_lower_bound: number;
  target_score: number;
  improvement_delta: number;
  plateau_delta: number;
  plateau_patience_windows: number;
  early_stop_plateau_windows: number;
  tick_delay_ms: number;
};

export type TrainingProgressDTO = {
  games_played: number;
  batches_done: number;
  windows_done: number;
  best_score: number;
  last_score: number;
  plateau_windows: number;
};

export type TrainingJobDTO = {
  id: string;
  ruleset_id: string;
  lifecycle_state: TrainingLifecycleState;
  stage_state: string | null;
  profile_id: string | null;
  seed_bot_version_id: string | null;
  seed: number | null;
  stop_reason: string | null;
  current_weights: Record<string, number>;
  best_weights: Record<string, number>;
  params: TrainingParamsDTO;
  progress: TrainingProgressDTO;
};

export type TrainingCheckpointDTO = {
  checkpoint_id: string;
  job_id: string;
  path: string;
  batches_done: number;
  games_played: number;
  best_score: number;
  stage_state: string | null;
};

export type LeaguePoolType = 'baseline' | 'active' | 'league';

export type LeagueRatingDTO = {
  ruleset_id: string;
  bot_version_id: string;
  pool_type: LeaguePoolType;
  mu: number;
  sigma: number;
  conservative_score: number;
  matches_played: number;
  wins: number;
  losses: number;
  draws: number;
  winrate: number;
  updated_at: string;
};

export type LeagueMatrixCellDTO = {
  bot_a_id: string;
  bot_b_id: string;
  wins_a: number;
  wins_b: number;
  total: number;
};

export type LeagueSeasonLifecycleState =
  | 'Idle'
  | 'Running'
  | 'Pausing'
  | 'Paused'
  | 'Stopping'
  | 'Stopped'
  | 'Completed'
  | 'Error';

export type LeagueSeasonDTO = {
  id: string;
  ruleset_id: string;
  lifecycle_state: LeagueSeasonLifecycleState;
  seed: number;
  max_matches: number;
  microbatch_size: number;
  matches_done: number;
  stop_reason: string | null;
};

export type EventEnvelope<TPayload = Record<string, unknown>> = {
  event_type: string;
  entity_id: string;
  ruleset_id: string;
  seq: number;
  ts: string;
  payload: TPayload;
};

export type BotVersionDTO = {
  bot_version_id: string;
  ruleset_id: string;
  policy_type: string;
  feature_schema_version: string;
  lookahead_policy_version: string;
  weights: Record<string, number>;
  source_job_id: string | null;
  source_checkpoint_id: string | null;
  tags: string[];
  created_at: string;
};

export type TrainingCheckpointIndexDTO = {
  job_id: string;
  checkpoint_id: string;
  ruleset_id: string;
  batches_done: number;
  games_played: number;
  best_score: number;
  stage_state: string | null;
};
