# Fase 7 — Human feedback

La persistencia de feedback conserva respuesta original, corrección, hashes, diff unificado,
verificación determinista, revisor y eventos append-only. Las transiciones de revisión y de
candidato de training son máquinas de estado separadas. Solo feedback aceptado puede pasar
de `excluded` a `proposed`, y una segunda acción explícita lo lleva a `approved`.

La capa de dominio y persistencia está probada. La pantalla de revisión del escritorio queda
pendiente de conexión al Coordinator antes de considerar terminada la experiencia visual.
