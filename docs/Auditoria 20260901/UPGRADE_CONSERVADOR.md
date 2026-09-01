# Resumen ejecutivo de actualización (conservador)

Objetivo: recuperar reproducibilidad y soporte activo con mínimo cambio arquitectónico.

- Mantener React 19.2.x y Tauri 2.11.x.
- Mantener FastAPI/Pydantic/Uvicorn dentro de sus majors actuales.
- Elevar Python de baseline 3.12 a **3.13**.
- Migrar Vite **6 → 7** como paso conservador, no directamente a 8.
- Fijar Node **24 LTS** para builds.
- Introducir lock Python y CI antes de upgrades.
- No reestructurar módulos grandes salvo cambios imprescindibles.

# Fuentes de versiones (FUENTES_DE_VERSION)

| Componente | Detectado | Fuente | Confianza | Comentario |
|---|---|---|---|---|
| Python | `>=3.12` | `pyproject.toml` | Alta | rango, no versión exacta |
| FastAPI | `>=0.115,<1` | `pyproject.toml` | Alta | sin lock |
| Pydantic | `>=2.10,<3` | `pyproject.toml` | Alta | sin lock |
| Uvicorn | `>=0.34,<1` | `pyproject.toml` | Alta | sin lock |
| pytest | `>=8.3,<9` | `pyproject.toml` | Alta | solo dev |
| React | `19.2.7` | `apps/desktop/package.json` | Alta | pin exacto |
| React DOM | `19.2.7` | `apps/desktop/package.json` | Alta | pin exacto |
| Vite | `6.4.3` | `apps/desktop/package.json` | Alta | 2 majors detrás de actual |
| TypeScript | `5.9.3` | `apps/desktop/package.json` | Alta | pin exacto |
| Tauri JS API | `2.11.1` | `apps/desktop/package.json` | Alta | actual 2.11.x |
| Tauri CLI | `2.11.4` | `apps/desktop/package.json` | Alta | actual 2.11.x |
| Tauri Rust | `2` | `Cargo.toml` | Media | semver amplio, Cargo.lock resuelve |
| reqwest | `0.12` | `Cargo.toml` | Alta | rustls |
| torch | `>=2.7,<3` | requirements | Alta | ML profile sin lock |
| transformers | `>=4.53,<5` | requirements | Alta | sin lock |
| sentence-transformers | `>=5,<6` | requirements | Alta | retrieval |

# Referencias (EOL/soporte/CVEs/breaking changes) con fecha consultada

Fecha consultada: **2026-09-01**.

- Python 3.12: etapa “security fixes only”, hasta octubre de 2028; ya no recibe bugfixes regulares ni instaladores binarios nuevos. Fuente oficial: https://www.python.org/downloads/release/python-31213/
- Python 3.14.7 es la feature release actual consultada. Fuente oficial: https://www.python.org/downloads/release/python-3147/
- Node 24.20.0 figura como LTS y Node 26.8.1 como Current. Fuente oficial: https://nodejs.org/en/blog/release
- Node 20 figura EOL; 22 y 24 están LTS. Fuente oficial: https://nodejs.org/en/about/previous-releases
- React docs: última línea 19.2; 19.2.7 publicada en junio 2026. Fuente oficial: https://react.dev/versions
- Vite 8.1 publicado 2026-06-23; Vite 8 reemplaza esbuild/Rollup por Rolldown. Fuentes oficiales: https://vite.dev/blog/announcing-vite8-1 y https://vite.dev/blog/announcing-vite8
- Tauri 2.11.5 publicado 2026-07-01; 2.11.1 incluyó fixes de seguridad en ACL/orígenes remotos. Fuente oficial: https://tauri.app/release/tauri/all-versions/

No se asignan CVEs concretos a dependencias del proyecto porque no se ejecutó un resolver/audit sobre los locks y no se debe inferir vulnerabilidad solo por versión declarada.

# Matriz de obsolescencia (MATRIZ_DE_OBSOLESCENCIA)

| Área | Estado | Evidencia | Consecuencia | Acción |
|---|---|---|---|---|
| Python 3.12 | Riesgo | security-only | menos fixes/instaladores | baseline 3.13 |
| FastAPI/Pydantic/Uvicorn | Desconocido | rangos amplios sin lock | build variable | lock + resolver |
| React 19.2.7 | OK | oficial 19.2 | bajo | mantener |
| Vite 6.4.3 | Obsoleto por criterio C | 2 majors detrás + Vite 8 actual | compat/tooling | 6→7 conservador |
| Tauri 2.11.x | OK/Riesgo bajo | familia actual | patches perdidos | alinear al último 2.11.x |
| Node | Desconocido | no declarado | builds no reproducibles | Node 24 LTS |
| ML deps | Riesgo | rangos sin lock | incompat GPU/ABI | locks por perfil |
| CI | Obsoleto operativo | ausente | sin gates | crear workflow |

# Targets recomendados (mínimo viable) y justificación

- Python: **3.13.x**
- Node: **24 LTS**
- React: **19.2.7** (sin cambio)
- Vite: **7.x** primero
- TypeScript: **5.9.x**
- Tauri JS/Rust/CLI: último **2.11.x** compatible
- Python web stack: resolver a últimas versiones compatibles dentro de majors declarados y congelarlas.
- ML: mantener majors actuales, generar lock por hardware/perfil.

# Plan de cambios por área

## Runtime
1. CI dual temporal 3.12 + 3.13.
2. Corregir incompatibilidades.
3. Cambiar `requires-python` a `>=3.13`.
4. Retirar 3.12 cuando todo quede verde.

## Dependencias
- Añadir `uv.lock`/equivalente.
- Resolver web stack y ML profiles por separado.
- npm: `npm ci` obligatorio.
- Cargo: `--locked`.

## Toolchain
- Node 24 LTS explícito.
- Vite 6→7 siguiendo guía de migración.
- Mantener React y TypeScript.

## Config
- Preservar CORS restrictivo.
- Mantener secretos fuera de args.
- Documentar overrides de ejecutables como desarrollo.

## CI
- Python lint/type/test.
- npm ci + tsc + vite build.
- cargo fmt/clippy/test.
- secret scan + dependency audit.

# Touchpoints de cambio (TOUCHPOINTS_DE_CAMBIO)

| Ruta | Símbolo/área | Cambio | Riesgo | Test |
|---|---|---|---|---|
| `pyproject.toml` | runtime/deps | Python >=3.13 + lock tooling | 9 Medium | pytest |
| `requirements/*.txt` | ML profiles | resolver/lock | 12 Medium | training/retrieval smoke |
| `apps/desktop/package.json` | toolchain | engines Node + Vite 7 | 12 Medium | npm build |
| `package-lock.json` | lock | regenerar con Node 24 | 9 Medium | npm ci |
| `vite.config.ts` | Vite | migración 7 | 9 Medium | dev/build |
| `src-tauri/Cargo.toml` | Tauri | patch alignment | 6 Low | cargo test/build |
| `src-tauri/Cargo.lock` | lock | update controlado | 6 Low | cargo --locked |
| `.github/workflows/*` | nuevo | quality gates | 8 Medium | workflow |
| `scripts/build_desktop.ps1` | build | usar versiones fijadas | 8 Medium | portable build |
| `scripts/build_sidecar.ps1` | build | Python lock/runtime | 8 Medium | sidecar --help |

# Roadmap

## Quick wins
CI, Node pin, Python lock, dependency audits.

## Medio
Python 3.13 + Vite 7 + Tauri patches.

## Largo
Revisar 3.14/Vite 8 como modernización separada.

# TAREAS_UPGRADE_CONSERVADOR

## UGC-001 — Baseline reproducible
- Archivos: `pyproject.toml`, nuevo lock, `.github/workflows/*`
- Pasos: fijar Python/Node; instalar locked; ejecutar gates.
- Aceptación: checkout limpio produce mismas dependencias.
- Prioridad: P0; Severidad High; Riesgo 16; Esfuerzo M.

## UGC-002 — Python 3.13
- Archivos: `pyproject.toml`, scripts.
- Pasos: matriz 3.12/3.13, corregir, elevar baseline.
- Aceptación: test suite y sidecar build en 3.13.
- Dependencia: UGC-001.
- P1; Medium; Riesgo 9; M.

## UGC-003 — Vite 7
- Archivos: `package.json`, lock, Vite config.
- Pasos: upgrade major único; resolver deprecations.
- Aceptación: `tsc -b` + build + smoke desktop.
- P1; Medium; Riesgo 12; M.

## UGC-004 — Tauri 2.11.x patch
- Archivos: package/Cargo manifests+locks.
- Aceptación: frontend API/CLI/Rust alineados y build portable.
- P1; Medium; Riesgo 8; S.

## UGC-005 — Locks ML por perfil
- Archivos: `requirements/*`, locks nuevos.
- Aceptación: perfiles NVIDIA/retrieval reproducibles y AMD no especulativo.
- P1; High; Riesgo 12; M.

# Verificación y checklist post-upgrade

- [ ] install limpio y locked
- [ ] pytest
- [ ] lint/type check
- [ ] TypeScript build
- [ ] Rust fmt/clippy/test
- [ ] sidecar `--help`
- [ ] desktop portable smoke
- [ ] Coordinator↔Worker smoke
- [ ] secret scan
- [ ] dependency audit
- [ ] Broker/vault/Model Drift contract smoke en entorno autorizado

# Supuestos y límites

No se ejecutó build/test; targets se basan en manifiestos y fuentes oficiales consultadas 2026-09-01.
