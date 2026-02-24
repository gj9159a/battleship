use serde::Serialize;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::State;

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

    let python = std::env::var("BATTLESHIP_PYTHON").unwrap_or_else(|_| "python".to_string());

    let spawn_result = Command::new(python)
        .arg("-m")
        .arg("uvicorn")
        .arg("app.main:app")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg("8000")
        .current_dir(backend_dir)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();

    match spawn_result {
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
        .invoke_handler(tauri::generate_handler![backend_status, start_backend, stop_backend])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
