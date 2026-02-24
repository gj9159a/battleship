export type DesktopBackendStatus = {
  running: boolean;
  pid: number | null;
  last_error: string | null;
};

type TauriInvoke = <T = unknown>(cmd: string, args?: Record<string, unknown>) => Promise<T>;

function getInvoke(): TauriInvoke | null {
  const api = window.__TAURI__;
  if (!api || !api.core || typeof api.core.invoke !== 'function') {
    return null;
  }
  return api.core.invoke as TauriInvoke;
}

export function isDesktopRuntime(): boolean {
  return getInvoke() !== null;
}

export async function desktopBackendStatus(): Promise<DesktopBackendStatus | null> {
  const invoke = getInvoke();
  if (!invoke) {
    return null;
  }
  return invoke<DesktopBackendStatus>('backend_status');
}

export async function desktopBackendStart(): Promise<DesktopBackendStatus | null> {
  const invoke = getInvoke();
  if (!invoke) {
    return null;
  }
  return invoke<DesktopBackendStatus>('start_backend');
}

export async function desktopBackendStop(): Promise<DesktopBackendStatus | null> {
  const invoke = getInvoke();
  if (!invoke) {
    return null;
  }
  return invoke<DesktopBackendStatus>('stop_backend');
}
