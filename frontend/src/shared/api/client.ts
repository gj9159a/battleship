import type { GameSessionDTO, Placement, RulesetDTO, ShotDTO } from './types';

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
