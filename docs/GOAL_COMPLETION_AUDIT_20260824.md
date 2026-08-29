# Auditoría de cierre del nuevo interfaz y la destilación

Fecha de última actualización: 2026-08-25.

## Requisitos y evidencia

| Requisito | Evidencia autoritativa | Veredicto |
|---|---|---|
| Interfaz guiada por lo que se quiere entrenar | `MissionBoard` abre en **Quiero entrenar un modelo**, permite elegir estrategia, crear un plan, recorrer entradas/salidas y conservar borrador; TypeScript/Vite compilan | Implementado y compilado |
| Flujo completo y accionable | El recorrido muestra todas las etapas y abre Evidencia, Recursos, Experimentos, Revisiones, Datasets o Entrenamientos según el paso | Implementado; comprobación visual pendiente |
| Observabilidad operativa | La navegación incorpora `Registros` y `Métricas`; permite localizar jobs, revisar cronología/correlación y comparar resultados por configuración completa | Implementado, compilado y documentado; comprobación visual pendiente |
| Destilación como entrenamiento | UI, comando Tauri, cliente TypeScript, endpoint, servicio, `JobSpec`, Worker, executor y estados `DISTILLATION_QUEUED/SUCCEEDED` conectados | Implementado |
| Seguridad de destilación | Modelos distintos, hashes, licencias, permiso de uso de salidas, permiso de fine-tuning, C1–C6, preflight completo, hardware y aprobación humana obligatorios | Probado |
| Ejecución profesor→alumno | Dataset verificado → profesor local o AI Broker con modelo exacto → supervisión secuencial → preparación LoRA → checkpoint/reanudación → guardado → recarga → manifiesto y hashes | Probado de extremo a extremo con modelos reales |
| Profesor mediante AI Broker | `ollama/local/gemma4:12b`, fallback prohibido, token efímero y procedencia por tarea/modelo/uso/coste | Probado con 8 invocaciones reales |
| Ejecución con modelos reales | Profesor Broker `gemma4:12b`, profesor local `SmolLM2-360M-Instruct`, alumno `SmolLM2-135M-Instruct` y RTX 4060 Ti bf16 | Probado a escala funcional; falta ensayo de duración/calidad representativas |
| Interpretación R3/R4 | Los resultados conservan embedding, huella, dispositivo, `k`, suite, snapshot y modelo; parejas incompatibles se bloquean y R4 no se presenta como mejora general | Implementado y probado; falta una suite con potencia suficiente |
| Ejecutable que no se cierre solo | Smoke de arranque superado; reproducción de carpeta no escribible confirma que la ventana permanece abierta y presenta el error en lugar de terminar con código 101 | Probado |
| Suite completa | Python: 162 pasadas y 1 omitida por privilegio de symlinks. Rust: 3 pasadas. TypeScript/Vite, `compileall`, `cargo fmt --check`, build nativa release y smoke de arranque: superados | Probado |
| Fidelidad respecto al diseño elegido | Existe una captura comparada de la versión anterior; la versión actual añade Observabilidad e iconos y requiere una captura nueva a 1487 × 1058 | Pendiente por permiso local guardado del navegador |
| Tratamiento del token de AI Broker | Se usó de forma efímera en las pruebas reales; no se transportó dentro de jobs, no se registró ni se persistió | Probado |

## Decisión

El producto está implementado, compila y sus flujos funcionales principales están cubiertos. La
destilación real ya no es un bloqueo de cierre. Todavía faltan estas evidencias de alcance completo:

1. capturas del interfaz actual —incluidos `Registros` y `Métricas`— para cerrar `design-qa.md`;
2. Benchmark A y corpus ampliado con aprobación humana;
3. comparación R3/R4 con potencia suficiente y condiciones idénticas;
4. distribución física entre dos PCs con TLS y nodo AMD/WSL;
5. destilación de duración y calidad representativas, separada de la prueba funcional ya superada;
6. empaquetado MSI/NSIS en un entorno limpio.

No se debe sustituir ninguna de estas evidencias por una afirmación basada únicamente en el
código o en pruebas simuladas.
