# Fase 5 — Graph RAG

Fecha de implementación local: 2026-08-23

R4 expande candidatos de una estrategia base usando wikilinks entrantes y salientes,
resuelve rutas relativas o nombres no ambiguos, pondera enlaces y embeds, rerankea chunks y
conserva un trace de cada contribución. El ensamblador de contexto deduplica chunks, respeta
un presupuesto estricto y escribe la referencia de evidencia junto a cada bloque.

Las pruebas verifican que una nota semilla recupera su evidencia enlazada y que el contexto
no excede el límite. Al finalizar: `75 passed, 1 skipped`.

La puerta R4 frente a R3 permanece pendiente del mismo proveedor semántico real y del ground
truth aprobado. Implementación disponible no equivale a comparación ejecutada.
