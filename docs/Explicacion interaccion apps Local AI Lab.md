Tu duda es importante porque afecta a la arquitectura base. Con lo que ya existe en el ecosistema, \*\*no haría dos aplicaciones diferentes\*\*. Haría \*\*un único Local AI Lab, con el mismo código instalado en ambos PCs, pero con roles y capacidades distintas según cada nodo\*\*.



Esto encaja además con la arquitectura actual del ecosistema: cada aplicación conserva su dominio y se integra mediante contratos, sin compartir bases de datos internas; el propio informe contempla modelos locales ejecutándose en otra máquina de la LAN.  



\## Arquitectura que recomiendo



La máquina con la \*\*4060 Ti\*\* debería ser inicialmente el \*\*nodo coordinador\*\* de Local AI Lab, porque ahí están:



\* Obsidian;

\* Knowledge Orchestrator;

\* Model Drift;

\* las demás aplicaciones;

\* acceso directo al vault;

\* y todo el contexto del ecosistema.



La máquina AMD debería ser un \*\*nodo de cómputo\*\* de Local AI Lab.



Conceptualmente:



```text

PC NVIDIA 4060 Ti

──────────────────────────────────────────────

Local AI Lab

&#x20; ├─ Desktop UI

&#x20; ├─ Coordinator

&#x20; ├─ Experiment DB

&#x20; ├─ Vault Reader \[READ ONLY]

&#x20; ├─ RAG index

&#x20; ├─ Dataset manager

&#x20; ├─ Human review

&#x20; ├─ Model Drift adapter

&#x20; ├─ AI Broker adapter

&#x20; └─ Worker NVIDIA

&#x20;         │

&#x20;         │ Local AI Lab node protocol

&#x20;         ▼

PC AMD Ryzen AI Max+ 395

──────────────────────────────────────────────

Local AI Lab Worker

&#x20; ├─ hardware/capability detector

&#x20; ├─ large local model jobs

&#x20; ├─ training jobs

&#x20; ├─ embedding/index jobs

&#x20; ├─ dataset processing

&#x20; ├─ evaluation jobs

&#x20; └─ artifact cache

```



El punto importante es que son \*\*dos despliegues del mismo producto\*\*, no dos productos.



El mismo ejecutable/código puede arrancar como:



```text

local-ai-lab desktop

local-ai-lab coordinator

local-ai-lab worker

```



o combinar varios roles en una máquina.



Así evitamos mantener dos arquitecturas que acabarían divergiendo.



\## No asignaría las funciones rígidamente por GPU



Tampoco escribiría:



> AMD hace X y NVIDIA hace Y.



Eso volvería a crear el problema que teníamos al principio.



Cada nodo publica un `NodeCapabilities` real:



```text

hostname

OS

GPU

VRAM / memoria unificada

backend

ROCm/CUDA

bf16

fp16

model\_max\_size

training\_available

GGUF\_available

embedding\_available

tokens\_per\_second

free\_memory

disk\_free

software\_versions

```



Y Local AI Lab decide dónde puede ejecutarse cada \*\*tipo de trabajo\*\*, no qué proveedor/modelo de inferencia usar. Ese matiz es importante porque el routing de modelos ya pertenece a AI Broker. 



Por ejemplo, después de medir podríamos descubrir:



```text

Trabajo                         Nodo elegido

────────────────────────────────────────────────

UI / revisión humana            NVIDIA

Leer Obsidian                   NVIDIA

Indexado inicial                NVIDIA o AMD

Modelo grande cuantizado        AMD

LoRA 1.5B                       NVIDIA

LoRA 7B                         AMD, si es viable

Evaluación rápida CUDA          NVIDIA

Embeddings masivos              el más rápido

Model Drift                     NVIDIA

GGUF conversion                 cualquiera

```



Pero esto debe salir de benchmarks, no de nombres de GPU.



\---



\# El problema de Obsidian



Aquí sí recomiendo una decisión bastante clara:



\*\*El PC AMD no debería montar ni leer directamente el vault de Obsidian por red.\*\*



Técnicamente podríamos compartir la carpeta por SMB y hacer algo así:



```text

\\\\PC-NVIDIA\\ObsidianVault

```



pero no lo elegiría como arquitectura principal.



Nos introduciría problemas de:



\* cambios durante una lectura;

\* latencia;

\* watchers;

\* bloqueos;

\* rutas Windows/WSL;

\* hashes inconsistentes;

\* desconexiones;

\* exposición innecesaria del vault;

\* dependencia de SMB dentro de procesos Linux/WSL.



Y, sobre todo, el AMD \*\*no necesita realmente acceso vivo a Obsidian\*\*.



\## La solución: snapshot de conocimiento



El Local AI Lab instalado en la máquina NVIDIA es el único componente de este proyecto que lee el vault.



Solo lectura:



```text

Obsidian

&#x20;   │

&#x20;   │ filesystem local READ ONLY

&#x20;   ▼

Vault Reader

&#x20;   │

&#x20;   ▼

Knowledge Snapshot

```



Ese snapshot podría tener algo como:



```text

snapshot\_2026-08-23\_001/

├── manifest.json

├── notes.jsonl

├── chunks.jsonl

├── links.jsonl

├── hashes.json

└── metadata.json

```



Y un identificador:



```text

vault\_snapshot\_id:

sha256:9eea...

```



El AMD trabaja sobre \*\*ese snapshot\*\*, no sobre el vault.



Esto tiene una ventaja enorme para experimentación: sabemos exactamente \*\*qué versión del conocimiento vio cada modelo\*\*.



\---



\# Dos formas de trabajar desde AMD



Dependiendo del trabajo, ni siquiera necesitamos copiar todo el snapshot.



\### Para RAG



La consulta podría funcionar así:



```text

Usuario

&#x20;  ↓

Local AI Lab Coordinator (NVIDIA)

&#x20;  ↓

retrieval sobre Vault

&#x20;  ↓

top chunks + evidencias

&#x20;  ↓

trabajo enviado al nodo AMD

&#x20;  ↓

modelo genera respuesta

&#x20;  ↓

Coordinator valida citas

```



El AMD nunca ve el vault entero. Solo recibe, por ejemplo:



```text

query

\+ 18 chunks

\+ IDs

\+ metadata

```



Esto sería mi opción por defecto para inferencia.



\### Para entrenamiento o experimentos masivos



Ahí sí interesa transferir un paquete completo:



```text

dataset\_package\_0042/

├── manifest.json

├── train.jsonl

├── validation.jsonl

├── evaluation.jsonl

├── source\_hashes.json

└── task\_contract.yaml

```



Se copia una vez al AMD, verifica hash y trabaja localmente durante horas.



No está consultando constantemente el PC NVIDIA.



\---



\# Esto mejora además la reproducibilidad



Supongamos que ejecutamos:



```text

Experimento E-142

```



Podríamos registrar:



```text

vault\_snapshot     = sha256:AAA

retrieval\_config   = hybrid-v3

embedding\_model    = XXX

generator\_model    = YYY

node               = amd-max395

dataset            = sha256:BBB

prompt             = sha256:CCC

```



Tres semanas después Obsidian habrá cambiado muchísimo.



Pero podemos decir:



> E-142 trabajó exactamente con el snapshot AAA.



Eso es mucho mejor que:



> usó “el vault que había aquel día”.



Y encaja perfectamente con la filosofía de Model Drift, que conserva manifiestos, identidad técnica, telemetría y huellas de cada tirada. 



\---



\# ¿Y Knowledge Orchestrator?



Aquí conviene mantener dos relaciones diferentes.



```text

Knowledge Orchestrator

&#x20;       │

&#x20;       │ WRITE / ownership

&#x20;       ▼

&#x20;    Obsidian

&#x20;       ▲

&#x20;       │ READ ONLY

&#x20;       │

&#x20;  Local AI Lab

```



Local AI Lab \*\*no necesita pedirle a Knowledge Orchestrator las notas\*\* si están disponibles localmente en el PC NVIDIA.



Knowledge Orchestrator continúa siendo quien:



\* crea;

\* revisa;

\* modifica;

\* publica;

\* mantiene;



el conocimiento. Eso ya es exactamente su dominio. 



Su API puede resultar útil para otras cosas:



```text

estado de publicación

procedencia

claims

manual\_lock

workflows

metadata que no esté en Markdown

```



Pero no convertiría a Knowledge Orchestrator en un servidor de archivos solo para resolver este problema.



\---



\# Una distinción importante: vault vs índice



El AMD tampoco debería mantener “una segunda copia de Obsidian”.



Debe mantener una \*\*caché derivada\*\*.



Por ejemplo:



```text

NVIDIA

Obsidian = fuente de conocimiento



&#x20;       ↓ snapshot



AMD

\~/.local-ai-lab/cache/

&#x20;   vault/

&#x20;      sha256-AAA/

&#x20;      sha256-BBB/

```



Esos datos son:



\* regenerables;

\* inmutables;

\* identificados por hash;

\* eliminables cuando dejan de usarse.



No son otro vault.



Eso evita tener que sincronizar bidireccionalmente nada.



\---



\# ¿Dónde viviría la base de Local AI Lab?



También aquí evitaría una BD compartida por red.



El informe establece como principio que cada aplicación sea dueña de su persistencia y que no se consulte directamente la SQLite de otra aplicación. 



Yo ampliaría el mismo principio entre nodos de Local AI Lab.



El \*\*Coordinator NVIDIA\*\* posee el estado autoritativo:



```text

projects

experiments

benchmarks

human feedback

dataset manifests

promotion decisions

node registry

jobs

```



El worker AMD mantiene solamente:



```text

job cache

datasets transferidos

checkpoints

model cache

temporary artifacts

local metrics

```



Y devuelve artefactos/resultados al coordinator.



No:



```text

AMD ──► \\\\NVIDIA\\local-ai-lab.db

```



Sí:



```text

AMD ──HTTPS/API──► Local AI Lab Coordinator

```



\---



\# Qué ocurre si el PC NVIDIA está apagado



Esto también hay que definir.



Mi propuesta:



El worker AMD puede terminar trabajos ya recibidos aunque el Coordinator desaparezca.



Ejemplo:



```text

NVIDIA envía entrenamiento #347

&#x20;      ↓

AMD persiste job local

&#x20;      ↓

NVIDIA se apaga

&#x20;      ↓

AMD continúa 6 horas

&#x20;      ↓

termina + guarda resultado

&#x20;      ↓

NVIDIA vuelve

&#x20;      ↓

AMD reporta resultado

```



Es el mismo principio de durabilidad que ya aparece repetidamente en tu ecosistema: persistir intención, usar estados recuperables e idempotencia, en vez de fingir una transacción distribuida. 



\---



\# Y podría abrir Local AI Lab desde ambos PCs



Incluso teniendo un coordinador principal, no limitaría la interfaz a una máquina.



Podríamos tener:



```text

NVIDIA

Local AI Lab Desktop

&#x20;       │

&#x20;       ▼

Coordinator local



AMD

Local AI Lab Desktop (opcional)

&#x20;       │

&#x20;       │ LAN

&#x20;       ▼

Coordinator NVIDIA

```



Así, cuando estés sentado delante del AMD puedes abrir la misma aplicación y ver:



\* experimentos;

\* entrenamiento;

\* GPU;

\* métricas;

\* datasets;

\* resultados;



pero sigues teniendo \*\*una única fuente de estado\*\*.



El Desktop AMD sería un cliente del Coordinator NVIDIA.



\---



\# Topología que dejaría fijada en la SPEC



```text

&#x20;                   PC NVIDIA 4060 Ti

&#x20;       ┌────────────────────────────────┐

&#x20;       │                                │

&#x20;       │ Obsidian                       │

&#x20;       │ Knowledge Orchestrator         │

&#x20;       │ Model Drift                    │

&#x20;       │ otras apps                     │

&#x20;       │                                │

&#x20;       │      Local AI Lab              │

&#x20;       │  ┌──────────────────────────┐  │

&#x20;       │  │ Coordinator             │  │

&#x20;       │  │ Desktop UI              │  │

&#x20;       │  │ Experiment DB           │  │

&#x20;       │  │ Vault Reader RO         │  │

&#x20;       │  │ RAG/index               │  │

&#x20;       │  │ Dataset Manager         │  │

&#x20;       │  │ Worker NVIDIA           │  │

&#x20;       │  └────────────┬─────────────┘  │

&#x20;       │               │                │

&#x20;       └───────────────┼────────────────┘

&#x20;                       │ authenticated LAN

&#x20;                       │ jobs / artifacts /

&#x20;                       │ snapshots

&#x20;                       ▼

&#x20;       ┌────────────────────────────────┐

&#x20;       │ PC AMD Ryzen AI Max+ 395       │

&#x20;       │                                │

&#x20;       │ Local AI Lab                   │

&#x20;       │  ┌──────────────────────────┐  │

&#x20;       │  │ Worker AMD              │  │

&#x20;       │  │ model cache             │  │

&#x20;       │  │ snapshot cache          │  │

&#x20;       │  │ training               │  │

&#x20;       │  │ inference              │  │

&#x20;       │  │ embeddings             │  │

&#x20;       │  │ evaluation             │  │

&#x20;       │  └──────────────────────────┘  │

&#x20;       └────────────────────────────────┘



&#x20;                        │

&#x20;                 ambos pueden usar

&#x20;                        ▼



&#x20;                   ┌───────────┐

&#x20;                   │ AI Broker │

&#x20;                   └───────────┘

```



Esto también respeta la recomendación del informe de mantener un inventario de despliegue con nodos, puertos, servicios y capacidades efectivas. 



\## Mi decisión para la SPEC



Por tanto fijaría ya estas tres decisiones:



\* \*\*Un único Local AI Lab\*\*, no dos aplicaciones especializadas.

\* \*\*Arquitectura Coordinator + Workers\*\*, con capacidades detectadas dinámicamente.

\* \*\*Obsidian solo se lee localmente en el PC NVIDIA\*\*; los demás nodos reciben contextos, datasets o snapshots inmutables mediante el protocolo de Local AI Lab.



Y añadiría una cuarta:



> \*\*Nunca montar el vault remoto como dependencia operativa del nodo AMD.\*\*



Puede existir SMB como herramienta manual de diagnóstico o contingencia, pero no como contrato arquitectónico.



Con esto ya considero resuelta la principal incertidumbre distribuida. El siguiente paso sería actualizar la \*\*Spec resumida definitiva de Local AI Lab\*\*, incorporando Coordinator/Worker, snapshotting del vault, integración automática con Model Drift, benchmark real + controlado y las fronteras con AI Broker/Knowledge Orchestrator. Después ya podríamos convertirla en el nuevo prompt maestro para Claude Code/Codex.



