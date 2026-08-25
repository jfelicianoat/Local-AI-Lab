# Local AI Lab — Informe de Fase 0

**Estado:** en curso  
**Fecha:** 23 de agosto de 2026  
**Veredicto:** **PUERTA CERRADA — evidencia parcial del nodo NVIDIA**

## 1. Resultado

Se ha implementado el primer componente ejecutable de Local AI Lab: un detector de
capacidades no destructivo, sin dependencias externas y con salida JSON versionada y
sellada mediante SHA-256.

El detector diferencia evidencia `declared`, `detected`, `tested` y `benchmarked`. Esta
ejecución solo produce hechos `detected`; no convierte presencia de hardware o runtimes en
compatibilidad ML.

Artefactos:

- `artifacts/phase0/node-nvidia-20260823.json` — informe bruto del nodo;
- `artifacts/phase0/deployment-manifest.v1.json` — topología y huecos conocidos;
- `src/local_ai_lab/capabilities/` — contrato y probe;
- `src/local_ai_lab/broker/` — negociación estrictamente read-only con AI Broker;
- `tests/test_capability_probe.py` — pruebas del contrato y guardas.
- `tests/test_broker_compatibility.py` — compatibilidad, seguridad y fallos del Broker;
- `artifacts/phase0/broker-requirements.v1.json` — requisitos declarativos por fase;
- `scripts/run_phase0_probe.ps1` — ejecución portable del probe y verificación inmediata.

## 2. Restricciones respetadas

- no se instaló software;
- no se modificaron drivers, WSL, BIOS, firmware, firewall ni configuración global;
- no se accedió al vault para leer notas;
- no se modificó ni consultó la persistencia de AI Broker;
- no se escribió nada nuevo dentro de AI Broker;
- no se ejecutaron inferencias, entrenamiento, LoRA ni benchmarks;
- todos los comandos del detector pertenecen a una allowlist de inspección.
- el cliente del Broker solo puede expresar GET hacia `/health` y
  `/api/v1/capabilities`; las pruebas usan un transporte simulado y no tocaron el servicio.

## 3. Contrato implementado

`NodeCapabilityReport` contiene:

- versión de schema;
- identidad provisional del nodo;
- timestamp UTC;
- hechos con estado, fuente, unidad y fecha;
- observaciones de cada probe;
- limitaciones explícitas;
- hash SHA-256 del payload canónico.

La identidad actual es UUIDv5 derivada del hostname y está marcada como provisional. La
identidad definitiva será UUIDv7 persistida durante el pairing autenticado.

## 4. Evidencia del nodo NVIDIA

Informe:

```text
report_id = 01a03041-72f5-7727-9732-f7e36a2dfb73
sha256    = 77925647d76c669cac203655b6dbb56d2e0bbe638f89c79407becc62fd0c4578
```

| Hecho | Estado | Valor observado | Fuente |
| --- | --- | --- | --- |
| Hostname | detected | `DESKTOP-CAQ5SL5` | Python platform |
| Sistema | detected | Windows 11 · build `10.0.26200` | Python platform |
| CPU | detected parcial | AMD64 Family 25 Model 97 · 24 procesadores lógicos | Python/entorno |
| RAM física | detected | 136.593.424.384 bytes · 127,21 GiB | Win32 API |
| Disco de datos | detected | 353.909.325.824 bytes libres · 329,60 GiB | `disk_usage` |
| Python | detected | 3.14.0 | comando de versión |
| Node.js | detected | 24.11.1 | comando de versión |
| pnpm | detected | 11.20.0 | comando de versión |
| Rust | detected | 1.97.1 | comando de versión |
| GPU | detected | NVIDIA GeForce RTX 4060 Ti | `nvidia-smi` |
| VRAM total informada | detected | 16.380 MiB | `nvidia-smi` |
| Driver NVIDIA | detected | 610.88 | `nvidia-smi` |

La temperatura y el estado de potencia incluidos en el JSON son muestras puntuales, no un
benchmark térmico.

## 5. Observaciones no completadas

| Probe | Resultado | Interpretación correcta |
| --- | --- | --- |
| `rocminfo` | unavailable | no está en este entorno; no afirma nada sobre el nodo AMD |
| `wsl --status` | error `E_ACCESSDENIED` | el sandbox no puede enumerar WSL; WSL queda desconocido |
| vault `Y:\Mi unidad\Vaults` | access denied desde sandbox | ruta declarada, no detectada ni probada |
| AI Broker `/capabilities` | no ejecutado | versión desplegada y capacidades siguen desconocidas |
| runtimes ML Python | absent | `torch`, `onnxruntime` y `transformers` no están instalados en este Python; no se instaló nada |

## 6. Pruebas

Comando ejecutado:

```powershell
python -m pytest -q -p no:cacheprovider `
  --basetemp ".phase0-test-tmp-20260823-2016"
```

Resultado del conjunto ampliado:

```text
26 passed
```

Cobertura conductual:

- parseo de GPU NVIDIA;
- toda evidencia del probe permanece en `detected`;
- un error de WSL no se transforma en capacidad negativa;
- hash canónico verificable;
- rechazo de informes manipulados o malformados;
- rechazo de ejecutables fuera de allowlist y de rutas de ejecutable inyectadas;
- decodificación de diagnósticos UTF-16 de Windows;
- ninguna consulta del detector referencia AI Broker.
- un Broker 2.9 con capacidades reproducibles satisface `formal_evaluation`;
- un contrato 2.8 o flags ausentes recomienda actualización solo cuando la fase los exige;
- los campos aditivos desconocidos se toleran;
- 401/403, 429, 5xx, errores permanentes y contrato inválido se clasifican por separado;
- los endpoints con credenciales, query, fragmento, path o esquema inseguro se rechazan;
- la interfaz de transporte no permite expresar POST y el token no se serializa;
- el artefacto de requisitos coincide con la política ejecutable.

La primera ejecución de tests no fue concluyente porque la carpeta temporal compartida no
permitía escritura. Se repitió en una carpeta nueva dentro del proyecto.

La negociación real con AI Broker no se ejecutó: todavía no se ha declarado el endpoint del
servicio desplegado. Por tanto, su versión sigue siendo `unknown` y no se solicita instalar
una versión nueva en este momento.

El informe generado se verificó posteriormente con:

```powershell
python -m local_ai_lab.cli verify-report `
  "artifacts/phase0/node-nvidia-20260823.json"
```

Resultado: hash válido
`77925647d76c669cac203655b6dbb56d2e0bbe638f89c79407becc62fd0c4578`.

## 7. Limitaciones

- no hay informe ejecutado en el nodo AMD;
- no se probó tensor real, dtype, forward, backward, gradientes ni 20 pasos;
- no se cargó ningún modelo;
- no se probó inferencia, embeddings, LoRA, checkpoint o resume;
- no se midieron tokens/s, memoria pico ni estabilidad;
- no se probó red entre nodos, pairing, TLS, heartbeat o jobs;
- no se negoció el contrato del AI Broker desplegado;
- no se enumeró `Y:\Mi unidad\Vaults`;
- no se verificó Model Drift mediante un contrato automatizable;
- no se construyó todavía el desktop Tauri ni el Coordinator.

## 8. Riesgos descubiertos

1. El runtime Python disponible es 3.14, pero AI Broker conserva un entorno virtual que
   apuntaba a otra instalación inexistente. Local AI Lab no dependerá de ese entorno.
2. La ruta `Y:` y WSL pueden estar disponibles para el usuario interactivo pero no para
   procesos aislados o servicios. La identidad de ejecución forma parte del despliegue.
3. Un informe de hardware sin workloads solo sirve para filtrar imposibles; no autoriza a
   asignar entrenamiento o inferencia.
4. La versión en disco de AI Broker y el servicio desplegado pueden diferir. La integración
   se decide solo mediante negociación del servicio.

## 9. Próximos pasos de Fase 0

1. Ejecutar el mismo probe en el PC AMD y traer el JSON sellado.
2. Añadir probes ML separados y opt-in para NVIDIA y AMD: tensor, dtype, backward, 20 pasos,
   modelo, LoRA y checkpoint.
3. Seleccionar un vault hijo bajo `Y:\Mi unidad\Vaults` y ejecutar enumeración read-only.
4. Obtener el endpoint de AI Broker y consultar únicamente health/capabilities.
5. Medir red entre nodos sin abrir puertos o cambiar firewall automáticamente.
6. Implementar pairing y protocolo de heartbeat/jobs en la Fase 1 después de cerrar la
   evidencia de despliegue.

## 10. Puerta de salida

La Fase 0 no puede cerrarse todavía. Requiere:

- capability reports de ambos nodos;
- smoke ML probado o degradación explícita por nodo;
- vault seleccionado y lectura protegida comprobada;
- AI Broker desplegado negociado en modo de solo lectura;
- red y autenticación entre nodos;
- inventario de almacenamiento y throughput;
- límites y sustituciones registrados.

**Decisión recomendada:** mantener la puerta cerrada y continuar con la evidencia del nodo
AMD y los smoke tests opt-in, sin comenzar aún el esqueleto distribuido de Fase 1.
