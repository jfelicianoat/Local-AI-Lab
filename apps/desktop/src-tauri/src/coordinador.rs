//! Arranque y localizacion del sidecar Coordinator.
//!
//! El puerto se toma libre del sistema y el token se genera por sesion:
//! dos arranques no comparten credencial.
use std::fs::OpenOptions;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use tauri::Manager;

use crate::sesion::DesktopSession;

pub(crate) fn start_coordinator(
    app: &tauri::AppHandle,
) -> Result<(DesktopSession, Option<Child>), Box<dyn std::error::Error>> {
    if let (Ok(endpoint), Ok(app_token)) = (
        std::env::var("LOCAL_AI_LAB_COORDINATOR_ENDPOINT"),
        std::env::var("LOCAL_AI_LAB_APP_TOKEN"),
    ) {
        return Ok((
            DesktopSession {
                endpoint,
                app_token,
            },
            None,
        ));
    }

    let listener = TcpListener::bind("127.0.0.1:0")?;
    let port = listener.local_addr()?.port();
    drop(listener);
    let app_token = uuid::Uuid::new_v4().simple().to_string();
    let data_dir = match std::env::var_os("LOCAL_AI_LAB_DATA_DIR") {
        Some(path) => PathBuf::from(path),
        None => app.path().app_local_data_dir()?,
    };
    std::fs::create_dir_all(&data_dir)?;
    let database = data_dir.join("coordinator").join("state.db");
    if let Some(parent) = database.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let resource_dir = app.path().resource_dir()?;
    let executable = resolve_coordinator_executable(
        &resource_dir,
        std::env::var_os("LOCAL_AI_LAB_COORDINATOR_EXECUTABLE").map(PathBuf::from),
        Path::is_file,
    );
    if !executable.is_file() {
        return Err(format!(
            "No se encontró el sidecar del Coordinator en {}",
            executable.display()
        )
        .into());
    }
    let log_path = data_dir.join("coordinator.log");
    let log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)?;
    let log_error = log.try_clone()?;
    let child = Command::new(executable)
        .arg("--database")
        .arg(database)
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(port.to_string())
        .env("LOCAL_AI_LAB_APP_TOKEN", &app_token)
        .stdin(Stdio::null())
        .stdout(Stdio::from(log))
        .stderr(Stdio::from(log_error))
        .spawn()?;
    Ok((
        DesktopSession {
            endpoint: format!("http://127.0.0.1:{port}"),
            app_token,
        },
        Some(child),
    ))
}

pub(crate) fn resolve_coordinator_executable(
    resource_dir: &Path,
    override_path: Option<PathBuf>,
    is_file: impl Fn(&Path) -> bool,
) -> PathBuf {
    if let Some(path) = override_path {
        return path;
    }
    let bundled = resource_dir.join("local-ai-lab-coordinator.exe");
    if is_file(&bundled) {
        return bundled;
    }
    let portable = resource_dir
        .join("resources")
        .join("local-ai-lab-coordinator.exe");
    if is_file(&portable) {
        return portable;
    }
    bundled
}

#[cfg(test)]
mod tests {
    use super::resolve_coordinator_executable;
    use crate::sesion::failed_session_state;
    use std::path::Path;

    #[test]
    fn portable_build_resolves_coordinator_from_resources_subdirectory() {
        let root = Path::new(r"D:\portable");
        let nested = root.join("resources").join("local-ai-lab-coordinator.exe");

        let resolved = resolve_coordinator_executable(root, None, |candidate| candidate == nested);

        assert_eq!(resolved, nested);
    }

    #[test]
    fn installed_build_prefers_coordinator_at_resource_root() {
        let root = Path::new(r"C:\Program Files\Local AI Lab");
        let bundled = root.join("local-ai-lab-coordinator.exe");

        let resolved = resolve_coordinator_executable(root, None, |candidate| candidate == bundled);

        assert_eq!(resolved, bundled);
    }

    #[test]
    fn coordinator_startup_failure_is_preserved_for_the_ui() {
        let state = failed_session_state("Acceso denegado. (os error 5)");

        assert!(state.session.is_none());
        assert_eq!(
            state.startup_error.as_deref(),
            Some("No se pudo iniciar el Coordinator local: Acceso denegado. (os error 5)")
        );
    }
}
