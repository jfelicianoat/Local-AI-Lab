# Estado de implementación

Fecha de corte: 2026-08-25.

Este documento separa deliberadamente **implementado**, **probado localmente** y **pendiente
de prueba real**. Ninguna capacidad de hardware o integración externa se presenta como
verificada solo por existir código o documentación.

## Resumen por fase

| Fase | Implementación disponible | Evidencia actual | Puerta |
|---|---|---|---|
| A | Arquitectura, dominio, seguridad, recuperación y riesgos | Documento de diseño | Entregada |
| 0 | Probe de nodo, informes por hash y negociación read-only de Broker | Tests de contrato 2.9, incluido client-tool loop | Pendiente AMD, NVIDIA, red y Broker reales |
| 1 | Desktop/Coordinator/Worker, auth, jobs, leases, cancelación, outbox y CAS | Tests con dos workers simulados y desconexión | Pendiente dos PCs y TLS desplegado |
| 2 | Vault read-only, snapshot, hashes, índice FTS5 generacional, grafo y auditoría | Tests temporales sin cambios de bytes/mtime | Pendiente vault real y symlink privilegiado |
| 3 | Corpus controlado y registro inmutable de benchmark real humano | Validador determinista y API/UI | Pendiente aprobación humana |
| 4 | R1 lexical y jobs R2 semántico/R3 híbrido con embeddings locales | Ejecutor distribuido y tests controlados | Pendiente modelo local real |
| 5 | R4 con wikilinks, expansión, pesos, reranking y contexto acotado | Tests deterministas | Pendiente comparación R4/R3 real |
| 6 | Respuesta multifuente, citas y verificadores | Snapshot controlado | Pendiente benchmark del vault real |
| 7 | Revisión, diff, editor, evidencia y doble aprobación de training | Repository/API/UI y tests | Pendiente uso humano real |
| 8 | Plan v2 sellado, ZIP R3/R4 y comparación por CLI pública de Model Drift | R3/R4 reales con embeddings locales; ciclo formal por las tres vías | **Superada** |
| 9 | Dataset inmutable, procedencia, dedup, contaminación y splits | Tests de construcción/verificación | Pendiente candidatos reales |
| 10 | C1–C6, resolver, LoRA, destilación secuencial profesor→alumno, checkpoint/resume, reload y manifests | Contratos, planificación, executor y flujo de producto; sin carga larga real | Pendiente hardware/modelos y overfit |
| 11 | Ejecución F1/F2 y estrategias B0–L1 bajo contrato común | Tests de contratos | Pendiente runs reales |
| 12 | Comparación multidimensional sin score global | API/UI y vista de registros | Pendiente runs reales |
| 13 | Selector con umbral, restricciones, incertidumbre y explicación | Tests deterministas | Pendiente evidencia aprobada |
| 14 | Jobs A1/M1 con runtime agent/mixture delegado a AI Broker y retrieval local como client tool | Tests de planificación y ejecución contractual | Pendiente Broker/Workers reales |
| 15 | Adapter zip, merge safetensors, GGUF y paquete verificable por CAS | Export adapter controlado | Pendiente modelo/convertidor reales |

## Verificaciones ejecutadas

- `python -m pytest -q --basetemp=.full-test-tmp-20260825-broker-teacher`: **158 passed,
  1 skipped**. El skip corresponde a creación de symlinks no permitida por la identidad de
  pruebas de Windows.
- `python -m compileall -q src tests`: pasa.
- TypeScript (`tsc -b`) y React/Vite (`vite build`): pasan.
- `cargo check --offline` en `apps/desktop/src-tauri`: pasa.
- `scripts/build_sidecar.ps1`: genera el Coordinator y su smoke `--help` pasa.
- Tauri release: genera `target/release/local-ai-lab-desktop.exe`.
- Arranque portable: smoke real superado; resuelve el Coordinator tanto en la disposición
  portable `resources/` como en la raíz usada por los instaladores. Tres tests Rust fijan ambas
  rutas y que un fallo del Coordinator se muestre en la UI sin cerrar el escritorio.
- Destilación: la prueba integral recorre dataset verificado, generación del profesor, preparación
  supervisada del alumno, checkpoint, reanudación solicitada, guardado, recarga del adapter y
  manifiesto con hashes. Se prueban los dos orígenes del profesor: caché local y AI Broker con
  modelo exacto, fallback prohibido y trazabilidad de tarea/uso/coste. La frontera
  `torch`/Transformers/PEFT usa dobles deterministas; sigue pendiente una ejecución con un alumno
  causal real y el entorno local de entrenamiento instalado.
- MSI/NSIS: pendientes únicamente de disponer de WiX 3.14 y NSIS 3.11 en la caché local;
  Tauri no pudo descargarlos porque el entorno no permite red.
- Graphify: 1.889 nodos y 3.879 aristas de código fuente; cero endpoints ausentes/colgantes, self-loops,
  duplicados o colisiones multigraph.

## Integraciones externas

### AI Broker

Solo existe acceso por contrato HTTP. Local AI Lab no lee ni modifica su SQLite,
configuración o repositorio. Las estrategias fijan modelo, desactivan fallback silencioso,
marcan exclusión de aprendizaje y conservan telemetría y coste desconocido como desconocido.

Para la fase formal y A1/M1 se requiere que `/capabilities` anuncie las capacidades necesarias
del contrato 2.9. Si el Broker instalado no las anuncia, la UI lo marca `UPGRADE_REQUIRED` y
debe instalarse una versión compatible antes de esa prueba.

**Probado el 2026-08-24** contra el servicio real en `192.168.1.52:8765`: contrato 2.9
observado y los cuatro conjuntos de requisitos (`phase0`, `retrieval`, `formal_evaluation`,
`agent_experiments`) satisfechos. Se ejecutó además una inferencia completa con modelo exacto,
sin fallback y con telemetría. Esa ejecución destapó cuatro defectos que los transportes
falsos de las pruebas ocultaban; están detallados y corregidos en
[`docs/AUDIT_20260824.md`](AUDIT_20260824.md).

### Model Drift

La integración usa solo su CLI pública y nunca su base de datos. Genera un plan R3/R4 con
identidades y hashes exactos e invoca `evaluar-tratamientos`. Si la instalación local no
expone ese contrato, la ejecución formal se bloquea explícitamente.

**Ampliado y probado el 2026-08-24**: la instalación local expone también
`evaluar-tratamientos`. El contrato v2 recibe artefactos de retrieval ya calculados, verifica
su integridad y comparabilidad y genera el informe formal sin acceder a persistencia ajena ni
realizar nuevas llamadas al Broker.

**Ciclo completo ejecutado el 2026-08-24** con R3/R4 reales sobre el corpus controlado,
producidos con embeddings locales (`bert-base-uncased` en caché, sin red) y empaquetados como
los recoge el Worker:

- R3 `R3.hybrid-rrf.v1` → recall 0.867, nDCG 0.836. R4 `R4.hybrid-graph.v1` → recall 1.000,
  nDCG 0.936. La expansión por grafo mejora de verdad el ranking.
- Model Drift emite el informe formal y declara sus límites: con 5 casos no hay potencia para
  concluir, y registra como garantía ausente que no observó el proceso que produjo los
  artefactos. El veredicto es «sin cambios relevantes» pese a la mejora medida.
- Ejecutado por las tres vías: integración directa, `CoordinatorService` y el endpoint
  `POST /app/v1/model-drift/comparisons`. El registro queda `MODEL_DRIFT_VERIFIED` y aparece
  en el workspace que consume la UI.

Protecciones comprobadas rechazando lo que deben: orden R3/R4 invertido, hash de artefacto
falso, plan manipulado tras el sellado, ZIP alterado un solo bit, ausencia de confirmación
humana y experimentos de corpus distinto. El informe HTML no es reproducible byte a byte
porque incorpora la marca de tiempo de generación; el plan y los artefactos sí lo son.

### Vaults

La ruta declarada es `Y:\Mi unidad\Vaults`. La UI solo ofrece descubrir, snapshot e indexar
mediante el backend; el webview no recibe acceso directo al sistema de archivos.

**Probado el 2026-08-24** sobre `Y:\Mi unidad\Vaults\Conocimiento_Youtube`: snapshot
`COMPLETE` de 10 notas y 647 chunks sin holes, e índice FTS5 construido y consultado. El vault
quedó idéntico byte a byte en contenido, tamaño y mtime, comprobado antes y después.

## Pruebas reales que quedan para el usuario

1. Ejecutar probes NVIDIA y AMD/WSL y aprobar los informes.
2. Desplegar Coordinator y Worker con TLS entre dos PCs; probar desconexión y reenvío.
3. Crear un snapshot del vault real y confirmar externamente que Obsidian no cambió.
4. Aprobar el corpus controlado y redactar/revisar el benchmark real.
5. Probar embeddings, inferencia, LoRA, checkpoint/resume y conversiones con modelos aprobados.
   Para destilación, el profesor puede venir de AI Broker o de la caché local; el alumno sí debe ser
   un modelo causal local distinto, con PEFT y hardware aprobados. También debe confirmarse que los
   términos del profesor permiten usar sus respuestas para entrenamiento y que los del alumno
   permiten fine-tuning y el uso previsto del adapter. El código no sustituye esa comprobación.
6. ~~Negociar AI Broker mediante GET~~ — hecho el 2026-08-24: contrato 2.9 satisfecho.
7. ~~Ejecutar R3/R4 reales y revisar la comparación~~ — hecho el 2026-08-24. Queda revisar
   humanamente el informe y ampliar el corpus: con 5 casos Model Drift no alcanza potencia
   para concluir nada, por bien que se comporte R4.
8. Revisar humanamente la calidad de las respuestas citadas ahora que el pipeline completo
   llega al Broker real.

No se han modificado AI Broker, Knowledge Orchestrator, Athena, WSL, drivers,
BIOS, Obsidian ni los vaults reales. Tampoco se ha hecho commit, push o despliegue.
