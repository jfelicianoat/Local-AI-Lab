# Fase 4 — Retrieval baseline

Fecha de implementación local: 2026-08-23

Se implementaron R1 con FTS5, el contrato de R2 con embeddings normalizados y similitud
coseno, y R3 mediante Reciprocal Rank Fusion. Todos devuelven chunks con referencia al hash
del snapshot. Las métricas deterministas mantienen por separado Recall@k, Precision@k, hit
rate, MRR, nDCG, cobertura y redundancia; no producen un score global.

El runner conserva suite, fingerprint, estado de revisión humana, ranking completo y hash
del informe. Las pruebas usan un proveedor de embeddings conceptual identificado como
`test-only`; esto valida el contrato, no la calidad de un modelo real.

La puerta R1/R2/R3 permanece pendiente hasta disponer de ground truth aprobado y ejecutar
R2/R3 con un worker cuya capacidad de embeddings esté probada. No se ha consultado ni
modificado AI Broker para esta implementación.
