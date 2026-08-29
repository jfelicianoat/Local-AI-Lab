# Manual de uso de Local AI Lab

Versión del manual: 1.0  
Aplicación documentada: Local AI Lab 0.1.0  
Fecha de revisión: 24 de agosto de 2026

## 1. Qué es Local AI Lab

Local AI Lab es un laboratorio privado para comparar estrategias de inteligencia artificial sobre conocimiento local, revisar sus respuestas, preparar datos aprobados y ejecutar entrenamiento y exportación de modelos con evidencia recuperable.

La aplicación no es un chat de propósito general. Su unidad de trabajo es un **ensayo**: cada resultado queda relacionado con el snapshot, los modelos, el Worker, los parámetros y los hashes que lo produjeron.

Sus reglas principales son:

- Los vaults se abren en **solo lectura**. Los snapshots e índices se escriben fuera del vault.
- AI Broker se usa por su contrato HTTP público. Local AI Lab no lee ni modifica su base de datos, repositorio o configuración.
- Model Drift se usa por su CLI pública. Local AI Lab no accede a su persistencia.
- Los modelos se identifican de forma exacta. No se permite un cambio silencioso de modelo ni fallback.
- Un dato no entra en entrenamiento por haber sido corregido: necesita revisión aceptada y una segunda aprobación explícita.
- Las comparaciones conservan sus métricas por separado; no inventan una puntuación global.
- `UNKNOWN` significa «no comprobado», no «ausente» ni «incompatible».

## 2. Componentes

| Componente | Función |
|---|---|
| Aplicación de escritorio | Interfaz principal del operador. |
| Coordinator | Guarda el estado, aplica las puertas de seguridad y distribuye trabajos. Se inicia automáticamente con el escritorio. |
| Worker | Ejecuta cargas en un equipo autorizado: embeddings, inferencia, entrenamiento o conversión. |
| AI Broker | Servicio externo que ejecuta inferencias, agentes y mezclas de agentes. |
| Model Drift | Aplicación externa que realiza la comparación formal entre tratamientos R3 y R4. |
| Vault | Carpeta de notas privada; en este equipo la raíz prevista es `Y:\Mi unidad\Vaults`. |

## 3. Antes de empezar

### 3.1 Requisitos mínimos para abrir la aplicación

1. Localice esta carpeta:

   `D:\Desarrollo\Proyectos TFM\Local AI Lab\apps\desktop\src-tauri\target\release`

2. Compruebe que están presentes:

   - `local-ai-lab-desktop.exe`
   - la carpeta `resources`
   - dentro de `resources`, `local-ai-lab-coordinator.exe`

3. No separe el ejecutable de la carpeta `resources`. El Coordinator empaquetado es necesario para arrancar.

Para explorar la interfaz, crear snapshots y ejecutar R1 no hacen falta AI Broker, Model Drift ni un Worker. Las operaciones distribuidas sí necesitan sus dependencias correspondientes.

### 3.2 Requisitos por tipo de operación

| Operación | Requisito adicional |
|---|---|
| Snapshot e índice | Acceso de lectura a la raíz de vaults. |
| R1 controlado | Ninguno. Es local y sintético. |
| R2, R3 y R4 | Worker conectado con `embeddings.semantic` probado y modelo de embeddings ya cacheado. |
| B0–F2 | Worker, AI Broker compatible y modelo exacto disponible. |
| A1/M1 | AI Broker 2.9 compatible con agentes/client tools o mixture of agents. |
| Comparación formal | R3 y R4 comparables y Model Drift con `evaluar-tratamientos`. |
| Entrenamiento | Dataset aprobado, Worker preparado, modelo base local y preflight superado. |
| Exportación | Entrenamiento completado y formato probado por el Worker. |

### 3.3 Datos y privacidad

Por defecto, el estado del escritorio se guarda en:

`%LOCALAPPDATA%\lab.localai.desktop`

Los elementos más importantes son:

- `coordinator\state.db`: estado local del laboratorio.
- `coordinator.log`: registro de arranque y errores del Coordinator.
- artefactos, snapshots e índices bajo las carpetas administradas por el Coordinator.

No edite `state.db` manualmente. Para una copia de seguridad, cierre Local AI Lab y copie la carpeta completa `lab.localai.desktop` a un destino seguro.

## 4. Abrir, actualizar y cerrar

### Abrir

1. Ejecute `local-ai-lab-desktop.exe`.
2. Espere a que desaparezca **Iniciando el Coordinator local…**.
3. Confirme que aparece la página **Resumen**.
4. Si se muestran datos anteriores, pulse **Actualizar evidencia**.

El escritorio elige un puerto local libre y crea un token interno nuevo. No es necesario configurar ninguno de los dos.

### Cerrar

1. Espere a que termine cualquier operación local corta.
2. Para un job distribuido, revise antes su estado en **Operaciones > Jobs distribuidos**.
3. Cierre la ventana. El escritorio detiene el Coordinator que inició.

Un Worker puede conservar progreso pendiente en su propio journal si pierde la conexión. El estado debe revisarse al volver a abrir la aplicación.

### Si el ejecutable se cierra solo

1. Compruebe que `resources\local-ai-lab-coordinator.exe` sigue junto al portable.
2. Abra `%LOCALAPPDATA%\lab.localai.desktop\coordinator.log`.
3. Busque el último error de arranque.
4. Desde la carpeta del proyecto puede ejecutar `scripts\smoke_desktop.ps1` para comprobar el portable.
5. Si el smoke falla, regenere primero el sidecar con `scripts\build_sidecar.ps1` y después el portable con `scripts\build_desktop.ps1 -Target Portable`.

## 5. Cómo leer la interfaz

La navegación izquierda agrupa nueve áreas:

1. **Resumen**: puerta actual, evidencia y dependencias externas.
2. **Nodos**: Workers registrados, estado y capacidades probadas.
3. **Conocimiento**: descubrimiento de vaults, snapshots e índices.
4. **Experimentos**: benchmarks, estrategias, Broker, Model Drift y selector.
5. **Revisiones**: corrección y aprobación humana.
6. **Datasets**: creación de versiones inmutables a partir de candidatos aprobados.
7. **Operaciones**: preflight, entrenamiento, exportación, progreso y cancelación.
8. **Registros**: historial de trabajos, estado, Worker, etapa y correlación para diagnóstico.
9. **Métricas**: comparación de resultados por configuración experimental completa.

La columna derecha muestra la **puerta actual**:

- **Puerta abierta**: toda la evidencia exigida para esa puerta está registrada.
- **Puerta pendiente**: falta evidencia o existe un bloqueo.
- **PROBADO**: existe evidencia real recuperable.
- **DETECTADO**: se observó una capacidad, pero no se probó con la carga correspondiente.
- **PENDIENTE**: aún no hay prueba.
- **BLOQUEADO**: el sistema conoce la condición que impide continuar.

Después de que termine un Worker o una herramienta externa, pulse **Actualizar evidencia**. La pantalla no se refresca continuamente por sí sola.

## 6. Preparación inicial

### Caso 1. Comprobar AI Broker sin modificarlo

1. Abra **Experimentos**.
2. Busque **AI Broker · negociación read-only**.
3. Escriba el endpoint. En esta red se ha usado `http://192.168.1.52:8765`.
4. Seleccione la fase:

   - **Conectividad básica** para `phase0`.
   - **Generación RAG** para `retrieval`.
   - **Evaluación formal 2.9** para `formal_evaluation`.
   - **A1 + M1 (2.9)** para `agent_experiments`.

5. Si el Broker exige autenticación, escriba el token en **Token efímero**.
6. Pulse **Consultar health + capabilities**.
7. Lea el resultado:

   - `SATISFIED`: la fase está cubierta.
   - `UPGRADE_REQUIRED`: faltan capacidades anunciadas; instale una versión compatible antes de esa fase.
   - `UNKNOWN`: no pudo confirmarse por red, autenticación o respuesta no reconocida. No implica que haya que actualizar.

La consulta solo realiza `GET /health` y `GET /api/v1/capabilities`. El token no se guarda. Bórrelo del campo al terminar.

### Caso 2. Comprobar un nodo antes de registrarlo

Este caso es de administración y se realiza una vez en cada equipo Worker.

1. Abra PowerShell en la carpeta de Local AI Lab.
2. Active el entorno correspondiente al Worker.
3. Genere el informe de capacidades:

   ```powershell
   $env:PYTHONPATH = "src"
   python -m local_ai_lab.cli probe-node --data-root "." --output "artifacts/phase0/node-report.json"
   ```

4. Verifique su hash:

   ```powershell
   python -m local_ai_lab.cli verify-report "artifacts/phase0/node-report.json"
   ```

5. Recuerde: el probe marca capacidades **detectadas**. Solo un smoke real de cada carga puede convertirlas en **probadas**.

### Caso 3. Emparejar un Worker

La pantalla **Nodos** es de consulta; el alta se realiza desde administración. El Coordinator
que arranca automáticamente con el escritorio escucha solo en este equipo. Para Workers en
otros ordenadores debe desplegarse un Coordinator accesible por TLS y abrir el escritorio
contra ese servicio administrado.

1. En el equipo Coordinator, usando la base de datos del servicio desplegado, genere un código de un solo uso:

   ```powershell
   $env:PYTHONPATH = "src"
   python -m local_ai_lab.cli pair-code --database ".local/coordinator/state.db" --valid-seconds 300
   ```

2. En el Worker, instale el perfil apropiado:

   ```powershell
   .\scripts\install_worker.ps1 -Profile Core
   ```

   Use `Nvidia` para preparar el perfil NVIDIA. Para AMD/WSL use `bash scripts/install_worker_wsl.sh` dentro de WSL.

3. Empareje el Worker con un endpoint TLS del Coordinator:

   ```powershell
   .\.venv-worker\Scripts\local-ai-lab-worker.exe `
     --endpoint "https://coordinator.lan" `
     --node-id "worker-01" `
     --data-root ".local-worker" `
     pair --pairing-code "<codigo>"
   ```

4. Inícielo con el informe creado:

   ```powershell
   .\.venv-worker\Scripts\local-ai-lab-worker.exe `
     --endpoint "https://coordinator.lan" `
     --node-id "worker-01" `
     --data-root ".local-worker" `
     run --capability-report "artifacts\phase0\node-report.json"
   ```

5. En el escritorio, abra **Nodos** y pulse **Actualizar evidencia**.
6. Compruebe el nombre, el estado, las capacidades y el heartbeat.

El Worker protege su credencial con DPAPI en Windows y no la imprime. El emparejamiento remoto por HTTP sin TLS se rechaza.

## 7. Conocimiento privado

### Caso 4. Descubrir vaults

1. Abra **Conocimiento**.
2. En **Raíz permitida de vaults**, deje o escriba `Y:\Mi unidad\Vaults`.
3. Pulse **Buscar vaults**.
4. Compruebe el número encontrado.
5. Seleccione uno en **Vault**.

Solo se muestran vaults hijos de la raíz permitida. Una ruta fuera de ella o un enlace que intente escapar debe ser rechazado.

### Caso 5. Crear un snapshot de solo lectura

1. Complete el caso anterior.
2. Seleccione el vault.
3. Pulse **Crear snapshot read-only**.
4. Espere el mensaje final.
5. Acepte como utilizable únicamente un registro con estado `COMPLETE`.
6. Guarde como referencia el SHA-256 mostrado en su tarjeta.

Si los archivos cambian mientras se leen, el snapshot queda `INCOMPLETE`. No lo use: estabilice el vault y cree otro. El snapshot no modifica contenido, tamaño ni fecha de las notas.

### Caso 6. Construir o actualizar el índice

1. En **Conocimiento**, seleccione un **Snapshot completo**.
2. Pulse **Construir índice**.
3. Espere un registro `READY`.
4. Si ya existía un índice, la aplicación crea una nueva generación incremental; no sobrescribe la anterior como si fuera el mismo artefacto.

Repita snapshot e índice cuando cambie el conocimiento que desea evaluar. No compare ensayos de snapshots distintos como si fueran equivalentes.

## 8. Benchmarks y estrategias

### Significado de las estrategias

| ID | Estrategia |
|---|---|
| B0 | Modelo base con prompt mínimo. |
| B1 | Modelo base con prompt optimizado. |
| R1 | RAG lexical. |
| R2 | RAG semántico. |
| R3 | RAG híbrido lexical + semántico. |
| R4 | R3 más expansión por grafo/wikilinks; es una alternativa experimental, no una mejora garantizada. |
| L1 | Modelo local de mayor capacidad con el mejor RAG. |
| F1 | Modelo fine-tuned. |
| F2 | Modelo fine-tuned con RAG. |
| A1 | Agente del Broker con retrieval como herramienta. |
| M1 | Mixture of agents del Broker con RAG. |

### Caso 7. Ejecutar R1 controlado

1. Abra **Experimentos**.
2. En **R1 · baseline lexical**, elija `k`, el número máximo de resultados recuperados. Empiece con 5.
3. Pulse **Ejecutar R1 controlado**.
4. Espere el registro.
5. Interprete el estado:

   - `LOCAL_VERIFIED`: el ground truth usado estaba aprobado.
   - `PENDING_HUMAN_REVIEW`: la ejecución terminó, pero falta aprobar el ground truth.

R1 usa un corpus sintético local. No usa el vault real ni AI Broker.

### Caso 8. Ejecutar R2, R3 o R4 de retrieval

1. Confirme en **Nodos** que el Worker anuncia `embeddings.semantic` como **probado**.
2. Confirme que el modelo de embeddings ya está en su caché local. La aplicación no lo descargará.
3. Abra **Experimentos > R2–R4 · retrieval con embeddings**.
4. Seleccione R2, R3 o R4.
5. Seleccione el Worker.
6. Escriba la ruta o ID exacto del modelo de embeddings.
7. Escriba los 64 caracteres del SHA-256 del modelo o caché.
8. Escriba el dispositivo probado: `cpu`, `cuda` o `mps` según corresponda.
9. Ajuste `k` en el bloque R1; ese valor también se utiliza aquí.
10. Pulse **Enviar benchmark**.
11. Abra **Operaciones**, siga el job y pulse **Actualizar evidencia** cuando termine.
12. Confirme `EXPERIMENT_SUCCEEDED` antes de usar el resultado en otra comparación.

Si el botón está desactivado, revise Worker, modelo, hash de 64 caracteres y dispositivo.

### Caso 9. Registrar un benchmark humano del vault real

1. Cree primero un snapshot `COMPLETE`.
2. Abra **Experimentos > Benchmark A · vault real**.
3. Pulse **Preparar plantilla del snapshot**.
4. En **Definición revisada**, complete el JSON sin eliminar estos principios:

   - `training_eligible` debe permanecer en `false`.
   - `snapshot_hash` debe ser el hash del snapshot elegido.
   - `human_review.status` debe ser `approved`.
   - cada caso necesita `case_id`, consulta y respuesta de referencia humana.
   - cada evidencia debe identificar nota, ruta, sección, chunk y referencia al snapshot.

5. Escriba el nombre del revisor humano.
6. Compruebe cada referencia contra el snapshot.
7. Pulse **Validar y registrar benchmark real**.
8. Confirme el estado `HUMAN_APPROVED`.

La aplicación rechaza JSON inválido, referencias inexistentes, hashes incorrectos y referencias de otro snapshot.

### Caso 10. Ejecutar B0–F2 con contrato común

1. Compruebe AI Broker para **Generación RAG** y conserve un informe satisfecho.
2. Confirme que el Worker está conectado y tiene probada la carga necesaria.
3. Abra **Experimentos > B0–F2 · contrato común de estrategia**.
4. Seleccione la estrategia.
5. Seleccione el informe Broker satisfecho.
6. Seleccione el Worker y escriba el endpoint del Broker.
7. Complete proveedor, deployment y modelo exactos.
8. Para R2, R3, R4, L1 o F2, complete también modelo de embeddings, SHA-256 y dispositivo.
9. Para F1 o F2, seleccione un entrenamiento Local AI Lab con estado `TRAINING_SUCCEEDED`.
10. Pulse **Ejecutar estrategia**.
11. Siga el job en **Operaciones**.
12. Revise sus métricas y respuestas solo cuando aparezca `EXPERIMENT_SUCCEEDED`.

El Worker obtiene el token del Broker desde su almacén local o la variable `LOCAL_AI_LAB_BROKER_TOKEN`; el job no lo transporta.

### Caso 11. Comparar formalmente R3 y R4 con Model Drift

1. Termine un R3 y un R4 con estado `EXPERIMENT_SUCCEEDED`.
2. Compruebe que ambos usan la misma suite, snapshot, casos, `k`, modelo y huella de embeddings, modelo generativo y orden de tratamientos.
3. Abra **Experimentos > Evaluación formal · Model Drift**.
4. Seleccione el R3 y el R4.
5. Indique el ejecutable público, por ejemplo `...\Model_Drift\.venv\Scripts\model-drift.exe`.
6. Indique la carpeta de trabajo de Model Drift.
7. Marque la confirmación de ejecución externa.
8. Pulse **Ejecutar comparación formal**.
9. Espere el informe y confirme `MODEL_DRIFT_VERIFIED`.
10. Lea el veredicto, la potencia y las limitaciones. Un resultado favorable a R3 o R4 solo describe esa configuración; con pocos casos no demuestra superioridad general ni equivalencia.

La aplicación identifica cada resultado por la configuración completa. Por ejemplo, en las pruebas existentes R4 superó a R3 con `bert-base-uncased`, pero quedó por debajo con `all-MiniLM-L6-v2`. Con cinco casos no hay potencia para generalizar.

Local AI Lab entrega ZIPs ya calculados y un plan sellado. Model Drift verifica orden, identidad y hashes. Si su CLI no expone `evaluar-tratamientos`, la operación se bloquea: hay que instalar una versión compatible de Model Drift.

### Caso 12. Ejecutar A1 o M1

1. Compruebe AI Broker con **A1 + M1 (2.9)**.
2. Confirme un Worker con embeddings probados.
3. Abra **Experimentos > A1 / M1 · AI Broker + RAG**.
4. Seleccione A1 o M1.
5. Seleccione el informe Broker 2.9 satisfecho.
6. Complete endpoint y Worker.
7. Complete proveedor, deployment y modelo exactos.
8. Complete modelo de embeddings cacheado, SHA-256 y dispositivo.
9. Pulse **Ejecutar suite A1/M1**.
10. Siga el job y revise el resultado completado.

Local AI Lab resuelve retrieval; el Broker conserva su runtime de agente o mezcla. La frontera se fija como `local_only`, sin fallback y excluida de aprendizaje.

### Caso 13. Generar una recomendación de estrategia

1. Complete al menos dos ejecuciones comparables con estado satisfactorio.
2. Abra **Experimentos > Selector de estrategia**.
3. Marque los ensayos que desea comparar.
4. Indique el mínimo de casos comparables.
5. Si la decisión lo exige, marque **Exigir veredicto formal de Model Drift**.
6. Pulse **Generar recomendación**.
7. Lea el estado:

   - `RECOMMENDATION`: hay evidencia suficiente bajo las restricciones.
   - `INSUFFICIENT_EVIDENCE`: faltan casos, comparabilidad o veredicto.

8. Lea siempre la incertidumbre. La recomendación no activa automáticamente ninguna estrategia.

### Caso 14. Seguir una ejecución en Registros

1. Abra **Registros** en el grupo **Observabilidad**.
2. Use el buscador para localizar un job por identificador, correlación, Worker o estado.
3. Seleccione el job en la lista.
4. Revise Worker, duración, configuración y última etapa en el panel de detalle.
5. Recorra la línea temporal para distinguir creación, asignación, ejecución y resultado.
6. Copie el identificador de correlación cuando necesite relacionar el trabajo con un informe o diagnóstico.

Un trabajo en `failed`, `orphaned` o `needs_review` aparece como atención requerida; Registros no lo reintenta ni lo oculta.

### Caso 15. Comparar resultados en Métricas

1. Abra **Métricas** en el grupo **Observabilidad**.
2. Compruebe cuántas ejecuciones tienen métricas, verificación formal y una muestra de al menos 20 casos.
3. Busque o filtre mentalmente por la configuración exacta mostrada: estrategia, embedding, huella corta, `k`, suite y snapshot.
4. Compare recall, nDCG, MRR, latencia y tamaño de muestra.
5. Lea **Alcance de la conclusión** antes de elegir una estrategia.

No compare filas de configuraciones distintas como si aislaran únicamente R3 frente a R4. Si hay menos de 20 casos, la interfaz marca que la evidencia es insuficiente para generalizar.

## 9. Revisión humana y datasets

### Caso 16. Corregir y aceptar una respuesta

1. Abra **Revisiones**.
2. Seleccione un caso en la cola izquierda.
3. Compare **Respuesta original** con las evidencias y el snapshot indicados.
4. Edite **Corrección** como un objeto JSON válido.
5. Pulse **Guardar y verificar**.
6. Confirme **Evidencia verificada** y que el diff quedó registrado.
7. Pulse **Enviar revisión**. El estado pasa de `draft` a `submitted`.
8. Una persona autorizada revisa el resultado y pulsa **Aceptar revisión**. Pasa a `accepted`.

Una revisión aceptada queda cerrada para edición. Si la verificación determinista falla, corrija los errores antes de enviarla.

### Caso 17. Aprobar un candidato para entrenamiento

1. Parta de una revisión `accepted` con training `excluded`.
2. Pulse **Proponer para training**. El estado pasa a `proposed`.
3. Realice una segunda comprobación de calidad, privacidad, licencia y ausencia de contaminación.
4. Pulse **Aprobar training**. El estado pasa a `approved`.

Corregir, aceptar y aprobar para entrenamiento son tres decisiones distintas. No use los benchmarks ni sus respuestas de referencia como datos de training.

### Caso 18. Construir un dataset aprobado

1. Confirme que existe al menos un candidato de training `approved`.
2. Abra **Datasets**.
3. Escriba un nombre de versión descriptivo, por ejemplo `feedback-privado-v1`.
4. Escriba una semilla de split estable de al menos 8 caracteres.
5. Pulse **Construir dataset aprobado**.
6. Confirme `READY_FOR_TRAINING` y el número de ejemplos incluidos.
7. Observe que los candidatos usados pasan a `exported` para evitar su reutilización silenciosa.

El constructor deduplica ejemplos y excluye automáticamente IDs y fingerprints de benchmark.

## 10. Entrenamiento, exportación y jobs

### Caso 19. Ejecutar el preflight obligatorio

1. Abra **Operaciones > 1 · Prueba corta obligatoria**.
2. Seleccione un dataset `READY_FOR_TRAINING`.
3. Seleccione el Worker.
4. Escriba la ruta o ID exacto del modelo base ya presente en el Worker.
5. Seleccione `bf16` o `fp16` según la capacidad probada.
6. Pulse **Ejecutar C1–C6 + 8 ejemplos + resume**.
7. Siga el job en la tabla.
8. Pulse **Actualizar evidencia** al terminar.
9. Continúe únicamente si aparece `PREFLIGHT_PASSED`.

El preflight comprueba compatibilidad, memoria, carga corta, checkpoint, reanudación y recarga. No sustituya esta evidencia por una casilla o una estimación manual.

### Caso 20. Autorizar un entrenamiento LoRA

1. Abra **Operaciones > 2 · Entrenamiento largo autorizado**.
2. Seleccione el preflight aprobado.
3. Seleccione un baseline comparable.
4. Elija el objetivo: formato, comportamiento, clasificación, selección de tools o argumentos estructurados.
5. Escriba una hipótesis falsable: qué espera mejorar y cómo decidirá si ocurrió.
6. Escriba quién lo aprueba.
7. Pulse **Autorizar entrenamiento**.
8. Siga estados, progreso y checkpoints en **Jobs distribuidos**.
9. Use el resultado solo con `TRAINING_SUCCEEDED`.

La aplicación fija una época desde esta interfaz. El Worker debe conservar checkpoints y validar la recarga del resultado.

### Caso 21. Exportar un modelo o adaptador

1. Abra **Operaciones > 3 · Exportación verificable**.
2. Seleccione un entrenamiento `TRAINING_SUCCEEDED`.
3. Seleccione un Worker que tenga probada la conversión requerida.
4. Marque uno o más formatos:

   - `adapter`
   - `merged_model`
   - `safetensors`
   - `gguf`

5. Escriba la licencia aplicable.
6. Escriba el runtime de serving, por ejemplo `transformers`.
7. Si eligió GGUF, indique el conversor local de llama.cpp.
8. Pulse **Crear paquete exportable**.
9. Espere `EXPORT_SUCCEEDED`.
10. Verifique el manifiesto y los SHA-256 antes de mover o publicar el paquete.

La existencia de un conversor no basta: su formato debe aparecer como probado en el heartbeat del Worker.

### Caso 22. Seguir o cancelar un job

1. Abra **Operaciones > Jobs distribuidos**.
2. Identifique el job por tipo, ID y correlation ID.
3. Revise estado, nodo asignado y progreso.
4. Para detener uno cancelable, pulse **Cancelar**.
5. Espere `cancelling` y después `cancelled`; pulse **Actualizar evidencia**.

Estados habituales:

| Estado | Significado y acción |
|---|---|
| `ready` | Espera un Worker compatible. |
| `leased` / `acknowledged` | El Worker lo recibió. |
| `running` | Está ejecutándose. |
| `paused` | Existe checkpoint; puede reanudarse. |
| `cancelling` | La cancelación fue solicitada. |
| `succeeded_pending_sync` | Terminó en el Worker y falta sincronizar. |
| `succeeded` | Terminado y sincronizado. |
| `failed_pending_sync` / `failed` | Falló; revise progreso, resultado y logs. |
| `orphaned` | Se perdió el lease o la conexión; no lo duplique manualmente. |
| `needs_review` | Hace falta decisión humana antes de reanudar o reemplazar. |

La cancelación es cooperativa: no apague el equipo salvo emergencia, porque podría impedir el checkpoint y la sincronización final.

## 11. Verificación real de Fase 8

Este procedimiento sirve para repetir una comprobación no destructiva de Broker/Model Drift desde un PowerShell normal del equipo:

1. Abra PowerShell en la raíz del proyecto.
2. Cargue el token sin escribirlo en un archivo ni en el historial:

   ```powershell
   $env:LOCAL_AI_LAB_BROKER_TOKEN = Read-Host "Token de AI Broker"
   ```

3. Para comprobar Broker, modelo exacto e inferencia aislada:

   ```powershell
   .\scripts\verify_phase8_real.ps1
   ```

4. Para incluir una comparación R3/R4 existente:

   ```powershell
   .\scripts\verify_phase8_real.ps1 -Plan "ruta\plan.json" -Report "ruta\informe.html"
   ```

5. Para comprobar solo contrato y artefactos, sin inferencia:

   ```powershell
   .\scripts\verify_phase8_real.ps1 -SkipInference
   ```

6. Elimine el token del entorno al terminar:

   ```powershell
   Remove-Item Env:\LOCAL_AI_LAB_BROKER_TOKEN
   ```

No pase el token como argumento ni lo copie al manual, a un informe o a una captura.

## 12. Recorridos recomendados

### Primera prueba segura, sin datos privados

1. Abra la aplicación.
2. Revise **Resumen**.
3. Ejecute R1 controlado.
4. Revise el registro y su hash.
5. Si dispone de Worker y embeddings, ejecute R2, R3 y R4 sobre el corpus controlado.
6. Compare R3 y R4 con Model Drift.

### Evaluación con un vault real

1. Descubra el vault.
2. Cree snapshot `COMPLETE`.
3. Construya el índice.
4. Redacte y apruebe el benchmark real.
5. Compruebe Broker.
6. Ejecute estrategias sobre la misma suite y snapshot.
7. Revise manualmente respuestas y citas.
8. Genere una recomendación solo con resultados comparables.

### De feedback a modelo exportado

1. Ejecute una estrategia real.
2. Corrija y verifique la respuesta.
3. Envíe y acepte la revisión.
4. Proponga y apruebe separadamente el candidato.
5. Construya un dataset inmutable.
6. Ejecute y supere el preflight.
7. Autorice el entrenamiento con hipótesis y baseline.
8. Compruebe `TRAINING_SUCCEEDED`.
9. Exporte únicamente formatos probados.
10. Verifique manifiesto y hashes.

## 13. Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| La aplicación muestra que el Coordinator no pudo iniciarse | Falta el sidecar, la carpeta de datos no es escribible o el proceso auxiliar no arranca | La ventana permanece abierta para mostrar el error. Revise `resources`, los permisos de la carpeta de datos y `coordinator.log`; después pulse **Reintentar conexión**. |
| **Mostrando la última evidencia recibida** | El Coordinator dejó de responder durante una actualización | Pulse **Volver a intentar**; si persiste, cierre, revise el log y reabra. |
| No aparecen vaults | Unidad Y: no montada, raíz incorrecta o sin permisos de lectura | Abra la ruta en el Explorador y vuelva a buscar. |
| Snapshot `INCOMPLETE` | El vault cambió durante la lectura | Espere a que termine la sincronización y cree uno nuevo. |
| No se puede construir el índice | El snapshot no es `COMPLETE` | Seleccione o cree un snapshot completo. |
| No aparece ningún Worker | No está emparejado, ejecutándose o sincronizado | Revise Worker, endpoint TLS y heartbeat; actualice evidencia. |
| Botón R2–R4 desactivado | Falta Worker, modelo, hash válido o dispositivo | Complete todos los campos y use un SHA-256 de 64 caracteres. |
| `UPGRADE_REQUIRED` en Broker | El contrato observado no cubre la fase | Instale una versión que anuncie las capacidades ausentes y repita la consulta. |
| `UNKNOWN` en Broker | Red, token o respuesta no confirmada | Compruebe conectividad y autenticación antes de concluir incompatibilidad. |
| Model Drift se bloquea | CLI antigua, falta confirmación o tratamientos no comparables | Compruebe `evaluar-tratamientos`, rutas, hashes, R3/R4 y la casilla de confirmación. |
| No se puede enviar una revisión | Corrección inválida o evidencia no verificada | Guarde un objeto JSON válido y resuelva los errores de verificación. |
| No se puede crear dataset | No hay candidatos `approved` | Complete revisión, aceptación, propuesta y aprobación. |
| No se puede entrenar | Dataset, preflight, baseline, hipótesis o aprobador ausentes | Complete la cadena de autorización; no fuerce la base de datos. |
| Job permanece `ready` | Ningún Worker satisface sus requisitos | Revise capacidades probadas, modelo local y conexión. |
| Job `orphaned` | Se perdió conexión o lease | Recupere el Worker y espere la reconciliación; no lance un duplicado. |
| GGUF desactivado o rechazado | Falta conversor o capacidad probada | Configure el conversor local y pruebe esa carga en el Worker. |

## 14. Misiones guiadas y destilación

### Cómo iniciar cualquier entrenamiento

1. Abra **Misiones**.
2. En **Quiero entrenar un modelo**, elija una estrategia:
   **LoRA / SFT local**, **Fine-tuning + RAG**, **Destilación de otro LLM** o
   **Que la app recomiende**.
3. Pulse **Crear plan guiado**. La aplicación mostrará el recorrido completo, sus entradas,
   salidas y bloqueos.
4. Escriba la tarea que debe aprender el modelo, un criterio de éxito verificable y las
   restricciones de privacidad, licencia y ejecución.
5. Pulse **Continuar**. El borrador se guarda localmente y puede retomarse desde
   **Planes y borradores**.
6. En cada etapa use el botón principal para abrir la herramienta necesaria. No avance por
   una marca visual: compruebe que la evidencia de la etapa anterior existe realmente.

### Caso 23. Entrenar por destilación de otro LLM

Esta implementación realiza **destilación secuencial supervisada**: el profesor puede estar
servido por **AI Broker** o cargarse localmente en el Worker. Genera las respuestas de
entrenamiento y un alumno local distinto aprende esas respuestas mediante LoRA. No transfiere
logits internos ni descarga modelos silenciosamente.

1. Abra **Misiones**, seleccione **Destilación de otro LLM** y pulse
   **Crear plan guiado**.
2. Defina una hipótesis falsable y un criterio de éxito frente a un baseline ya registrado.
3. Elija dónde está el profesor:
   - **AI Broker**: seleccione una comprobación de capacidades satisfecha e indique endpoint,
     proveedor, deployment y modelo exactos. El token permanece en el entorno del Worker y
     nunca viaja dentro del job.
   - **Caché local**: indique la ruta o ID local y su SHA-256.
   El alumno siempre es local, debe ser distinto del profesor y debe estar en la caché del Worker.
4. Abra **Datasets** desde el flujo y elija o construya un dataset aprobado. Solo se usa su
   partición de entrenamiento; la procedencia original se conserva.
5. Abra **Entrenamientos** y ejecute primero la **Prueba corta obligatoria** usando el modelo
   alumno exacto. La destilación no puede utilizar un preflight de otro modelo o dataset.
6. En **Destilación profesor → alumno**, seleccione el dataset, el preflight aprobado y el
   baseline comparable.
7. Identifique el profesor según su origen y escriba la ruta/ID y el SHA-256 del alumno.
8. Registre la licencia o los términos de uso aplicables a profesor y alumno.
9. **“Permisos compatibles” no significa que ambas licencias deban llamarse igual.** Significa
   que los términos del profesor permiten usar sus respuestas como datos de entrenamiento y que
   los del alumno permiten fine-tuning y el uso previsto del adapter resultante. Local AI Lab
   exige confirmación humana porque no puede tomar por sí sola una decisión jurídica.
10. Seleccione el objetivo, describa la hipótesis y registre quién autoriza la ejecución.
11. Ajuste la temperatura del profesor y el máximo de tokens. Con temperatura `0` la generación
    es determinista salvo las limitaciones del runtime registradas en el manifest.
12. Pulse **Autorizar destilación**.
13. Revise el trabajo en **Jobs distribuidos**. Si el profesor está en AI Broker, el Worker
    envía cada prompt aprobado como una tarea de modelo exacto, prohíbe fallback y registra task,
    modelo servido, uso y coste observado. Si es local, se carga con `local_files_only`. El alumno
    siempre se carga localmente.
14. Al completarse, Local AI Lab conserva el adapter del alumno, las respuestas destiladas,
    hashes de procedencia, configuración de generación, métricas y manifest verificable.
15. Ejecute el alumno contra el baseline desde **Experimentos** antes de exportarlo.
16. Si supera el criterio de éxito, vuelva a **Entrenamientos** y cree el paquete exportable.

La disponibilidad del formulario demuestra que el flujo está implementado; no demuestra que
los modelos concretos que usted elija quepan en la memoria o sean compatibles con su hardware.

#### Qué es PEFT

**PEFT** (*Parameter-Efficient Fine-Tuning*) es la librería de Python que usa el Worker para
crear un adapter **LoRA** entrenando una fracción pequeña de los parámetros del alumno. No es un
modelo, un servicio ni una cuenta externa. Se instala en el entorno de entrenamiento del Worker;
el usuario normal no tiene que manejarla durante cada ejecución. La prueba corta debe confirmar
que PEFT puede crear, guardar, reanudar y volver a cargar el adapter antes del entrenamiento largo.

## 15. Reglas de operación segura

Antes de aceptar un resultado como evidencia:

- confirme el estado final, no solo que se creó un job;
- compruebe snapshot, suite, modelo y parámetros;
- conserve el SHA-256 del registro o artefacto;
- no mezcle resultados de snapshots o conjuntos de casos distintos;
- no copie tokens en argumentos, logs, capturas o documentos;
- no edite las SQLite del Coordinator, Broker o Model Drift;
- no presente una capacidad detectada como probada;
- no entrene con benchmarks ni con feedback que no tenga doble aprobación;
- no interprete falta de potencia estadística como ausencia de diferencia;
- no publique una exportación sin revisar licencia, manifiesto y hashes.

## 16. Lista de comprobación final

- [ ] El escritorio abre y el Coordinator responde.
- [ ] La evidencia está actualizada.
- [ ] El vault usado tiene snapshot `COMPLETE` e índice `READY`.
- [ ] Los Workers necesarios están conectados y sus cargas aparecen como probadas.
- [ ] AI Broker satisface la fase exacta que se va a ejecutar.
- [ ] Los modelos y cachés están identificados por ruta/ID y SHA-256.
- [ ] Los ensayos comparados comparten suite, snapshot, casos y parámetros.
- [ ] Model Drift ha emitido un informe formal cuando se exige.
- [ ] Cada corrección aceptada conserva verificación y diff.
- [ ] Cada candidato de training tiene aprobación separada.
- [ ] El dataset está libre de benchmarks y es reproducible por su semilla.
- [ ] El preflight se superó antes del entrenamiento largo.
- [ ] La exportación contiene licencia, manifiesto y hashes verificables.

## 17. Documentación relacionada

- [Estado de implementación](IMPLEMENTATION_STATUS.md)
- [Despliegue de Workers](WORKER_DEPLOYMENT.md)
- [Auditoría real del 24 de agosto de 2026](AUDIT_20260824.md)
- [Informe de comparación formal](PHASE_8_REPORT.md)
- [Diseño y arquitectura](../DESIGN.md)
