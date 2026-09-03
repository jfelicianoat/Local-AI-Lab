//! Sesion del escritorio contra el Coordinator local.
//!
//! El token vive aqui y no llega nunca a React: la superficie web pide
//! operaciones por nombre, no endpoints con credencial.
use std::process::Child;
use std::sync::Mutex;

#[derive(Clone)]
pub(crate) struct DesktopSession {
    pub(crate) endpoint: String,
    pub(crate) app_token: String,
}

#[derive(Clone, Default)]
pub(crate) struct DesktopSessionState {
    pub(crate) session: Option<DesktopSession>,
    pub(crate) startup_error: Option<String>,
}

pub(crate) struct SessionState(pub(crate) Mutex<DesktopSessionState>);
pub(crate) struct CoordinatorProcess(pub(crate) Mutex<Option<Child>>);

pub(crate) fn failed_session_state(error: impl std::fmt::Display) -> DesktopSessionState {
    DesktopSessionState {
        session: None,
        startup_error: Some(format!("No se pudo iniciar el Coordinator local: {error}")),
    }
}

pub(crate) fn require_session(state: &SessionState) -> Result<DesktopSession, String> {
    let snapshot = state
        .0
        .lock()
        .map_err(|_| "No se pudo abrir la sesión local")?
        .clone();
    snapshot.session.ok_or_else(|| {
        snapshot.startup_error.unwrap_or_else(|| {
            "El Coordinator local todavía no ha sido iniciado por el empaquetador".to_string()
        })
    })
}
