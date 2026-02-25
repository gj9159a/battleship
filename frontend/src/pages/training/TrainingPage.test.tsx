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
  current_weights: {
    hunt_heat: 1,
    target_adjacent: 0.9,
  },
  best_weights: {
    hunt_heat: 1,
    target_adjacent: 0.9,
  },
  params: {
    games_per_candidate: 100,
    epoch_iters: 2,
    microbatch_size: 100,
    eval_window_batches: 2,
    checkpoint_interval_batches: 50,
    population_size: 32,
    train_split: 0.7,
    worker_count: 12,
    quality_gate_games: 256,
    quality_gate_min_winrate: 0.57,
    quality_gate_min_lower_bound: 0.53,
    target_score: 0.8,
    improvement_delta: 0.008,
    plateau_delta: 0.0015,
    plateau_patience_windows: 8,
    early_stop_plateau_windows: 30,
    min_windows_before_early_stop: 120,
    tick_delay_ms: 0,
    autoevolve_enabled: true,
    meta_plateau_patience_cycles: 3,
    strictness_max_level: 3,
  },
  progress: {
    games_played: 0,
    batches_done: 0,
    windows_done: 0,
    best_score: 0,
    last_score: 0,
    plateau_windows: 0,
    cycle_index: 0,
    strictness_level: 0,
    meta_plateau_counter: 0,
    champion_gate_lcb: 0,
    eval_protocol_hash: '',
  },
};

const JOB_RUNNING = {
  ...JOB_IDLE,
  lifecycle_state: 'Running',
  stage_state: 'Warmup',
};

afterEach(() => {
  vi.useRealTimers();
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

      if (url.endsWith('/api/v1/training/jobs/job-1') && method === 'GET') {
        return new Response(JSON.stringify(JOB_RUNNING), { status: 200 });
      }

      throw new Error(`Unhandled request: ${url} ${method}`);
    });

    render(<TrainingPage />);

    await waitFor(() => {
      expect(screen.getByText('Готово к запуску тренировки.')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Запустить тренировку' }));

    await waitFor(() => {
      expect(screen.getByTestId('training-job-id')).toHaveTextContent('job-1');
      expect(screen.getByTestId('training-job-id')).toHaveTextContent('Running');
    });
  });

  it('retries rulesets loading after transient failure', async () => {
    vi.stubGlobal('WebSocket', undefined as unknown as typeof WebSocket);

    let rulesetCalls = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? 'GET';

      if (url.endsWith('/api/v1/rulesets') && method === 'GET') {
        rulesetCalls += 1;
        if (rulesetCalls === 1) {
          throw new Error('Failed to fetch');
        }
        return new Response(JSON.stringify(RULESETS), { status: 200 });
      }

      throw new Error(`Unhandled request: ${url} ${method}`);
    });

    render(<TrainingPage />);

    await waitFor(() => {
      expect(screen.getByText('Не удалось загрузить профили правил. Повторяем...')).toBeInTheDocument();
    });

    await waitFor(
      () => {
        expect(screen.getByText('Готово к запуску тренировки.')).toBeInTheDocument();
      },
      { timeout: 4000 },
    );
  });
});
