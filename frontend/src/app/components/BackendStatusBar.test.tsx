import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { BackendStatusBar } from './BackendStatusBar';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  delete window.__TAURI__;
  delete window.__TAURI_INTERNALS__;
});

describe('BackendStatusBar', () => {
  it('shows web backend status from health endpoint', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          status: 'ok',
          service: 'battleship-backend',
          ts: '2026-02-24T00:00:00+00:00',
        }),
        { status: 200 },
      ),
    );

    render(<BackendStatusBar />);

    await waitFor(() => {
      expect(screen.getByText('Бэкенд: онлайн')).toBeInTheDocument();
      expect(screen.getByText('Режим: веб')).toBeInTheDocument();
    });
  });

  it('runs start and stop commands in desktop mode', async () => {
    let running = false;

    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === 'backend_status') {
            return { running, pid: running ? 4242 : null, last_error: null };
          }
          if (command === 'start_backend') {
            running = true;
            return { running: true, pid: 4242, last_error: null };
          }
          if (command === 'stop_backend') {
            running = false;
            return { running: false, pid: null, last_error: null };
          }
          throw new Error(`Unknown command ${command}`);
        }),
      },
    };

    render(<BackendStatusBar />);

    await waitFor(() => {
      expect(screen.getByText('Режим: десктоп')).toBeInTheDocument();
      expect(screen.getByText('Бэкенд: оффлайн')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Запустить бэкенд' }));

    await waitFor(() => {
      expect(screen.getByText('Бэкенд: онлайн')).toBeInTheDocument();
      expect(screen.getByText('Режим: десктоп | pid 4242')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Остановить бэкенд' }));

    await waitFor(() => {
      expect(screen.getByText('Бэкенд: оффлайн')).toBeInTheDocument();
    });
  });

  it('detects desktop mode via __TAURI_INTERNALS__ bridge', async () => {
    window.__TAURI_INTERNALS__ = {
      invoke: vi.fn(async (command: string) => {
        if (command === 'backend_status') {
          return { running: false, pid: null, last_error: null };
        }
        throw new Error(`Unknown command ${command}`);
      }),
    };

    render(<BackendStatusBar />);

    await waitFor(() => {
      expect(screen.getByText('Режим: десктоп')).toBeInTheDocument();
      expect(screen.getByText('Бэкенд: оффлайн')).toBeInTheDocument();
    });
  });
});
