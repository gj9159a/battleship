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
