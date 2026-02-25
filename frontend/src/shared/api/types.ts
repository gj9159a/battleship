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
  games_per_candidate: number;
  epoch_iters: number;
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
  min_windows_before_early_stop: number;
  tick_delay_ms: number;
  autoevolve_enabled: boolean;
  meta_plateau_patience_cycles: number;
  strictness_max_level: number;
};

export type TrainingProgressDTO = {
  games_played: number;
  batches_done: number;
  windows_done: number;
  best_score: number;
  last_score: number;
  plateau_windows: number;
  cycle_index: number;
  current_population_size: number;
  strictness_level: number;
  meta_plateau_counter: number;
  champion_gate_lcb: number;
  eval_protocol_hash: string;
  last_wr_baseline?: number;
  last_wr_active?: number;
  last_avg_turns_win?: number;
  last_avg_shots_to_sink_all?: number;
  last_p95_shots_to_sink_all?: number;
  last_avg_shots_to_first_hit?: number;
  last_avg_shots_after_first_hit_to_sink_all?: number;
  last_avg_misses_before_first_hit?: number;
  last_eval_seed_anchor?: number;
  last_incumbent_seed_anchor?: number;
  last_eval_paired?: boolean;
  last_eval_mirrored?: boolean;
  selection_robust_score_candidate?: number;
  selection_robust_score_incumbent?: number;
  selection_robust_delta?: number;
  selection_noninferiority_passed?: boolean;
  selection_attack_efficiency_candidate?: number;
  selection_attack_efficiency_incumbent?: number;
  selection_attack_delta?: number;
  selection_tiebreak_used?: boolean;
  selection_decision_reason?: string;
  elite_candidates_evaluated?: number;
  elite_selected_candidate_index?: number;
  elite_selection_reason?: string;
  sigma_mean?: number;
  sigma_min?: number;
  sigma_max?: number;
  restart_count?: number;
  last_restart_reason?: string;
  last_restart_anchor_score?: number;
  last_restart_window?: number;
  elite_fallback_used?: boolean;
  frozen_suite_summaries?: Record<string, FrozenSuiteSummaryDTO>;
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

export type FrozenSuiteSummaryDTO = {
  run_id?: string;
  suite_id?: string;
  suite_kind?: string;
  suite_tier?: string;
  created_at?: string;
  subject_type?: 'bot_version' | 'checkpoint';
  subject_ref?: string;
  suite_protocol_hash?: string;
  eval_seed_anchor?: number;
  seed_count?: number;
  games_per_seed?: number;
  paired_eval?: boolean;
  mirrored_first_player?: boolean;
  winrate?: number;
  lcb?: number;
  avg_shots_to_sink_all?: number;
  p95_shots_to_sink_all?: number;
  avg_shots_to_first_hit?: number;
  avg_shots_after_first_hit_to_sink_all?: number;
  avg_misses_before_first_hit?: number;
};

export type PlacementBiasReportDTO = {
  report_id: string;
  ruleset_id: string;
  sample_count: number;
  seed_anchor: number;
  seed_derivation_scheme: string;
  generator_version: string;
  created_at: string;
  occupancy_heatmap: number[][];
  occupancy_by_ship_len: Record<string, number[][]>;
  orientation_stats_by_len: Record<string, { horizontal: number; vertical: number; count: number }>;
  edge_center_bias: Record<string, number>;
  corner_bias: Record<string, number>;
  retry_stats: Record<string, unknown>;
  seed_reproducibility_check: Record<string, unknown>;
};
