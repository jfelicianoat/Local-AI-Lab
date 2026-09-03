//! Puente entre la superficie React y el Coordinator local.
//!
//! El fichero esta partido por responsabilidad:
//!
//! - `sesion`      — la sesion y su token, que no salen de Rust.
//! - `comandos`    — lo unico que React puede pedir.
//! - `coordinador` — arranque y ciclo de vida del sidecar.
mod comandos;
mod coordinador;
mod sesion;

use std::sync::Mutex;
use tauri::Manager;

use comandos::*;
use coordinador::start_coordinator;
use sesion::{failed_session_state, CoordinatorProcess, DesktopSessionState, SessionState};

pub fn run() {
    let application = tauri::Builder::default()
        .manage(SessionState(Mutex::new(DesktopSessionState::default())))
        .manage(CoordinatorProcess(Mutex::new(None)))
        .setup(|app| {
            match start_coordinator(app.handle()) {
                Ok((session, child)) => {
                    *app.state::<SessionState>()
                        .0
                        .lock()
                        .map_err(|_| "session lock poisoned")? = DesktopSessionState {
                        session: Some(session),
                        startup_error: None,
                    };
                    *app.state::<CoordinatorProcess>()
                        .0
                        .lock()
                        .map_err(|_| "process lock poisoned")? = child;
                }
                Err(error) => {
                    let failure = failed_session_state(error);
                    eprintln!(
                        "{}",
                        failure
                            .startup_error
                            .as_deref()
                            .unwrap_or("Error de inicio")
                    );
                    *app.state::<SessionState>()
                        .0
                        .lock()
                        .map_err(|_| "session lock poisoned")? = failure;
                }
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            load_overview,
            load_workspace,
            load_reviews,
            load_jobs,
            cancel_job,
            save_review_correction,
            transition_review,
            transition_training_candidate,
            discover_vaults,
            create_vault_snapshot,
            create_knowledge_index,
            run_controlled_retrieval_benchmark,
            create_semantic_retrieval_benchmark,
            register_real_benchmark,
            run_model_drift_comparison,
            check_broker_compatibility,
            select_strategy,
            create_broker_agent_experiment,
            create_strategy_run,
            build_approved_feedback_dataset,
            create_training_preflight,
            create_training_run,
            create_distillation_run,
            create_model_export
        ])
        .build(tauri::generate_context!())
        .expect("error while building Local AI Lab desktop");
    application.run(|handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            if let Ok(mut process) = handle.state::<CoordinatorProcess>().0.lock() {
                if let Some(child) = process.as_mut() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        }
    });
}
