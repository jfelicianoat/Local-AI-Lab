# Auditoría de Local AI Lab: intención, implementación y usabilidad

**Fecha:** 29 de septiembre de 2026.  
**Versión examinada:** `ad9bd34370dccf38c6896564f58e3e6535ab6848` (`ad9bd34`, 5 de septiembre de 2026).  
**Directorio:** `D:\Desarrollo\Proyectos TFM\Local AI Lab`.  
**Naturaleza:** auditoría; no se han corregido ni modificado los archivos de producto.

## 1. Dictamen

**Local AI Lab tiene una base técnica relevante, pero todavía no cumple de extremo a extremo su objetivo de decidir qué estrategia resuelve mejor una tarea sobre conocimiento privado.** Hay módulos funcionales y pruebas útiles, junto con desconexiones entre esos módulos que pueden bloquear al operador o atribuir a los resultados más garantías de las demostradas.

Los problemas principales son:

1. **La versión actual no se puede construir mediante los recorridos documentados:** falla TypeScript y el empaquetador del Coordinator apunta a un archivo que ya no existe.
2. **El conocimiento privado se puede registrar, pero los lanzadores de experimentos siguen utilizando la suite controlada.** No hay un recorrido integrado para ejecutar el benchmark real registrado y obtener feedback de producción elegible para entrenar.
3. **F1/F2 no vinculan el modelo evaluado al adaptador entrenado.** Además, los resultados de destilación quedan excluidos de ese selector.
4. **La evidencia puede interpretarse incorrectamente:** el selector descarta la calidad, el verificador acepta afirmaciones sin evidencia en el texto principal y los benchmarks reales admiten referencias inexistentes.
5. **La recuperación distribuida tiene fallos reproducibles:** cancelación posterior al arranque, repetición de resultados, vencimiento de leases y reasignación al mismo Worker.
6. **La interfaz promete un recorrido guiado, evidencia recuperable y privacidad de “solo este equipo” que sus flujos actuales no sostienen de forma consistente.**

Mi recomendación es **tratar esta versión como una implementación experimental y no como una herramienta ya validada para decidir promociones o superioridad de estrategias**. No hace falta rehacer el proyecto: hace falta cerrar los contratos entre captura, ejecución, evaluación, revisión, entrenamiento y decisión, con pruebas que atraviesen esas fronteras.

## 2. Alcance, método y límites

Se contrastaron README, PRODUCT, DESIGN, diseño de Fase A, instrucciones originales de desarrollo e interacción entre apps, manual de uso, estado de implementación y declaraciones de los informes de fases. Los informes históricos se usaron como contexto de lo prometido, no como pruebas de que el código actual funciona.

El repositorio contiene 91 archivos Python bajo `src`, 24 archivos de pruebas Python y 16 archivos en la carpeta principal del frontend. Se revisaron los puntos de entrada, contratos, servicios, persistencia, protocolos Worker/Coordinator, evaluación, datasets, entrenamiento, integración Broker/Model Drift, componentes de interfaz y empaquetado. **Esto no equivale a una inspección exhaustiva de cada línea ni a una prueba de todos los modelos y equipos.**

Se ejecutaron la suite Python, las pruebas Rust y el build del frontend. Se añadieron doce reproducciones aisladas, sin red ni GPU, utilizando datos sintéticos y algunas ayudas de las pruebas existentes. Sus resultados están en [resultados_reproducciones.json](<D:/Desarrollo/Proyectos TFM/Local AI Lab/docs/Auditoria 20260929/resultados_reproducciones.json>).

El grafo Graphify ayudó a localizar áreas, pero aún señala los antiguos archivos `coordinator/service.py`, `repository.py` y `api.py`. Las evidencias del informe se verificaron en los archivos actuales. No estuvo disponible `codebase-memory-mcp`; se utilizó el grafo local y búsquedas dirigidas.

**Límite de usabilidad:** la política del navegador rechazó la apertura de `http://127.0.0.1:5178` por un permiso denegado. No se intentó eludir el bloqueo. No hay capturas nuevas ni validación visual de esta versión. Las observaciones UX son una revisión estática de componentes, comportamiento programado y manual; no se afirma haber comprobado contraste real, navegación completa con teclado, lector de pantalla o diseño a distintos tamaños.

No se ejecutaron inferencias, entrenamientos, conversiones, llamadas a AI Broker/Model Drift reales ni accesos al vault del usuario. Tampoco se verificó la red entre dos PCs, AMD/WSL, certificados, instaladores o correspondencia del ejecutable preexistente con este commit. Las afirmaciones históricas sobre pruebas reales permanecen como antecedentes, no como resultados de esta auditoría.

### Resultados actuales de verificación

| Comprobación | Resultado | Qué acredita |
|---|---|---|
| Python, `pytest -q --basetemp=.audit-20260929-tests` | **171 passed, 1 skipped**, 9,01 s | La suite existente pasa en Python 3.14.0 |
| Prueba omitida | Creación de symlink sin privilegios | Esa protección no se volvió a verificar en ejecución |
| Frontend, `npm run build` | **Falla TS2322** en `experiments.tsx:94` | La versión fuente actual no supera su build |
| Rust, `cargo test --offline` | **3 passed** | Resolución de rutas del sidecar y conservación del error de arranque |
| Vite de desarrollo | Arrancó | No acredita compilación TypeScript ni funcionamiento Tauri |
| Reproducciones adicionales | **12 escenarios ejecutados** | Confirman los comportamientos concretos descritos más abajo |
| Script de sidecar | Entrada referenciada inexistente | Bloqueo verificado por inspección; no se sobrescribió el binario existente |
| Interfaz visual | **No verificada** | Apertura bloqueada por política del navegador |

Pasar las pruebas existentes no invalida estos hallazgos: las reproducciones cubren casos que no están representados por esa suite.

## 3. Intención frente a lo desarrollado

La intención principal aparece en [PRODUCT.md](<D:/Desarrollo/Proyectos TFM/Local AI Lab/PRODUCT.md>) y en las [instrucciones de desarrollo](<D:/Desarrollo/Proyectos TFM/Local AI Lab/docs/Instrucciones y razones sobre como será el desarrollo de la app.md>): experimentar antes de entrenar, usar conocimiento privado con evidencia recuperable, comparar estrategias con rigor y elegir la alternativa menos compleja que cumpla las restricciones.

| Intención | Implementación observada | Evaluación |
|---|---|---|
| Comparar prompting, RAG, modelos locales, fine-tuning, destilación y Broker | Existen familias B/R/L/F/A/M y ejecutores | Amplia cobertura nominal; F1/F2 no atan el modelo al resultado entrenado |
| Trabajar sobre conocimiento privado | Snapshot read-only, índice, registro de benchmark real | Captura implementada; falta conexión del benchmark real a los lanzadores |
| Fine-tuning justificado frente a alternativas | Preflight, baseline e hipótesis requeridos | Baseline validado por categoría, no por evidencia suficiente ni comparabilidad |
| Seleccionar la solución más sencilla que alcanza calidad | Selector lexicográfico y restricciones | La capa de servicio elimina calidad y la prioridad por defecto no usa complejidad |
| Evidencia y hashes reproducibles | CAS, manifests, suites y hashes | Buen soporte; varios hashes de modelos son declaraciones del usuario sin comprobación |
| Citas obligatorias y revisión humana | Verificador y estados de aprobación separados | Cobertura parcial; texto principal sin findings puede pasar y UI oculta contexto/diff |
| Benchmarks separados de training | DatasetFactory excluye IDs de benchmark | El servicio solo aporta IDs de la suite controlada |
| Model Drift dueño de la estadística formal | CLI pública, plan sellado y artefactos | Integración conservada; el resultado formal no alimenta correctamente el selector |
| Recuperación distribuida | Journal, outbox, leases, fencing | Implementados, pero fallan casos de cancelación/replay/reasignación y falta recuperación operativa |
| Windows/NVIDIA y AMD/WSL | Scripts por perfil y resolución de hardware | Worker de WSL bloqueado por protección de secretos solo Windows |
| Privacidad local por defecto | `risk.data_classification=local_only`, cargas locales sin descarga | Control contractual positivo; texto “solo este equipo” incorrecto para topología distribuida |
| App accionable y reanudable | Misiones y formularios por sección | Navegación guiada parcial, sin entidad de misión ligada a trabajos y evidencias |
| Estado real, no aparentar capacidades | Vocabulario declared/detected/tested/benchmarked | Overview y algunas garantías de interfaz están fijados en código |
| Mismo producto instalable y reproducible | Python + Tauri + scripts | Build actual roto y documentos de verificación anteriores al commit |

### Lo que conviene conservar

El Coordinator y los Workers no comparten SQLite; existen autenticación de sesión y de nodos, protección DPAPI en Windows, CAS con verificación de contenido, lectura del vault con operaciones de solo lectura y snapshots verificables. El frontend usa comandos Tauri y no recibe el token del Coordinator. La revisión y la aprobación de entrenamiento son estados distintos. Los modelos locales se abren sin descargar automáticamente. La integración con Model Drift utiliza su contrato externo y no su persistencia. La interfaz incluye etiquetas de estado, controles nativos, mensajes con `role=status/alert`, reglas de foco y movimiento reducido.

Estas decisiones proporcionan una base útil. Las correcciones deben reforzarlas, especialmente en las transiciones entre módulos.

## 4. Hallazgos y cambios necesarios

**Prioridades:** P1 = corregir antes de distribuir esta versión o confiar en decisiones/resultados afectados; P2 = corregir para completar el flujo y hacerlo operable de forma sostenida. No se ha asignado P0: no se ha demostrado una pérdida de datos o incidente real. “Reproducido” significa ejecutado con datos sintéticos; “verificado en código” significa que se comprobó la ruta concreta, sin ejecutar el entorno externo.

### H01 · P1 · Dos bloqueos independientes de construcción

**Evidencia.** El frontend añade `demonstrable_execution` en [experiments.tsx:88](<D:/Desarrollo/Proyectos TFM/Local AI Lab/apps/desktop/src/experiments.tsx:88>), pero [api.ts:122](<D:/Desarrollo/Proyectos TFM/Local AI Lab/apps/desktop/src/api.ts:122>) no lo admite. El build devuelve TS2322 en la llamada de la línea 94. Por otra parte, [build_sidecar.ps1:22](<D:/Desarrollo/Proyectos TFM/Local AI Lab/scripts/build_sidecar.ps1:22>) pasa a PyInstaller `src/local_ai_lab/coordinator/api.py`, eliminado al convertir la API en paquete. El punto de entrada actual es `coordinator/api/__main__.py`.

**Impacto.** Ni el frontend ni el empaquetado completo documentado pueden reproducirse desde el código actual. Un `.exe` anterior no demuestra que esta revisión sea distribuible.

**Cambio necesario.** Unificar el tipo de fase de Broker entre formulario y API; corregir el punto de entrada PyInstaller y comprobar sus importaciones/datos. Añadir una comprobación conjunta de Python, TypeScript, Rust y empaquetado.

**Cierre verificable.** Build del frontend, regeneración del sidecar, build portable y smoke desde una carpeta nueva, asociados al mismo commit y sin reutilizar un sidecar antiguo. **Certeza:** build frontend reproducido; ruta inexistente comprobada.

### H02 · P1 · El recorrido de conocimiento privado no llega a la ejecución experimental

**Evidencia.** [evaluacion.py:151](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/service/evaluacion.py:151>) registra una suite real. Sin embargo, los jobs semánticos, A1/M1 y B0–F2 construyen su propio baseline desde `run_controlled_lexical_benchmark` y empaquetan `bundled_controlled_suite_root`: [evaluacion.py:97](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/service/evaluacion.py:97>), [estrategias.py:136](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/service/estrategias.py:136>) y [estrategias.py:258](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/service/estrategias.py:258>). Sus contratos no reciben un benchmark real seleccionado.

**Impacto.** El usuario puede crear snapshot, índice y benchmark del vault, pero las ejecuciones accesibles siguen evaluando el corpus sintético. Los candidatos de revisión generados por esos runs son casos del benchmark controlado, que correctamente se excluyen al construir el dataset. Falta un origen integrado de consultas/revisiones no pertenecientes a benchmarks para completar el recorrido normal de feedback a entrenamiento. Tener APIs de módulos o scripts históricos de pruebas no resuelve ese recorrido del producto.

**Cambio necesario.** Introducir selección explícita de proyecto, suite, snapshot e índice en todos los lanzadores. Unificar runners de suite controlada y real. Añadir una sesión de consulta o un importador de ejemplos autorizados, separado del conjunto de evaluación.

**Cierre verificable.** Desde una instalación vacía: snapshot sintético de un vault de prueba → benchmark real de ese snapshot → R1/R3/R4 sobre sus casos → comparación; y por un canal separado consulta de entrenamiento → revisión → dataset. Comprobar IDs, contenido y hashes en cada paso. **Certeza:** verificado en código.

### H03 · P1 · F1/F2 no demuestran que se evalúa el modelo entrenado

**Evidencia.** [estrategias.py:245](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/service/estrategias.py:245>) comprueba `TRAINING_SUCCEEDED`, pero el payload de las líneas 277–291 no incorpora el job de entrenamiento, el adaptador ni su paquete. [strategies/executor.py:62](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/strategies/executor.py:62>) ejecuta F1 como B1 contra el `target_model` introducido por el usuario; F2 ejecuta RAG contra ese mismo destino.

**Reproducción.** Se aceptó un registro entrenado con base `trained-base` y un objetivo Broker `unrelated-base`. El job solo recibió snapshot, suite e índice. No recibió adaptador.

**Impacto.** Una fila titulada F1/F2 puede evaluar un modelo ajeno al entrenamiento y atribuir sus resultados al fine-tuning. Es posible que un operador publique manualmente el adaptador en Broker, pero la aplicación no comprueba esa relación.

**Cambio necesario.** Vincular el resultado de entrenamiento con una identidad de modelo servido verificable: carga local del adaptador o registro de despliegue Broker con hashes de base, adaptador, tokenizer y configuración. Bloquear F1/F2 si no se puede demostrar esa identidad.

**Cierre verificable.** Una prueba debe fallar si se cambia el modelo destino o el adaptador, y demostrar que la inferencia utiliza los pesos producidos por el job. **Certeza:** payload reproducido y ejecutor inspeccionado; no se ejecutó ML.

### H04 · P1 · El alumno destilado no se puede seleccionar para evaluación F1/F2

**Evidencia.** [experiments.tsx:150](<D:/Desarrollo/Proyectos TFM/Local AI Lab/apps/desktop/src/experiments.tsx:150>) solo muestra `TRAINING_SUCCEEDED`; el servicio aplica el mismo filtro. El finalizador usa `DISTILLATION_SUCCEEDED` para destilación: [trabajos.py:206](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/service/trabajos.py:206>). Exportación sí acepta ambos estados.

**Impacto.** El recorrido del manual “destilar → comparar con baseline → exportar” queda interrumpido para un resultado válido de destilación.

**Cambio necesario.** Sustituir comprobaciones dispersas de etiquetas por una capacidad común de “artefacto de modelo evaluable”, con identidad verificada como en H03.

**Cierre verificable.** Completar una destilación de prueba, seleccionarla en F1/F2 y comprobar que se evalúa el alumno generado. **Certeza:** verificado en código.

### H05 · P1 · El selector puede recomendar sin evidencia y descarta calidad

**Evidencia.** [estrategias.py:70](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/service/estrategias.py:70>) construye todos los runs con `quality={}` y usa `0.0` si falta latencia. No exige estado final ni métricas presentes. [selector.py:16](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/experiments/selector.py:16>) ordena por `quality.fidelity`, recall y latencia; complejidad no forma parte de la prioridad por defecto, y no existe umbral de calidad para decidir que una estrategia “cumple”. La UI solo ofrece runs con recall, excluyendo normalmente B0/B1/F1 de esta decisión.

**Reproducción.** Dos registros `EXPERIMENT_QUEUED`, con IDs de casos pero sin medidas, obtienen `RECOMMENDATION` para B0 al permitir un caso y desactivar el requisito formal, incluso con máximo de latencia de 1 ms. La interfaz filtra parte de este caso; la API sigue aceptándolo.

**Cambio necesario.** Exigir ejecución completa y artefacto validado, representar desconocidos como desconocidos, conservar calidad y definir criterios mínimos por tarea. Después de filtrar por cumplimiento, priorizar simplicidad y restricciones declaradas. Permitir comparar bases, RAG y modelos entrenados con dimensiones apropiadas.

**Cierre verificable.** No hay recomendación para runs en cola, métricas ausentes o calidad insuficiente; una alternativa más simple que cumple gana frente a otra más compleja cuando esa es la política. **Certeza:** reproducido.

### H06 · P1 · La comparación formal no cierra el circuito del selector

**Evidencia.** [evaluacion.py:257](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/service/evaluacion.py:257>) crea un registro independiente `MODEL_DRIFT_VERIFIED`. No actualiza los experimentos comparados ni proporciona una relación que `select_strategy` consulte. Este último lee exclusivamente el `formal_status` del resumen de cada run. Los runs originales conservan `unverified`, mientras el registro de comparación carece de los campos necesarios para ser un run seleccionable.

**Impacto.** Exigir veredicto formal puede excluir R3/R4 aunque ya se haya ejecutado su comparación. Desactivar esa casilla evita la protección en vez de utilizar correctamente la evidencia. Además, completar una CLI y obtener un HTML no debe confundirse con demostrar superioridad; el propio registro fija `superiority_established=False`.

**Cambio necesario.** Modelar un resultado formal estructurado asociado a los IDs y hashes exactos de los runs, con veredicto, incertidumbre, criterios y referencia al informe. El selector debe consultar esa relación sin recalcular estadísticas de Model Drift.

**Cierre verificable.** Comparar dos runs, seleccionar esas mismas versiones y comprobar que se reconoce el veredicto; modificar configuración o artefacto debe invalidar la relación. **Certeza:** verificado en código.

### H07 · P1 · El verificador puede aprobar contenido sin evidencia y fallar ante JSON inválido

**Evidencia.** [response_verifier.py:59](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/evaluation/response_verifier.py:59>) comprueba citas y números en `findings`, pero no exige cobertura del texto `answer`. Con lista vacía, las condiciones universales y `not findings` resultan verdaderas. Tras detectar una forma inválida, continúa iterando campos sin normalizarlos.

**Reproducción.** Una respuesta que afirma una deuda de `987654321 EUR` de `Inventado Apellido`, con `findings=[]`, obtiene `deterministic_pass=true`. Con `findings=null`, el verificador lanza `TypeError` en lugar de devolver un informe de rechazo.

**Impacto.** La UI puede mostrar “Evidencia verificada” y habilitar aprobación de una respuesta no respaldada. Una salida imperfecta de un modelo puede abortar el job entero. Tampoco la mera coincidencia de nombres/números prueba que una afirmación esté sustentada semánticamente.

**Cambio necesario.** Separar validación estructural, existencia de citas, cobertura factual y revisión semántica. Fallar de forma controlada ante tipos incorrectos. Reservar una salida sin findings para una abstención explícita y comprobable; no convertirla en aprobado general.

**Cierre verificable.** Cubrir afirmación sin citas, respuesta vacía, contradicción sin soporte, citas existentes pero irrelevantes, `null` y tipos erróneos. Mostrar exactamente qué capa se verificó. **Certeza:** reproducido.

### H08 · P1 · El benchmark real admite citas inexistentes

**Evidencia.** [benchmark/real.py:61](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/benchmark/real.py:61>) solo verifica que existan las claves de la referencia. [evaluacion.py:153](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/service/evaluacion.py:153>) comprueba que hay un snapshot completo con ese hash, pero no abre sus notas/chunks para verificar las citas. La interfaz dice que valida cada evidencia contra el snapshot.

**Reproducción.** Con un snapshot completo generado en la prueba, una definición con `note-1` y un chunk inexistente compuesto por 64 letras `b` queda `HUMAN_APPROVED`.

**Cambio necesario.** Resolver el snapshot registrado y validar note ID, ruta, sección, chunk y referencia exacta. Separar aprobación humana de integridad técnica; una declaración de aprobación no reemplaza la segunda.

**Cierre verificable.** Rechazar cita inexistente, chunk de otro snapshot, ruta discordante y referencia manipulada. **Certeza:** reproducido por la ruta de registro del servicio.

### H09 · P1 · La exclusión de contaminación ignora los benchmarks reales

**Evidencia.** [entrenamiento.py:33](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/service/entrenamiento.py:33>) pasa a DatasetFactory únicamente casos y fingerprint del corpus controlado. [factory.py:65](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/dataset/factory.py:65>) solo bloquea IDs en esa lista; los fingerprints se anotan pero no se contrastan con la procedencia de cada candidato. El texto del frontend promete excluir todos los benchmarks automáticamente.

**Reproducción.** Se registra por el servicio una suite del tipo real, se prepara un candidato aprobado de uno de sus casos con la ayuda sintética de tests y se construye el dataset. El ejemplo se incluye y pasa a `exported`; el fingerprint de esa suite no figura en las exclusiones.

**Impacto.** Cuando se conecte el benchmark real al resto del flujo, o se incorporen revisiones por API, puede entrar información de evaluación en training y falsear la mejora obtenida.

**Cambio necesario.** Registro común de conjuntos reservados, procedencia explícita por suite/caso/snapshot y exclusión de todas las versiones relevantes. Añadir controles de duplicados de contenido y partición por grupo cuando existan ejemplos relacionados; un cambio de ID no debe eludir la reserva.

**Cierre verificable.** Casos controlados y reales, renombrados o repetidos, no pueden entrar en train/validation; conservar la causa de exclusión. **Certeza:** reproducido con candidato sintético aprobado.

### H10 · P1 · Cancelar después del arranque no detiene correctamente el trabajo

**Evidencia.** [runtime.py:98](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/worker/runtime.py:98>) reutiliza la misma clave `control:job:generation`. [trabajos.py:149](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/service/trabajos.py:149>) hace idempotente esa lectura de control. La primera respuesta queda en caché. Las pruebas existentes cancelan antes de la primera consulta, por lo que no detectan el caso posterior.

**Reproducción.** Arranca un ejecutor, se solicita cancelar y este publica progreso. Continúa ejecutándose y termina intentando éxito. El Coordinator rechaza la transición `cancelling → succeeded_pending_sync`, quedando en `cancelling`.

**Cambio necesario.** Hacer la lectura de control fresca o utilizar una secuencia de consulta; mantener idempotente la solicitud de cancelación, no congelar su observación. Añadir consulta independiente y callbacks de cancelación durante training e inferencia.

**Cierre verificable.** Cancelación antes de iniciar, durante carga, entre pasos y durante espera Broker, con estado final coherente y latencia de respuesta acotada. **Certeza:** reproducido.

### H11 · P1 · Reenviar un resultado aceptado rompe la idempotencia

**Evidencia.** [trabajos.py:174](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/service/trabajos.py:174>) protege `repository.complete`, pero ejecuta `_finalize_product_job` después, también cuando devuelve una respuesta almacenada. El finalizador vuelve a crear las revisiones. La tabla protege la unicidad, por lo que el replay falla en vez de devolver el éxito original.

**Reproducción.** Dos llamadas idénticas a `complete_job`, con la misma clave, devuelven primero éxito y después `IntegrityError: UNIQUE constraint failed: reviews.run_id, reviews.case_id, reviews.reviewer`.

**Impacto.** Si el servidor aceptó la operación pero se perdió la respuesta, el Worker puede quedar reintentando una confirmación que nunca se completa. También existen ventanas de fallo entre el cambio de estado, el registro idempotente y los efectos de producto.

**Cambio necesario.** Convertir finalización en una transición durable y reejecutable: transacción para efectos en la misma SQLite, claves únicas con semántica de upsert verificada y outbox para efectos externos. El replay no debe volver a producir efectos ni fallar.

**Cierre verificable.** Repetir complete antes/después de simular pérdida de respuesta y caída entre fases; obtener exactamente una revisión por caso y una confirmación exitosa. **Certeza:** reproducido.

### H12 · P1 · Leases, reinicio y reasignación no forman un ciclo de recuperación completo

**Evidencia.** [repository/base.py:146](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/repository/base.py:146>) valida nodo, generación y token, pero no vencimiento. `expire_leases` y `reconcile_orphan` existen en el repositorio; no se encontró su activación en el servicio operativo, API o CLI. [worker/cli.py:74](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/worker/cli.py:74>) sincroniza outbox y reclama nuevos jobs, sin recuperar los locales aceptados/en ejecución sin mensajes pendientes. [journal.py:61](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/worker/journal.py:61>) rechaza cualquier nuevo intento del mismo job.

**Reproducciones.** Un lease fijado como vencido en 2000 todavía permite completar con éxito. Tras expirar y reencolar un job, el mismo Worker recibe generación 2 pero `accept_lease` falla por conflicto de identidad.

**Impacto.** Una caída puede dejar jobs sin recuperación efectiva, y un trabajo reasignado puede bloquear al Worker. El heartbeat se envía entre jobs y la renovación depende de callbacks de progreso; [training/executor.py:163](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/training/executor.py:163>) no comunica progreso durante `trainer.train`. Añadir un expirador sin corregir esa renovación agravaría los fallos.

**Cambio necesario.** Supervisión periódica independiente; política explícita de gracia/offline; reconciliación al arrancar; journal por `(job_id, attempt_id)`; tratamiento visible de `accepted=false/stale_attempt`; reanudación de checkpoints como operación de producto con artefacto y autorización. No basta con aceptar un argumento `resume_from_checkpoint` en el ejecutor.

**Cierre verificable.** Fault injection en accept/ack/training/upload/complete y posterior reinicio; ningún resultado viejo se promueve y cada trabajo tiene una decisión recuperable. **Certeza:** dos defectos reproducidos; ausencia de integración verificada en código.

### H13 · P1 · Autenticación de nodos sin autorización de artefactos

**Evidencia.** [nodos.py:84](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/service/nodos.py:84>) permite descargar cualquier hash existente a cualquier nodo autenticado. Las operaciones de chunks/commit tampoco vinculan la sesión de subida al nodo propietario o al trabajo.

**Reproducción.** Un Worker emparejado sin ningún job puede descargar un artefacto sintético restringido si conoce su SHA-256.

**Impacto.** Se amplía el acceso de un nodo comprometido a datos ajenos a sus trabajos. El hash no es una autorización; conocerlo por registros, planes o transferencias anteriores es suficiente. No se ha demostrado una fuga real ni acceso sin autenticación.

**Cambio necesario.** Autorizar por nodo, intento, job y artefacto; emitir permisos acotados para entradas y salidas y asociar uploads a su propietario. Aplicar revocación y caducidad.

**Cierre verificable.** Otro Worker, un lease obsoleto y un nodo revocado deben recibir rechazo aunque presenten un hash válido. **Certeza:** descarga reproducida.

### H14 · P1 · Se puede promover éxito sin comprobar el artefacto de resultado

**Evidencia.** [trabajos.py:203](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/service/trabajos.py:203>) decide el estado por `outcome`, conserva el hash anterior si faltan artefactos y actualiza evidencia de capacidades. La comprobación de CAS de la línea 356 solo condiciona guardar la ubicación; ocurre después de registrar éxito.

**Reproducción.** La prueba de finalización produjo `EXPERIMENT_SUCCEEDED` sin aportar un paquete de resultado. El hash conservado no representa el resultado medido.

**Impacto.** Un bug o un Worker comprometido puede convertir una declaración en éxito/evidencia y condicionar decisiones posteriores. Verificar la integridad de un blob no verifica por sí solo la validez de sus métricas.

**Cambio necesario.** Esquema estricto de resultado por tipo de job; exigir artefactos esperados, CAS íntegro y coherencia entre suite, casos, snapshot, modelo e intento antes de promover. Separar declaración del Worker de evidencia comprobada por Coordinator.

**Cierre verificable.** Rechazar éxito sin paquete, con hash falso, esquema incorrecto o métricas discordantes. No modificar capacidades en esos casos. **Certeza:** reproducido e inspeccionado.

### H15 · P1 · Identidad de modelos y endpoint comprobado insuficientemente vinculados

**Evidencia.** [retrieval/executor.py:25](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/retrieval/executor.py:25>) valida longitud del fingerprint y después lo copia, sin calcularlo sobre el modelo cargado. Los fingerprints locales de profesor/alumno también se reciben y se reflejan en manifests. [broker/client.py:257](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/broker/client.py:257>) solo compara identidad servida si contiene las tres claves; omitirlas permite continuar. Los lanzadores de estrategia/agentes no atan `broker_endpoint` al informe de compatibilidad, a diferencia del profesor Broker de destilación, que sí lo hace.

**Reproducciones.** El cliente aceptó un resultado con `model_used={}` y telemetría vacía. Un informe sintético de compatibilidad de `:8765` autorizó un job destinado a `:9999`.

**Impacto.** Dos runs pueden aparentar mismo modelo/entorno sin demostrarlo. Un Worker toma su token del entorno y lo enviará al endpoint recibido; debe estar ligado al destino autorizado.

**Cambio necesario.** Fingerprint calculado por el Worker sobre pesos, configuración y tokenizer, revision inmutable y comparación con lo aprobado. Rechazar o clasificar como no verificable una identidad servida incompleta. Ligar compatibilidad, credencial, destino y vigencia; conservar por separado identidad lógica y hash de pesos.

**Cierre verificable.** Mutar pesos manteniendo nombre, omitir `served_by` o cambiar endpoint invalida la ejecución verificable. **Certeza:** dos reproducciones y verificación estática de fingerprints.

### H16 · P1 · El entrenamiento no necesita un baseline realmente válido

**Evidencia.** [entrenamiento.py:155](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/service/entrenamiento.py:155>) y la línea 250 solo exigen que baseline sea categoría `experiment` o `comparison`. Los informes de compatibilidad Broker también se guardan como experimentos, y los formularios enumeran todos los registros. No se exige ejecución completa, calidad medida, misma tarea ni comparación con prompting/RAG. `contains_mutable_facts=False` se fija en la propuesta de LoRA sin derivarlo del contenido o una decisión explícita.

**Impacto.** La regla “fine-tuning debe ganarse su existencia” es una declaración documental más fuerte que la puerta real. Se puede elegir un elemento que no es un baseline medido.

**Cambio necesario.** Contrato de baseline elegible, con procedencia, métricas, tarea/suite y estado verificado. Incorporar un criterio de éxito falsable y política de datos aprobada al plan; diferenciar exportación experimental de promoción validada.

**Cierre verificable.** Un check de conectividad, un run fallido/en cola y un baseline de otra tarea no deben autorizar training. **Certeza:** verificado en código.

### H17 · P1 · El Worker documentado para WSL no dispone de protección de secretos

**Evidencia.** [worker/cli.py:35](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/worker/cli.py:35>) llama obligatoriamente a `platform_secret_protector()`. [security/secrets.py:63](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/security/secrets.py:63>) solo implementa Windows y lanza una excepción fuera de `os.name == 'nt'`. El instalador WSL termina comprobando `--help`, que no llega a ese arranque.

**Impacto.** El perfil AMD/WSL no es solo una carga ML pendiente de probar: el flujo normal de pair/run ejecutado con Python de WSL tiene un bloqueo de software previo.

**Cambio necesario.** Proveedor de secretos para Linux/WSL, seleccionable e integrado en CLI, o arquitectura explícita de Worker Windows con ejecución WSL y puente probado. No degradar a credenciales en claro como solución.

**Cierre verificable.** Pair, almacenamiento protegido, reinicio, autenticación y job mínimo dentro del perfil WSL soportado. **Certeza:** ruta de fallo verificada en código; WSL no ejecutado.

### H18 · P2 · Costes, latencia y calidad no llegan íntegros a la comparación

**Evidencia.** [strategies/executor.py:73](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/strategies/executor.py:73>) guarda costes por caso, pero el retorno de las líneas 140–149 no expone coste agregado y el finalizador no lo incorpora al resumen. La latencia de suite suma tiempos Broker, excluyendo preparación y retrieval; los benchmarks de retrieval miden otro tramo. La calidad es una tasa de verificación determinista y no la fidelidad requerida por el selector.

**Impacto.** El usuario no puede tomar una decisión homogénea de coste/rendimiento/calidad. Comparar cifras con nombres iguales pero alcances distintos induce a error. Mantener desconocidos como desconocidos es correcto; perder medidas disponibles no lo es.

**Cambio necesario.** Contrato de métricas con unidad, alcance, denominador y procedencia: por caso, total de suite, p50/p95, carga, retrieval, generación, memoria pico, tokens y coste por moneda. Preservar lo conocido y no sumar un total “verificado” si faltan componentes. Separar validez de formato/citas de calidad de respuesta.

**Cierre verificable.** Los costes conocidos sobreviven a Worker → Coordinator → UI y las latencias comparadas cubren el mismo tramo. **Certeza:** verificado en código.

### H19 · P2 · Las misiones no son todavía un flujo reanudable ligado a evidencia

**Evidencia.** [mission.tsx:105](<D:/Desarrollo/Proyectos TFM/Local AI Lab/apps/desktop/src/mission.tsx:105>) guarda un único objeto en localStorage. Los pasos se marcan completados por `index < activeStep` y cualquier paso puede seleccionarse tras crear el plan. `continueFlow` solo cambia de pantalla o índice. [App.tsx:101](<D:/Desarrollo/Proyectos TFM/Local AI Lab/apps/desktop/src/App.tsx:101>) muestra datasets, trainings y exports bajo “Planes y borradores”, no una lista de misiones guardadas.

**Matiz.** Destilación sí precarga origen/modelos y criterio de éxito desde el borrador; no todo el contexto se pierde. Esa precarga parcial no crea una relación entre misión, recursos, jobs, métricas y resultado.

**Impacto.** Se puede aparentar etapas completadas sin ejecutarlas. No se pueden gestionar varios planes ni reanudar por el último paso comprobado. La pantalla inicial “Quiero entrenar un modelo”, con destilación seleccionada, y la opción “Fine-tuning + RAG” desplazan el propósito de comparar primero alternativas simples. “Que la app recomiende” hereda mensajes de dataset/entrenamiento incluso cuando no son requisitos de la estrategia.

**Cambio necesario.** Entidad persistente `Mission/ExperimentPlan` con tarea, restricciones, criterios, recursos y enlaces a jobs. Estado derivado de evidencia; diferenciar “visitado”, “configurado”, “ejecutado” y “validado”. Entrada principal “Resolver una tarea / comparar estrategias”, con prompting y RAG sin entrenamiento como opciones explícitas.

**Cierre verificable.** Dos misiones independientes, cierre/reapertura y salto entre pantallas conservan su contexto; visitar Exportar no completa Entrenar/Comparar. **Certeza:** revisión estática de UX.

### H20 · P2 · La revisión humana oculta precisamente la evidencia que debe revisar

**Evidencia.** [knowledge.tsx:73](<D:/Desarrollo/Proyectos TFM/Local AI Lab/apps/desktop/src/knowledge.tsx:73>) muestra JSON original/corrección, pero no renderiza `context.query`, prompt, contexto recuperado ni el diff; solo avisa de que el diff está registrado. No ofrece acciones de rechazo aunque el dominio contempla esos estados. Cambiar de revisión sustituye el editor sin aviso de cambios no guardados.

**Impacto.** Se pide aprobar evidencia sin presentarla y se obliga a editar estructura JSON. La revisión se vuelve lenta y propensa a errores; no es suficiente mostrar el estado del verificador.

**Cambio necesario.** Vista de pregunta/respuesta, citas navegables al snapshot, panel de contexto y diff real. Editor estructurado con JSON avanzado opcional; aceptar/rechazar/devolver con motivo y aviso de cambios pendientes. Mostrar límites de cada comprobación.

**Cierre verificable.** Un revisor localiza una afirmación, abre su chunk, corrige, ve el diff y acepta o rechaza sin editar IDs manualmente. **Certeza:** revisión estática de UX; no se midió tiempo de uso humano.

### H21 · P2 · Las garantías de “solo este equipo” son estáticas y excesivas

**Evidencia.** [App.tsx:76](<D:/Desarrollo/Proyectos TFM/Local AI Lab/apps/desktop/src/App.tsx:76>) y línea 82 siempre afirman “Solo este equipo”, “Todo se ejecuta en este equipo” y “Ningún dato sale del entorno local”. [mission.tsx:129](<D:/Desarrollo/Proyectos TFM/Local AI Lab/apps/desktop/src/mission.tsx:129>) repite la limitación aunque el plan use Worker remoto o Broker. El cliente sí envía `local_only` al Broker: no se ha demostrado una salida a cloud.

**Impacto.** Se confunde “sin cloud” con “sin transferencia entre equipos”. El operador no ve dónde se procesarán los datos ni qué servicio recibirá contenido.

**Cambio necesario.** Indicador derivado del plan: equipo/Worker, endpoint Broker, proveedor, clasificación y transferencias previstas. Mostrar “red privada/local” cuando corresponda. Para futuras excepciones cloud, autorización por ejecución con resumen de datos, modelo, presupuesto y política, sin afirmaciones fijas.

**Cierre verificable.** Un job remoto y otro local presentan destinos distintos y coherentes; ninguna etiqueta promete confinamiento físico no demostrado. **Certeza:** texto y rutas verificados, sin afirmar fuga real.

### H22 · P2 · Seguimiento, recuperación de errores y salida de resultados insuficientes

**Evidencia.** [App.tsx:55](<D:/Desarrollo/Proyectos TFM/Local AI Lab/apps/desktop/src/App.tsx:55>) carga una vez y después exige actualización manual. El Worker convierte fallos del ejecutor en tipo/código genéricos: [runtime.py:67](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/worker/runtime.py:67>). El puente HTTP Tauri no fija timeout en los clientes creados en [comandos.rs:476](<D:/Desarrollo/Proyectos TFM/Local AI Lab/apps/desktop/src-tauri/src/comandos.rs:476>) y línea 505. `RecordBoard` y las tablas de comparación muestran hashes, pero no acciones para abrir el informe o guardar el paquete exportado.

**Impacto.** Jobs que terminan pueden seguir pareciendo en cola; operaciones bloqueadas dejan un estado de espera sin límite de aplicación; errores como modelo ausente o memoria insuficiente pierden explicación. “Exporte correcto” no resuelve por sí solo cómo obtener el archivo.

**Cambio necesario.** Polling o eventos con reconexión y freshness visible; errores estructurados y saneados con causa, fase y acción recomendada; timeout y cancelación de solicitudes; acciones seguras de abrir informe/guardar paquete mediante backend/Tauri. Preservar claves de idempotencia al reintentar la misma intención.

**Cierre verificable.** Completar un job actualiza la vista sin intervención; una desconexión es recuperable; el usuario obtiene el informe y el paquete desde la app. **Certeza:** revisión estática.

### H23 · P2 · Overview no refleja las comprobaciones que el propio producto registra

**Evidencia.** [repository/capacidades.py:153](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/repository/capacidades.py:153>) devuelve siempre fase `phase1`, puerta `pending_real_nodes` y dependencias Broker/vault/Model Drift `unknown`. No deriva esos valores de los registros de producto. El estado de nodo se pone `online` al registrarse o enviar heartbeat y no se encontró una transición operativa de caducidad a offline. Las capacidades probadas se fusionan por rango, sin invalidarlas al cambiar entorno.

**Impacto.** Configuración y Evidencia pueden contradecir Experimentos; un equipo apagado conserva apariencia de disponible. Un cambio de modelo/runtime/hardware puede mantener pruebas antiguas como si siguieran vigentes.

**Cambio necesario.** Derivar estados de evidencia actual, fecha y configuración; conservar historial sin confundirlo con disponibilidad presente. Separar “registrado”, “conectado”, “capaz” y “probado para esta configuración”.

**Cierre verificable.** Una negociación válida actualiza dependencias; un heartbeat vencido cambia disponibilidad; una modificación de entorno exige revalidación. **Certeza:** verificado en código.

### H24 · P2 · Escalabilidad y operación prolongada no están cerradas

**Evidencia.** [http_transport.py:105](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/worker/http_transport.py:105>) descarga el artefacto completo en memoria y [runtime.py:138](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/worker/runtime.py:138>) vuelve a tratarlo como bloque completo. El workspace consulta todos los registros: [producto.py:77](<D:/Desarrollo/Proyectos TFM/Local AI Lab/src/local_ai_lab/coordinator/repository/producto.py:77>). Las suites reconstruyen snapshot/índice para cada ejecución. El log del sidecar se abre siempre en append: [coordinador.rs:55](<D:/Desarrollo/Proyectos TFM/Local AI Lab/apps/desktop/src-tauri/src/coordinador.rs:55>).

**Impacto.** El comportamiento con paquetes grandes y muchos experimentos puede degradar memoria, disco y tiempos. No se ha medido un límite real en esta auditoría; son riesgos derivados de operaciones concretas, no una afirmación de rendimiento observado.

**Cambio necesario.** Descarga a fichero por streaming con hash incremental y reanudación; paginación; reutilización de entradas inmutables; cuota y desglose de almacenamiento; rotación de logs y backup/restore probado. Limpieza como plan revisable que proteja evidencia retenida.

**Cierre verificable.** Transferencia interrumpida de un paquete grande, miles de registros y restauración de una copia, con presupuestos declarados de RAM, tiempo y disco. **Certeza:** riesgo técnico fundado; falta benchmark de escala.

### H25 · P2 · Seguridad distribuida documentada más amplia que la implementada

**Evidencia.** Fase A exige identidad Ed25519, mTLS, revocación, autorización por acción y manifests firmados. El código actual usa código de pairing, token bearer, hash y TLS mediante endpoint externo; no se encontró gestión operativa de certificados cliente, firmas de manifiestos ni un flujo de revocación en los puntos de entrada revisados. La documentación de Fase 1 reconoce parte de esta limitación.

**Impacto.** TLS del servidor, hash de contenido y token de acceso son controles útiles, pero no equivalen al modelo de confianza originalmente especificado. Antes de usar datos privados entre nodos debe estar decidida y probada esa frontera.

**Cambio necesario.** Acordar y documentar el modelo realmente soportado; implementar identidad/revocación y autorización por artefacto/job. Si se mantiene la terminación TLS externa, definir quién valida certificados, cómo rota credenciales y cómo se prueba la recuperación. Hash para integridad y firma/autenticación para procedencia deben distinguirse.

**Cierre verificable.** Nodo revocado no puede renovar, descargar o completar; certificado no válido se rechaza; un manifest alterado o emitido por un actor no autorizado no se acepta. **Certeza:** brecha de implementación/documentación; no prueba de penetración de la LAN.

### H26 · P2 · Documentación y verificación continua no representan el estado actual

**Evidencia.** README y estado de implementación afirman builds correctos y se apoyan en el corte del 25 de agosto; el commit actual es de septiembre y no compila. PRODUCT aún indica que no existen evidencias reales de Broker/vault, mientras otros documentos narran que sí las hubo. README vuelve a decir que los comandos de snapshot no se ejecutaron sobre el vault real. El manual mantiene nombres como “Operaciones” y “Conocimiento” junto a los actuales “Entrenamientos” y “Recursos”. Graphify apunta a archivos eliminados. No hay workflows versionados en `.github/workflows` ni pruebas de frontend declaradas en `package.json`.

**Impacto.** El usuario no sabe qué es histórico, qué está vigente ni qué build utiliza. La refactorización rompió el empaquetador y la ampliación del contrato rompió TypeScript sin que la suite Python lo detectara.

**Cambio necesario.** Un único estado de release con commit, versiones, comandos, resultados, artefactos y limitaciones; marcar informes antiguos como históricos. Actualizar manual desde flujos reales y regenerar el índice de código. Añadir verificación automatizada de contratos Python/TypeScript/Rust y smoke del paquete.

**Cierre verificable.** Un checkout nuevo sigue el manual, construye la misma release y completa el recorrido mínimo; cualquier divergencia contractual bloquea la integración. **Certeza:** comprobado documentalmente y con build.

## 5. Usabilidad por recorrido

**Todos los pasos de esta tabla se evaluaron desde el código; ninguno tiene captura de ejecución de esta auditoría.** El “estado” valora la completitud funcional observada, no la calidad visual renderizada.

| Paso | Qué intenta hacer el usuario | Estado | Cambio prioritario |
|---|---|---|---|
| 1 | Abrir la app y saber qué puede hacer | Parcial | Construcción fiable, estado de entorno real y entrada centrada en la tarea |
| 2 | Crear y guardar una misión | Parcial | Persistencia por misión; progreso por evidencia; lista real de planes |
| 3 | Preparar Broker y Workers | Incompleto | Descubrimiento/configuración asistida, disponibilidad vigente y solución WSL |
| 4 | Seleccionar vault, snapshot e índice | Implementado a nivel de servicio/UI | Selector explícito y contexto persistente; progreso y acceso a detalles |
| 5 | Definir benchmark del vault | Defectuoso | Editor guiado, citas verificadas y aprobación independiente |
| 6 | Ejecutar alternativas sobre ese benchmark | Bloqueado por integración | Llevar suite/snapshot/índice seleccionados hasta el Worker |
| 7 | Seguir o cancelar una ejecución | Defectuoso | Actualización automática, control fresco y errores recuperables |
| 8 | Revisar y corregir respuestas | Parcial | Contexto, citas, diff, rechazo y protección de cambios no guardados |
| 9 | Construir dataset | Parcial | Origen de ejemplos no reservados y exclusión global de benchmarks |
| 10 | Hacer preflight y entrenar/destilar | Parcial | Baseline válido, identidad de modelo y recuperación real por checkpoint |
| 11 | Evaluar el resultado entrenado | Defectuoso | Enlace verificable con adaptador y soporte de resultados destilados |
| 12 | Comparar, decidir y exportar | Parcial | Métricas completas, veredicto ligado a runs y apertura/descarga de artefactos |

### Accesibilidad: lo respaldado y lo pendiente

El código muestra buenas bases: botones, labels y selects nativos; `aria-current` en navegación; `aria-pressed` al elegir estrategia; mensajes `role=status/alert`; estados con texto; tratamiento de movimiento reducido y foco visible para algunos controles.

Persisten riesgos que requieren prueba visual y asistiva: tamaño de textos auxiliares de 10–12 px; foco al cambiar de sección sin navegación por URL ni gestión explícita; tablas/flujo horizontal con zoom; editores JSON extensos; lectura de errores y estados simultáneos. **No se concluye incumplimiento de contraste ni conformidad WCAG a partir del CSS.**

La prueba pendiente debe recorrer teclado completo, foco después de una operación y al cambiar de página, zoom al 200 %, lector de pantalla y estados vacíos/error. Debe realizarse sobre el paquete real y con datos sintéticos representativos.

## 6. Plan de mejora propuesto

El orden evita pulir pantallas que todavía presentan resultados o estados incorrectos. Los tamaños son orientativos de complejidad: S = cambio localizado; M = varias capas; L = cambio transversal. No son estimaciones de calendario.

| Orden | Entrega concreta | Hallazgos | Tamaño | Condición de salida |
|---|---|---|---|---|
| 1 | Release construible y trazable | H01, H26 | S–M | Frontend, sidecar y portable producidos desde el mismo commit |
| 2 | Protocolo recuperable y cancelable | H10–H12, H14 | L | Reinicio, replay y cancelación probados con fallos inyectados |
| 3 | Evidencia válida antes de decidir | H05–H09, H15–H16 | L | Ninguna recomendación/training con evidencia ausente, inválida o contaminada |
| 4 | Recorrido privado completo | H02 | L | Suite real y consulta de producción conectadas a revisión/dataset |
| 5 | Evaluación del modelo realmente generado | H03–H04 | L | F1/F2 usan adaptador identificado y admiten destilación |
| 6 | Red y Worker soportados | H13, H17, H25 | L | WSL o alternativa definida; autorización y revocación probadas |
| 7 | Métricas y decisión coherentes | H06, H18 | M–L | Coste, calidad, latencia y resultado formal comparables y trazables |
| 8 | Misiones y revisión utilizables | H19–H23 | M–L | El operador completa el recorrido sin JSON/rutas/IDs innecesarios |
| 9 | Operación sostenida | H24, H26 | M | Escala, almacenamiento, backup/restore y documentación verificados |

### Recorrido mínimo que debería exigirse para declarar la app útil

1. Instalar/abrir una release identificada y registrar un Worker soportado.
2. Crear un snapshot de un vault de prueba y validar integridad sin escribir en el origen.
3. Crear una suite humana pequeña sobre ese snapshot y reservar sus casos.
4. Ejecutar B1, R1 y R3 sobre los mismos casos; añadir R4 solo como hipótesis concreta.
5. Mostrar citas, respuesta, métricas comparables y límites; obtener el resultado formal cuando corresponda.
6. Registrar una decisión que pueda recomendar quedarse con prompting/RAG.
7. Por un canal distinto, recoger ejemplos de uso autorizados y revisarlos; construir un dataset no contaminado.
8. Justificar entrenamiento, ejecutar preflight y entrenar/destilar con identidad y checkpoints verificables.
9. Evaluar ese adaptador concreto contra el baseline reservado.
10. Obtener un paquete y un informe recuperables; reiniciar y reconstruir toda la trazabilidad desde la app.

Durante el recorrido se debe interrumpir al menos una conexión, repetir una confirmación y cancelar un job iniciado. El objetivo es demostrar que el resultado sigue siendo válido y recuperable, no solo que cada botón devuelve una respuesta.

## 7. Pruebas que faltan en la estrategia actual

| Área | Caso que debe añadirse | Riesgo que evita |
|---|---|---|
| Build | Contrato de fase Broker y empaquetador tras mover módulos | Release que pasa Python pero no se puede distribuir |
| Misiones | Recarga con varios planes y avance solo por evidencia | Progreso ficticio o pérdida de contexto |
| Corpus real | Snapshot seleccionado llega al runner y sus referencias existen | Comparar inadvertidamente el corpus sintético |
| Evaluación | `answer` factual sin findings, JSON mal tipado y citas irrelevantes | Aprobación falsa o abortos por salida del modelo |
| Dataset | Todos los benchmarks registrados y variantes de ID/contenido | Contaminación de entrenamiento |
| Modelo | Adaptador ausente, identidad servida incompleta, pesos modificados | Comparación de un modelo diferente |
| Selector | Runs pendientes, calidad ausente, datos desconocidos, empate y simplicidad | Recomendaciones sin sustento |
| Formal | Resultado ligado exactamente a sus dos runs | Casilla formal imposible de satisfacer o evidencia heredada |
| Worker | Cancelar después del primer control y durante training | Trabajo atascado/consumo innecesario |
| Persistencia | Respuesta complete perdida y caída en mitad del finalizador | Replay fallido o efectos parciales |
| Recuperación | Lease vencido, reinicio antes de ack y reasignación al mismo nodo | Jobs huérfanos permanentes |
| Seguridad | Descarga/subida ajenas, revocación, claims de éxito sin CAS | Acceso excesivo o evidencia falsa |
| Plataformas | Pair/run real dentro del perfil WSL | Instalador que solo supera `--help` |
| Usabilidad | Recorrido de doce pasos, teclado, zoom y lector de pantalla | Flujos técnicamente presentes pero impracticables |

## 8. Entregables y reproducción

El informe completo es este archivo. Las reproducciones están en [reproducir_hallazgos.py](<D:/Desarrollo/Proyectos TFM/Local AI Lab/docs/Auditoria 20260929/reproducir_hallazgos.py>) y su salida en [resultados_reproducciones.json](<D:/Desarrollo/Proyectos TFM/Local AI Lab/docs/Auditoria 20260929/resultados_reproducciones.json>). Cada ejecución crea una carpeta sintética nueva junto al script; no sobrescribe bases del usuario ni contacta servicios externos. Usa algunas ayudas de tests para construir estados controlados, y no constituye una validación ML ni una prueba de ataque a servicios reales.

Desde la raíz del proyecto:

```powershell
rtk proxy python -X utf8 "docs/Auditoria 20260929/reproducir_hallazgos.py"
```

Las pruebas existentes se ejecutaron con almacenamiento temporal bajo `.audit-20260929-tests`. Se conservan los artefactos sintéticos para trazabilidad. No se realizó commit, despliegue ni modificación de las aplicaciones vecinas.

**Decisión recomendada:** conservar la arquitectura y priorizar el cierre del recorrido y la veracidad de la evidencia. La próxima versión debe demostrar que compara los datos y modelos seleccionados, que puede detenerse y recuperarse, y que el usuario puede inspeccionar por qué se recomienda una estrategia. Esas son las condiciones para que el laboratorio cumpla su propósito.
