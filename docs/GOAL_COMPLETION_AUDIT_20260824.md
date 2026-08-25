# Auditoría de cierre del nuevo interfaz y la destilación

Fecha de última actualización: 2026-08-25.

## Requisitos y evidencia

| Requisito | Evidencia autoritativa | Veredicto |
|---|---|---|
| Interfaz guiada por lo que se quiere entrenar | `MissionBoard` abre en **Quiero entrenar un modelo**, permite elegir estrategia, crear un plan, recorrer entradas/salidas y conservar borrador; TypeScript/Vite compilan | Implementado y compilado |
| Flujo completo y accionable | El recorrido muestra todas las etapas y abre Evidencia, Recursos, Experimentos, Revisiones, Datasets o Entrenamientos según el paso | Implementado; comprobación visual pendiente |
| Destilación como entrenamiento | UI, comando Tauri, cliente TypeScript, endpoint, servicio, `JobSpec`, Worker, executor y estados `DISTILLATION_QUEUED/SUCCEEDED` conectados | Implementado |
| Seguridad de destilación | Modelos distintos, hashes, licencias, permiso de uso de salidas, permiso de fine-tuning, C1–C6, preflight completo, hardware y aprobación humana obligatorios | Probado |
| Ejecución profesor→alumno | Prueba integral: dataset verificado → profesor local o AI Broker con modelo exacto → supervisión secuencial → preparación LoRA → checkpoint/reanudación → guardado → recarga → manifiesto y hashes | Probado con dobles deterministas de las fronteras Broker y ML |
| Profesor mediante AI Broker | Comprobación de capacidades previa, endpoint y destino exactos, fallback prohibido, token solo en el entorno del Worker y procedencia por tarea/modelo/uso/coste | Implementado y probado contractualmente; falta elegir el modelo real |
| Ejecución con modelos reales | El profesor puede estar en Broker; falta indicar el alumno causal local, instalar/comprobar PEFT y aprobar el hardware | Pendiente de entorno/hardware real |
| Ejecutable que no se cierre solo | Smoke de arranque superado; reproducción de carpeta no escribible confirma que la ventana permanece abierta y presenta el error en lugar de terminar con código 101 | Probado |
| Suite completa | Python: 158 pasadas y 1 omitida por privilegio de symlinks. Rust: 3 pasadas. TypeScript/Vite, `compileall`, `cargo fmt --check` y compilación Rust offline: superados | Probado |
| Fidelidad respecto al diseño elegido | Diseño fuente disponible a 1487 × 1058; la captura de la vista local fue denegada y la sesión nativa no permite captura válida | Bloqueado por falta de imagen renderizada |
| Tratamiento del token de AI Broker | No fue necesario para estas verificaciones; no se pasó al proceso, no se registró y no se persistió | Probado por ausencia de uso |

## Decisión

El producto está implementado, compila y sus flujos funcionales están cubiertos. El objetivo no
puede declararse cerrado todavía porque faltan dos evidencias de alcance completo:

1. una captura autorizada del interfaz real para compararla con el diseño elegido y cerrar
   `design-qa.md` con `final result: passed`;
2. una ejecución de destilación con un profesor exacto de AI Broker (o uno local), un alumno causal
   local distinto, PEFT instalado y hardware aprobado. La prueba integral actual valida la
   orquestación y los artefactos, pero no demuestra la compatibilidad del alumno que se elija ni la
   calidad resultante.

No se debe sustituir ninguna de estas dos evidencias por una afirmación basada únicamente en el
código o en pruebas simuladas.
