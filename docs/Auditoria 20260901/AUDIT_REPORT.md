# Resumen ejecutivo

- Proyecto analizado en **modo proyecto** a partir del ZIP adjunto; análisis por lectura estática, sin asumir ejecución.
- Arquitectura local-first distribuida coherente: Coordinator FastAPI + Worker + escritorio Tauri/React + SQLite + adaptadores a AI Broker, Model Drift y vault.
- El repositorio contiene 72 ficheros Python bajo `src/`, 24 módulos de test y 576 símbolos Python (clases/funciones/métodos) detectables por AST.
- **High / Maintainability:** `src/local_ai_lab/coordinator/service.py` (~84 KB), `apps/desktop/src/App.tsx` (~97 KB), `coordinator/repository.py` (~41 KB) y `coordinator/api.py` (~31 KB) concentran demasiadas responsabilidades y elevan el coste de cambio.
- **High / Testing+Delivery:** no se encontró `.github/workflows`, GitLab CI ni equivalente versionado; el README afirma compilación/pruebas locales, pero el repositorio no impone quality gates reproducibles.
- **Medium / Dependency:** Python usa rangos amplios (`>=,<`) sin lockfile reproducible; frontend y Rust sí tienen `package-lock.json` y `Cargo.lock`.
- **Medium / Obsolescence:** Python declara `>=3.12`; 3.12 sigue con fixes de seguridad hasta octubre de 2028, pero ya no recibe bugfixes regulares ni instaladores binarios nuevos. Conviene elevar el baseline.
- **Medium / Tooling:** Vite 6.4.3 está dos majors por detrás de Vite 8.1 (publicado 2026-06-23).
- **Positive / Security:** el Worker usa timeouts HTTP, idempotency keys, validación SHA-256 y almacenamiento de secreto mediante DPAPI en Windows; no se observó `shell=True`.
- **Positive / Boundary:** la UI React no accede directamente a filesystem/SQLite/secretos; Tauri media contra un Coordinator en loopback con token efímero.

# Mapa del sistema

```text
apps/desktop (React/Vite)
  -> Tauri Rust commands
     -> Coordinator FastAPI (loopback + X-App-Token)
        -> CoordinatorService / repositories / SQLite
        -> AI Broker (compatibilidad/inferencia)
        -> Model Drift CLI (proceso externo)
        -> vault/snapshots/index
        -> jobs distribuidos
           -> Worker HTTP transport/runtime
              -> entrenamiento / retrieval / benchmark / artifacts
```

Clasificación:
- **Código:** `src/local_ai_lab/**`, `apps/desktop/src/**`, `apps/desktop/src-tauri/src/**`
- **Config/build:** `pyproject.toml`, `package.json`, `package-lock.json`, `Cargo.toml`, `Cargo.lock`, `tauri.conf.json`
- **Contratos:** `packages/contracts/schemas/**`
- **Tests:** `tests/test_*.py`
- **Scripts:** `scripts/**`
- **Docs:** `README.md`, `PRODUCT.md`, `DESIGN.md`, `docs/**`
- **Generados/artefactos:** `graphify-out/**`, binario sidecar y artefactos de build.

Entrypoints:
- `local-ai-lab = local_ai_lab.cli:main`
- `local-ai-lab-coordinator = local_ai_lab.coordinator.api:main`
- `local-ai-lab-worker = local_ai_lab.worker.cli:main`
- React: `apps/desktop/src/main.tsx`
- Tauri: `apps/desktop/src-tauri/src/main.rs` / `lib.rs`

# Cómo funciona

El escritorio Tauri inicia el Coordinator empaquetado en `127.0.0.1` usando un puerto efímero y genera un token de sesión. React invoca comandos Tauri; Rust añade `X-App-Token` al hablar con FastAPI. El Coordinator persiste estado en SQLite, ofrece API de aplicación y API versionada de nodo, coordina leases, heartbeats, artefactos y ejecución distribuida. El Worker usa un token de dispositivo, idempotency keys, timeouts y verificación SHA-256. Integraciones externas se encapsulan: AI Broker por HTTP, Model Drift por CLI pública y vault por snapshots/indexado local.

# Hallazgos por fichero

## `pyproject.toml`
### Rol del fichero
Manifest de paquete Python, runtime y dependencias base.

### Hallazgos
| Sev | Tipo | I | P | Riesgo | Evidencia | Recomendación |
|---|---|---:|---:|---:|---|---|
| Medium | Dependency | 3 | 4 | 12 | `fastapi>=0.115,<1`, `pydantic>=2.10,<3`, `uvicorn>=0.34,<1`; no lock Python | Añadir lock reproducible y proceso de actualización |
| Medium | Obsolescence | 3 | 3 | 9 | `requires-python = ">=3.12"` | Conservador: >=3.13; modernización: 3.14.x |
| Low | Testing | 2 | 3 | 6 | solo `pytest` como dev dependency | Añadir coverage, lint, type-check y security/dependency checks |

## `src/local_ai_lab/coordinator/service.py`
### Rol del fichero
Orquestación central de casos de uso.

### Hallazgos
| Sev | Tipo | I | P | Riesgo | Evidencia | Recomendación |
|---|---|---:|---:|---:|---|---|
| High | Architecture | 4 | 4 | 16 | ~84 KB, múltiples dominios/casos de uso | Extraer servicios por bounded context: nodes/jobs, benchmarking, training, retrieval, review, export |
| High | Maintainability | 4 | 4 | 16 | alto radio de cambio | Introducir interfaces/ports y transacciones por caso de uso |

## `src/local_ai_lab/coordinator/api.py`
### Rol del fichero
API FastAPI y modelos de request.

### Hallazgos
| Sev | Tipo | I | P | Riesgo | Evidencia | Recomendación |
|---|---|---:|---:|---:|---|---|
| Medium | Architecture | 3 | 4 | 12 | ~31 KB y numerosos endpoints/modelos en un fichero | Separar routers `app`, `node`, `training`, `retrieval`, `review` |
| Low | Security | 2 | 2 | 4 | CORS limitado a orígenes Tauri y token de app | Mantener allowlist; documentar threat model de loopback |

## `src/local_ai_lab/coordinator/repository.py`
### Rol del fichero
Persistencia y transiciones de jobs.

### Hallazgos
| Sev | Tipo | I | P | Riesgo | Evidencia | Recomendación |
|---|---|---:|---:|---:|---|---|
| Medium | Maintainability | 3 | 4 | 12 | ~41 KB, SQL + state machine | Separar repositorios por agregado |
| Low | Security | 2 | 1 | 2 | SQL dinámico solo usa columna seleccionada por whitelist y placeholders | Mantener whitelist; añadir test de regresión |

## `src/local_ai_lab/storage/sqlite.py`
### Rol del fichero
Conexiones/transacciones SQLite.

### Hallazgos
- `WAL`, `foreign_keys=ON`, `synchronous=FULL` y rollback explícito son decisiones sólidas.
- `BEGIN IMMEDIATE` reduce ciertas carreras pero puede aumentar contención bajo concurrencia; medir antes de cambiar.

## `src/local_ai_lab/worker/http_transport.py`
### Rol del fichero
Cliente Worker→Coordinator.

### Hallazgos
- Positivo: timeout configurable, errores transitorios distinguidos, idempotency keys, autenticación y SHA-256 en descarga.
- Riesgo medio operativo: no hay política explícita de backoff/jitter en esta capa; verificar que runtime la aplique antes de añadirla aquí.

## `src/local_ai_lab/security/secrets.py`
### Rol del fichero
Protección de credenciales del Worker.

### Hallazgos
- Positivo: DPAPI `CRYPTPROTECT_UI_FORBIDDEN` para usuario Windows.
- Limitación deliberada: en no-Windows falla cerrado (`SecretProtectionUnavailable`); el roadmap AMD/WSL necesitará protector equivalente si el Worker debe correr allí.

## `src/local_ai_lab/model_drift/integration.py`
### Rol del fichero
Adaptador a Model Drift CLI.

### Hallazgos
- Positivo: `subprocess.run` recibe lista de argumentos, `shell=False` implícito y timeout.
- Medium: executable/working directory son inputs del flujo de aplicación; existe confirmación humana, pero conviene allowlist/validación de ejecutable y registrar fingerprint del binario.

## `apps/desktop/src/App.tsx`
### Rol del fichero
Superficie React principal.

### Hallazgos
| Sev | Tipo | I | P | Riesgo | Evidencia | Recomendación |
|---|---|---:|---:|---:|---|---|
| High | Maintainability | 4 | 5 | 20 | ~97 KB en un componente/fichero | Extraer feature modules, hooks y state machines |
| Medium | Testing | 3 | 4 | 12 | no se observan tests TS/React en árbol principal | Añadir Vitest + Testing Library para flujos críticos |

## `apps/desktop/src-tauri/src/lib.rs`
### Rol del fichero
Bridge seguro React→Coordinator y lifecycle del sidecar.

### Hallazgos
- Positivo: Coordinator ligado a `127.0.0.1`, token efímero y secreto no expuesto a React.
- Medium / Reliability: se crea un `reqwest::Client::new()` por operación; reutilizar un cliente en estado compartido mejora pooling y configuración homogénea de timeout.
- Medium / Security: el override `LOCAL_AI_LAB_COORDINATOR_EXECUTABLE` permite seleccionar binario externo. Adecuado para desarrollo, pero en producción conviene restringirlo o verificar hash/firma.

## `apps/desktop/package.json`
### Rol del fichero
Toolchain frontend.

### Hallazgos
- React 19.2.7 está en la rama actual.
- Vite 6.4.3 está dos majors por detrás de Vite 8.1.
- No se declara `engines.node`; build reproducible depende del Node instalado.

## `apps/desktop/src-tauri/Cargo.toml`
### Rol del fichero
Dependencias Rust/Tauri.

### Hallazgos
- Tauri 2.x está en familia soportada; frontend API 2.11.1 coincide con la rama 2.11.x.
- Rust usa edición 2021; modernización puede evaluar edition 2024, sin necesidad inmediata.

# Hallazgos transversales

1. **Arquitectura:** dominio razonablemente modular en carpetas, pero Coordinator Service/API y App.tsx son “composition roots” sobredimensionados.
2. **Fiabilidad:** hay buen uso de timeouts, leases, idempotencia, SHA-256 y transacciones; falta convertir esas garantías en tests/gates CI obligatorios.
3. **Seguridad:** no se detectó `shell=True`; CORS es restrictivo; tokens de producción no aparecen hardcodeados. Los tokens encontrados están en tests.
4. **Observabilidad:** existe log de sidecar a fichero, pero no se ve una capa transversal de logging estructurado, correlation IDs, métricas y trazas.
5. **Tests:** 24 módulos Python cubren contratos, worker, retrieval, distillation, feedback, drift, etc.; falta frontend/Rust testing visible y cobertura/gate automatizado.
6. **Dependencias:** locks presentes para npm/Rust, no para Python/ML profiles.
7. **Repositorio:** `graphify-out` y binarios generados aumentan mucho tamaño/ruido; valorar artefactos de release fuera de Git o con política explícita.

# Estándares recomendados

- Ruff + formatter, mypy/pyright, pytest+coverage para Python.
- ESLint + TypeScript strict + Vitest/Testing Library para frontend.
- `cargo fmt`, `cargo clippy`, `cargo test`, `cargo audit` para Rust.
- Conventional/structured logging JSON con `correlation_id`, `job_id`, `node_id`.
- Dependabot/Renovate con ventanas controladas.
- Lock reproducible para Python (`uv.lock` o equivalente).
- PR gates: lint, types, unit, integration-lite, build desktop, dependency audit, secret scanning.
- ADRs para protocolo Worker, seguridad loopback, Model Drift y persistencia.

# Roadmap

## Quick wins
- Añadir CI y baseline de quality gates.
- Añadir lock Python.
- Declarar Node LTS en `.nvmrc`/`.node-version` y `engines`.
- Reusar `reqwest::Client`.
- Excluir/gestionar artefactos generados.

## Medio plazo
- Migrar Vite 6→8.
- Subir Python baseline a 3.13.
- Romper `App.tsx`, `coordinator/service.py` y `coordinator/api.py`.
- Tests React/Rust e integración Coordinator↔Worker.

## Largo plazo
- Python 3.14.
- Observabilidad estructurada.
- Ports/adapters explícitos para Broker/Model Drift/vault.
- Hardening de ejecutables externos, SBOM y firma de releases.

# Tareas para ejecución

- **AUD-001 (P0, High, 20, M):** CI reproducible multi-stack.
- **AUD-002 (P0, High, 16, L):** descomponer CoordinatorService.
- **AUD-003 (P1, High, 20, L):** modularizar `App.tsx`.
- **AUD-004 (P1, Medium, 12, M):** lock Python + política de dependencias.
- **AUD-005 (P1, Medium, 12, S):** Node LTS explícito.
- **AUD-006 (P1, Medium, 9, S):** cliente reqwest compartido + timeout.
- **AUD-007 (P2, Medium, 9, M):** observabilidad transversal.
- **AUD-008 (P2, Medium, 8, M):** hardening ejecutable Model Drift/sidecar.

# Supuestos y límites del análisis

- Análisis por lectura estática; **no se ejecutaron** tests, builds, binarios, GPU, Broker, Model Drift ni vault.
- Se priorizó código fuente y configuración; `graphify-out/**`, binarios y artefactos generados no se auditaron línea a línea.
- La presencia de tests demuestra intención/cobertura nominal, no su estado verde actual.
- El repositorio GitHub consultado muestra la misma estructura principal que el ZIP y 2 commits al 2026-09-01.
