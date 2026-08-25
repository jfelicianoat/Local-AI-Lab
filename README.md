# Local AI Lab

Laboratorio local y distribuido para comparar estrategias de IA sobre conocimiento privado.

## Manual de uso

El recorrido completo de la aplicación, con preparación, todos los casos de uso paso a paso,
estados, resolución de incidencias y listas de comprobación, está en
[`docs/MANUAL_DE_USO.md`](docs/MANUAL_DE_USO.md).

## Estado

- Fases A–15: superficie de código y contratos implementada.
- Verificación local: la cifra actual se registra en `docs/IMPLEMENTATION_STATUS.md`; Python,
  TypeScript, React/Vite y Rust compilan correctamente.
- Auditoría del 2026-08-24 contra Broker, vault y Model Drift reales, con seis defectos
  corregidos: [`docs/AUDIT_20260824.md`](docs/AUDIT_20260824.md).
- Binario Coordinator regenerado y probado con `--help`; ejecutable Tauri de producción
  generado en `apps/desktop/src-tauri/target/release/local-ai-lab-desktop.exe`.
- Puertas reales pendientes: dos nodos físicos, un alumno causal local y una ejecución
  profesor→alumno sobre hardware aprobado. El profesor puede servirse desde AI Broker. AI Broker,
  el vault real y el puente formal de Model Drift ya fueron comprobados sin modificar sus datos
  internos.
- Los instaladores MSI/NSIS requieren que WiX/NSIS estén disponibles localmente. Tauri intentó
  descargarlos, pero la red está deshabilitada en este entorno; el ejecutable portable sí está listo.

La comprobación real de Fase 8 puede repetirse sin guardar credenciales:

```powershell
$env:LOCAL_AI_LAB_BROKER_TOKEN = Read-Host "Token de AI Broker"
.\scripts\verify_phase8_real.ps1 -Plan "ruta\al\plan.json" -Report "ruta\al\informe.html"
Remove-Item Env:\LOCAL_AI_LAB_BROKER_TOKEN
```

El detalle que distingue código implementado de evidencia real está en
[`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).

## Detector de capacidades

No instala software ni ejecuta cargas ML. Solo usa una allowlist de consultas de lectura y
clasifica sus resultados como evidencia `detected`.

```powershell
$env:PYTHONPATH = "src"
python -m local_ai_lab.cli probe-node `
  --data-root "." `
  --output "artifacts/phase0/node-report.json"

python -m local_ai_lab.cli verify-report `
  "artifacts/phase0/node-report.json"
```

## Compatibilidad de AI Broker

El negociador solo puede hacer `GET /health` y `GET /api/v1/capabilities`. No expone una
operación POST, no lee la base de datos del Broker y no guarda credenciales en el informe.
Los campos futuros del contrato se toleran. Los errores de red o autenticación producen
estado `unknown`, no una recomendación falsa de actualización.

Probado el 2026-08-24 contra el servicio real: contrato 2.9 satisfecho en los cuatro
conjuntos de requisitos. El token se pasa mediante una variable de entorno, nunca como
argumento:

```powershell
$env:PYTHONPATH = "src"
$env:LOCAL_AI_LAB_BROKER_TOKEN = "<token>"
python -m local_ai_lab.cli check-broker `
  --endpoint "http://127.0.0.1:8765" `
  --phase phase0 `
  --token-env LOCAL_AI_LAB_BROKER_TOKEN `
  --output "artifacts/phase0/broker-observed.json"
```

Conjuntos de requisitos disponibles: `phase0`, `retrieval`, `formal_evaluation` y
`agent_experiments`. La ejecución formal y A1/M1 requieren el contrato 2.9. Si el servicio
desplegado no lo satisface, la UI devolverá `UPGRADE_REQUIRED` antes de enviar un experimento.

Las tareas de inferencia se autentican con la misma cabecera `X-Admin-Token` que la
negociación de capacidades.

## Pruebas

```powershell
python -m pytest -q
```

## Worker distribuido

Para dar de alta un Worker, el Coordinator acuña un código de un solo uso:

```powershell
$env:PYTHONPATH = "src"
python -m local_ai_lab.cli pair-code `
  --database ".local/coordinator/state.db" `
  --valid-seconds 300
```

El Worker es el mismo producto en ambos nodos. Incluye emparejamiento de un solo uso,
credencial protegida, heartbeat, capacidades, leases, cancelación, journal/outbox offline y
transferencia autenticada de artefactos por bloques con verificación SHA-256. Consulta
[`docs/WORKER_DEPLOYMENT.md`](docs/WORKER_DEPLOYMENT.md).

## Escritorio

La aplicación Tauri/React está en `apps/desktop`. El shell Rust inicia el Coordinator
empaquetado en loopback con un token efímero que nunca entrega a React. El build de Tauri usa
directamente las dependencias locales de `node_modules`, sin pedir a pnpm una reinstalación.

El sidecar se regenera con:

```powershell
.\scripts\build_sidecar.ps1
```

El ejecutable portable completo se reproduce sin red con:

```powershell
.\scripts\build_desktop.ps1 -Target Portable
```

Cuando WiX/NSIS estén disponibles localmente puede usarse `-Target Msi`, `-Target Nsis` o
`-Target All`.

El arranque del portable, incluido el sidecar y la base de datos local, se verifica con:

```powershell
.\scripts\smoke_desktop.ps1
```

La evidencia de una puerta se registra solo desde un artefacto existente, cuyo SHA-256 se
calcula antes de guardar el estado:

```powershell
$env:PYTHONPATH = "src"
python -m local_ai_lab.cli record-evidence `
  --database ".local/coordinator/state.db" `
  --id "phase1.core" `
  --label "Núcleo distribuido" `
  --status tested `
  --artifact "docs/PHASE_1_REPORT.md"
```

AI Broker es una dependencia externa de solo lectura. Local AI Lab no modifica su
repositorio, configuración, entorno ni persistencia.

## Comparación formal con Model Drift

R2/R3/R4 necesitan embeddings locales. El perfil vive en `requirements/retrieval.txt` y se
instala en su propio entorno para no contaminar el del Coordinator:

```powershell
python -m venv .venv-retrieval
.\.venv-retrieval\Scripts\pip install -r requirements\retrieval.txt
```

El modelo de embeddings debe estar ya en la caché local: el proveedor abre con
`local_files_only=True` y no descarga nada.

La comparación formal la ejecuta Model Drift; Local AI Lab solo sella el plan y entrega los
artefactos. Requiere confirmación humana explícita:

```powershell
curl -X POST http://127.0.0.1:<puerto>/app/v1/model-drift/comparisons `
  -H "X-App-Token: <token>" -H "Content-Type: application/json" `
  -d '{"r3_experiment_id":"...","r4_experiment_id":"...",
       "executable":"D:\\...\\Model_Drift\\.venv\\Scripts\\model-drift.exe",
       "working_directory":"D:\\...\\Model_Drift","confirmed":true}'
```

Model Drift rechaza el tratamiento si el plan fue manipulado tras sellarlo, si un artefacto no
coincide con su SHA-256, si R3/R4 vienen en otro orden o si los dos experimentos no comparten
suite y snapshot. Local AI Lab conserva sus propias métricas de retrieval por separado y nunca
lee la persistencia de Model Drift.

## Snapshot e índice del vault

Estos comandos solo exponen lectura del vault y escriben los artefactos en una carpeta local
separada. No se han ejecutado contra el vault real de esta máquina.

```powershell
$env:PYTHONPATH = "src"
python -m local_ai_lab.cli snapshot-vault `
  --allowed-root "Y:\Mi unidad\Vaults" `
  --vault "Y:\Mi unidad\Vaults\<vault>" `
  --output-root ".local\snapshots"

python -m local_ai_lab.cli build-index `
  --snapshot ".local\snapshots\vault_snapshot_<id>" `
  --database ".local\indexes\knowledge_<id>.sqlite3"
```

Un snapshot que no converge se conserva como `INCOMPLETE` y no puede alimentar un índice
presentado como completo. El detalle y la evidencia automatizada están en
`docs/PHASE_2_REPORT.md`.
