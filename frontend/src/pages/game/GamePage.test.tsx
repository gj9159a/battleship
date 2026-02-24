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

    fireEvent.click(screen.getByRole('button', { name: 'Start Game' }));

    await waitFor(() => {
      expect(screen.getByTestId('session-id')).toHaveTextContent('Session: session-1');
    });

    expect(fetchMock).toHaveBeenCalled();
  });
});
