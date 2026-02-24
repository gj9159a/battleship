import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { LeaguePage } from './LeaguePage';

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
  vi.restoreAllMocks();
});

describe('LeaguePage', () => {
  it('registers bot and refreshes table', async () => {
    vi.stubGlobal('WebSocket', undefined as unknown as typeof WebSocket);

    let registered = false;

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? 'GET';

      if (url.endsWith('/api/v1/rulesets') && method === 'GET') {
        return new Response(JSON.stringify(RULESETS), { status: 200 });
      }

      if (url.endsWith('/api/v1/league/classic_v1/table') && method === 'GET') {
        const rows = registered
          ? [
              {
                ruleset_id: 'classic_v1',
                bot_version_id: 'candidate-001',
                pool_type: 'league',
                mu: 25,
                sigma: 8.333,
                conservative_score: 0,
                matches_played: 0,
                wins: 0,
                losses: 0,
                draws: 0,
                winrate: 0,
                updated_at: '2026-02-24T00:00:00Z',
              },
            ]
          : [];
        return new Response(JSON.stringify(rows), { status: 200 });
      }

      if (url.endsWith('/api/v1/league/classic_v1/matchup-matrix') && method === 'GET') {
        return new Response(JSON.stringify([]), { status: 200 });
      }

      if (url.endsWith('/api/v1/league/classic_v1/bots') && method === 'POST') {
        registered = true;
        return new Response(
          JSON.stringify({
            ruleset_id: 'classic_v1',
            bot_version_id: 'candidate-001',
            pool_type: 'league',
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

    render(<LeaguePage />);

    await waitFor(() => {
      expect(screen.getByText('Готово к работе с лигой.')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText('Bot version id'), { target: { value: 'candidate-001' } });
    fireEvent.click(screen.getByRole('button', { name: 'Register bot' }));

    await waitFor(() => {
      expect(screen.getByTestId('league-table')).toHaveTextContent('candidate-001');
    });
  });
});
