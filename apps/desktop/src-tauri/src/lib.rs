use std::fs::OpenOptions;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::Manager;

#[derive(Clone)]
struct DesktopSession {
    endpoint: String,
    app_token: String,
}

#[derive(Clone, Default)]
struct DesktopSessionState {
    session: Option<DesktopSession>,
    startup_error: Option<String>,
}

struct SessionState(Mutex<DesktopSessionState>);
struct CoordinatorProcess(Mutex<Option<Child>>);

fn failed_session_state(error: impl std::fmt::Display) -> DesktopSessionState {
    DesktopSessionState {
        session: None,
        startup_error: Some(format!("No se pudo iniciar el Coordinator local: {error}")),
    }
}

fn require_session(state: &SessionState) -> Result<DesktopSession, String> {
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

#[tauri::command]
async fn load_overview(state: tauri::State<'_, SessionState>) -> Result<serde_json::Value, String> {
    load_app_json(state, "/app/v1/overview").await
}

#[tauri::command]
async fn load_workspace(
    state: tauri::State<'_, SessionState>,
) -> Result<serde_json::Value, String> {
    load_app_json(state, "/app/v1/workspace").await
}

#[tauri::command]
async fn load_reviews(state: tauri::State<'_, SessionState>) -> Result<serde_json::Value, String> {
    load_app_json(state, "/app/v1/reviews").await
}

#[tauri::command]
async fn load_jobs(state: tauri::State<'_, SessionState>) -> Result<serde_json::Value, String> {
    load_app_json(state, "/app/v1/jobs").await
}

#[tauri::command]
async fn cancel_job(
    state: tauri::State<'_, SessionState>,
    job_id: String,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        &format!("/app/v1/jobs/{job_id}/cancel"),
        serde_json::json!({"idempotency_key": format!("desktop-cancel-{}", uuid::Uuid::new_v4())}),
    )
    .await
}

#[tauri::command]
async fn save_review_correction(
    state: tauri::State<'_, SessionState>,
    review_id: String,
    corrected_response: serde_json::Value,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::PUT,
        &format!("/app/v1/reviews/{review_id}/correction"),
        serde_json::json!({"actor": "desktop-user", "corrected_response": corrected_response}),
    )
    .await
}

#[tauri::command]
async fn transition_review(
    state: tauri::State<'_, SessionState>,
    review_id: String,
    to_state: String,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        &format!("/app/v1/reviews/{review_id}/state"),
        serde_json::json!({"actor": "desktop-user", "to_state": to_state}),
    )
    .await
}

#[tauri::command]
async fn transition_training_candidate(
    state: tauri::State<'_, SessionState>,
    review_id: String,
    to_state: String,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        &format!("/app/v1/reviews/{review_id}/training-state"),
        serde_json::json!({"actor": "desktop-user", "to_state": to_state}),
    )
    .await
}

#[tauri::command]
async fn discover_vaults(
    state: tauri::State<'_, SessionState>,
    allowed_root: String,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/vaults/discover",
        serde_json::json!({"allowed_root": allowed_root}),
    )
    .await
}

#[tauri::command]
async fn create_vault_snapshot(
    state: tauri::State<'_, SessionState>,
    allowed_root: String,
    vault_name: String,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/snapshots",
        serde_json::json!({"allowed_root": allowed_root, "vault_name": vault_name}),
    )
    .await
}

#[tauri::command]
async fn create_knowledge_index(
    state: tauri::State<'_, SessionState>,
    snapshot_id: String,
    previous_index_id: Option<String>,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/indexes",
        serde_json::json!({"snapshot_id": snapshot_id, "previous_index_id": previous_index_id}),
    )
    .await
}

#[tauri::command]
async fn run_controlled_retrieval_benchmark(
    state: tauri::State<'_, SessionState>,
    k: u16,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/benchmarks/controlled/retrieval",
        serde_json::json!({"k": k}),
    )
    .await
}

#[tauri::command]
async fn create_semantic_retrieval_benchmark(
    state: tauri::State<'_, SessionState>,
    strategy_id: String,
    node_id: String,
    embedding_model: String,
    embedding_model_fingerprint: String,
    device: String,
    k: u16,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/benchmarks/controlled/semantic",
        serde_json::json!({
            "strategy_id": strategy_id, "node_id": node_id,
            "embedding_model": embedding_model,
            "embedding_model_fingerprint": embedding_model_fingerprint,
            "device": device, "k": k,
            "idempotency_key": format!("desktop-semantic-{}", uuid::Uuid::new_v4())
        }),
    )
    .await
}

#[tauri::command]
async fn register_real_benchmark(
    state: tauri::State<'_, SessionState>,
    definition: serde_json::Value,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/benchmarks/real",
        serde_json::json!({"definition": definition}),
    )
    .await
}

#[tauri::command]
async fn run_model_drift_comparison(
    state: tauri::State<'_, SessionState>,
    r3_experiment_id: String,
    r4_experiment_id: String,
    executable: String,
    working_directory: String,
    confirmed: bool,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/model-drift/comparisons",
        serde_json::json!({
            "r3_experiment_id": r3_experiment_id, "r4_experiment_id": r4_experiment_id,
            "executable": executable, "working_directory": working_directory,
            "confirmed": confirmed
        }),
    )
    .await
}

#[tauri::command]
async fn check_broker_compatibility(
    state: tauri::State<'_, SessionState>,
    endpoint: String,
    phase: String,
    token: Option<String>,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/broker/compatibility",
        serde_json::json!({"endpoint": endpoint, "phase": phase, "token": token}),
    )
    .await
}

#[tauri::command]
async fn select_strategy(
    state: tauri::State<'_, SessionState>,
    experiment_ids: Vec<String>,
    privacy: Option<String>,
    max_latency_ms: Option<f64>,
    max_cost: Option<String>,
    minimum_cases: u32,
    require_formal_verdict: bool,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/strategy-selection",
        serde_json::json!({
            "experiment_ids": experiment_ids, "privacy": privacy,
            "max_latency_ms": max_latency_ms, "max_cost": max_cost,
            "minimum_cases": minimum_cases,
            "require_formal_verdict": require_formal_verdict
        }),
    )
    .await
}

#[tauri::command]
async fn create_broker_agent_experiment(
    state: tauri::State<'_, SessionState>,
    strategy_id: String,
    broker_check_id: String,
    broker_endpoint: String,
    node_id: String,
    provider: String,
    deployment: String,
    model: String,
    embedding_model: String,
    embedding_model_fingerprint: String,
    device: String,
    k: u16,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/broker/agent-experiments",
        serde_json::json!({
            "strategy_id": strategy_id, "broker_check_id": broker_check_id,
            "broker_endpoint": broker_endpoint, "node_id": node_id,
            "target_model": {"provider": provider, "deployment": deployment, "model": model},
            "embedding_model": embedding_model,
            "embedding_model_fingerprint": embedding_model_fingerprint,
            "device": device, "k": k,
            "idempotency_key": format!("desktop-agent-{}", uuid::Uuid::new_v4())
        }),
    )
    .await
}

#[tauri::command]
async fn create_strategy_run(
    state: tauri::State<'_, SessionState>,
    strategy_id: String,
    broker_check_id: String,
    broker_endpoint: String,
    node_id: String,
    provider: String,
    deployment: String,
    model: String,
    embedding_model: Option<String>,
    embedding_model_fingerprint: Option<String>,
    device: String,
    training_job_id: Option<String>,
    k: u16,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/strategy-runs",
        serde_json::json!({
            "strategy_id": strategy_id, "broker_check_id": broker_check_id,
            "broker_endpoint": broker_endpoint, "node_id": node_id,
            "target_model": {"provider": provider, "deployment": deployment, "model": model},
            "embedding_model": embedding_model,
            "embedding_model_fingerprint": embedding_model_fingerprint,
            "device": device, "training_job_id": training_job_id, "k": k,
            "idempotency_key": format!("desktop-strategy-{}", uuid::Uuid::new_v4())
        }),
    )
    .await
}

#[tauri::command]
async fn build_approved_feedback_dataset(
    state: tauri::State<'_, SessionState>,
    name: String,
    split_seed: String,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/datasets",
        serde_json::json!({
            "name": name, "split_seed": split_seed, "actor": "desktop-user"
        }),
    )
    .await
}

#[tauri::command]
async fn create_training_preflight(
    state: tauri::State<'_, SessionState>,
    dataset_id: String,
    node_id: String,
    base_model: String,
    dtype: String,
    seed: u32,
    max_length: u32,
    rank: u32,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/training/preflight",
        serde_json::json!({
            "dataset_id": dataset_id, "node_id": node_id, "base_model": base_model,
            "dtype": dtype, "seed": seed, "max_length": max_length,
            "lora_config": {"rank": rank, "alpha": rank * 2, "dropout": 0.0},
            "idempotency_key": format!("desktop-preflight-{}", uuid::Uuid::new_v4())
        }),
    )
    .await
}

#[tauri::command]
async fn create_training_run(
    state: tauri::State<'_, SessionState>,
    dataset_id: String,
    preflight_job_id: String,
    baseline_experiment_id: String,
    objective: String,
    hypothesis: String,
    approved_by: String,
    epochs: f64,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/training/runs",
        serde_json::json!({
            "dataset_id": dataset_id, "preflight_job_id": preflight_job_id,
            "baseline_experiment_id": baseline_experiment_id, "objective": objective,
            "hypothesis": hypothesis, "approved_by": approved_by, "epochs": epochs,
            "idempotency_key": format!("desktop-training-{}", uuid::Uuid::new_v4())
        }),
    )
    .await
}

#[tauri::command]
async fn create_distillation_run(
    state: tauri::State<'_, SessionState>,
    dataset_id: String,
    preflight_job_id: String,
    baseline_experiment_id: String,
    teacher_source: String,
    broker_check_id: Option<String>,
    teacher_broker_endpoint: Option<String>,
    teacher_provider: Option<String>,
    teacher_deployment: Option<String>,
    teacher_model: String,
    teacher_model_fingerprint: Option<String>,
    student_model: String,
    student_model_fingerprint: String,
    teacher_license: String,
    student_license: String,
    teacher_outputs_training_allowed: bool,
    student_finetuning_allowed: bool,
    objective: String,
    hypothesis: String,
    approved_by: String,
    epochs: f64,
    temperature: f64,
    max_new_tokens: u32,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/training/distillation",
        serde_json::json!({
            "dataset_id": dataset_id,
            "preflight_job_id": preflight_job_id,
            "baseline_experiment_id": baseline_experiment_id,
            "teacher_source": teacher_source,
            "broker_check_id": broker_check_id,
            "teacher_broker_endpoint": teacher_broker_endpoint,
            "teacher_target_model": match (teacher_provider, teacher_deployment) {
                (Some(provider), Some(deployment)) => Some(serde_json::json!({
                    "provider": provider,
                    "deployment": deployment,
                    "model": teacher_model.clone()
                })),
                _ => None,
            },
            "teacher_model": teacher_model,
            "teacher_model_fingerprint": teacher_model_fingerprint,
            "student_model": student_model,
            "student_model_fingerprint": student_model_fingerprint,
            "teacher_license": teacher_license,
            "student_license": student_license,
            "teacher_outputs_training_allowed": teacher_outputs_training_allowed,
            "student_finetuning_allowed": student_finetuning_allowed,
            "objective": objective,
            "hypothesis": hypothesis,
            "approved_by": approved_by,
            "epochs": epochs,
            "generation_config": {
                "temperature": temperature,
                "max_new_tokens": max_new_tokens
            },
            "idempotency_key": format!("desktop-distillation-{}", uuid::Uuid::new_v4())
        }),
    )
    .await
}

#[tauri::command]
async fn create_model_export(
    state: tauri::State<'_, SessionState>,
    training_job_id: String,
    node_id: String,
    formats: Vec<String>,
    license_id: String,
    serving_runtime: String,
    llama_cpp_converter: Option<String>,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/exports",
        serde_json::json!({
            "training_job_id": training_job_id, "node_id": node_id,
            "formats": formats, "license_id": license_id,
            "serving": {"runtime": serving_runtime, "local_only": true},
            "llama_cpp_converter": llama_cpp_converter,
            "idempotency_key": format!("desktop-export-{}", uuid::Uuid::new_v4())
        }),
    )
    .await
}

async fn load_app_json(
    state: tauri::State<'_, SessionState>,
    path: &str,
) -> Result<serde_json::Value, String> {
    let session = require_session(state.inner())?;
    let response = reqwest::Client::new()
        .get(format!(
            "{}{}",
            session.endpoint.trim_end_matches('/'),
            path
        ))
        .header("X-App-Token", &session.app_token)
        .send()
        .await
        .map_err(|error| format!("No se pudo conectar con el Coordinator local: {error}"))?;
    if !response.status().is_success() {
        return Err(format!(
            "El Coordinator local respondió con HTTP {}",
            response.status().as_u16()
        ));
    }
    response
        .json::<serde_json::Value>()
        .await
        .map_err(|error| format!("El Coordinator devolvió una respuesta inválida: {error}"))
}

async fn mutate_app_json(
    state: tauri::State<'_, SessionState>,
    method: reqwest::Method,
    path: &str,
    body: serde_json::Value,
) -> Result<serde_json::Value, String> {
    let session = require_session(state.inner())?;
    let response = reqwest::Client::new()
        .request(
            method,
            format!("{}{}", session.endpoint.trim_end_matches('/'), path),
        )
        .header("X-App-Token", &session.app_token)
        .json(&body)
        .send()
        .await
        .map_err(|error| format!("No se pudo conectar con el Coordinator local: {error}"))?;
    if !response.status().is_success() {
        let status = response.status().as_u16();
        let detail = response.text().await.unwrap_or_default();
        return Err(format!(
            "El Coordinator rechazó la operación ({status}): {detail}"
        ));
    }
    response
        .json::<serde_json::Value>()
        .await
        .map_err(|error| format!("El Coordinator devolvió una respuesta inválida: {error}"))
}

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

fn start_coordinator(
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

fn resolve_coordinator_executable(
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
    use super::{failed_session_state, resolve_coordinator_executable};
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
