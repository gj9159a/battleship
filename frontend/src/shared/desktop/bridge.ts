export type DesktopBackendStatus = {
  running: boolean;
  pid: number | null;
  last_error: string | null;
};

type TauriInvoke = <T = unknown>(cmd: string, args?: Record<string, unknown>) => Promise<T>;

type TauriGlobals = {
  __TAURI__?: {
    core?: {
      invoke?: TauriInvoke;
    };
  };
  __TAURI_INTERNALS__?: {
    invoke?: TauriInvoke;
  };
};

function getInvoke(): TauriInvoke | null {
  const globals = window as TauriGlobals;
  if (globals.__TAURI__?.core?.invoke && typeof globals.__TAURI__.core.invoke === 'function') {
    return globals.__TAURI__.core.invoke;
  }
  if (globals.__TAURI_INTERNALS__?.invoke && typeof globals.__TAURI_INTERNALS__.invoke === 'function') {
    return globals.__TAURI_INTERNALS__.invoke;
  }
  return null;
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
