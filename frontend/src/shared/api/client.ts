import type {
  EventEnvelope,
  GameSessionDTO,
  LeagueMatrixCellDTO,
  LeaguePoolType,
  LeagueRatingDTO,
  LeagueSeasonDTO,
  Placement,
  RulesetDTO,
  ShotDTO,
  TrainingCheckpointDTO,
  TrainingJobDTO,
  TrainingParamsDTO,
} from './types';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `HTTP ${response.status}`);
  }

  return (await response.json()) as T;
}

export function getRulesets(): Promise<RulesetDTO[]> {
  return request<RulesetDTO[]>('/api/v1/rulesets');
}

export function getBackendHealth(): Promise<{ status: string; service: string; ts: string }> {
  return request<{ status: string; service: string; ts: string }>('/api/v1/health');
}

export function createGameSession(payload: {
  ruleset_id: string;
  player_placements: Placement[];
  opponent_placements: Placement[];
  first_player: 0 | 1;
}): Promise<GameSessionDTO> {
  return request<GameSessionDTO>('/api/v1/game/sessions', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getGameSession(sessionId: string): Promise<GameSessionDTO> {
  return request<GameSessionDTO>(`/api/v1/game/sessions/${sessionId}`);
}

export function shoot(sessionId: string, row: number, col: number): Promise<ShotDTO> {
  return request<ShotDTO>(`/api/v1/game/sessions/${sessionId}/shots`, {
    method: 'POST',
    body: JSON.stringify({ row, col }),
  });
}

export function createTrainingJob(payload: {
  ruleset_id: string;
  profile_id?: string | null;
  seed?: number | null;
  params?: TrainingParamsDTO;
}): Promise<TrainingJobDTO> {
  return request<TrainingJobDTO>('/api/v1/training/jobs', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getTrainingJob(jobId: string): Promise<TrainingJobDTO> {
  return request<TrainingJobDTO>(`/api/v1/training/jobs/${jobId}`);
}

export function commandTrainingJob(
  jobId: string,
  command: 'start' | 'pause' | 'resume' | 'stop',
): Promise<TrainingJobDTO> {
  return request<TrainingJobDTO>(`/api/v1/training/jobs/${jobId}/commands`, {
    method: 'POST',
    body: JSON.stringify({ command }),
  });
}

export function getTrainingCheckpoints(jobId: string): Promise<TrainingCheckpointDTO[]> {
  return request<TrainingCheckpointDTO[]>(`/api/v1/training/jobs/${jobId}/checkpoints`);
}

export function loadTrainingCheckpoint(jobId: string, checkpointId: string): Promise<TrainingJobDTO> {
  return request<TrainingJobDTO>(`/api/v1/training/jobs/${jobId}/resume-from/${checkpointId}`, {
    method: 'POST',
  });
}

export function registerLeagueBot(
  rulesetId: string,
  botVersionId: string,
  poolType: LeaguePoolType,
): Promise<LeagueRatingDTO> {
  return request<LeagueRatingDTO>(`/api/v1/league/${rulesetId}/bots`, {
    method: 'POST',
    body: JSON.stringify({ bot_version_id: botVersionId, pool_type: poolType }),
  });
}

export function getLeagueTable(rulesetId: string): Promise<LeagueRatingDTO[]> {
  return request<LeagueRatingDTO[]>(`/api/v1/league/${rulesetId}/table`);
}

export function getLeagueMatchupMatrix(rulesetId: string): Promise<LeagueMatrixCellDTO[]> {
  return request<LeagueMatrixCellDTO[]>(`/api/v1/league/${rulesetId}/matchup-matrix`);
}

export function createLeagueSeason(payload: {
  ruleset_id: string;
  seed: number;
  max_matches: number;
  microbatch_size: number;
}): Promise<LeagueSeasonDTO> {
  return request<LeagueSeasonDTO>('/api/v1/league/seasons', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getLeagueSeason(seasonId: string): Promise<LeagueSeasonDTO> {
  return request<LeagueSeasonDTO>(`/api/v1/league/seasons/${seasonId}`);
}

export function commandLeagueSeason(
  seasonId: string,
  command: 'start' | 'pause' | 'resume' | 'stop',
): Promise<LeagueSeasonDTO> {
  return request<LeagueSeasonDTO>(`/api/v1/league/jobs/${seasonId}/commands`, {
    method: 'POST',
    body: JSON.stringify({ command }),
  });
}

export function recordLeagueMatch(payload: {
  ruleset_id: string;
  bot_a_id: string;
  bot_b_id: string;
  winner_id: string | null;
}): Promise<void> {
  return request<Record<string, unknown>>(`/api/v1/league/${payload.ruleset_id}/matches`, {
    method: 'POST',
    body: JSON.stringify({
      bot_a_id: payload.bot_a_id,
      bot_b_id: payload.bot_b_id,
      winner_id: payload.winner_id,
    }),
  }).then(() => undefined);
}

export function connectEvents(onEvent: (event: EventEnvelope) => void): (() => void) | null {
  if (typeof WebSocket === 'undefined') {
    return null;
  }

  const wsBase = API_BASE.replace(/^http/, 'ws');
  const socket = new WebSocket(`${wsBase}/api/v1/ws`);
  socket.onmessage = (message) => {
    try {
      const payload = JSON.parse(message.data) as EventEnvelope;
      onEvent(payload);
    } catch {
      // Ignore malformed event.
    }
  };

  return () => {
    socket.close();
  };
}
