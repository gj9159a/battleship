import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { BotsPage } from './BotsPage';

const RULESETS = [
  {
    id: 'classic_v1',
    name: 'Classic Battleship v1',
    board_size: 10,
    fleet: [5, 4, 3, 3, 2],
    placement_no_touch: false,
    extra_turn_on_hit: true,
  },
];

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe('BotsPage', () => {
  it('imports bot into league and selects seed', async () => {
    const bots = [
      {
        bot_version_id: 'candidate-100',
        ruleset_id: 'classic_v1',
        policy_type: 'probability_strong',
        feature_schema_version: 'classic_features_v1',
        lookahead_policy_version: 'adaptive_v1',
        weights: { hunt_density: 0.61 },
        source_job_id: 'job-0',
        source_checkpoint_id: 'job-0-b5',
        tags: [],
        created_at: '2026-02-24T00:00:00Z',
      },
    ];

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? 'GET';

      if (url.endsWith('/api/v1/rulesets') && method === 'GET') {
        return new Response(JSON.stringify(RULESETS), { status: 200 });
      }

      if (url.includes('/api/v1/bots?ruleset_id=classic_v1') && method === 'GET') {
        return new Response(JSON.stringify(bots), { status: 200 });
      }

      if (url.endsWith('/api/v1/league/classic_v1/bots') && method === 'POST') {
        return new Response(
          JSON.stringify({
            ruleset_id: 'classic_v1',
            bot_version_id: 'candidate-100',
            pool_type: 'active',
            mu: 25,
            sigma: 8.333,
            conservative_score: 0,
            matches_played: 0,
            wins: 0,
            losses: 0,
            draws: 0,
            winrate: 0,
            updated_at: '2026-02-24T00:00:00Z',
          }),
          { status: 200 },
        );
      }

      throw new Error(`Unhandled request: ${url} ${method}`);
    });

    render(<BotsPage />);

    await waitFor(() => {
      expect(screen.getByText('Готово к работе с ботами.')).toBeInTheDocument();
    });

    fireEvent.click(screen.getAllByRole('button', { name: 'Импорт в лигу' })[0]);

    await waitFor(() => {
      expect(screen.getByTestId('bots-status-text')).toHaveTextContent('импортирован в пул лиги');
    });

    fireEvent.click(screen.getAllByRole('button', { name: 'Выбрать как seed' })[0]);

    expect(window.localStorage.getItem('training.seed_bot_version_id')).toBe('candidate-100');
    expect(screen.getByTestId('bots-seed-selection')).toHaveTextContent('candidate-100');
  });
});
