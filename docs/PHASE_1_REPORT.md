# Local AI Lab — Informe de Fase 1

**Estado de implementación:** completado localmente  
**Estado de la puerta:** pendiente de prueba en los dos equipos reales  
**Fecha:** 23 de agosto de 2026

## Resultado

Se ha construido un único núcleo distribuido instalable con roles Coordinator, Worker y
Desktop. El Coordinator conserva el estado autoritativo en SQLite local; cada Worker usa su
propio journal y outbox. Ninguna base se comparte por red.

Un dry-run simulado demostró dentro del proceso de pruebas que dos workers con journals
separados pueden reclamar jobs, persistirlos antes de aceptar, perder conexión, terminar,
conservar el resultado y sincronizarlo al recuperar la conexión. Esto es evidencia de prueba
automatizada, no evidencia de red real entre los PCs NVIDIA y AMD.

## Software implementado

- modelo de job y estados explícitos;
- pairing de un solo uso y credenciales de dispositivo almacenadas como hash;
- heartbeat y publicación de capacidades;
- claim, ack, progreso, renovación, finalización y reconciliación;
- `Idempotency-Key`, leases monotónicos y fencing de intentos obsoletos;
- journal y outbox local del Worker;
- protección DPAPI de lease tokens en Windows;
- transporte HTTPS del Worker, con HTTP permitido solo en loopback;
- API FastAPI `/node/v1` y vista saneada `/app/v1/overview`;
- CAS local con chunks reanudables y verificación SHA-256;
- contratos JSON Schema versionados;
- shell Tauri 2 y superficie React “Mesa de evidencia”;
- proxy Rust para que el secreto del sidecar nunca llegue a React;
- sidecar Windows generado mediante PyInstaller e incluido como recurso Tauri.

## Verificación ejecutada

```text
python -m pytest -q -p no:cacheprovider --basetemp .phase1-test-tmp-20260823-7
50 passed in 1.61s
```

Cobertura relevante:

- pairing consumible una sola vez y autenticación obligatoria;
- dos workers con tres bases locales distintas;
- desconexión, finalización offline y resincronización;
- idempotencia y conflicto por reutilización incorrecta de clave;
- expiración de lease, requeue y resultado obsoleto conservado sin promoción;
- asignación condicionada por capacidades probadas;
- rechazo de SQLite y CAS en rutas UNC;
- chunks corruptos o incompletos rechazados;
- API estricta y token efímero de Desktop;
- evidencia de puerta pendiente por defecto y registrada solo con SHA-256;
- schemas contractuales parseables.

Comprobaciones adicionales:

```text
cargo check --offline
Finished dev profile

local-ai-lab-coordinator.exe --help
exit code 0

Impeccable detector
[]
```

El revisor visual independiente detectó cinco defectos materiales. Fueron corregidos: secreto
fuera de React, retry real, evidencia antigua marcada, destinos futuros deshabilitados y
procedencia/hash obligatorios para estados no pendientes.

## Lo que no se verificó

- build TypeScript/React: faltan paquetes en la caché y el sandbox denegó la descarga;
- render real, zoom, lector de pantalla y navegación de teclado en WebView2;
- instalador MSI/NSIS completo;
- conexión TLS real entre los dos PCs;
- rotación/revocación de credenciales y mTLS;
- pérdida física de red, suspensión o reinicio de cualquiera de los nodos;
- throughput real de artefactos;
- ejecución del Worker en el PC AMD;
- integración desplegada con AI Broker, vault o Model Drift.

## Seguridad y límites

- React no recibe tokens, rutas de bases, acceso al filesystem ni permisos de shell.
- La CSP del WebView no permite conexiones de red desde React.
- Rust conserva el token en memoria y realiza la lectura autenticada del overview.
- El sidecar enlaza loopback por defecto y exige token de sesión.
- Las conexiones Worker remotas requieren HTTPS.
- El ejecutable PyInstaller se generó localmente; todavía no está firmado.

## Veredicto y puerta

**Implementación de Fase 1: preparada para pruebas del usuario.**  
**Puerta estratégica: abierta solo para continuar implementación desacoplada; no validada en
producción.**

Para declarar la puerta probada hacen falta ambos equipos, TLS/pairing real, ejecución del
dry-run en cada Worker y una desconexión física con resincronización. Hasta entonces la UI
mostrará esos controles como `PENDIENTE`.
