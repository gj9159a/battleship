import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from '../../app/App';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('GamePage', () => {
  it('loads rulesets and starts a game session', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);

      if (url.endsWith('/api/v1/rulesets') && !init?.method) {
        return new Response(
          JSON.stringify([
            {
              id: 'classic_v1',
              name: 'Classic Battleship v1',
              board_size: 10,
              fleet: [5, 4, 3, 3, 2],
              placement_no_touch: false,
              extra_turn_on_hit: true,
            },
          ]),
          { status: 200 },
        );
      }

      if (url.endsWith('/api/v1/health') && !init?.method) {
        return new Response(
          JSON.stringify({
            status: 'ok',
            service: 'battleship-backend',
            ts: '2026-02-24T00:00:00+00:00',
          }),
          { status: 200 },
        );
      }

      if (url.endsWith('/api/v1/game/sessions') && init?.method === 'POST') {
        return new Response(
          JSON.stringify({
            id: 'session-1',
            ruleset_id: 'classic_v1',
            lifecycle_state: 'running',
            current_player: 0,
            winner: null,
            player_placements: [
              { row: 0, col: 0, length: 5, orientation: 'H' },
              { row: 2, col: 0, length: 4, orientation: 'H' },
              { row: 4, col: 0, length: 3, orientation: 'H' },
              { row: 6, col: 0, length: 3, orientation: 'H' },
              { row: 8, col: 0, length: 2, orientation: 'H' },
            ],
            opponent_bot_version_id: 'classic_v1-baseline-strong',
            shots: [],
          }),
          { status: 200 },
        );
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Готово к старту.')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Начать игру' }));

    await waitFor(() => {
      expect(screen.getByTestId('session-id')).toHaveTextContent('Сессия: session-1');
    });

    expect(fetchMock).toHaveBeenCalled();
  });
});
