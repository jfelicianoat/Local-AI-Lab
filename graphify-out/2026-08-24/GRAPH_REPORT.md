# Graph Report - Local AI Lab  (2026-08-24)

## Corpus Check
- 176 files · ~152,950 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1919 nodes · 3936 edges · 202 communities (136 shown, 66 thin omitted)
- Extraction: 75% EXTRACTED · 25% INFERRED · 0% AMBIGUOUS · INFERRED: 1002 edges (avg confidence: 0.63)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Contrato AI Broker
- Estrategia y evidencia
- Informes de capacidades
- Verificación de informes
- Pruebas de Broker
- Sondeo no destructivo
- Arquitectura distribuida
- Fronteras externas
- Interfaz de comandos
- Paquete Broker
- Paquete capacidades
- Configuración del proyecto
- properties
- CoordinatorService
- App.tsx
- WorkerRuntime
- ModelDriftIntegration
- JobSpec
- CoordinatorConflict
- ReadOnlyVaultAdapter
- ArtifactStore
- FineTuningProposal
- phase-evidence.v1.schema.json
- StrategyRun
- HttpCoordinatorTransport
- package.json
- ServiceTransport
- manifest.json
- FakeBrokerTransport
- SnapshotVerifier
- _retrievers
- .load
- .run
- FakeBrokerTransport
- KnowledgeIndexBuilder
- CachedEmbeddingProvider
- test_product_workflows.py
- desktop-schema.json
- LeaseGrant
- test_agent_planner.py
- PHASE_10_REPORT.md
- lib.rs
- tauri.conf.json
- .load
- test_contract_schemas.py
- .build
- compilerOptions
- properties
- PHASE_11_REPORT.md
- PHASE_12_REPORT.md
- properties
- properties
- definitions
- definitions
- PHASE_13_REPORT.md
- Local AI Lab — Informe de Fase 0
- PHASE_14_REPORT.md
- PHASE_15_REPORT.md
- PHASE_9_REPORT.md
- properties
- properties
- properties
- install_worker_wsl.sh
- _node_credentials
- Value
- created_at
- FineTuningProposal
- .__init__
- _verifier_and_evidence
- test_vault_read_only.py
- windows-schema.json
- evidence
- main
- test_worker_cli.py
- node-protocol.v1.schema.json
- lease_token
- external_dependencies
- Product
- properties
- permissions
- webviews
- properties
- permissions
- webviews
- Design System — Assay Ledger
- properties
- items
- Local AI Lab — Diseño de Fase A
- jobSpec
- properties
- evidence
- CapabilityRemote
- CapabilityRemote
- compilerOptions
- atlas-decision-new.md
- Local AI Lab — Informe de Fase 1
- 3. Reconocimiento del ecosistema existente
- Local AI Lab
- Fase 2 — Read-only Vault Index
- 5. Coordinator, workers y protocolo
- overview.v1.schema.json
- research-response.v1.schema.json
- workspace.v1.schema.json
- items
- .run
- default.json
- 6. Snapshots del vault y `knowledge_index`
- items
- Fase 3 — Corpus controlado
- 13. Plan de verificación y puertas
- additionalProperties
- Capability
- description
- Fase 8 — Model Drift
- 12. Hardware y deployment
- 2. Alcance y no objetivos
- 4. Arquitectura lógica
- 7. Modelo de dominio y datos
- 9. Benchmarks, métricas y evaluación
- evidence
- Identifier
- Identifier
- tsconfig.json
- 10. Seguridad y privacidad
- 15. Verificación realizada durante la Fase A
- kind
- note_id
- note_path
- created_at
- SURFACE.md
- atlas-roadmap.md
- garden-notes.md
- PHASE_4_REPORT.md
- PHASE_5_REPORT.md
- PHASE_6_REPORT.md
- PHASE_7_REPORT.md
- README.md
- reviews
- __init__.py
- __init__.py
- __init__.py
- __init__.py
- __init__.py
- __init__.py
- __init__.py
- __init__.py
- Estado autoritativo del Coordinator
- Paquete de dataset inmutable
- Knowledge Snapshot
- NodeCapabilities
- Coordinator NVIDIA
- Durabilidad de jobs desconectados
- Transferencia de contexto RAG
- No montar el vault remoto en AMD
- Un único producto distribuido
- Scheduler por capacidades
- Dataset Factory
- Spec definitiva de Local AI Lab
- Fine-tuning condicionado por evidencia
- Evaluación formal mediante Model Drift
- Investigación y síntesis multifuente
- Escalera progresiva de estrategias
- Puerta de Fase 0 cerrada
- Taxonomía declared detected tested benchmarked
- NodeCapabilityReport
- Evidencia detectada del nodo NVIDIA
- Informe de Fase 0
- Frontera de AI Broker
- Arquitectura Coordinator-Worker
- Benchmark dual real y controlado
- Desarrollo gobernado por puertas de evidencia
- Frontera de Knowledge Orchestrator
- SQLite local y CAS de artefactos
- Bridge contractual de Model Drift
- Diseño de Fase A
- Snapshots read-only del vault
- Controles de seguridad y privacidad
- Interfaz común Strategy
- AI Broker como dependencia de solo lectura

## God Nodes (most connected - your core abstractions)
1. `CoordinatorService` - 134 edges
2. `AuthenticationError` - 63 edges
3. `IdempotencyConflict` - 62 edges
4. `CoordinatorConflict` - 52 edges
5. `SnapshotError` - 43 edges
6. `CoordinatorRepository` - 42 edges
7. `LeaseRejected` - 40 edges
8. `utc_timestamp()` - 40 edges
9. `VaultSecurityError` - 39 edges
10. `ReadOnlyVaultAdapter` - 38 edges

## Surprising Connections (you probably didn't know these)
- `test_export_job_requires_tested_conversion_capabilities()` --calls--> `ExportJobPlanner`  [INFERRED]
  tests/test_exporting.py → src/local_ai_lab/exporting/planner.py
- `ConceptEmbedding` --uses--> `ControlledCorpusSuite`  [INFERRED]
  tests/test_retrieval.py → src/local_ai_lab/benchmark/controlled.py
- `test_benchmark_report_preserves_cases_evidence_and_review_state()` --calls--> `RetrievalBenchmarkRunner`  [INFERRED]
  tests/test_retrieval.py → src/local_ai_lab/benchmark/retrieval_runner.py
- `FakeTokenizer` --uses--> `CapabilityFact`  [INFERRED]
  tests/test_training_contracts.py → src/local_ai_lab/capabilities/model.py
- `_report()` --calls--> `CapabilityFact`  [INFERRED]
  tests/test_training_contracts.py → src/local_ai_lab/capabilities/model.py

## Import Cycles
- None detected.

## Communities (202 total, 66 thin omitted)

### Community 0 - "Contrato AI Broker"
Cohesion: 0.11
Nodes (23): Exception, BrokerCheckError, BrokerCompatibilityChecker, BrokerCompatibilityReport, BrokerRequirement, contract_at_least(), normalize_broker_endpoint(), Any (+15 more)

### Community 2 - "Informes de capacidades"
Cohesion: 0.11
Nodes (30): Clock, CommandResult, CapabilityFact, isoformat_utc(), NodeCapabilityReport, ProbeObservation, Any, datetime (+22 more)

### Community 3 - "Verificación de informes"
Cohesion: 0.11
Nodes (18): Connection, FeedbackRepository, FeedbackStateError, Any, Path, ValueError, Path, SentenceTransformerEmbeddingProvider (+10 more)

### Community 4 - "Pruebas de Broker"
Cohesion: 0.08
Nodes (16): CoordinatorRepository, Any, datetime, Path, _requirements_satisfied(), canonical_json(), new_id(), sha256_text() (+8 more)

### Community 5 - "Sondeo no destructivo"
Cohesion: 0.04
Nodes (46): minItems, type, minLength, type, items, minItems, type, properties (+38 more)

### Community 8 - "Interfaz de comandos"
Cohesion: 0.19
Nodes (21): AgentExperimentPlanner, AgentExperimentRequest, BrokerAgentCapabilities, Plans Broker/Athena delegation and deliberately contains no autonomous runtime., _decode_spec(), DisconnectPolicy, IdempotencyClass, JobSpec (+13 more)

### Community 14 - "properties"
Cohesion: 0.04
Nodes (46): additionalProperties, minimum, type, additionalProperties, properties, required, type, format (+38 more)

### Community 15 - "CoordinatorService"
Cohesion: 0.50
Nodes (4): default, description, type, description

### Community 16 - "App.tsx"
Cohesion: 0.07
Nodes (58): buildApprovedFeedbackDataset(), cancelJob(), changeReviewState(), changeTrainingState(), checkBrokerCompatibility(), createBrokerAgentExperiment(), createKnowledgeIndex(), createModelExport() (+50 more)

### Community 17 - "WorkerRuntime"
Cohesion: 0.50
Nodes (4): description, required, type, Capability

### Community 18 - "ModelDriftIntegration"
Cohesion: 0.12
Nodes (19): CommandResult, CommandTransport, ExternalTreatmentRef, FormalEvaluationPlan, ModelDriftCliCapabilities, ModelDriftCompatibilityError, ModelDriftIntegration, Path (+11 more)

### Community 19 - "JobSpec"
Cohesion: 0.18
Nodes (20): BrokerAgentExperimentExecutor, Any, Executes A1/M1 through Broker 2.9 while Local AI Lab owns retrieval tools., ControlledBenchmarkArtifact, RetrievalBenchmarkRunner, KnowledgeIndex, HybridRetriever, LexicalRetriever (+12 more)

### Community 20 - "CoordinatorConflict"
Cohesion: 0.13
Nodes (6): bundled_controlled_suite_root(), Path, run_controlled_lexical_benchmark(), CoordinatorService, Any, Path

### Community 21 - "ReadOnlyVaultAdapter"
Cohesion: 0.16
Nodes (10): RetrievalCandidate, AssembledContext, BaseRetriever, ContextAssembler, ContextBlock, GraphExpansion, _jsonl(), Path (+2 more)

### Community 22 - "ArtifactStore"
Cohesion: 0.20
Nodes (14): ArtifactIntegrityError, ArtifactStore, _copy_and_hash(), _hash_file(), BinaryIO, Path, ValueError, UploadManifest (+6 more)

### Community 23 - "FineTuningProposal"
Cohesion: 0.24
Nodes (43): BaseModel, ArtifactChunkRequest, ArtifactInitiateRequest, BrokerAgentExperimentRequest, BrokerCompatibilityRequest, _call(), CancelRequest, ClaimRequest (+35 more)

### Community 24 - "phase-evidence.v1.schema.json"
Cohesion: 0.08
Nodes (24): additionalProperties, allOf, pattern, type, $id, minLength, type, minLength (+16 more)

### Community 25 - "StrategyRun"
Cohesion: 0.22
Nodes (12): StrategyComparator, StrategyComparison, StrategyRun, Evidence-gated, lexicographic selector; it never emits a probability as certaint, SelectionConstraints, SelectionDecision, StrategySelector, _run() (+4 more)

### Community 26 - "HttpCoordinatorTransport"
Cohesion: 0.06
Nodes (38): Array, c_char, _Blob, platform_secret_protector(), Protocol, RuntimeError, Encrypt secrets for the current Windows user using native DPAPI., SecretProtectionUnavailable (+30 more)

### Community 27 - "package.json"
Cohesion: 0.10
Nodes (20): dependencies, react, react-dom, @tauri-apps/api, devDependencies, @tauri-apps/cli, @types/react, @types/react-dom (+12 more)

### Community 29 - "manifest.json"
Cohesion: 0.05
Nodes (37): minItems, type, properties, required, type, $id, properties, cases (+29 more)

### Community 30 - "FakeBrokerTransport"
Cohesion: 0.27
Nodes (4): Any, Path, ResearchResponseVerifier, VerificationReport

### Community 31 - "SnapshotVerifier"
Cohesion: 0.19
Nodes (8): discover_vaults(), BinaryIO, Path, List direct child directories without opening vault contents., A capability-limited port: enumeration and binary reads are the only operations., Detection only; it never attempts a canary write against the real vault., ReadOnlyVaultAdapter, VaultExclusionPolicy

### Community 32 - "_retrievers"
Cohesion: 0.32
Nodes (12): CachedEmbeddingProvider, Path, _retrievers(), test_benchmark_report_preserves_cases_evidence_and_review_state(), test_context_assembly_is_bounded_deduplicated_and_keeps_evidence(), test_embedding_cache_is_scoped_by_model_and_avoids_recomputation(), test_r1_accepts_natural_questions_and_returns_traceable_chunks(), test_r2_uses_real_provider_contract_and_validates_vectors() (+4 more)

### Community 33 - ".load"
Cohesion: 0.25
Nodes (10): Any, Path, ValueError, RealBenchmarkSuite, RealBenchmarkValidationError, _definition(), Path, test_real_benchmark_pending_review_cannot_close_gate() (+2 more)

### Community 34 - ".run"
Cohesion: 0.20
Nodes (20): Path, registered(), test_api_rejects_unknown_fields(), test_authenticated_artifact_protocol_commits_verified_chunks(), test_claim_filters_jobs_by_tested_capabilities(), test_claim_honors_explicit_node_allowlist(), test_desktop_overview_requires_ephemeral_app_token(), test_desktop_workspace_is_authenticated_and_contains_only_registered_records() (+12 more)

### Community 35 - "FakeBrokerTransport"
Cohesion: 0.11
Nodes (27): BrokerHttpResponse, BrokerInvocation, BrokerInvocationError, BrokerTaskClient, BrokerTaskTransport, Any, Protocol, RuntimeError (+19 more)

### Community 36 - "KnowledgeIndexBuilder"
Cohesion: 0.29
Nodes (4): LexicalHit, Any, Path, _records()

### Community 37 - "CachedEmbeddingProvider"
Cohesion: 0.06
Nodes (44): DatasetError, DatasetFactory, DatasetResult, DatasetVerifier, _jsonl(), Any, Path, RuntimeError (+36 more)

### Community 38 - "test_product_workflows.py"
Cohesion: 0.21
Nodes (14): FastAPI, create_app(), main(), Path, test_controlled_benchmark_desktop_route_requires_session_and_returns_record(), test_controlled_r1_benchmark_runs_and_is_persisted_as_product_evidence(), test_dataset_workflow_consumes_only_explicitly_approved_feedback(), test_export_job_uses_portable_training_artifact_and_tested_worker_capability() (+6 more)

### Community 39 - "desktop-schema.json"
Cohesion: 0.40
Nodes (4): anyOf, description, $schema, title

### Community 40 - "LeaseGrant"
Cohesion: 0.19
Nodes (13): _decode_note(), _digest(), _entry_key(), _jsonl(), _local_root(), Any, Path, Protocol (+5 more)

### Community 41 - "test_agent_planner.py"
Cohesion: 0.27
Nodes (16): KnowledgeIndexBuilder, Creates a disposable local SQLite projection from a verified snapshot., Builds a local immutable snapshot without exposing vault mutation operations., SnapshotBuilder, Path, Un vault real de Windows mezcla UTF-8 con cp1252 heredado.      Decodificarlo to, _records(), _state() (+8 more)

### Community 43 - "lib.rs"
Cohesion: 0.18
Nodes (48): AppHandle, build_approved_feedback_dataset(), cancel_job(), check_broker_compatibility(), CoordinatorProcess, create_broker_agent_experiment(), create_knowledge_index(), create_model_export() (+40 more)

### Community 44 - "tauri.conf.json"
Cohesion: 0.11
Nodes (18): app, security, windows, build, beforeBuildCommand, beforeDevCommand, devUrl, frontendDist (+10 more)

### Community 45 - ".load"
Cohesion: 0.19
Nodes (12): ControlledCorpusSuite, CorpusDocument, Any, Path, ValueError, SuiteValidationError, Path, test_controlled_suite_covers_required_cases_and_is_never_training_data() (+4 more)

### Community 46 - "test_contract_schemas.py"
Cohesion: 0.38
Nodes (5): Path, El schema que se envía al Broker debe exigir lo mismo que verifica el nivel 1., test_overview_matches_canonical_required_shape(), test_runtime_response_schema_matches_the_canonical_contract(), test_workspace_matches_canonical_required_shape()

### Community 47 - ".build"
Cohesion: 0.11
Nodes (32): deterministic_zip(), Path, safe_extract_zip(), _sha(), publish_directory(), Path, Publica un directorio de staging renombrándolo, reintentando el bloqueo de Windo, deterministic_zip() (+24 more)

### Community 48 - "compilerOptions"
Cohesion: 0.11
Nodes (17): compilerOptions, allowJs, allowSyntheticDefaultImports, esModuleInterop, forceConsistentCasingInFileNames, isolatedModules, jsx, lib (+9 more)

### Community 49 - "properties"
Cohesion: 0.11
Nodes (18): $ref, $ref, $ref, $ref, $ref, format, type, properties (+10 more)

### Community 52 - "properties"
Cohesion: 0.13
Nodes (15): type, enum, enum, properties, type, correlation_id, disconnect_policy, idempotency_class (+7 more)

### Community 53 - "properties"
Cohesion: 0.12
Nodes (17): pattern, type, type, properties, artifact_sha256, category, record_id, status (+9 more)

### Community 54 - "definitions"
Cohesion: 0.15
Nodes (13): definitions, Number, PermissionEntry, Target, Value, anyOf, description, anyOf (+5 more)

### Community 55 - "definitions"
Cohesion: 0.15
Nodes (13): definitions, Number, PermissionEntry, Target, Value, anyOf, description, anyOf (+5 more)

### Community 57 - "Local AI Lab — Informe de Fase 0"
Cohesion: 0.17
Nodes (11): 10. Puerta de salida, 1. Resultado, 2. Restricciones respetadas, 3. Contrato implementado, 4. Evidencia del nodo NVIDIA, 5. Observaciones no completadas, 6. Pruebas, 7. Limitaciones (+3 more)

### Community 61 - "properties"
Cohesion: 0.17
Nodes (12): type, format, type, type, properties, type, attempt_id, expires_at (+4 more)

### Community 62 - "properties"
Cohesion: 0.17
Nodes (12): type, type, properties, format, type, type, capabilities_observed, hostname (+4 more)

### Community 63 - "properties"
Cohesion: 0.17
Nodes (12): pattern, type, properties, chunk_id, section, snapshot_id, source_reference, type (+4 more)

### Community 67 - "_node_credentials"
Cohesion: 0.67
Nodes (3): alias, Header, _node_credentials()

### Community 68 - "Value"
Cohesion: 0.36
Nodes (9): chunk_identity(), _chunks(), _frontmatter(), parse_markdown(), ParsedChunk, ParsedLink, ParsedNote, _slug() (+1 more)

### Community 69 - "created_at"
Cohesion: 0.67
Nodes (3): format, type, created_at

### Community 71 - "FineTuningProposal"
Cohesion: 0.44
Nodes (5): TrainingContractReport, FineTuningProposal, Any, TrainingPlanBuilder, HardwareResolution

### Community 72 - ".__init__"
Cohesion: 0.38
Nodes (3): EmbeddingProvider, Path, Protocol

### Community 73 - "_verifier_and_evidence"
Cohesion: 0.67
Nodes (6): Path, test_finding_without_evidence_fails_even_when_shape_is_valid(), test_invented_chunk_and_unsupported_number_are_rejected(), test_missing_information_response_does_not_require_invented_citation(), test_response_with_exact_evidence_and_supported_facts_passes(), _verifier_and_evidence()

### Community 74 - "test_vault_read_only.py"
Cohesion: 0.67
Nodes (6): make_vault(), Path, test_adapter_exposes_only_included_files_and_binary_reads(), test_adapter_rejects_traversal_and_exclusions(), test_selected_vault_must_be_a_direct_child(), test_symlink_is_rejected_when_platform_allows_it()

### Community 75 - "windows-schema.json"
Cohesion: 0.40
Nodes (4): anyOf, description, $schema, title

### Community 76 - "evidence"
Cohesion: 0.50
Nodes (4): $defs, evidence, additionalProperties, required

### Community 77 - "main"
Cohesion: 0.67
Nodes (3): build_parser(), main(), ArgumentParser

### Community 322 - "test_worker_cli.py"
Cohesion: 0.33
Nodes (3): default_executors(), Any, test_default_worker_executors_are_explicit_and_bounded()

### Community 329 - "node-protocol.v1.schema.json"
Cohesion: 0.18
Nodes (10): additionalProperties, $id, oneOf, properties, lease, protocol_version, const, $schema (+2 more)

### Community 330 - "lease_token"
Cohesion: 0.18
Nodes (11): leaseMutation, minimum, type, maxLength, minLength, type, properties, required (+3 more)

### Community 331 - "external_dependencies"
Cohesion: 0.18
Nodes (11): type, additionalProperties, properties, required, type, type, ai_broker, external_dependencies (+3 more)

### Community 332 - "Product"
Cohesion: 0.18
Nodes (10): Accessibility & Inclusion, Capabilities and Constraints, Evidence on Hand, Operating Context, Platform, Positioning, Product, Product Principles (+2 more)

### Community 334 - "properties"
Cohesion: 0.20
Nodes (10): properties, type, default, description, type, identifier, local, remote (+2 more)

### Community 335 - "permissions"
Cohesion: 0.20
Nodes (10): $ref, description, items, type, uniqueItems, description, items, type (+2 more)

### Community 336 - "webviews"
Cohesion: 0.20
Nodes (10): type, webviews, windows, items, description, items, type, description (+2 more)

### Community 337 - "properties"
Cohesion: 0.20
Nodes (10): properties, type, default, description, type, identifier, local, remote (+2 more)

### Community 338 - "permissions"
Cohesion: 0.20
Nodes (10): $ref, description, items, type, uniqueItems, description, items, type (+2 more)

### Community 339 - "webviews"
Cohesion: 0.20
Nodes (10): type, webviews, windows, items, description, items, type, description (+2 more)

### Community 340 - "Design System — Assay Ledger"
Cohesion: 0.20
Nodes (9): Color roles, Components and states, Composition, Design System — Assay Ledger, Direction, Motion, Prohibitions, Scene and mode (+1 more)

### Community 341 - "properties"
Cohesion: 0.20
Nodes (10): type, format, type, type, properties, gate_status, observed_at, phase (+2 more)

### Community 342 - "items"
Cohesion: 0.33
Nodes (6): items, type, additionalProperties, required, type, findings

### Community 344 - "Local AI Lab — Diseño de Fase A"
Cohesion: 0.22
Nodes (8): 11. Observabilidad y auditoría, 14. Riesgos, 16. Tabla de certeza y resolución de pendientes, 17. Recomendación, 18. Decisiones exactas que necesita aprobar el usuario antes de comenzar la Fase 0, 1. Decisión ejecutiva, 8. Interfaz común de estrategias, Local AI Lab — Diseño de Fase A

### Community 345 - "jobSpec"
Cohesion: 0.22
Nodes (9): $defs, jobSpec, leaseGrant, additionalProperties, required, type, additionalProperties, required (+1 more)

### Community 346 - "properties"
Cohesion: 0.22
Nodes (9): type, type, type, properties, answer, contradictions, missing_information, uncertainties (+1 more)

### Community 347 - "evidence"
Cohesion: 0.22
Nodes (9): minLength, type, items, minItems, type, properties, $ref, claim (+1 more)

### Community 351 - "CapabilityRemote"
Cohesion: 0.25
Nodes (8): description, properties, required, type, CapabilityRemote, urls, description, type

### Community 352 - "CapabilityRemote"
Cohesion: 0.25
Nodes (8): description, properties, required, type, CapabilityRemote, urls, description, type

### Community 353 - "compilerOptions"
Cohesion: 0.29
Nodes (6): compilerOptions, composite, module, moduleResolution, skipLibCheck, include

### Community 354 - "atlas-decision-new.md"
Cohesion: 0.29
Nodes (4): Ensayo controlado, Decisión de arquitectura — junio de 2026, Decisión de arquitectura — enero de 2026, Proyecto Atlas

### Community 355 - "Local AI Lab — Informe de Fase 1"
Cohesion: 0.25
Nodes (7): Lo que no se verificó, Local AI Lab — Informe de Fase 1, Resultado, Seguridad y límites, Software implementado, Veredicto y puerta, Verificación ejecutada

### Community 356 - "3. Reconocimiento del ecosistema existente"
Cohesion: 0.25
Nodes (8): 3.1 Evidencia inspeccionada, 3.2 AI Broker: frontera real, 3.3 Knowledge Orchestrator: frontera real, 3.4 Model Drift: frontera real y hueco contractual, 3.5 Athena, 3.6 vaulttrain, 3. Reconocimiento del ecosistema existente, Puerta de compatibilidad por fase

### Community 464 - "Local AI Lab"
Cohesion: 0.05
Nodes (34): 1. Autenticación incorrecta contra el Broker (bloqueante), 2. El error del Broker se descartaba, 3. El schema enviado no era el contrato exigido (bloqueante), 4. El timeout del Broker estaba fijo en 180 s, 5. El emparejamiento documentado no se podía ejecutar, 6. El snapshot corrompía el 80 % del vault (bloqueante), 7. Publicación de snapshot sin reintento, Auditoría funcional contra las instrucciones — 2026-08-24 (+26 more)

### Community 486 - "Fase 2 — Read-only Vault Index"
Cohesion: 0.29
Nodes (6): Artefactos, Controles implementados, Evidencia automatizada, Fase 2 — Read-only Vault Index, Puerta pendiente, Resultado

### Community 487 - "5. Coordinator, workers y protocolo"
Cohesion: 0.29
Nodes (7): 5.1 Responsabilidades del Coordinator, 5.2 Responsabilidades del Worker, 5.3 `NodeCapabilities`, 5.4 Protocolo v1, 5.5 Estados de job, 5.6 Persistencia, 5. Coordinator, workers y protocolo

### Community 488 - "overview.v1.schema.json"
Cohesion: 0.29
Nodes (6): additionalProperties, $id, required, $schema, title, type

### Community 489 - "research-response.v1.schema.json"
Cohesion: 0.29
Nodes (6): additionalProperties, $id, required, $schema, title, type

### Community 490 - "workspace.v1.schema.json"
Cohesion: 0.29
Nodes (6): additionalProperties, $id, required, $schema, title, type

### Community 491 - "items"
Cohesion: 0.29
Nodes (7): $defs, records, additionalProperties, required, type, items, type

### Community 525 - ".run"
Cohesion: 0.24
Nodes (5): Protocol, RetrievalBenchmarkReport, Retriever, evaluate_retrieval(), RetrievalMetrics

### Community 543 - "default.json"
Cohesion: 0.33
Nodes (5): description, identifier, permissions, $schema, windows

### Community 544 - "6. Snapshots del vault y `knowledge_index`"
Cohesion: 0.33
Nodes (6): 6.1 Selección del vault, 6.2 `ReadOnlyVaultAdapter`, 6.3 Algoritmo de snapshot consistente, 6.4 Identidad estable, 6.5 `knowledge_index`, 6. Snapshots del vault y `knowledge_index`

### Community 545 - "items"
Cohesion: 0.33
Nodes (6): additionalProperties, required, type, items, type, nodes

### Community 548 - "Fase 3 — Corpus controlado"
Cohesion: 0.40
Nodes (4): Estado de la puerta, Evidencia automatizada, Fase 3 — Corpus controlado, Resultado

### Community 549 - "13. Plan de verificación y puertas"
Cohesion: 0.40
Nodes (5): 13. Plan de verificación y puertas, Fase 0 — hardware y deployment, Fase 1 — esqueleto distribuido, Fase 2 — vault e índice read-only, Fases 3–8 — retrieval, benchmarks y Model Drift

### Community 550 - "additionalProperties"
Cohesion: 0.40
Nodes (5): minimum, type, additionalProperties, type, job_counts

### Community 552 - "Capability"
Cohesion: 0.50
Nodes (4): description, required, type, Capability

### Community 555 - "description"
Cohesion: 0.50
Nodes (4): default, description, type, description

### Community 556 - "Fase 8 — Model Drift"
Cohesion: 0.50
Nodes (3): Contrato implementado, Estado de la puerta, Fase 8 — Model Drift

### Community 557 - "12. Hardware y deployment"
Cohesion: 0.50
Nodes (4): 12.1 Nodo NVIDIA inspeccionado, 12.2 Nodo AMD, 12.3 Inventario de despliegue, 12. Hardware y deployment

### Community 558 - "2. Alcance y no objetivos"
Cohesion: 0.50
Nodes (4): 2.1 Objetivo del producto, 2.2 No objetivos, 2.3 Invariantes, 2. Alcance y no objetivos

### Community 559 - "4. Arquitectura lógica"
Cohesion: 0.50
Nodes (4): 4.1 Capas, 4.2 Monorepo propuesto para la Fase 1, 4.3 Desktop y sidecar, 4. Arquitectura lógica

### Community 560 - "7. Modelo de dominio y datos"
Cohesion: 0.50
Nodes (4): 7.1 Agregados principales, 7.2 IDs, hashes y tiempo, 7.3 Respuesta de investigación, 7. Modelo de dominio y datos

### Community 561 - "9. Benchmarks, métricas y evaluación"
Cohesion: 0.50
Nodes (4): 9.1 Dos benchmarks separados, 9.2 Familias de métricas, 9.3 Integración Model Drift, 9. Benchmarks, métricas y evaluación

### Community 562 - "evidence"
Cohesion: 0.50
Nodes (4): items, type, $ref, evidence

### Community 627 - "Identifier"
Cohesion: 0.67
Nodes (3): Identifier, description, oneOf

### Community 628 - "Identifier"
Cohesion: 0.67
Nodes (3): Identifier, description, oneOf

### Community 630 - "10. Seguridad y privacidad"
Cohesion: 0.67
Nodes (3): 10.1 Modelo de amenaza mínimo, 10.2 Controles, 10. Seguridad y privacidad

### Community 631 - "15. Verificación realizada durante la Fase A"
Cohesion: 0.67
Nodes (3): 15.1 Comandos y resultados, 15.2 Qué no se verificó, 15. Verificación realizada durante la Fase A

### Community 633 - "kind"
Cohesion: 0.67
Nodes (3): minLength, type, kind

### Community 634 - "note_id"
Cohesion: 0.67
Nodes (3): format, type, note_id

### Community 635 - "note_path"
Cohesion: 0.67
Nodes (3): minLength, type, note_path

### Community 636 - "created_at"
Cohesion: 0.67
Nodes (3): format, type, created_at

## Knowledge Gaps
- **534 isolated node(s):** `name`, `private`, `version`, `type`, `dev` (+529 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **66 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CoordinatorService` connect `CoordinatorConflict` to `Contrato AI Broker`, `Pruebas de Broker`, `Interfaz de comandos`, `ModelDriftIntegration`, `ArtifactStore`, `FineTuningProposal`, `StrategyRun`, `ServiceTransport`, `FakeBrokerTransport`, `SnapshotVerifier`, `.load`, `.run`, `CachedEmbeddingProvider`, `test_product_workflows.py`, `LeaseGrant`, `test_agent_planner.py`, `.load`, `test_contract_schemas.py`, `FineTuningProposal`, `main`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Why does `WorkerRuntime` connect `HttpCoordinatorTransport` to `.run`, `Pruebas de Broker`, `ServiceTransport`?**
  _High betweenness centrality (0.027) - this node is a cross-community bridge._
- **Why does `AuthenticationError` connect `FineTuningProposal` to `Contrato AI Broker`, `.load`, `.run`, `Pruebas de Broker`, `CachedEmbeddingProvider`, `FineTuningProposal`, `Interfaz de comandos`, `test_agent_planner.py`, `LeaseGrant`, `.load`, `ModelDriftIntegration`, `CoordinatorConflict`, `ArtifactStore`, `StrategyRun`, `ServiceTransport`, `FakeBrokerTransport`, `SnapshotVerifier`?**
  _High betweenness centrality (0.023) - this node is a cross-community bridge._
- **Are the 70 inferred relationships involving `CoordinatorService` (e.g. with `main()` and `ArtifactChunkRequest`) actually correct?**
  _`CoordinatorService` has 70 INFERRED edges - model-reasoned connections that need verification._
- **Are the 60 inferred relationships involving `AuthenticationError` (e.g. with `ArtifactChunkRequest` and `ArtifactInitiateRequest`) actually correct?**
  _`AuthenticationError` has 60 INFERRED edges - model-reasoned connections that need verification._
- **Are the 60 inferred relationships involving `IdempotencyConflict` (e.g. with `ArtifactChunkRequest` and `ArtifactInitiateRequest`) actually correct?**
  _`IdempotencyConflict` has 60 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `CoordinatorConflict` (e.g. with `ArtifactChunkRequest` and `ArtifactInitiateRequest`) actually correct?**
  _`CoordinatorConflict` has 41 INFERRED edges - model-reasoned connections that need verification._