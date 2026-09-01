# Resumen ejecutivo de modernización

La modernización no debe limitarse a bumps: el mayor retorno está en reducir los tres hotspots monolíticos, establecer CI/observabilidad y hacer reproducibles los entornos Python/ML.

# Diferencias clave vs plan conservador

- Python **3.14.x** en vez de 3.13.
- Vite **8.1+** en vez de 7.
- Node 24 LTS como base estable de producción.
- Refactor explícito de Coordinator y frontend.
- Observabilidad estructurada.
- Tests React/Rust e integración/contratos.
- SBOM, firma/hash de sidecars y política de supply chain.

# Targets recomendados (modernización) y justificación

- Python: **3.14.7+ dentro de 3.14**
- Node: **24 LTS** (no 26 Current para producción conservadora)
- React: 19.2.x
- Vite: **8.1.x+**
- TypeScript: 5.9.x o compatible requerido por toolchain final
- Tauri: último 2.11.x/2.x estable verificado
- Rust: toolchain estable fijado (`rust-toolchain.toml`); evaluar edition 2024
- Python web: últimas releases compatibles tras lock/test
- ML: entornos independientes por capacidad/hardware, locks y fingerprint

# Plan por áreas

## Arquitectura
- `CoordinatorService` → servicios de aplicación por dominio.
- `coordinator/api.py` → routers pequeños.
- `repository.py` → repositorios por agregado.
- `App.tsx` → feature slices (`nodes`, `benchmarks`, `training`, `review`, `exports`).
- Ports/adapters para Broker, Model Drift, vault y Worker transport.

## Observabilidad
- Logging JSON.
- `correlation_id`, `job_id`, `node_id`, `experiment_id`.
- métricas de leases, retries, latencia, fallos de artifact transfer.
- OpenTelemetry opcional/local-first, sin exfiltración por defecto.

## Tests
- contract tests para JSON schemas y API.
- integration Coordinator↔Worker con transporte real loopback.
- Vitest/Testing Library para estados loading/empty/error/retry.
- Rust tests para sidecar lifecycle y command bridge.
- smoke de empaquetado.

## CI
- jobs separados Python/frontend/Rust.
- cache por lock hash.
- reproducibilidad `npm ci`, Cargo `--locked`, Python locked.
- coverage thresholds graduales.
- dependency/secret scan.
- build artifact con SBOM + checksum.

## Dependencias
- Renovate/Dependabot por grupos.
- actualizaciones patch automáticas solo con gates.
- majors en PR separada.

## Infra/release
- sacar binarios generados del source tree cuando sea posible.
- checksums/firma para sidecar.
- release manifest con commit + locks + toolchain versions.

# Touchpoints — PHASE_0

| Ruta/módulo | Cambio | Riesgo | Validación |
|---|---|---|---|
| `pyproject.toml` | Python 3.14 + dev tooling + lock | 12 | full Python suite |
| `apps/desktop/package.json` | Node pin, Vite 8 | 16 | TS/build/smoke |
| `apps/desktop/src/App.tsx` | extraer features | 20 | component/e2e-lite |
| `coordinator/service.py` | split por casos de uso | 20 | integration tests |
| `coordinator/api.py` | routers | 12 | API contract tests |
| `coordinator/repository.py` | repos por agregado | 16 | persistence tests |
| `src-tauri/src/lib.rs` | shared reqwest client + lifecycle | 12 | cargo tests/smoke |
| `model_drift/integration.py` | executable fingerprint/allowlist | 12 | adapter tests |
| `worker/*` | telemetry/backoff policy | 12 | distributed tests |
| `.github/workflows/*` | quality gates | 16 | protected branch |

# PLAN_POR_FASES

## Fase 0 — Fundación
- CI reproducible.
- locks/toolchains.
- linters/types.
- baseline de cobertura.
- logging estructurado.
- contract smoke.

## Fase 1 — Upgrades mayores
- Python 3.14.
- Vite 8.
- Tauri patch/latest 2.x validado.
- resolver deps web/ML.

## Fase 2 — Refactors
- Coordinator modular.
- React feature modules.
- ports/adapters.
- repositories por agregado.
- shared HTTP client.

## Fase 3 — Hardening
- SBOM/checksums/firma.
- executable allowlists.
- resiliencia/backoff.
- métricas/trazas.
- pruebas de dos nodos físicos + AMD/WSL.

# Roadmap

## Quick wins
CI, locks, toolchain pins, shared reqwest client, dependency scanning.

## Medio
Python 3.14/Vite 8, tests frontend/Rust, routers API.

## Largo
Descomposición completa de Coordinator/App, observabilidad, release supply-chain y pruebas multi-nodo reales.

# TAREAS_UPGRADE_MODERNIZACION

## UGM-001 — Plataforma CI multi-stack
- Archivos: nuevo `.github/workflows/*`, manifests.
- Pasos: Python/frontend/Rust, caches por lock, audits.
- Aceptación: PR no mergeable si falla cualquier gate crítico.
- P0; High; Riesgo 20; M.

## UGM-002 — Python 3.14
- Archivos: `pyproject.toml`, scripts, locks.
- Aceptación: todos los tests + sidecar build.
- Dep: UGM-001.
- P1; High; Riesgo 12; M.

## UGM-003 — Vite 8
- Archivos: frontend manifest/config/lock.
- Pasos: migrar 6→7→8 en commits separados; validar Rolldown/plugins.
- Aceptación: build, dev, Tauri smoke.
- P1; High; Riesgo 16; M.

## UGM-004 — Descomponer CoordinatorService
- Archivos: `coordinator/service.py` + nuevos módulos.
- Pasos: extraer por dominio sin cambiar contratos externos.
- Aceptación: API/contract tests invariantes.
- P1; High; Riesgo 20; L.

## UGM-005 — Modularizar App.tsx
- Archivos: `apps/desktop/src/App.tsx` + feature dirs.
- Aceptación: estados y flujos equivalentes con tests.
- P1; High; Riesgo 20; L.

## UGM-006 — Observabilidad
- Archivos: coordinator/worker/adapters.
- Aceptación: logs JSON correlacionables y métricas locales.
- P2; Medium; Riesgo 12; M.

## UGM-007 — Hardening ejecutables
- Archivos: Tauri sidecar + Model Drift adapter + release scripts.
- Aceptación: fingerprint/hash registrado y overrides restringidos en release.
- P2; High; Riesgo 15; M.

## UGM-008 — Suite frontend/Rust
- Archivos: tests nuevos.
- Aceptación: loading/empty/error/retry, lifecycle sidecar y bridge cubiertos.
- P1; Medium; Riesgo 12; M.

# Verificación y checklist post-modernización

- [ ] locks reproducibles
- [ ] Python lint/types/tests/coverage
- [ ] frontend lint/types/unit/build
- [ ] Rust fmt/clippy/test/audit
- [ ] contract tests schemas/API
- [ ] Coordinator↔Worker integration
- [ ] artifact transfer integrity
- [ ] Broker compatibility
- [ ] Model Drift sealed-plan flow
- [ ] vault snapshot/index flow
- [ ] Tauri portable smoke
- [ ] SBOM/checksums
- [ ] rollback documented
- [ ] dos nodos físicos + TLS
- [ ] AMD/WSL gate real

# Supuestos y límites

- No se ejecutaron workloads ni infraestructura real.
- La Fase 0 cubre los touchpoints críticos; para completar el 100% de símbolos, continuar por carpeta/módulo.
- NEXT_PHASE_ASK: elegir el siguiente lote entre `coordinator/`, `worker/`, `training+retrieval/` o `apps/desktop/`.
