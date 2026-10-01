# Manual de uso de Local AI Lab

Versión del manual: 1.9
Aplicación documentada: Local AI Lab Desktop 0.1.1; Coordinator/Worker 0.1.0
Fecha de revisión: 1 de octubre de 2026

El estado de release y los límites verificados en esta revisión están en
[RELEASE_STATUS_20260929.md](RELEASE_STATUS_20260929.md). Las secciones de integración
avanzada conservan evidencia histórica del 24 de agosto; compruebe de nuevo cada
dependencia antes de basar una decisión en ella.

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

   `D:\Desarrollo\Proyectos TFM\Local AI Lab\dist\candidate-20261001-r7`

2. Compruebe que están presentes:

   - `local-ai-lab-desktop.exe`
   - la carpeta `resources`
   - dentro de `resources`, `local-ai-lab-coordinator.exe`

3. No separe el ejecutable de la carpeta `resources`. El Coordinator empaquetado es necesario para arrancar.

Este es el candidato local construido tras corregir la instalación de dependencias
del escritorio. Su construcción está comprobada; el recorrido visual y el cierre
completo de la aplicación siguen pendientes por las restricciones del entorno de
prueba. Consulte el estado de revisión antes de tratarlo como una release validada.

Para explorar la interfaz, crear snapshots y ejecutar R1 no hacen falta AI Broker, Model Drift ni un Worker. Las operaciones distribuidas sí necesitan sus dependencias correspondientes.

### 3.2 Requisitos por tipo de operación

| Operación | Requisito adicional |
|---|---|
| Snapshot e índice | Acceso de lectura a la raíz de vaults. |
| R1 controlado | Ninguno. Es local y sintético. |
| R2, R3 y R4 | Worker conectado con `embeddings.semantic` probado y modelo de embeddings ya cacheado. |
| B0–L1 | Worker, AI Broker compatible y modelo exacto disponible. |
| F1/F2 | Entrenamiento completado, adaptador y modelo base locales, Worker compatible. No usa el token del Broker durante la inferencia. |
| A1/M1 | AI Broker 2.9 compatible con agentes/client tools o mixture of agents. |
| Ejecución demostrable | AI Broker **2.10**: separa el trabajo del Broker del suyo (`invocation_contract`), acusa recibo de la compresión del prompt (`prompt_compression_echo`) y marca el entregable (`canonical_artifacts`). |
| Comparación formal | R3 y R4 comparables y Model Drift con `evaluar-tratamientos`. |
| Entrenamiento | Dataset aprobado, Worker preparado, modelo base local y preflight superado. |
| Exportación | Entrenamiento validado, Worker conectado y formato probado; si falta la prueba, use la comprobación inicial. |

### 3.3 Datos y privacidad

Por defecto, el estado del escritorio se guarda en:

`%LOCALAPPDATA%\lab.localai.desktop`

Los elementos más importantes son:

- `coordinator\state.db`: estado local del laboratorio.
- `coordinator.log`: registro de arranque y errores del Coordinator.
- artefactos, snapshots e índices bajo las carpetas administradas por el Coordinator.

No edite `state.db` manualmente. Con la app cerrada, use el procedimiento de
[copia y restauración verificable](#copia-y-restauración-verificable).

## 4. Abrir, actualizar y cerrar

### Abrir

1. Ejecute `local-ai-lab-desktop.exe`.
2. Espere a que desaparezca **Iniciando el Coordinator local…**.
3. Confirme que aparece **Misiones**.
4. Si se muestran datos anteriores, pulse **Actualizar**.

El escritorio elige un puerto local libre y crea un token interno nuevo. No es necesario configurar ninguno de los dos.

### Cerrar

1. Espere a que termine cualquier operación local corta.
2. Para un job distribuido, revise antes su estado en **Entrenamientos > Jobs distribuidos**.
3. Cierre la ventana. El escritorio detiene el Coordinator que inició.

Un Worker puede conservar progreso pendiente en su propio journal si pierde la conexión. El estado debe revisarse al volver a abrir la aplicación.

### Si el ejecutable se cierra solo

1. Compruebe que `resources\local-ai-lab-coordinator.exe` sigue junto al portable.
2. Abra `%LOCALAPPDATA%\lab.localai.desktop\coordinator.log`.
3. Busque el último error de arranque.
4. Desde la carpeta del proyecto puede ejecutar `scripts\smoke_desktop.ps1` para comprobar el portable.
5. Si el smoke falla, regenere primero el sidecar con `scripts\build_sidecar.ps1` y después el portable con `scripts\build_desktop.ps1 -Target Portable`.

## 5. Cómo leer la interfaz

La navegación izquierda comienza en **Misiones**. **Planes y borradores** permite
reanudar varios planes guardados en el Coordinator. **Evidencia** muestra la puerta,
dependencias y Workers; **Recursos**, los vaults, snapshots e índices;
**Experimentos**, los benchmarks y comparaciones; **Revisiones** y **Datasets**, el
control de ejemplos; **Entrenamientos**, el preflight, los jobs y las exportaciones.
**Registros**, **Métricas** y **Configuración** ofrecen seguimiento y diagnóstico.

El historial de productos, revisiones y jobs se abre por páginas de hasta 50
elementos por grupo. Si un resultado antiguo no aparece en un selector, pulse
**Cargar historial** en la barra superior. El contador muestra los registros
cargados y el total; la actualización automática conserva las páginas que haya
abierto. La búsqueda de **Registros** examina las ejecuciones cargadas; para
buscar entre las anteriores, cargue más historial.

En **Configuración**, el apartado de almacenamiento muestra los artefactos
guardados, el espacio reservado por transferencias pendientes, los fragmentos
temporales, el límite disponible y el espacio libre del disco. El límite de
artefactos es de 100 GiB por defecto; se puede ajustar antes de abrir la app
con `LOCAL_AI_LAB_ARTIFACT_QUOTA_BYTES` (número entero de bytes). Una transferencia
nueva se rechaza si supera ese límite o no queda espacio para montarla. Este
límite se aplica al almacén de artefactos y no incluye la base de datos,
snapshots ni índices externos.

Para liberar espacio, abra **Configuración → Liberar espacio**, elija 30, 60 o
90 días sin actividad y pulse **Revisar limpieza**. La propuesta muestra cada
archivo o transferencia, su tamaño y última actividad. Revise la lista y marque
la autorización antes de **Eliminar elementos revisados**: el borrado es
permanente. No se borran productos, datasets, evidencia, entradas de trabajos ni
checkpoints registrados; tampoco transferencias de trabajos pendientes o que
necesitan revisión. Los registros de transferencias completadas pueden retirarse
sin borrar el archivo que sigue referenciado por un resultado.

La app vuelve a comprobar las referencias al ejecutar la propuesta; si han
cambiado, pide revisar otra. Cada propuesta incluye como máximo 200 elementos
y caduca a las 24 horas. Una limpieza interrumpida aparece al volver a abrir
Configuración con **Completar limpieza pendiente**. El apartado **Limpieza
pendiente** cuenta los archivos que todavía ocupan disco durante esa recuperación.
Los historiales y las copias de seguridad no se purgan con esta acción.

Las misiones se guardan en el Coordinator: abrir una etapa no demuestra que
se haya ejecutado o validado. Compruebe los registros de evidencia correspondientes.

Para vincular un resultado, vuelva a su etapa y pulse **Vincular evidencia**.
La app comprueba su procedencia: el experimento debe usar el benchmark de la
misión, la revisión debe pertenecer a ese experimento y la comparación debe
incluir los experimentos vinculados. En entrenamiento, dataset, preflight,
modelo evaluado y exportación deben corresponder entre sí. La destilación
comprueba además el profesor y el alumno definidos en el plan.

Si falta un requisito, el resultado permanece **Configurado** y muestra qué
debe vincular o completar. Un resultado de otro recorrido se rechaza con una
explicación. Retirar evidencia o cambiar los modelos del plan vuelve a calcular
el avance; se conservan los vínculos para poder revisarlos o retirarlos. Tener
una evaluación terminada no completa **Comparar**: vincule también su comparación.
Estas comprobaciones de procedencia requieren revisar personalmente que la tarea,
el criterio de éxito y el contenido de las respuestas tengan sentido entre sí.

La columna derecha muestra la **puerta actual**:

- **Puerta abierta**: toda la evidencia exigida para esa puerta está registrada.
- **Puerta pendiente**: falta evidencia o existe un bloqueo.
- **PROBADO**: existe evidencia real recuperable.
- **DETECTADO**: se observó una capacidad, pero no se probó con la carga correspondiente.
- **PENDIENTE**: aún no hay prueba.
- **BLOQUEADO**: el sistema conoce la condición que impide continuar.

La aplicación consulta el Coordinator periódicamente. Pulse **Actualizar** si quiere
comprobar el estado de inmediato; si aparece el aviso de datos desactualizados,
revise la conexión y vuelva a intentarlo.

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
   - **Ejecución demostrable (2.10)** para `demonstrable_execution`.

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

La tabla de Workers en **Evidencia** es de consulta y revocación; el alta se realiza desde administración. El Coordinator
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

5. En el escritorio, abra **Evidencia** y pulse **Actualizar**.
6. Compruebe el nombre, el estado, las capacidades y el heartbeat.

El informe inicial se comprueba al arrancar. El Worker vuelve a observar hardware,
driver, intérprete y versiones de paquetes ML al inicio y cada 30 segundos entre
trabajos; no ejecuta entrenamiento durante esa observación. Un job largo puede
retrasar la siguiente observación hasta que termine.

Si cambia el entorno, **Evidencia** avisa de las capacidades que necesitan otra
prueba. Repetir un heartbeat no las convierte en probadas. Ejecute un preflight
nuevo antes de entrenar: el anterior deja de ser seleccionable y aparece como
`PREFLIGHT_ENVIRONMENT_CHANGED`. Un resultado antiguo conserva su salida histórica,
pero no valida el entorno nuevo. Al abrir una base de una versión anterior, las
pruebas sin identidad de entorno también deben repetirse.

El Worker protege su credencial con DPAPI en Windows. En Linux/WSL exige la variable
`LOCAL_AI_LAB_WORKER_PASSPHRASE` para cifrarla con Scrypt y AES-GCM. Guarde la
frase fuera del directorio del Worker y vuelva a proporcionarla al reiniciar. El
emparejamiento remoto por HTTP sin TLS se rechaza. El perfil WSL aún necesita una
prueba de extremo a extremo en un equipo con acceso autorizado a WSL.

La recuperación de una confirmación también comprueba el Worker, el intento y
la credencial del lease. Un Worker revocado o un lease reasignado no puede usar
una respuesta guardada para obtener autorización. El Worker original puede recuperar
su confirmación de finalización aceptada tras una desconexión, aunque haya vencido
el tiempo del lease; eso no permite iniciar operaciones nuevas con un lease vencido.

## 7. Conocimiento privado

### Caso 4. Descubrir vaults

1. Abra **Recursos**.
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

1. En **Recursos**, seleccione un **Snapshot completo**.
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

R1 usa un corpus sintético local cuando no se ha elegido un benchmark aprobado;
con una suite real seleccionada, usa su snapshot e índice. No usa AI Broker.

### Caso 8. Ejecutar R2, R3 o R4 de retrieval

1. Confirme en **Evidencia** que el Worker anuncia `embeddings.semantic` como **probado**.
2. Confirme que el modelo de embeddings ya está en su caché local. La aplicación no lo descargará.
3. Abra **Experimentos > R2–R4 · retrieval con embeddings**.
4. Seleccione R2, R3 o R4.
5. Seleccione el Worker.
6. Escriba la ruta o ID exacto del modelo de embeddings.
7. Escriba los 64 caracteres del SHA-256 del modelo o caché.
8. Escriba el dispositivo probado: `cpu`, `cuda` o `mps` según corresponda.
9. Ajuste `k` en el bloque R1; ese valor también se utiliza aquí.
10. Pulse **Enviar benchmark**.
11. Abra **Entrenamientos**, siga el job; la vista se actualiza automáticamente.
12. Confirme `EXPERIMENT_SUCCEEDED` antes de usar el resultado en otra comparación.

Si el botón está desactivado, revise Worker, modelo, hash de 64 caracteres y dispositivo.

### Caso 9. Registrar un benchmark humano del vault real

1. Cree primero un snapshot `COMPLETE`.
2. Abra **Experimentos > Benchmark A · vault real**.
3. Seleccione el snapshot completo y su índice.
4. Escriba una pregunta de evaluación y pulse **Buscar fuentes**.
5. Lea los fragmentos encontrados y marque los que respaldan la respuesta.
6. Escriba la respuesta de referencia y el nombre de su autor; pulse **Añadir caso**.
7. Repita para las demás preguntas. Puede quitar un caso antes de registrar la suite.
8. Escriba la persona que revisó y aprobó el benchmark y pulse
   **Registrar benchmark aprobado**.
9. Confirme el estado `HUMAN_APPROVED`.

La aplicación construye los IDs y referencias al snapshot. Rechaza fuentes
inexistentes, hashes incorrectos y referencias de otro snapshot.

### Caso 10. Ejecutar B0–F2 con contrato común

1. Para B0–L1, compruebe AI Broker para **Generación RAG** y conserve un informe satisfecho.
2. Confirme que el Worker está conectado y tiene probada la carga necesaria.
3. Abra **Experimentos > B0–F2 · contrato común de estrategia**.
4. Seleccione la estrategia.
5. Para B0–L1, seleccione el informe Broker satisfecho y escriba el endpoint.
6. Seleccione el Worker. Para B0–L1, complete proveedor, deployment y modelo exactos.
7. Para R2, R3, R4 o L1, complete el modelo de embeddings y su SHA-256 local.
8. Para F1 o F2, seleccione un entrenamiento o destilación completados. La aplicación fija la suite, el snapshot, el índice, k y, en F2, el modelo de embeddings a partir del baseline.
9. Para R2–L1 y F1/F2, elija el dispositivo de inferencia compatible con el Worker y el modelo.
10. Pulse **Ejecutar estrategia**.
11. Siga el job en **Entrenamientos**.
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

### Consulta independiente para entrenamiento

En **Revisiones > Nueva consulta para entrenamiento**, elija un snapshot completo y
su índice, escriba una pregunta distinta de las preguntas del benchmark y pulse
**Buscar fuentes**. Lea los fragmentos, marque los que respaldan la respuesta,
escriba la respuesta propuesta y pulse **Crear borrador de revisión**. El sistema
rechaza una pregunta que duplique una consulta aprobada de benchmark para ese
snapshot. El borrador necesita revisión humana y aprobación separada para
entrenamiento antes de entrar en un dataset.

### Caso 16. Corregir y aceptar una respuesta

1. Abra **Revisiones**.
2. Seleccione un caso en la cola izquierda.
3. Compare **Respuesta original** con las evidencias y el snapshot indicados.
4. Edite **Respuesta final** y las afirmaciones en **Corrección**. Use **Edición avanzada de JSON y citas** si necesita cambiar la estructura o las referencias.
5. Pulse **Guardar y verificar**.
6. Compruebe **Estructura y referencias verificadas** y abra **Ver cambios frente al original**. Esta comprobación no valida por sí sola la fidelidad de la respuesta.
7. Pulse **Enviar revisión**. El estado pasa de `draft` a `submitted`.
8. Una persona autorizada revisa el resultado y pulsa **Aceptar revisión**. Pasa a `accepted`.

Una revisión aceptada queda cerrada para edición. Si la verificación determinista falla, corrija los errores antes de enviarla.

Si sale a otra pantalla o cambia de revisión con una corrección o un motivo de rechazo
pendiente, se pide confirmar su descarte. Durante una operación hay que esperar a
que termine. Si la versión guardada cambia mientras edita, su texto se conserva y
aparece un aviso: revise el cambio antes de usar **Cargar la versión guardada**;
esa acción descarta la corrección local solo tras confirmación. No se puede guardar
por encima de un conflicto pendiente. La lógica se comprobó con pruebas; falta
verificar este recorrido visualmente y comprobar el aviso al cerrar la ventana nativa.

Si otra sesión guarda o cambia el estado justo antes de su decisión, el Coordinator
rechaza el guardado o la aprobación antigua y la app solicita los datos actuales.
Su corrección local permanece disponible; revise el conflicto antes de recargar.
La aceptación y la aprobación para entrenamiento también se vinculan a la versión
que se mostró. Use el escritorio y la carpeta `resources` del mismo candidato;
la migración conserva las revisiones existentes.

### Caso 17. Aprobar un candidato para entrenamiento

1. Parta de una revisión `accepted` con training `excluded`.
2. Pulse **Proponer para training**. El estado pasa a `proposed`.
3. Realice una segunda comprobación de calidad, privacidad, licencia y ausencia de contaminación.
4. Pulse **Aprobar training**. El estado pasa a `approved`.

Corregir, aceptar y aprobar para entrenamiento son tres decisiones distintas. No use los benchmarks ni sus respuestas de referencia como datos de training.

### Caso 18. Construir un dataset aprobado

1. Confirme que existe al menos un candidato de training `approved`.
2. Abra **Datasets** y seleccione el snapshot del que proceden esos ejemplos.
3. Escriba un nombre de versión descriptivo, por ejemplo `feedback-privado-v1`.
4. Escriba una semilla de split estable de al menos 8 caracteres.
5. Pulse **Construir dataset aprobado**.
6. Confirme `READY_FOR_TRAINING` y el número de ejemplos incluidos.
7. Observe que los candidatos usados pasan a `exported` para evitar su reutilización silenciosa.

El constructor deduplica ejemplos y excluye automáticamente IDs y fingerprints de benchmark.

## 10. Entrenamiento, exportación y jobs

### Caso 19. Ejecutar el preflight obligatorio

1. Abra **Entrenamientos > 1 · Prueba corta obligatoria**.
2. Seleccione un dataset `READY_FOR_TRAINING`.
3. Seleccione el Worker.
4. Escriba la ruta o ID exacto del modelo base ya presente en el Worker.
5. Seleccione `bf16` o `fp16` según la capacidad probada.
6. Pulse **Ejecutar C1–C6 + 8 ejemplos + resume**.
7. Siga el job en la tabla.
8. Espere la actualización automática o pulse **Actualizar**.
9. Continúe únicamente si aparece `PREFLIGHT_PASSED`.

El preflight entrena 20 pasos con 8 ejemplos y comprueba guardado, recarga,
reanudación, contratos C1–C6 y separación del benchmark. El Coordinator verifica
el paquete, su manifiesto, hashes, configuración e identidad del intento antes de
dar la prueba por superada. La memoria libre declarada no calcula el margen para
un entrenamiento largo.

Al actualizar desde una versión anterior, los resultados que carecían de estas
comprobaciones aparecen como **Resultado anterior pendiente de validación**. Sus
archivos se conservan y los informes y exportaciones siguen pudiéndose guardar.
Repita las pruebas afectadas; un resultado antiguo no autoriza nuevos trabajos.
Debe corresponder al entorno actual del Worker. Los cambios de temperatura,
memoria disponible o espacio libre no obligan a repetirlo; cambiar driver,
hardware, intérprete o dependencias sí invalida las capacidades anteriores.

### Caso 20. Autorizar un entrenamiento LoRA

1. Abra **Entrenamientos > 2 · Entrenamiento largo autorizado**.
2. Seleccione el preflight aprobado.
3. Seleccione un baseline B1 o R4 completado que evalúe el mismo snapshot del dataset.
4. Elija el objetivo: formato, comportamiento, clasificación, selección de tools o argumentos estructurados.
5. Escriba una hipótesis falsable: qué espera mejorar y cómo decidirá si ocurrió.
6. Confirme que el objetivo no memoriza hechos cambiantes del vault e indique una mejora mínima de verificación de formato y citas entre 0 y 1 frente al baseline. Este número no mide por sí solo la fidelidad de la respuesta.
7. Escriba quién lo aprueba.
8. Pulse **Autorizar entrenamiento**.
9. Siga estados, progreso y checkpoints en **Jobs distribuidos**.
10. Tras `TRAINING_SUCCEEDED`, ejecute F1 si el baseline era B1, o F2 si era R4, sobre la misma suite, casos, snapshot e índice. El Coordinator rechaza otra configuración y registra si la mejora de verificación alcanza la meta. La calidad de respuesta necesita revisión humana antes de promocionar el modelo; un export sigue siendo experimental.
11. Use el resultado solo con `TRAINING_SUCCEEDED`.

La aplicación fija una época desde esta interfaz. El Worker debe conservar checkpoints y validar la recarga del resultado.

### Caso 21. Exportar un modelo o adaptador

1. Abra **Entrenamientos > 3 · Exportación experimental verificable**.
2. Seleccione un entrenamiento o destilación completados con resultado validado.
3. Seleccione un Worker conectado que haya enviado su información de entorno.
4. Marque uno o más formatos:

   - `adapter`
   - `merged_model`
   - `safetensors`
   - `gguf`

5. Escriba la licencia aplicable.
6. Escriba el motor para usar el modelo, por ejemplo `transformers`.
7. Si eligió GGUF, indique la ruta del conversor llama.cpp en el Worker seleccionado.
8. Si algún formato aparece pendiente, pulse **Comprobar y crear primer paquete**.
   Para conversiones, el Worker necesita torch, transformers y PEFT instalados.
   La comprobación hace la conversión completa; reserve tiempo, memoria y disco.
   Si todos los formatos están probados, pulse **Crear paquete exportable**.
9. Espere `EXPORT_SUCCEEDED`.
10. Pulse **Guardar paquete** en la tarjeta de exportación. Se guarda en
    **Descargas/Local AI Lab**; la aplicación verifica el SHA-256 durante la descarga.
11. Verifique el manifiesto y los SHA-256 antes de mover o publicar el paquete.

La existencia de un conversor no basta: el Coordinator exige evidencia de una
carga completada para ese formato. Un entrenamiento completado verifica
`export.adapter`; declarar un formato como probado en un heartbeat no lo autoriza.
La comprobación inicial valida el resultado antes de registrar la capacidad.
Un fallo conserva el formato pendiente. Cada paquete incluye el tokenizer guardado
y su plantilla; la metadata de pesos fusionados incluye la configuración del modelo.
La conversión fusionada debe poder recargarse sin discrepancias de pesos y conservar
la misma plantilla. La salida GGUF debe tener una cabecera compatible y no estar vacía.
Estas comprobaciones no sustituyen una prueba de inferencia real en el motor de destino.
En **Experimentos**, **Guardar informe** permite conservar un informe completado
con la misma comprobación de integridad.

### Caso 22. Seguir o cancelar un job

1. Abra **Entrenamientos > Jobs distribuidos**.
2. Identifique el job por tipo, ID y correlation ID.
3. Revise estado, nodo asignado y progreso.
4. Para detener uno cancelable, pulse **Cancelar**.
5. Espere `cancelling` y después `cancelled`; pulse **Actualizar** si necesita confirmarlo de inmediato.

Estados habituales:

| Estado | Significado y acción |
|---|---|
| `ready` | Espera un Worker compatible. |
| `leased` / `acknowledged` | El Worker lo recibió. |
| `running` | Está ejecutándose. |
| `paused` | Pausa registrada; compruebe el estado del Worker antes de tomar otra decisión. |
| `cancelling` | La cancelación fue solicitada. |
| `succeeded_pending_sync` | Terminó en el Worker y falta sincronizar. |
| `succeeded` | Terminado y sincronizado. |
| `failed_pending_sync` / `failed` | Falló; revise progreso, resultado y logs. |
| `orphaned` | Se perdió el lease o la conexión; no lo duplique manualmente. |
| `needs_review` | Hace falta una decisión humana: reanudar, reiniciar o descartar el entrenamiento. |

La cancelación es cooperativa: no apague el equipo salvo emergencia, porque podría impedir el checkpoint y la sincronización final.
Si el Worker se reinicia, recupera trabajos repetibles con lease vigente y
reenvía resultados pendientes. Un entrenamiento interrumpido durante la
ejecución no se repite automáticamente.

Para recuperar un entrenamiento LoRA o de destilación, abra **Registros**, seleccione
el trabajo `failed` o `needs_review` y revise **Recuperación del entrenamiento**.
Seleccione un Worker en línea. Si hay un checkpoint publicado, **Reanudar desde
paso…** crea un trabajo nuevo con el estado exacto del entrenador. En destilación
también conserva las respuestas del profesor y evita repetir su generación. Si no
hay checkpoint, **Reiniciar desde cero** vuelve a ejecutar todo el trabajo; con
profesor servido por Broker puede ocasionar nuevas llamadas y coste. En
`needs_review`, **Descartar trabajo** lo cancela. Una recuperación conserva el
historial anterior y la app muestra el ID del trabajo nuevo. Solo se autoriza una
decisión de recuperación para cada trabajo interrumpido.

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
2. Revise **Evidencia**.
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
| `execution_evidence.prompt_compression` es `null` | El Broker no acusa recibo de la compresión (anterior al 2.10) | No significa que no hubiera poda: significa que no consta. Use un Broker 2.10 si el experimento tiene que demostrarlo. |
| `execution_evidence.auxiliary_roles` no está vacío | El Broker sondeó otro modelo con el mismo contenido bajo su `task_id` (§8.4) | No es un fallo ni se le factura, pero el contenido lo vio otro modelo. Si eso no es tolerable, exija `auxiliary_invocations_optout`. |
| `UNKNOWN` en Broker | Red, token o respuesta no confirmada | Compruebe conectividad y autenticación antes de concluir incompatibilidad. |
| Model Drift se bloquea | CLI antigua, falta confirmación o tratamientos no comparables | Compruebe `evaluar-tratamientos`, rutas, hashes, R3/R4 y la casilla de confirmación. |
| No se puede enviar una revisión | Corrección inválida o evidencia no verificada | Guarde un objeto JSON válido y resuelva los errores de verificación. |
| No se puede crear dataset | No hay candidatos `approved` | Complete revisión, aceptación, propuesta y aprobación. |
| No se puede entrenar | Dataset, preflight, baseline, hipótesis o aprobador ausentes | Complete la cadena de autorización; no fuerce la base de datos. |
| El entorno del Worker cambió | Las pruebas anteriores corresponden a otro entorno | Ejecute un preflight nuevo y vuelva a probar las cargas afectadas. |
| Job permanece `ready` | Ningún Worker satisface sus requisitos | Revise capacidades probadas, modelo local y conexión. |
| Job `orphaned` | Se perdió conexión o lease | Recupere el Worker y espere la reconciliación; no lance un duplicado. |
| GGUF desactivado o rechazado | Falta conversor o capacidad probada | Configure el conversor local y pruebe esa carga en el Worker. |

## 14. Misiones guiadas y destilación

### Cómo iniciar una misión

1. Abra **Misiones**.
2. En **Quiero resolver una tarea**, elija **Comparar y elegir**, **Prompting sin
   entrenamiento**, **RAG sin entrenamiento**, **LoRA / SFT local** o **Destilación
   de otro LLM**.
3. Escriba la tarea, un criterio de éxito verificable y las restricciones.
4. Pulse **Crear plan guiado**. El plan se guarda en el Coordinator y aparece en
   **Planes y borradores**; puede reabrirlo desde otro escritorio conectado al
   mismo Coordinator.
5. Abra la herramienta de cada etapa. Cuando tenga un resultado, vuelva a la
   misión, selecciónelo en **Evidencia de esta etapa** y pulse **Vincular evidencia**.
   También puede retirar una asociación equivocada.
6. Lea el estado de cada etapa: **Configurado**, **Ejecutado**, **Validado** o
   **Requiere atención**. El estado se calcula con los registros y jobs actuales;
   visitar una etapa no la da por terminada. Al reabrir la misión se muestra el
   primer paso pendiente de evidencia.

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
    Confirme que el objetivo no memoriza hechos cambiantes y fije la mejora mínima
    de verificación de formato y citas frente al baseline; la meta debe ser positiva y alcanzable.
11. Ajuste la temperatura del profesor y el máximo de tokens. Con temperatura `0` la generación
    es determinista salvo las limitaciones del runtime registradas en el manifest.
12. Pulse **Autorizar destilación**.
13. Revise el trabajo en **Jobs distribuidos**. Si el profesor está en AI Broker, el Worker
    envía cada prompt aprobado como una tarea de modelo exacto, prohíbe fallback y registra task,
    modelo servido, uso y coste observado. Si es local, se carga con `local_files_only`. El alumno
    siempre se carga localmente.
14. Al completarse, Local AI Lab conserva el adapter del alumno, las respuestas destiladas,
    hashes de procedencia, configuración de generación, métricas y manifest verificable.
15. Ejecute F1 contra B1 o F2 contra R4 desde **Experimentos** con la misma suite y configuración. Compruebe la comparación registrada; distingue verificación determinista de calidad de respuesta.
16. Vuelva a **Entrenamientos** para crear un paquete experimental verificable. Requiera revisión humana de calidad antes de promoverlo para uso de producción.

La disponibilidad del formulario demuestra que el flujo está implementado; no demuestra que
los modelos concretos que usted elija quepan en la memoria o sean compatibles con su hardware.

#### Qué es PEFT

**PEFT** (*Parameter-Efficient Fine-Tuning*) es la librería de Python que usa el Worker para
crear un adapter **LoRA** entrenando una fracción pequeña de los parámetros del alumno. No es un
modelo, un servicio ni una cuenta externa. Se instala en el entorno de entrenamiento del Worker;
el usuario normal no tiene que manejarla durante cada ejecución. La prueba corta debe confirmar
que PEFT puede crear, guardar, reanudar y volver a cargar el adapter antes del entrenamiento largo.

## 15. Reglas de operación segura

### Copia y restauración verificable

Cierre el escritorio y detenga cualquier Coordinator independiente antes de crear
la copia. Desde la carpeta del proyecto, use el Python donde está instalado Local
AI Lab y coloque el archivo fuera de la carpeta de datos:

```powershell
python -m local_ai_lab.maintenance.backup backup `
  "$env:LOCALAPPDATA\lab.localai.desktop\coordinator\state.db" `
  "D:\Copias\local-ai-lab.zip"
python -m local_ai_lab.maintenance.backup verify "D:\Copias\local-ai-lab.zip"
```

Para ensayar la restauración, indique **una carpeta nueva que no exista**:

```powershell
python -m local_ai_lab.maintenance.backup restore `
  "D:\Copias\local-ai-lab.zip" "D:\Pruebas\coordinator-restaurado"
```

La restauración comprueba cada archivo y la integridad SQLite antes de publicar
la carpeta. Incluye datos privados y hashes de credenciales: almacene y transfiera
el ZIP en un destino protegido. Para volver a usar los datos restaurados, configure
el Coordinator para esa carpeta; no sustituya una instalación abierta.

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
