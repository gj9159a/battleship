import { useEffect, useState } from 'react';

import { getBackendHealth } from '../../shared/api/client';
import {
  desktopBackendStart,
  desktopBackendStatus,
  desktopBackendStop,
  isDesktopRuntime,
} from '../../shared/desktop/bridge';

type Mode = 'desktop' | 'web';

type HealthState = {
  online: boolean;
  mode: Mode;
  pid: number | null;
  error: string | null;
};

async function probe(mode: Mode): Promise<HealthState> {
  if (mode === 'desktop') {
    const status = await desktopBackendStatus();
    if (!status) {
      return { online: false, mode, pid: null, error: 'Мост десктоп недоступен' };
    }
    return { online: status.running, mode, pid: status.pid, error: status.last_error };
  }

  try {
    const health = await getBackendHealth();
    return { online: health.status === 'ok', mode, pid: null, error: null };
  } catch (error) {
    return { online: false, mode, pid: null, error: (error as Error).message };
  }
}

export function BackendStatusBar() {
  const mode: Mode = isDesktopRuntime() ? 'desktop' : 'web';
  const [state, setState] = useState<HealthState>({ online: false, mode, pid: null, error: null });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let mounted = true;

    const update = async () => {
      const next = await probe(mode);
      if (mounted) {
        setState(next);
      }
    };

    void update();
    const timer = window.setInterval(() => {
      void update();
    }, 2000);

    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [mode]);

  async function onStart() {
    setBusy(true);
    try {
      await desktopBackendStart();
      const next = await probe('desktop');
      setState(next);
    } finally {
      setBusy(false);
    }
  }

  async function onStop() {
    setBusy(true);
    try {
      await desktopBackendStop();
      const next = await probe('desktop');
      setState(next);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="backend-bar" data-testid="backend-status-bar">
      <span className={state.online ? 'backend-pill backend-pill-online' : 'backend-pill backend-pill-offline'}>
        Бэкенд: {state.online ? 'онлайн' : 'оффлайн'}
      </span>
      <span className="backend-meta">
        Режим: {mode === 'desktop' ? 'десктоп' : 'веб'}
        {state.pid ? ` | pid ${state.pid}` : ''}
      </span>
      {mode === 'desktop' && (
        <div className="backend-actions">
          <button type="button" className="mini-btn" onClick={onStart} disabled={busy || state.online}>
            Запустить бэкенд
          </button>
          <button type="button" className="mini-btn" onClick={onStop} disabled={busy || !state.online}>
            Остановить бэкенд
          </button>
        </div>
      )}
      {state.error && <span className="backend-error">{state.error}</span>}
    </div>
  );
}
