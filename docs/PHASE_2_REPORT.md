# Fase 2 — Read-only Vault Index

Fecha de implementación local: 2026-08-23

## Resultado

Se ha implementado una frontera de lectura deliberadamente estrecha para vaults Obsidian,
un snapshot local inmutable con verificación SHA-256 y una proyección SQLite regenerable.
El código no expone operaciones para escribir, borrar o renombrar contenido del vault.

La puerta de fase permanece pendiente de la prueba del usuario sobre el vault real. Las
pruebas automatizadas usan exclusivamente vaults temporales creados dentro del workspace;
no se ha abierto `Y:\Mi unidad\Vaults`.

## Controles implementados

- El vault seleccionado debe ser hijo directo de una raíz permitida.
- Se rechazan rutas absolutas, traversal, enlaces simbólicos y reparse points.
- `.obsidian`, `.git`, `.trash`, `.stfolder` y temporales quedan excluidos.
- No se realiza canary write; el acceso de escritura de la identidad solo se detecta.
- El snapshot hace dos inventarios y revalida tamaño/mtime después de cada lectura.
- Los archivos inestables se reintentan de forma acotada; la falta de convergencia produce
  estado `INCOMPLETE` y huecos explícitos, nunca un falso `COMPLETE`.
- Cada objeto fuente se guarda por SHA-256 en `objects/sha256/<prefijo>/<hash>`.
- `note_id`, revisión, `chunk_id` y `link_id` son estables y trazables.
- El hash global usa ruta, tipo, tamaño, hash fuente y política de inclusión ordenados.
- El snapshot se promueve desde staging local, se reabre, se verifica y se marca read-only
  de mejor esfuerzo.
- El índice SQLite solo se crea en una ruta nueva local y rechaza reemplazar uno existente.
- La búsqueda FTS5 devuelve una referencia de evidencia al hash del snapshot y al chunk.

## Artefactos

- Adaptador: `src/local_ai_lab/knowledge_index/vault.py`
- Parser/chunker: `src/local_ai_lab/knowledge_index/markdown.py`
- Snapshot y verificador: `src/local_ai_lab/knowledge_index/snapshot.py`
- Proyección: `src/local_ai_lab/knowledge_index/projection.py`
- Contrato: `packages/contracts/schemas/vault-snapshot.v1.schema.json`
- Pruebas: `tests/test_vault_read_only.py`, `tests/test_snapshot_and_projection.py`

## Evidencia automatizada

Resultado local: `62 passed, 1 skipped`. La omisión corresponde a una prueba de enlace
simbólico que Windows no permite crear con la identidad del sandbox. El rechazo de reparse
points sigue implementado en el adaptador.

Las pruebas verifican reproducibilidad del hash, estabilidad de identidades, ausencia de
cambios de bytes/mtime en el vault, exclusión de `.obsidian`, detección de mutaciones,
rechazo de manipulación del snapshot, integridad SQLite y referencias de evidencia.

## Puerta pendiente

Para cerrar la puerta se requiere una ejecución supervisada contra una copia o vault real
montado con permisos efectivos de solo lectura y comparar un inventario externo antes y
después. Esa ejecución corresponde a la fase de pruebas del usuario; no se ha simulado como
evidencia real.
