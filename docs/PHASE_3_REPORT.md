# Fase 3 — Corpus controlado

Fecha de implementación local: 2026-08-23

## Resultado

Se ha creado `benchmarks/controlled/v1`, un corpus pequeño y determinista separado de
cualquier dataset de entrenamiento. Incluye seis documentos, cinco consultas y ground
truth exacto para single-hop, multi-hop, contradicciones, cifras, entidades, información
ausente y distractores.

El manifiesto siempre fija `purpose: benchmark_only` y `training_eligible: false`. El
validador rechaza cambiar cualquiera de estos límites, clasificaciones parciales de los
documentos, relaciones rotas, hechos sin documento relevante, IDs duplicados o una suite
que no cubra todas las clases requeridas.

## Estado de la puerta

La implementación está terminada, pero la puerta permanece pendiente. `human_review.status`
es `pending` y el modo estricto rechaza ejecutar la suite como aprobada. Solo una revisión
humana puede cambiar ese estado a `approved`; no se ha autovalidado el ground truth.

## Evidencia automatizada

El conjunto total alcanza `67 passed, 1 skipped` al finalizar esta fase. Las pruebas de
Fase 3 validan cobertura, clasificación exacta relevante/irrelevante, aislamiento de
training, bloqueo de la puerta humana y cambio de fingerprint ante cualquier modificación
de un documento.
