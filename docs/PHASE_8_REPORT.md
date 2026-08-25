# Fase 8 — Model Drift

## Contrato implementado

Model Drift expone ahora `evaluar-tratamientos` mediante un contrato de plan v2 sellado.
Local AI Lab entrega las rutas y SHA-256 de los ZIP R3/R4 ya calculados —retrieval o ejecución
RAG completa—; Model Drift valida plan, artefactos, suite, snapshot, profundidad, estrategias,
modelo servido, ausencia de fallback, métricas y casos.
La integración usa exclusivamente la CLI pública y no lee la SQLite de Model Drift.

La medida de retrieval es determinista: se compara el valor exacto por caso y la potencia
externa depende del número de casos de la suite. No se inventan repeticiones ni se relanzan
tratamientos contra AI Broker.

## Estado de la puerta

Implementada y probada con artefactos contractuales. Para cerrarla con evidencia de producto se necesita:

1. completar dos jobs reales R3/R4 sobre la misma suite y snapshot;
2. ejecutar la comparación desde la pantalla y revisar el HTML asociado.

AI Broker permanece sin modificaciones. Model Drift sí se amplió en su propio proyecto para
incorporar este contrato público.

## Verificación real repetible

El script `scripts/verify_phase8_real.ps1` comprueba, en una sola ejecución, el contrato 2.9,
selecciona únicamente un modelo local despachable, realiza una inferencia aislada de Model
Drift sin fallback y excluida del aprendizaje y, si recibe `-Plan`, genera el informe R3/R4.
El token se lee de `LOCAL_AI_LAB_BROKER_TOKEN` y nunca se acepta como argumento ni se guarda.
