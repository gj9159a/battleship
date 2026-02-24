use serde::Serialize;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{Manager, State};

#[derive(Default)]
struct BackendManager {
    inner: Mutex<BackendRuntime>,
}

#[derive(Default)]
struct BackendRuntime {
    child: Option<Child>,
    last_error: Option<String>,
}

#[derive(Serialize)]
struct BackendStatus {
    running: bool,
    pid: Option<u32>,
    last_error: Option<String>,
}

impl Drop for BackendManager {
    fn drop(&mut self) {
        if let Ok(mut runtime) = self.inner.lock() {
            stop_runtime(&mut runtime);
        }
    }
}

fn has_backend_app(dir: &Path) -> bool {
    dir.join("app").join("main.py").is_file()
}

fn resolve_backend_dir() -> Result<PathBuf, String> {
    if let Ok(explicit) = std::env::var("BATTLESHIP_BACKEND_DIR") {
        let path = PathBuf::from(explicit);
        if has_backend_app(&path) {
            return Ok(path);
        }
        return Err(format!("BATTLESHIP_BACKEND_DIR is invalid: {}", path.display()));
    }

    let cwd = std::env::current_dir().map_err(|err| format!("current_dir failed: {err}"))?;

    let direct = cwd.join("backend");
    if has_backend_app(&direct) {
        return Ok(direct);
    }

    if let Some(parent) = cwd.parent() {
        let sibling = parent.join("backend");
        if has_backend_app(&sibling) {
            return Ok(sibling);
        }

        if let Some(grandparent) = parent.parent() {
            let sibling2 = grandparent.join("backend");
            if has_backend_app(&sibling2) {
                return Ok(sibling2);
            }
        }
    }

    Err(format!(
        "Cannot locate backend directory from {}. Set BATTLESHIP_BACKEND_DIR.",
        cwd.display()
    ))
}

fn refresh(runtime: &mut BackendRuntime) {
    if let Some(child) = runtime.child.as_mut() {
        match child.try_wait() {
            Ok(Some(_)) => {
                runtime.child = None;
            }
            Ok(None) => {}
            Err(err) => {
                runtime.last_error = Some(format!("backend_status failed: {err}"));
                runtime.child = None;
            }
        }
    }
}

fn status_from(runtime: &BackendRuntime) -> BackendStatus {
    BackendStatus {
        running: runtime.child.is_some(),
        pid: runtime.child.as_ref().map(Child::id),
        last_error: runtime.last_error.clone(),
    }
}

fn stop_runtime(runtime: &mut BackendRuntime) {
    if let Some(mut child) = runtime.child.take() {
        if let Err(err) = child.kill() {
            runtime.last_error = Some(format!("stop_backend kill failed: {err}"));
        }
        if let Err(err) = child.wait() {
            runtime.last_error = Some(format!("stop_backend wait failed: {err}"));
        }
    }
}

fn spawn_backend(backend_dir: &Path) -> Result<Child, String> {
    let mut candidates: Vec<(String, Vec<String>)> = Vec::new();

    if let Ok(explicit) = std::env::var("BATTLESHIP_PYTHON") {
        candidates.push((explicit, vec![]));
    }

    let venv_win = backend_dir.join(".venv").join("Scripts").join("python.exe");
    if venv_win.is_file() {
        candidates.push((venv_win.display().to_string(), vec![]));
    }

    let venv_unix = backend_dir.join(".venv").join("bin").join("python");
    if venv_unix.is_file() {
        candidates.push((venv_unix.display().to_string(), vec![]));
    }

    candidates.push(("python".to_string(), vec![]));
    candidates.push(("python3".to_string(), vec![]));
    candidates.push(("py".to_string(), vec!["-3".to_string()]));

    let mut errors: Vec<String> = Vec::new();
    for (program, mut prefix_args) in candidates {
        prefix_args.extend([
            "-m".to_string(),
            "uvicorn".to_string(),
            "app.main:app".to_string(),
            "--host".to_string(),
            "127.0.0.1".to_string(),
            "--port".to_string(),
            "8000".to_string(),
        ]);

        let spawn_result = Command::new(&program)
            .args(prefix_args)
            .current_dir(backend_dir)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn();

        match spawn_result {
            Ok(child) => return Ok(child),
            Err(err) => errors.push(format!("{program}: {err}")),
        }
    }

    Err(format!(
        "start_backend spawn failed for all python candidates: {}",
        errors.join(" | ")
    ))
}

#[tauri::command]
fn backend_status(state: State<'_, BackendManager>) -> BackendStatus {
    match state.inner.lock() {
        Ok(mut runtime) => {
            refresh(&mut runtime);
            status_from(&runtime)
        }
        Err(_) => BackendStatus {
            running: false,
            pid: None,
            last_error: Some("state lock poisoned".to_string()),
        },
    }
}

#[tauri::command]
fn start_backend(state: State<'_, BackendManager>) -> BackendStatus {
    let mut runtime = match state.inner.lock() {
        Ok(runtime) => runtime,
        Err(_) => {
            return BackendStatus {
                running: false,
                pid: None,
                last_error: Some("state lock poisoned".to_string()),
            }
        }
    };

    refresh(&mut runtime);
    if runtime.child.is_some() {
        return status_from(&runtime);
    }

    let backend_dir = match resolve_backend_dir() {
        Ok(path) => path,
        Err(err) => {
            runtime.last_error = Some(err);
            return status_from(&runtime);
        }
    };

    match spawn_backend(&backend_dir) {
        Ok(child) => {
            runtime.child = Some(child);
            runtime.last_error = None;
        }
        Err(err) => {
            runtime.last_error = Some(format!("start_backend spawn failed: {err}"));
        }
    }

    status_from(&runtime)
}

#[tauri::command]
fn stop_backend(state: State<'_, BackendManager>) -> BackendStatus {
    let mut runtime = match state.inner.lock() {
        Ok(runtime) => runtime,
        Err(_) => {
            return BackendStatus {
                running: false,
                pid: None,
                last_error: Some("state lock poisoned".to_string()),
            }
        }
    };

    refresh(&mut runtime);
    stop_runtime(&mut runtime);
    status_from(&runtime)
}

fn main() {
    tauri::Builder::default()
        .manage(BackendManager::default())
        .setup(|app| {
            let state = app.state::<BackendManager>();
            if let Ok(mut runtime) = state.inner.lock() {
                refresh(&mut runtime);
                if runtime.child.is_none() {
                    match resolve_backend_dir().and_then(|dir| spawn_backend(&dir)) {
                        Ok(child) => {
                            runtime.child = Some(child);
                            runtime.last_error = None;
                        }
                        Err(err) => {
                            runtime.last_error = Some(err);
                        }
                    }
                }
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend_status, start_backend, stop_backend])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
