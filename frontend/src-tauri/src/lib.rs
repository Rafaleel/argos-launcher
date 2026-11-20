//! Desktop shell: opens the UI and runs the Python backend next to it.
//!
//! shortcut: the backend runs from the source checkout (its .venv, or `uv run`); a packaged
//! build needs the backend bundled as a sidecar, which is not done yet.
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::{Manager, RunEvent};

pub const BACKEND_PORT: u16 = 8765;

struct Backend(Mutex<Option<Child>>);

fn backend_dir() -> PathBuf {
    std::env::var_os("ARGOS_BACKEND_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../../backend")))
}

fn start_backend() -> Option<Child> {
    // One backend only: a second one would close the first one's open sessions at start-up.
    if TcpStream::connect(("127.0.0.1", BACKEND_PORT)).is_ok() {
        log::info!("backend already running on port {BACKEND_PORT}");
        return None;
    }
    let dir = backend_dir();
    let venv_python = dir.join(".venv/bin/python");
    let port = BACKEND_PORT.to_string();
    let uvicorn = ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", port.as_str()];
    let mut cmd = if venv_python.exists() {
        let mut c = Command::new(venv_python);
        c.args(uvicorn);
        c
    } else {
        let mut c = Command::new("uv");
        c.args(["run", "python"]).args(uvicorn);
        c
    };
    match cmd.current_dir(&dir).spawn() {
        Ok(child) => Some(child),
        Err(err) => {
            log::error!("could not start the backend in {}: {err}", dir.display());
            None
        }
    }
}

fn stop_backend(child: &mut Child) {
    // SIGTERM lets uvicorn close cleanly; open game sessions end at their last heartbeat.
    unsafe {
        libc::kill(child.id() as i32, libc::SIGTERM);
    }
    let _ = child.wait();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            app.manage(Backend(Mutex::new(start_backend())));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(mut child) = app.state::<Backend>().0.lock().unwrap().take() {
                    stop_backend(&mut child);
                }
            }
        });
}
