//! Los comandos que React puede invocar, y solo esos.
//!
//! Cada uno traduce una accion de la interfaz a una llamada autenticada
//! contra el Coordinator en loopback. React no elige URL ni cabecera.
use crate::sesion::{require_session, SessionState};
use sha2::{Digest, Sha256};
use std::io::Write;
use tauri::Manager;

#[tauri::command]
pub(crate) async fn load_overview(state: tauri::State<'_, SessionState>) -> Result<serde_json::Value, String> {
    load_app_json(state, "/app/v1/overview").await
}

#[tauri::command]
pub(crate) async fn load_storage(state: tauri::State<'_, SessionState>) -> Result<serde_json::Value, String> {
    load_app_json(state, "/app/v1/storage").await
}

#[tauri::command]
pub(crate) async fn plan_storage_cleanup(state: tauri::State<'_, SessionState>, older_than_days: u32) -> Result<serde_json::Value, String> {
    mutate_app_json(state, reqwest::Method::POST, "/app/v1/storage/cleanup/plan",
        serde_json::json!({"older_than_days": older_than_days})).await
}

#[tauri::command]
pub(crate) async fn load_pending_storage_cleanup(state: tauri::State<'_, SessionState>) -> Result<serde_json::Value, String> {
    load_app_json(state, "/app/v1/storage/cleanup/pending").await
}

#[tauri::command]
pub(crate) async fn apply_storage_cleanup(state: tauri::State<'_, SessionState>, plan_id: String) -> Result<serde_json::Value, String> {
    mutate_app_json(state, reqwest::Method::POST, "/app/v1/storage/cleanup/apply",
        serde_json::json!({"plan_id": plan_id, "confirmed": true})).await
}

#[tauri::command]
pub(crate) async fn load_workspace(
    state: tauri::State<'_, SessionState>,
) -> Result<serde_json::Value, String> {
    load_app_json(state, "/app/v1/workspace").await
}

#[tauri::command]
pub(crate) async fn load_workspace_page(
    state: tauri::State<'_, SessionState>, limit: u32,
    groups: Vec<String>, cursors: serde_json::Value,
) -> Result<serde_json::Value, String> {
    mutate_app_json(state, reqwest::Method::POST, "/app/v1/workspace/page",
        serde_json::json!({"limit": limit, "groups": groups, "cursors": cursors})).await
}

fn valid_mission_id(value: &str) -> bool {
    !value.is_empty() && value.len() <= 128 &&
        value.chars().all(|ch| ch.is_ascii_alphanumeric() || ch == '-')
}

#[tauri::command]
pub(crate) async fn load_missions(state: tauri::State<'_, SessionState>) -> Result<serde_json::Value, String> {
    load_app_json(state, "/app/v1/missions").await
}

#[tauri::command]
pub(crate) async fn save_mission(
    state: tauri::State<'_, SessionState>, mission_id: String, strategy: String,
    task: String, success: String, constraints: String,
    teacher_source: Option<String>, teacher_model: Option<String>, student_model: Option<String>,
) -> Result<serde_json::Value, String> {
    if !valid_mission_id(&mission_id) { return Err("Identificador de misión no válido.".into()); }
    mutate_app_json(state, reqwest::Method::PUT, &format!("/app/v1/missions/{mission_id}"),
        serde_json::json!({"strategy": strategy, "task": task, "success": success,
            "constraints": constraints, "teacher_source": teacher_source,
            "teacher_model": teacher_model, "student_model": student_model})).await
}

#[tauri::command]
pub(crate) async fn link_mission_evidence(
    state: tauri::State<'_, SessionState>, mission_id: String, stage_index: u32,
    reference_kind: String, reference_id: String,
) -> Result<serde_json::Value, String> {
    if !valid_mission_id(&mission_id) { return Err("Identificador de misión no válido.".into()); }
    mutate_app_json(state, reqwest::Method::POST, &format!("/app/v1/missions/{mission_id}/links"),
        serde_json::json!({"stage_index": stage_index,
            "reference_kind": reference_kind, "reference_id": reference_id})).await
}

#[tauri::command]
pub(crate) async fn unlink_mission_evidence(
    state: tauri::State<'_, SessionState>, mission_id: String, stage_index: u32,
    reference_kind: String, reference_id: String,
) -> Result<serde_json::Value, String> {
    if !valid_mission_id(&mission_id) { return Err("Identificador de misión no válido.".into()); }
    mutate_app_json(state, reqwest::Method::POST, &format!("/app/v1/missions/{mission_id}/unlink"),
        serde_json::json!({"stage_index": stage_index,
            "reference_kind": reference_kind, "reference_id": reference_id})).await
}

#[tauri::command]
pub(crate) async fn load_reviews(state: tauri::State<'_, SessionState>) -> Result<serde_json::Value, String> {
    load_app_json(state, "/app/v1/reviews").await
}

#[tauri::command]
pub(crate) async fn load_reviews_page(
    state: tauri::State<'_, SessionState>, limit: u32, cursor: serde_json::Value,
) -> Result<serde_json::Value, String> {
    mutate_app_json(state, reqwest::Method::POST, "/app/v1/reviews/page",
        serde_json::json!({"limit": limit, "cursor": cursor})).await
}

#[tauri::command]
pub(crate) async fn preview_manual_example(
    state: tauri::State<'_, SessionState>, snapshot_id: String, index_id: String, query: String,
) -> Result<serde_json::Value, String> {
    mutate_app_json(state, reqwest::Method::POST, "/app/v1/manual-examples/preview",
        serde_json::json!({"snapshot_id": snapshot_id, "index_id": index_id, "query": query})).await
}

#[tauri::command]
pub(crate) async fn create_manual_example(
    state: tauri::State<'_, SessionState>, snapshot_id: String, index_id: String,
    query: String, answer: String, chunk_ids: Vec<String>, reviewer: String,
) -> Result<serde_json::Value, String> {
    mutate_app_json(state, reqwest::Method::POST, "/app/v1/manual-examples",
        serde_json::json!({"snapshot_id": snapshot_id, "index_id": index_id, "query": query,
            "answer": answer, "chunk_ids": chunk_ids, "reviewer": reviewer})).await
}

#[tauri::command]
pub(crate) async fn load_jobs(state: tauri::State<'_, SessionState>) -> Result<serde_json::Value, String> {
    load_app_json(state, "/app/v1/jobs").await
}

#[tauri::command]
pub(crate) async fn load_jobs_page(
    state: tauri::State<'_, SessionState>, limit: u32, cursor: serde_json::Value,
) -> Result<serde_json::Value, String> {
    mutate_app_json(state, reqwest::Method::POST, "/app/v1/jobs/page",
        serde_json::json!({"limit": limit, "cursor": cursor})).await
}

#[tauri::command]
pub(crate) async fn cancel_job(
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
pub(crate) async fn load_training_checkpoints(
    state: tauri::State<'_, SessionState>, job_id: String,
) -> Result<serde_json::Value, String> {
    load_app_json(state, &format!("/app/v1/jobs/{job_id}/checkpoints")).await
}

#[tauri::command]
pub(crate) async fn load_training_restart(
    state: tauri::State<'_, SessionState>, job_id: String,
) -> Result<serde_json::Value, String> {
    load_app_json(state, &format!("/app/v1/jobs/{job_id}/training-restart")).await
}

#[tauri::command]
pub(crate) async fn resume_training_checkpoint(
    state: tauri::State<'_, SessionState>, job_id: String, checkpoint_id: String,
    node_id: String,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state, reqwest::Method::POST,
        &format!("/app/v1/jobs/{job_id}/resume-checkpoint"),
        serde_json::json!({
            "checkpoint_id": checkpoint_id.clone(),
            "node_id": node_id.clone(),
            "idempotency_key": format!("desktop-resume-{checkpoint_id}-{node_id}"),
        }),
    ).await
}

#[tauri::command]
pub(crate) async fn restart_training_job(
    state: tauri::State<'_, SessionState>, job_id: String, node_id: String,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state, reqwest::Method::POST,
        &format!("/app/v1/jobs/{job_id}/restart-training"),
        serde_json::json!({
            "node_id": node_id.clone(),
            "idempotency_key": format!("desktop-restart-{job_id}-{node_id}"),
        }),
    ).await
}

#[tauri::command]
pub(crate) async fn revoke_node(
    state: tauri::State<'_, SessionState>,
    node_id: String,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        &format!("/app/v1/nodes/{node_id}/revoke"),
        serde_json::json!({}),
    )
    .await
}

#[tauri::command]
pub(crate) async fn save_product_artifact(
    app: tauri::AppHandle,
    state: tauri::State<'_, SessionState>,
    record_id: String,
) -> Result<String, String> {
    if record_id.is_empty() || !record_id.chars().all(|ch| ch.is_ascii_alphanumeric() || ch == '-') {
        return Err("El identificador del resultado no es válido.".into());
    }
    let session = require_session(state.inner())?;
    let downloads = app.path().download_dir()
        .map_err(|error| format!("No se encontró la carpeta Descargas: {error}"))?
        .join("Local AI Lab");
    std::fs::create_dir_all(&downloads)
        .map_err(|error| format!("No se pudo preparar Descargas: {error}"))?;
    let client = reqwest::Client::builder()
        .connect_timeout(std::time::Duration::from_secs(5))
        .timeout(std::time::Duration::from_secs(600))
        .build()
        .map_err(|error| format!("No se pudo preparar la descarga: {error}"))?;
    let mut response = client.get(format!(
        "{}/app/v1/records/{record_id}/artifact", session.endpoint.trim_end_matches('/')
    ))
    .header("X-App-Token", &session.app_token)
    .send().await
    .map_err(|error| format!("No se pudo descargar el resultado: {error}"))?;
    if !response.status().is_success() {
        return Err(format!("El Coordinator rechazó la descarga (HTTP {}).", response.status().as_u16()));
    }
    let expected = response.headers().get("x-artifact-sha256")
        .and_then(|value| value.to_str().ok()).unwrap_or("").to_string();
    if expected.len() != 64 || !expected.chars().all(|ch| ch.is_ascii_hexdigit()) {
        return Err("El resultado no incluye un hash verificable.".into());
    }
    let extension = if response.headers().get(reqwest::header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok()).unwrap_or("").starts_with("application/json") {
        "json"
    } else { "zip" };
    let filename = format!("resultado-{record_id}.{extension}");
    let mut destination = downloads.join(&filename);
    if destination.exists() {
        destination = downloads.join(format!("resultado-{record_id}-{}.{extension}", uuid::Uuid::new_v4()));
    }
    let temporary = downloads.join(format!(".{filename}.{}.partial", uuid::Uuid::new_v4()));
    let operation: Result<String, String> = async {
        let mut output = std::fs::OpenOptions::new().write(true).create_new(true)
            .open(&temporary).map_err(|error| format!("No se pudo guardar el resultado: {error}"))?;
        let mut digest = Sha256::new();
        while let Some(chunk) = response.chunk().await
            .map_err(|error| format!("Descarga interrumpida: {error}"))? {
            output.write_all(&chunk).map_err(|error| format!("No se pudo escribir el resultado: {error}"))?;
            digest.update(&chunk);
        }
        output.sync_all().map_err(|error| format!("No se pudo confirmar el archivo: {error}"))?;
        if format!("{:x}", digest.finalize()) != expected {
            return Err("El resultado descargado no coincide con su SHA-256.".into());
        }
        drop(output);
        std::fs::rename(&temporary, &destination)
            .map_err(|error| format!("No se pudo terminar de guardar el resultado: {error}"))?;
        Ok(destination.display().to_string())
    }.await;
    if operation.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    operation
}

#[tauri::command]
pub(crate) async fn save_review_correction(
    state: tauri::State<'_, SessionState>,
    review_id: String,
    corrected_response: serde_json::Value,
    expected_revision: u64,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::PUT,
        &format!("/app/v1/reviews/{review_id}/correction"),
        serde_json::json!({"actor": "desktop-user", "corrected_response": corrected_response, "expected_revision": expected_revision}),
    )
    .await
}

#[tauri::command]
pub(crate) async fn transition_review(
    state: tauri::State<'_, SessionState>,
    review_id: String,
    to_state: String,
    reason: Option<String>,
    expected_revision: u64,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        &format!("/app/v1/reviews/{review_id}/state"),
        serde_json::json!({"actor": "desktop-user", "to_state": to_state, "reason": reason, "expected_revision": expected_revision}),
    )
    .await
}

#[tauri::command]
pub(crate) async fn transition_training_candidate(
    state: tauri::State<'_, SessionState>,
    review_id: String,
    to_state: String,
    expected_revision: u64,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        &format!("/app/v1/reviews/{review_id}/training-state"),
        serde_json::json!({"actor": "desktop-user", "to_state": to_state, "expected_revision": expected_revision}),
    )
    .await
}

#[tauri::command]
pub(crate) async fn discover_vaults(
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
pub(crate) async fn create_vault_snapshot(
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
pub(crate) async fn create_knowledge_index(
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
pub(crate) async fn run_controlled_retrieval_benchmark(
    state: tauri::State<'_, SessionState>,
    k: u16,
    benchmark_id: Option<String>,
    snapshot_id: Option<String>,
    index_id: Option<String>,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/benchmarks/controlled/retrieval",
        serde_json::json!({"k": k, "benchmark_id": benchmark_id,
            "snapshot_id": snapshot_id, "index_id": index_id}),
    )
    .await
}

#[tauri::command]
pub(crate) async fn create_semantic_retrieval_benchmark(
    state: tauri::State<'_, SessionState>,
    strategy_id: String,
    node_id: String,
    embedding_model: String,
    embedding_model_fingerprint: String,
    device: String,
    k: u16,
    benchmark_id: Option<String>,
    snapshot_id: Option<String>,
    index_id: Option<String>,
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
            "benchmark_id": benchmark_id, "snapshot_id": snapshot_id, "index_id": index_id,
            "idempotency_key": format!("desktop-semantic-{}", uuid::Uuid::new_v4())
        }),
    )
    .await
}

#[tauri::command]
pub(crate) async fn register_real_benchmark(
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
pub(crate) async fn run_model_drift_comparison(
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
pub(crate) async fn check_broker_compatibility(
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
pub(crate) async fn select_strategy(
    state: tauri::State<'_, SessionState>,
    experiment_ids: Vec<String>,
    privacy: Option<String>,
    max_latency_ms: Option<f64>,
    max_cost: Option<String>,
    minimum_cases: u32,
    require_formal_verdict: bool,
    quality_metric: String,
    minimum_quality: f64,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/strategy-selection",
        serde_json::json!({
            "experiment_ids": experiment_ids, "privacy": privacy,
            "max_latency_ms": max_latency_ms, "max_cost": max_cost,
            "minimum_cases": minimum_cases,
            "require_formal_verdict": require_formal_verdict,
            "quality_metric": quality_metric,
            "minimum_quality": minimum_quality
        }),
    )
    .await
}

#[tauri::command]
pub(crate) async fn create_broker_agent_experiment(
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
    benchmark_id: Option<String>,
    snapshot_id: Option<String>,
    index_id: Option<String>,
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
            "benchmark_id": benchmark_id, "snapshot_id": snapshot_id, "index_id": index_id,
            "idempotency_key": format!("desktop-agent-{}", uuid::Uuid::new_v4())
        }),
    )
    .await
}

#[tauri::command]
pub(crate) async fn create_strategy_run(
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
    benchmark_id: Option<String>,
    snapshot_id: Option<String>,
    index_id: Option<String>,
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
            "benchmark_id": benchmark_id, "snapshot_id": snapshot_id, "index_id": index_id,
            "idempotency_key": format!("desktop-strategy-{}", uuid::Uuid::new_v4())
        }),
    )
    .await
}

#[tauri::command]
pub(crate) async fn build_approved_feedback_dataset(
    state: tauri::State<'_, SessionState>,
    name: String,
    split_seed: String,
    source_snapshot_id: String,
) -> Result<serde_json::Value, String> {
    mutate_app_json(
        state,
        reqwest::Method::POST,
        "/app/v1/datasets",
        serde_json::json!({
            "name": name, "split_seed": split_seed, "actor": "desktop-user",
            "source_snapshot_id": source_snapshot_id
        }),
    )
    .await
}

#[tauri::command]
pub(crate) async fn create_training_preflight(
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
pub(crate) async fn create_training_run(
    state: tauri::State<'_, SessionState>,
    dataset_id: String,
    preflight_job_id: String,
    baseline_experiment_id: String,
    objective: String,
    hypothesis: String,
    contains_mutable_facts: bool,
    minimum_quality_gain: f64,
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
            "hypothesis": hypothesis, "contains_mutable_facts": contains_mutable_facts,
            "minimum_quality_gain": minimum_quality_gain,
            "approved_by": approved_by, "epochs": epochs,
            "idempotency_key": format!("desktop-training-{}", uuid::Uuid::new_v4())
        }),
    )
    .await
}

#[tauri::command]
pub(crate) async fn create_distillation_run(
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
    contains_mutable_facts: bool,
    minimum_quality_gain: f64,
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
            "contains_mutable_facts": contains_mutable_facts,
            "minimum_quality_gain": minimum_quality_gain,
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
pub(crate) async fn create_model_export(
    state: tauri::State<'_, SessionState>,
    training_job_id: String,
    node_id: String,
    formats: Vec<String>,
    license_id: String,
    serving_runtime: String,
    llama_cpp_converter: Option<String>,
    verification_only: Option<bool>,
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
            "verification_only": verification_only.unwrap_or(false),
            "idempotency_key": format!("desktop-export-{}", uuid::Uuid::new_v4())
        }),
    )
    .await
}

pub(crate) async fn load_app_json(
    state: tauri::State<'_, SessionState>,
    path: &str,
) -> Result<serde_json::Value, String> {
    let session = require_session(state.inner())?;
    let client = reqwest::Client::builder()
        .connect_timeout(std::time::Duration::from_secs(5))
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .map_err(|error| format!("No se pudo preparar la conexión local: {error}"))?;
    let response = client
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

pub(crate) async fn mutate_app_json(
    state: tauri::State<'_, SessionState>,
    method: reqwest::Method,
    path: &str,
    body: serde_json::Value,
) -> Result<serde_json::Value, String> {
    let session = require_session(state.inner())?;
    let client = reqwest::Client::builder()
        .connect_timeout(std::time::Duration::from_secs(5))
        .timeout(std::time::Duration::from_secs(600))
        .build()
        .map_err(|error| format!("No se pudo preparar la conexión local: {error}"))?;
    let response = client
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
