# Fase 9 — Dataset Factory

La fábrica solo lee feedback en estado `approved`. Excluye por ID todos los casos de
benchmark antes de deduplicar, conserva fingerprints de las suites bloqueadas, elimina
duplicados exactos y asigna splits de forma determinista. Cada ejemplo incluye la cadena
completa de procedencia y el dataset se reabre para verificar hashes y conteos.

La implementación está probada; no existe todavía un dataset real elegible porque el usuario
no ha realizado revisiones ni aprobaciones.
