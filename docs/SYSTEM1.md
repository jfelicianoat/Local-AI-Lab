# Evaluación semántica con System 1

## Arquitectura y punto de integración

`StrategySuiteExecutor` ejecuta B0–F2 sobre una suite y un snapshot congelados,
aplica `ResearchResponseVerifier` y escribe `strategy-report.json`. El Coordinator
verifica el paquete y persiste su resumen; la aplicación muestra esos resúmenes.
La revisión humana y la evaluación formal con Model Drift son puertas separadas.
No había un judge semántico por respuesta configurado en este ejecutor.

La capa nueva se integra después de las comprobaciones deterministas. Consume
`POST /api/v1/system1/judge` a través del cliente Broker existente, contrato 2.11.
El Broker decide proveedores, modelos y fallback. El nuevo `Client_API.md` prima
sobre el orden de proveedores del prompt antiguo. No se contacta con LAYA,
Ollama ni LM Studio desde Local AI Lab.

Plan mínimo: ampliar el cliente; añadir evaluación y agregación; propagar la
configuración por el trabajo existente; guardar resultados en el informe y
mostrar sus métricas; verificar contrato, fallback y reejecución.

La función está desactivada por defecto. Al activarla se recomienda empezar en
modo sombra. El juez potente usa `BrokerTaskClient.invoke`, con un modelo exacto
configurado por el usuario. Si falta ese modelo o falla, el caso queda en el
flujo anterior de revisión, sin inventar una etiqueta. Las revisiones humanas,
los candidatos de entrenamiento y el estado formal no se autoaprueban.
