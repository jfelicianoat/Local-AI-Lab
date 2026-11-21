# Auditoría y corrección integral de Local AI Lab — 19/11/2026

Estado: IMPLEMENTADO CON VERIFICACIONES PENDIENTES. Base: `272de87`, árbol limpio al comenzar. Python 0.1.6;
escritorio 0.1.8. Instrucción: auditoría, implementación completa y revisión
adversarial del documento `Texto pegado(1).txt` de 19/11/2026.

Se trabaja con bases, vaults y artefactos sintéticos aislados. No se autoriza una
release por pasar los tests ni se reutiliza evidencia externa histórica como actual.

## Inventario y mapa de flujos

| Objetivo | Flujo / reglas | Componentes | Verificación prevista |
|---|---|---|---|
| Preparar el laboratorio | Arranque, sesión local, configuración, capabilities, nodos | Tauri, API, broker, security, capabilities | Build, Rust, API, arranque aislado |
| Definir y retomar trabajo | Misiones, borradores, etapas y evidencia explícita | mission.tsx, servicio/repositorio misiones | Navegación, reapertura, guardado y conflicto |
| Preparar conocimiento privado | Vault read-only → snapshot → índice → benchmark | knowledge_index, retrieval, benchmark, knowledge.tsx | Tests con vault sintético, hashes y persistencia |
| Comparar estrategias | Suite → job → Worker → resultado → métricas → Model Drift → selección | experiments, strategies, evaluation, model_drift | Tests contratos, fallos, informe y paginación |
| Revisar y crear ejemplos | Consulta → citas → corrección → aceptación → aprobación explícita | knowledge.tsx, feedback | API, revisión optimista, operaciones pendientes |
| Entrenar y exportar | Aprobaciones → dataset sin contaminación → preflight → entrenamiento → exportación | dataset, training, exporting, datasets.tsx | Integración sintética, cancelación y recuperación |
| Operar y recuperar | Historial, progreso, leases, artefactos, limpieza, backup y restore | worker, maintenance, activity | Suite distribuida local, restore sin origen |

## Registro único

Los criterios se comprobarán antes de marcar VERIFICADO. No se añaden propuestas
especulativas al compromiso de entrega.

| ID | Tipo / prioridad | Evidencia, problema e impacto | Criterio de aceptación | Estado |
|---|---|---|---|---|
| LAL-01 | Defecto / alta | Borrador nuevo no tiene missionId; navegar lo pierde. Guardado al desmontar silencia errores. | Borrador recuperable tras navegar/reiniciar; distinguir guardado local/remoto y fallos. | IMPLEMENTADO SIN VERIFICAR completamente: montaje, navegación y reapertura React/DOM pasan; persistencia en WebView real pendiente |
| LAL-02 | Defecto / alta | UPSERT de misión sin control de versión permite sobrescritura entre sesiones. | Escritura obsoleta devuelve 409 sin cambiar datos; migración conserva misiones y evidencia; UI conserva borrador. | VERIFICADO en repositorio, migración, HTTP/ASGI y conflicto/copia React; puente nativo pendiente en LAL-08 |
| LAL-03 | Defecto / alta | Restore conserva artifact_locations absolutos del origen (reproducido por árbitro). | Abrir informes, snapshots/índices y continuar trabajo con origen ausente; rutas externas explícitas. | VERIFICADO en integración sintética de servicio y filesystem |
| LAL-04 | Defecto / alta | Dataset se publica READY_FOR_TRAINING antes de consumir aprobaciones; revocación concurrente deja producto elegible (reproducido por árbitro). | Validación, publicación y consumo atómicos; conflicto no publica ni consume parcialmente. | VERIFICADO en integración sintética, incluida pérdida de acuse tras commit |
| LAL-05 | Defecto / media | Ejemplos manuales editables mientras se busca/crea; respuestas tardías usan contexto anterior o borran edición nueva. | Campos y selección estables durante operación; sin resultados de otra consulta ni borrado de texto posterior. | VERIFICADO en React/DOM: búsqueda y creación retardadas, fallo conservando respuesta y reintento correcto |
| LAL-06 | Defecto / media | Actualizaciones completas simultáneas pueden llegar fuera de orden; refresh manual cambia estado y puede ocultar datos al fallar. | Solo respuesta vigente modifica la vista; fallo conserva datos con aviso y reintento. | VERIFICADO en controlador de carreras y React: el fallo de refresco conserva la misma instancia del editor y el texto; tráfico nativo pendiente en LAL-08 |
| LAL-07 | Mejora de usabilidad / media | Estado «Plan guardado» no distingue edición pendiente, error o conflicto. | Mensajes comprensibles y recuperación del borrador sin sobrescribir otra sesión. | IMPLEMENTADO SIN VERIFICAR completamente: mensajes y acciones comprobados en React/DOM; valoración visual pendiente |
| LAL-08 | Tarea técnica | Ejecutar controles y conciliar todos los elementos con arbitraje independiente. | Python, frontend, Rust, empaquetado/arranque y revisión final con límites explícitos. | IMPLEMENTADO SIN VERIFICAR completamente: 454 Python, 35 frontend, 8 recorridos React y 7 TCP/TLS reales pasan; arranque conectado confirmado; falta repetir limpieza PS5.1 corregida y revisión visual |

## Situación inicial

- `npm test`: 23/23 pasan. `npm run build`: pasa.
- `cargo test --offline`: 3/3 pasan.
- Suite Python en ejecución aislada. Primer intento falló por una ruta temporal
  inexistente; segundo por falta de permiso en D:/workspace. Ninguno demuestra
  defectos de producto. La ejecución válida usa `.test-tmp/audit-20261119`.
- Navegador integrado: intento de abrir preview rechazado por sesión de pestaña;
  no constituye verificación de interfaz. Se intentará escritorio nativo aislado.
- Integraciones reales, GPU/entrenamiento y dos equipos físicos: aún NO VERIFICADO.

## Arbitraje

Árbitro independiente de solo lectura. Investigación inicial: pérdida de borradores,
concurrencia de misiones, restore dependiente del origen y publicación no atómica
del dataset. Se han realizado tres rondas formales con agente independiente; resultados abajo.

## Implementación y trazabilidad final

| ID | Componentes | Implementación y evidencia |
|---|---|---|
| LAL-01, LAL-07 | `mission.tsx`, `missionDraft.ts`, `App.tsx`, estilos | Borradores locales separados por misión y para el plan nuevo; selección en memoria aunque falle localStorage; bloqueo de salida si hay una operación pendiente o falla la conservación. Volver a Nueva misión recupera el borrador anterior; reemplazarlo cambiando estrategia exige confirmación. El montaje espera a cargar el plan antes de escribir su recovery. Una selección inexistente ya no es una identidad escribible: muestra aviso y permite crear otro plan, sin recrear el ID anterior ni borrar el borrador nuevo independiente. |
| LAL-02 | modelos/API, repositorio y servicio de misiones, contratos TS y comando Rust | Columna `revision` añadida sin borrar datos; `expected_revision` impide escrituras obsoletas con 409. Interfaz conserva texto local y permite cargar la versión guardada o crear copia. Regresiones de actualización, cliente antiguo y reapertura/migración en `tests/test_audit_20261119.py`. |
| LAL-03 | `maintenance/backup.py` | Backup v2 guarda mapa relativo de artefactos; restore verifica archivos y reubica registros al destino. Backup v1 con referencias requiere `--original-root` explícito. La prueba renombra el origen, recupera bytes del informe y reconstruye un índice desde el snapshot restaurado. |
| LAL-04 | `dataset/factory.py`, feedback, repositorio de producto y servicio de entrenamiento | Captura revisión de cada aprobación; vuelve a validarlas y consume/publica bajo una sola transacción SQLite. Un conflicto revierte todo. El fallo anterior al commit limpia solo la carpeta/ZIP propios, con validación de rutas; no borra CAS compartido. Una excepción posterior a un commit durable conserva archivos y producto. Ocho regresiones específicas de auditoría más fábrica/backup: 14 aprobadas. |
| LAL-05 | `knowledge.tsx` | Fieldset desactivado durante consulta/creación evita alterar el contexto usado por la respuesta. Falta el recorrido interactivo para acreditar el criterio completo. |
| LAL-06 | `latestRequest.ts`, `App.tsx` | Solo aplica respuesta vigente; polls en segundo plano se agrupan mientras hay petición pendiente; guardar misión invalida observaciones anteriores. Un refresco manual conserva la vista montada y el último dato útil, con aviso recuperable al fallar. Pruebas deterministas invierten éxito/error, simulan varios intervalos lentos e invalidación tras mutación. |

## Verificaciones ejecutadas sobre el cambio

| ID prueba | Objetivo y comando / preparación | Resultado observado | Evidencia |
|---|---|---|---|
| V01 | Suite Python sin endpoints/red; `run_offline.py`, TEMP y TMP dentro del espacio de pruebas | PASA: **416 passed**, 2 skipped, 45 deselected; 58,10 s | `.test-tmp/audit-20261119/python-final.log`; exclusiones enumeradas en `blocked-network-tests.txt` |
| V02 | Revocación concurrente, rollback, commit durable, migration y restore sin origen; pytest sobre audit/factory/backup | PASA: **14 passed**, 4,31 s | `related-final.log` y `related-final.xml` |
| V03 | `npm test` | PASA: **35 passed**; incluye selección inexistente, storage restringido, recuperación y carreras | `frontend-final.log` |
| V04 | `cargo test --offline --manifest-path src-tauri/Cargo.toml` | PASA: **3 passed** | `rust-final.log` |
| V05 | PyInstaller sidecar + TypeScript/Vite + Tauri sin instalador ni firma | PASA: también reconstruido el ajuste final de selección; advertencia informativa del linker | `build-final.log`, `native-final3.log` |
| V06 | Conexión loopback de socket con timeout de 2 s | BLOQUEADA: **WinError 10013** al conectar a 127.0.0.1, aun pudiendo enlazar el socket | Diagnóstico de esta sesión; no se habilitó acceso de red |
| V07 | Recorrido de escritorio con Coordinator/DB/WebView aislados | BLOQUEADA: ventana Local AI Lab enumerada; permiso de control de la ventana caducó antes de inspeccionar su contenido | Intento nativo con PID propio y datos en `native-journey/`; no acredita arranque funcional ni navegación |
| V08 | Vista compilada en navegador integrado | BLOQUEADA: política del navegador rechazó protocolo file; no se intentó eludirla | Intento de navegador; no se presenta como prueba de interfaz |
| V09 | `git diff --check` | PASA | Control local de los cambios |
| V10 | Smoke del paquete local completo con sidecar junto al ejecutable | BLOQUEADA: no se obtuvo señal de readiness; el helper informó de fallo al detener su árbol de proceso en este entorno. No acredita un arranque funcional | `packaged-smoke.log` |

Las rutas de evidencia de la tabla son relativas a `.test-tmp/audit-20261119/`, salvo código fuente/pruebas. Los informes de ejecuciones fallidas por TEMP/permisos y la compilación retenida por el proceso de prueba no son fallos demostrados del producto. Se conservaron y se repitieron los controles tras resolver esas condiciones.

La primera pasada no acreditaba los efectos React de MissionBoard. La continuación descrita abajo sí ejecuta montaje, eventos DOM, hooks y desmontaje de los componentes reales, con el transporte Tauri simulado. De las 45 pruebas inicialmente excluidas, **38 ya pasan con HTTP/ASGI dentro del proceso**. Las siete restantes requieren conexiones TCP/TLS reales; la lista exacta está en `full-inprocess-final/real-network-not-run.txt`. Los dos skipped requieren crear symlinks. La integración con servicios reales, inferencia GPU y dos equipos físicos no se ha comprobado en esta intervención.

## Arbitraje independiente y cierre

1. Ronda 1: cinco objeciones sobre storage, recuperación del borrador nuevo, polls lentos, respuesta anterior a guardar y residuos de dataset. Corregidas; añadida evidencia de carreras y filesystem.
2. Ronda 2: montaje inicial podía sobrescribir el borrador nuevo; cambio de estrategia reemplazaba otro borrador sin confirmación; limpieza podía borrar un dataset ya confirmado. Corregidas; regresión de pérdida de acuse tras commit aprobada.
3. Ronda 3: selección inexistente podía bloquear Crear/Nueva misión. Corregida después del último dictamen, con prueba nueva del resolver de selección; la integración de sus hooks sigue pendiente de observación. El árbitro leyó los resultados locales y **no otorgó aprobación global**.

No se ha realizado una cuarta ronda. El ajuste posterior al dictamen final recibió revisión del constructor, que es autoevaluación. El trabajo no se declara COMPLETADO Y VERIFICADO mientras falten las verificaciones esenciales de interacción y HTTP.

## Ejecutar y retomar

Para usar el código en desarrollo: Python 3.14, dependencias existentes del proyecto y Node compatible con `apps/desktop/package.json`. El ejecutable local se genera con:

```powershell
./scripts/build_desktop.ps1 -Python ./.venv-verify/Scripts/python.exe
```

No se ha publicado, instalado ni promovido una release. El lanzador habitual busca primero candidatos antiguos en `dist/candidate-*`; se ha preparado una copia local de prueba en **`dist/audit-20261119/`**, con `local-ai-lab-desktop.exe`, el sidecar actual en `resources/` y hashes en `verification.json`. Mantener esa estructura y usar un directorio de datos de prueba mediante `LOCAL_AI_LAB_DATA_DIR`. No confundir este paquete con una entrega aceptada: el smoke y la interacción siguen pendientes.

La migración de misiones se aplica al abrir una base existente y conserva contenido y enlaces. Las escrituras HTTP de misiones existentes deben enviar la revisión recibida como `expected_revision`; crear usa 0. Las copias v2 se reubican automáticamente; para v1 con artefactos, indicar el directorio original con `--original-root`.

Siguiente comprobación necesaria en un entorno con loopback y control visual disponibles: repetir en WebView/escritorio los recorridos ya aprobados en React/DOM, ejecutar las siete pruebas de red restantes y el smoke del paquete. Mantener datos sintéticos y registrar el resultado por ID antes de cambiar su estado.

## Continuación: contratos HTTP y recorridos React

Se comprobó que el bloqueo de conexiones locales afecta también al socket de despertar que asyncio crea en Windows. El traceback de `asyncio-startup-trace.txt` termina en `socket._fallback_socketpair/accept`, durante `asyncio.new_event_loop()`. Esta limitación no debe confundirse con un error de la lógica de misiones.

Se añadió `scripts/verify_inprocess_http.py`: conserva TestClient, la aplicación FastAPI, middleware, autenticación, validación y serialización HTTP reales; para el bucle de prueba usa una señal de hilo en lugar del socket de despertar. No abre conexiones ni permite I/O de red, no modifica el runtime de producción y **no acredita TCP/TLS ni el puente Rust**.

| Verificación actual | Resultado | Evidencia relativa a `.test-tmp/audit-20261119/` |
|---|---|---|
| 38 contratos inicialmente bloqueados: misiones, autorización, revisiones, datasets, jobs, exportación y paginación | **38 PASA**, 15,95 s | `http-inprocess-all.log`, `http-inprocess-all/results.xml` |
| Suite completa con ese soporte ASGI, excluyendo solo la red real | **454 PASA, 2 skipped, 7 deselected**, 78,67 s | `full-inprocess-final.log`, `full-inprocess-final/results.xml` |
| Pruebas habituales del frontend tras la corrección adicional | **35 PASA** | `frontend-resume-final.log` |
| Montaje y recorridos de componentes React reales en jsdom | **8 PASA** | `react-workflows-final.log` |
| Reconstrucción TypeScript/Vite y ejecutable nativo con la corrección adicional | **PASA** | `native-resume-final.log` |
| Smoke con limpieza corregida | Readiness **NO ACREDITADA**; causa primaria conservada, `cleanup_error=null` | `packaged-smoke-resume.log`; reporte `smoke.json` en la carpeta indicada por el helper |
| Script de pendientes, preflight local | **BLOCKED_LOCAL_TCP**; no inició tests de red ni smoke al detectar la restricción | `pending-precheck-final.log`, JSON bajo `.test-tmp/pending-checks/` |

Los ocho recorridos prueban: carga de plan guardado sin borrar otro borrador; navegación/reapertura; selección inexistente y creación con identidad nueva; fallo de refresco manteniendo el mismo editor; almacenamiento local denegado; conflicto entre sesiones con copia de trabajo; cambio de estrategia con cancelación/confirmación; fallo/reintento de guardado; y consulta manual retardada con bloqueo de campos, fallo y reintento de creación. Algunos recorridos combinan varios de esos escenarios. No son pruebas con usuarios ni inspección de píxeles, tamaños de ventana o accesibilidad de WebView.

**Defecto adicional reproducido y corregido (LAL-01/LAL-07):** la migración de borradores antiguos de `loadMissions()` todavía leía localStorage sin protección. Al denegar storage, el componente App mostraba un error y ocultaba todas las misiones remotas. Ahora la migración opcional no bloquea los planes guardados; se protege también la escritura del marcador de migración. El recorrido React verifica que la aplicación abre y permite entrar a un plan remoto aun con storage denegado.

Se mejoró `scripts/smoke_desktop.ps1` para aislar el perfil WebView, conservar stdout/stderr y un `smoke.json`, terminar solamente el proceso de prueba y sus descendientes mediante .NET, y preservar el error de arranque aunque falle la limpieza. El fallo anterior de taskkill ya no oculta el motivo principal.

Las comprobaciones React usan React/ReactDOM y `api.ts` reales; solo se simula `invoke` de Tauri y el Coordinator de ese recorrido. Se usó jsdom **30.0.1** ya instalado en el entorno de ChatyGPT, sin modificar ese proyecto ni instalar paquetes. Para reproducir con un jsdom compatible instalado:

```powershell
$env:LAL_TEST_JSDOM = 'D:\Desarrollo\Proyectos TFM\ChatyGPT\node_modules\jsdom'
Set-Location apps/desktop
npm run test:workflows
```

Desde la raíz, la suite ampliada se reproduce así; TEMP/TMP deben apuntar al espacio de prueba si el directorio temporal del entorno restringe permisos:

```powershell
.venv-verify/Scripts/python.exe scripts/verify_inprocess_http.py --all --output .test-tmp/verification-asgi
```

Para los siete casos de red y el smoke, `scripts/verify_pending_checks.ps1` comprueba primero que exista TCP local, usa exclusivamente datos sintéticos y conserva evidencia; no modifica permisos, firewall ni configuración de seguridad. Esas comprobaciones se mantienen pendientes en este entorno.

La nueva corrección y sus pruebas recibieron autoevaluación del constructor. Se conserva el límite de tres rondas formales independientes; no se atribuye a ese árbitro una aprobación posterior ni una aceptación global.

## Ejecución desde Windows del usuario: 19/11/2026, 13:20

La ejecución registrada en `.test-tmp/pending-checks/decef65869fa42c2b9ac673760d410e9/` acredita **7/7 pruebas TCP/TLS reales aprobadas**, en 7,16 s, con `network_exit_code=0`. Se cierran los siete casos de red pendientes para esa ejecución de Windows; el bloqueo de sockets descrito antes corresponde al entorno del agente.

El reporte `.test-tmp/desktop-smoke/faf65873c56147b1b46d417c307d7f56/smoke.json` conserva `ready=true` y `startup_error=null`. El log del Coordinator muestra arranque completo y solicitudes HTTP 200 del escritorio para overview, workspace, misiones, revisiones y jobs. Por tanto, el arranque conectado del paquete sí quedó acreditado en esa ejecución.

El error posterior era del helper: Windows PowerShell 5.1 usa .NET Framework y no dispone de `Process.Kill(bool)`. Se confirmó en ese runtime que la sobrecarga no existe. Se corrigió `smoke_desktop.ps1` para detectar la API disponible: usa `Kill(true)` en .NET moderno y `taskkill /PID <proceso de prueba> /T /F` en Windows PowerShell 5.1, conservando el error original y el registro de limpieza.

La sintaxis del cambio se comprobó con Windows PowerShell **5.1.26100.9711**. La ejecución de una fixture por archivo quedó bloqueada por AuthorizationManager en el entorno del agente; no se presenta como verificación ejecutada de la nueva rama de limpieza. Falta repetir esa limpieza desde Windows normal y la inspección visual del escritorio.

Para evitar que una ventana efímera oculte errores, se añadió `verificar_local_ai_lab.cmd`. Ejecuta el comprobador con Windows PowerShell, conserva su código de salida y hace una pausa final. La aplicación de prueba se abre y se cierra automáticamente por diseño. El PS1 imprime también el resultado de red y el error específico de arranque/limpieza cuando existe.
