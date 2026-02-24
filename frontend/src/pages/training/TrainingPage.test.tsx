import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { TrainingPage } from './TrainingPage';

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

const JOB_IDLE = {
  id: 'job-1',
  ruleset_id: 'classic_v1',
  lifecycle_state: 'Idle',
  stage_state: null,
  profile_id: null,
  seed_bot_version_id: null,
  seed: 42,
  stop_reason: null,
  params: {
    budget_games: 5000,
    microbatch_size: 20,
    eval_window_batches: 1,
    checkpoint_interval_batches: 5,
    target_score: 0.72,
    improvement_delta: 0.01,
    plateau_delta: 0.003,
    plateau_patience_windows: 4,
    early_stop_plateau_windows: 8,
    tick_delay_ms: 10,
  },
  progress: {
    games_played: 0,
    batches_done: 0,
    windows_done: 0,
    best_score: 0,
    last_score: 0,
    plateau_windows: 0,
  },
};

const JOB_RUNNING = {
  ...JOB_IDLE,
  lifecycle_state: 'Running',
  stage_state: 'Warmup',
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe('TrainingPage', () => {
  it('starts training job and shows running state', async () => {
    vi.stubGlobal('WebSocket', undefined as unknown as typeof WebSocket);

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? 'GET';

      if (url.endsWith('/api/v1/rulesets') && method === 'GET') {
        return new Response(JSON.stringify(RULESETS), { status: 200 });
      }

      if (url.endsWith('/api/v1/training/jobs') && method === 'POST') {
        return new Response(JSON.stringify(JOB_IDLE), { status: 200 });
      }

      if (url.endsWith('/api/v1/training/jobs/job-1/commands') && method === 'POST') {
        return new Response(JSON.stringify(JOB_RUNNING), { status: 200 });
      }

      if (url.endsWith('/api/v1/training/jobs/job-1/checkpoints') && method === 'GET') {
        return new Response(JSON.stringify([]), { status: 200 });
      }

      if (url.endsWith('/api/v1/training/jobs/job-1') && method === 'GET') {
        return new Response(JSON.stringify(JOB_RUNNING), { status: 200 });
      }

      throw new Error(`Unhandled request: ${url} ${method}`);
    });

    render(<TrainingPage />);

    await waitFor(() => {
      expect(screen.getByText('Готово к запуску тренировки.')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Start training' }));

    await waitFor(() => {
      expect(screen.getByTestId('training-job-id')).toHaveTextContent('job-1');
      expect(screen.getByTestId('training-job-id')).toHaveTextContent('Running');
    });
  });
});
