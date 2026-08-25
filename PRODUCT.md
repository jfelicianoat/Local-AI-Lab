# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

El usuario primario es el propietario u operador técnico del laboratorio local, trabajando
desde una aplicación de escritorio en Windows. **Supuesto pendiente de confirmación:** una
sola persona administra inicialmente los nodos, revisa respuestas y decide promociones.

## Product Purpose

Local AI Lab determina experimentalmente qué estrategia de IA resuelve mejor tareas sobre
conocimiento privado con la menor complejidad, coste, latencia y pérdida de privacidad. El
éxito no es ejecutar una demo: es obtener comparaciones reproducibles, trazables y útiles
para decidir entre prompting, RAG, modelos locales, fine-tuning, destilación profesor→alumno
y estrategias de AI Broker.

## Positioning

Un único producto distribuido convierte hardware local heterogéneo, snapshots inmutables de
conocimiento y estrategias intercambiables en evidencia comparable. No sustituye AI Broker,
Knowledge Orchestrator, Model Drift ni Athena; se integra con sus contratos.

## Operating Context

- PC NVIDIA: Desktop, Coordinator, Worker y lector directo del vault.
- PC AMD: Worker remoto sin montar Obsidian como dependencia de producción.
- Vaults declarados bajo `Y:\Mi unidad\Vaults`, siempre read-only desde Local AI Lab.
- AI Broker es una dependencia externa estrictamente read-only en esta máquina durante el
  desarrollo; su versión desplegada se negocia, nunca se presupone.
- El operador revisa evidencia, contradicciones, feedback, datasets y decisiones de promoción.

## Capabilities and Constraints

- Roles instalables `desktop`, `coordinator` y `worker` dentro del mismo producto.
- Jobs autenticados, idempotentes, con leases, fencing, journal local y reconciliación.
- Snapshots e informes identificados por SHA-256 y esquemas versionados.
- Evidencia clasificada como `declared`, `detected`, `tested` o `benchmarked`.
- El frontend nunca accede directamente a SQLite, vault, shell ni secretos.
- El contenido del vault parte de `local_only`; cloud y servicios con coste requieren
  confirmación humana informada.
- Fine-tuning debe justificarse mediante evidencia frente a prompting y RAG.

## Evidence on Hand

- Diseño aprobado y fronteras: `docs/PHASE_A_DESIGN.md`.
- Evidencia parcial de hardware NVIDIA: `artifacts/phase0/node-nvidia-20260823.json`.
- Contratos y pruebas locales del núcleo distribuido en `src/local_ai_lab/` y `tests/`.
- No existen aún evidencias reales del nodo AMD, del vault seleccionado, de la red entre
  nodos ni del servicio AI Broker desplegado. La interfaz no debe presentarlas como probadas.

## Product Principles

1. Evidencia antes que suposición.
2. Privacidad local por defecto y egress explícito.
3. Reproducibilidad mediante snapshots, contratos, hashes y procedencia.
4. Estrategias comparables sin ocultar sus trade-offs en un único score.
5. Recuperación distribuida sin fingir transacciones ACID entre máquinas.

## Accessibility & Inclusion

La interfaz debe ser operable con teclado, no depender únicamente del color para comunicar
estado, mantener contraste WCAG AA y explicar los estados técnicos con lenguaje comprensible.
