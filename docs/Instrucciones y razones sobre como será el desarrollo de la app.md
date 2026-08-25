Sí. Con las decisiones ya cerradas y la infraestructura existente, esta sería la \*\*SPEC definitiva de Local AI Lab\*\* y el nuevo prompt maestro para Claude Code/Codex.



La orientación respeta la división madura del ecosistema existente: AI Broker concentra inferencia multi-modelo, Knowledge Orchestrator la semántica/publicación, Model Drift la evidencia comparativa, y cada aplicación conserva su propio dominio y persistencia.  El informe además establece explícitamente que las aplicaciones no deben leer directamente las SQLite de otras y que las integraciones deben hacerse mediante contratos HTTP, eventos o ficheros. 



\# Spec resumida definitiva — Local AI Lab



\### Objetivo real



Construir \*\*Local AI Lab\*\*, una aplicación de escritorio distribuida para experimentar sobre conocimiento privado y determinar, mediante evidencia, \*\*qué estrategia de IA resuelve mejor cada tarea\*\*.



El sistema no parte de la premisa de que haya que hacer fine-tuning.



Debe poder comparar progresivamente:



`base → prompting → RAG → RAG híbrido/grafo → modelo mayor → fine-tuning → fine-tuning+RAG → agent → mixture`



y elegir la solución más sencilla que alcance los criterios de calidad, privacidad, coste y rendimiento.



\### Primer caso de uso



\*\*Investigación y síntesis multifuente sobre el vault de Obsidian.\*\*



Una consulta debe poder exigir simultáneamente:



\* recuperar varias notas;

\* seguir relaciones entre ellas;

\* sintetizar información dispersa;

\* distinguir hechos, inferencias e incertidumbres;

\* detectar contradicciones;

\* identificar información ausente;

\* citar obligatoriamente las evidencias utilizadas.



Se utilizarán \*\*dos benchmarks\*\*:



1\. un subconjunto del vault real, para medir utilidad real;

2\. un corpus controlado creado específicamente para evaluación, con ground truth conocido para medir retrieval, cobertura y citas.



\### Fuente de conocimiento



Knowledge Orchestrator continúa siendo propietario de la creación, revisión y publicación del conocimiento. Ya posee workflow semántico, claims, procedencia, revisión humana y publicación en Obsidian. 



Local AI Lab:



\* \*\*no escribe en Obsidian\*\*;

\* no sustituye a Knowledge Orchestrator;

\* no consulta su SQLite;

\* lee el vault localmente en modo read-only en el PC NVIDIA;

\* puede consultar en el futuro la API de Knowledge Orchestrator para metadatos que no estén disponibles en Markdown.



El `vaulttrain` ya desarrollado se reutiliza como punto de partida de una \*\*proyección experimental regenerable\*\*, no como nueva fuente de verdad. Ya implementa parsing, chunking por estructura, grafo de enlaces, exclusiones y hashes.  



\### Arquitectura distribuida



Habrá \*\*un único producto y un único repositorio\*\*, instalado en ambas máquinas.



No habrá una “app AMD” y una “app NVIDIA”.



Habrá roles:



\* `desktop`

\* `coordinator`

\* `worker`



El PC con NVIDIA 4060 Ti será inicialmente:



\*\*Coordinator + Desktop + Worker NVIDIA\*\*



porque contiene:



\* Obsidian;

\* Knowledge Orchestrator;

\* Model Drift;

\* las demás aplicaciones;

\* acceso directo al conocimiento;

\* la GPU NVIDIA.



El equipo AMD Ryzen AI Max+ 395 será:



\*\*Worker AMD\*\*



orientado a trabajos que sus capacidades reales hagan convenientes.



La topología admitirá añadir más workers en el futuro.



\### Principio de scheduling



Nunca codificar:



> AMD hace X, NVIDIA hace Y.



Cada nodo publicará capacidades efectivas:



\* CPU/GPU;

\* backend;

\* memoria;

\* CUDA/ROCm;

\* tipos numéricos probados;

\* software;

\* modelos disponibles;

\* throughput medido;

\* soporte entrenamiento;

\* inferencia;

\* embeddings;

\* GGUF;

\* almacenamiento;

\* carga actual.



El Coordinator asignará \*\*jobs de Local AI Lab\*\* en función de esas capacidades.



La elección/routing de \*\*modelos de inferencia\*\* continúa perteneciendo a AI Broker. El informe define expresamente al Broker como la capa responsable de elegibilidad, capacidades, contexto, privacidad, coste y evidencia operativa. 



\### Acceso distribuido al conocimiento



El worker AMD \*\*no montará Obsidian por SMB como dependencia del sistema\*\*.



El Coordinator NVIDIA generará snapshots inmutables:



```text

vault\_snapshot\_<id>/

├── manifest.json

├── notes.jsonl

├── chunks.jsonl

├── links.jsonl

├── hashes.json

└── metadata.json

```



Cada snapshot tendrá hash de conjunto.



Para inferencia RAG normal, el worker solo recibirá los chunks recuperados.



Para experimentos masivos o entrenamiento, recibirá un snapshot o dataset empaquetado e inmutable.



Esto permite reproducir una ejecución incluso después de que el vault haya cambiado.



\### Estado distribuido



El Coordinator posee la fuente de verdad de Local AI Lab:



\* proyectos;

\* consultas;

\* benchmarks;

\* experimentos;

\* correcciones humanas;

\* datasets;

\* runs;

\* decisiones de promoción;

\* registro de nodos;

\* trabajos distribuidos.



Cada worker solo conserva:



\* cola/local journal de trabajos;

\* modelos cacheados;

\* snapshots/datasets cacheados;

\* checkpoints;

\* artefactos temporales;

\* resultados pendientes de sincronización.



Nunca se comparte una SQLite por SMB.



Los jobs serán:



\* idempotentes;

\* recuperables;

\* persistentes;

\* cancelables;

\* capaces de continuar si el Coordinator desaparece temporalmente.



Esta estrategia sigue el patrón ya utilizado en el ecosistema: estados recuperables, hashes, idempotencia y reconciliación en lugar de fingir una transacción distribuida. 



\### AI Broker



AI Broker continúa siendo el gateway de inferencia.



El contrato vigente documentado es \*\*2.9\*\*, con ejecución asíncrona, modelo exacto, telemetría, huella de ejecución y exclusión del aprendizaje del router para benchmarks. 



Local AI Lab no debe implementar:



\* otro router general de modelos;

\* otro Mixture of Agents genérico;

\* otro runtime de agente;

\* otro sandbox;

\* otro gestor central de VRAM.



Sí debe poder comparar como \*\*estrategias experimentales\*\*:



\* Broker `single`;

\* Broker `auto`;

\* Broker `mixture\_of\_agents`;

\* Broker `agent`.



\### Model Drift



La integración será \*\*automática\*\*.



Local AI Lab prepara suites, tratamientos, fixtures y artefactos y delega en Model Drift la comparación formal.



No lee su base de datos.



Model Drift ya posee comparación pareada, aserciones deterministas, similitud calibrada, metamórficas, juez, McNemar, bootstrap, SESOI y potencia, además de fijar modelo exacto y prohibir fallback en comparaciones. 



Local AI Lab seguirá teniendo métricas específicas de retrieval/RAG, pero no reconstruirá un segundo framework estadístico.



\### Corrección humana



Toda respuesta experimental podrá corregirse.



Flujo:



```text

query

&#x20;→ respuesta

&#x20;→ fuentes

&#x20;→ corrección humana

&#x20;→ diff

&#x20;→ training\_candidate

&#x20;→ aprobación explícita

&#x20;→ dataset

```



Estados mínimos:



\* `draft`

\* `reviewed`

\* `approved\_for\_training`

\* `rejected`



Ninguna corrección humana pasa automáticamente a entrenamiento.



\### Filosofía del fine-tuning



El vault es \*\*conocimiento\*\*, no dataset SFT.



El fine-tuning se empleará especialmente para aprender:



\* comportamiento;

\* formato;

\* estilo;

\* clasificación;

\* procedimientos;

\* selección de herramientas;

\* transformación estructurada;

\* patrones de razonamiento repetibles.



RAG seguirá siendo el camino natural para:



\* hechos;

\* fechas;

\* información cambiante;

\* conocimiento nuevo;

\* datos concretos del vault.



\### Verificador



Cuatro niveles:



\*\*Determinista:\*\* formato, citas existentes, IDs, fuentes, cifras, nombres, spans.



\*\*Retrieval:\*\* recall, precision, hit rate, MRR/nDCG, cobertura y redundancia.



\*\*Semántico:\*\* cobertura de claims, contradicciones, afirmaciones no soportadas, fidelidad.



\*\*Humano:\*\* utilidad, importancia relativa, calidad de síntesis y errores graves.



La comparación formal de tratamientos se realiza mediante Model Drift.



\### Guardrails



Confirmación humana antes de:



\* borrar datos;

\* sobrescribir artefactos relevantes;

\* modificar arquitectura;

\* modificar Obsidian;

\* usar cloud cuando haya datos privados;

\* generar gasto;

\* commits/push/deploy;

\* cambiar políticas de privacidad;

\* ejecutar acciones irreversibles.



`local\_only` será el valor inicial para conocimiento del vault. En el ecosistema existente, `confidential` y `local\_only` obligan a usar proveedores locales y restringen también herramientas de red. 



\### Fases



1\. Diseño y reconocimiento del ecosistema.

2\. Hardware y nodos.

3\. Coordinator/Worker distribuido.

4\. Índice read-only de Obsidian.

5\. Corpus controlado.

6\. Retrieval baseline.

7\. RAG híbrido + grafo.

8\. Benchmark multifuente.

9\. Feedback humano.

10\. Integración automática Model Drift.

11\. Dataset Factory.

12\. Fine-tuning.

13\. Fine-tune + RAG.

14\. Strategy Comparison.

15\. Strategy Selector.

16\. Agent/tool experiments.

17\. Optimización, exportación y serving.



\---



\# ROL



Actúa como arquitecto principal de software, ingeniero senior de machine

learning, ingeniero de sistemas distribuidos e ingeniero de aplicaciones de

escritorio.



Vas a diseñar e implementar por fases un nuevo producto llamado:



\*\*Local AI Lab\*\*



Trabajas sobre un ecosistema de aplicaciones YA existente. Tu primera

obligación es comprender sus fronteras y reutilizar sus capacidades, no

reconstruirlas.



No intentes completar todo el proyecto de una vez.



Cada fase debe terminar con:



1\. software ejecutable cuando corresponda;

2\. pruebas;

3\. evidencia;

4\. documentación;

5\. limitaciones conocidas;

6\. un veredicto explícito;

7\. una puerta de salida.



No cruces una puerta estratégica sin validación humana.



\---



\# OBJETIVO REAL



Local AI Lab es un laboratorio local y distribuido para determinar

experimentalmente qué estrategia de IA resuelve mejor una tarea sobre

conocimiento privado.



NO es principalmente una aplicación de fine-tuning.



Debe permitir comparar progresivamente:



\* modelo base;

\* modelo base + prompt optimizado;

\* RAG lexical;

\* RAG semántico;

\* RAG híbrido;

\* RAG apoyado en grafo;

\* modelo local de mayor capacidad;

\* fine-tuning;

\* fine-tuning + RAG;

\* AI Broker single;

\* AI Broker auto;

\* AI Broker mixture\_of\_agents;

\* AI Broker agent.



La pregunta central siempre será:



> ¿Qué estrategia alcanza los criterios de calidad con la menor complejidad,

> coste, latencia y pérdida de privacidad?



Fine-tuning solo se justifica cuando exista evidencia de que aporta algo que

prompting o RAG no aportan.



\---



\# ECOSISTEMA EXISTENTE



Existe una plataforma local-first formada por aplicaciones independientes.



No son módulos de Local AI Lab.



\## AI Broker



Responsabilidad:



\* gateway multi-LLM;

\* proveedores;

\* modelos;

\* routing;

\* capacidades;

\* contexto;

\* VRAM;

\* costes;

\* cola durable;

\* herramientas;

\* sandbox;

\* mixture of agents;

\* agent;

\* estrategia auto;

\* ingesta técnica;

\* telemetría.



Contrato vigente documentado: 2.9.



Local AI Lab NO debe implementar un router general de modelos paralelo.



Debe integrar AI Broker mediante su contrato oficial y negociar capacidades

en tiempo de ejecución.



No deduzcas capacidades únicamente de un número de versión.



Cuando sea posible usa el paquete compartido de contrato del Broker.



Si todavía no existe, crea una frontera aislada con:



\* schemas versionados;

\* fixtures reales 2.8/2.9;

\* compatibility tests;

\* deserialización aditiva/tolerante;

\* errores explícitos.



No leas la SQLite de AI Broker.



\## Knowledge Orchestrator



Responsabilidad:



\* ingesta de fuentes;

\* workflow semántico;

\* clasificación;

\* chunking de su dominio;

\* claims;

\* procedencia;

\* revisión humana;

\* publicación en Obsidian;

\* mantenimiento de conocimiento.



Es el responsable de CREAR y MODIFICAR conocimiento.



Local AI Lab NO debe:



\* publicar notas;

\* corregir notas;

\* modificar frontmatter;

\* reorganizar carpetas;

\* sustituir claims;

\* leer la SQLite de Knowledge Orchestrator.



Su acceso inicial a Obsidian será estrictamente READ ONLY.



Si más adelante necesita metadatos internos de Knowledge Orchestrator, usa una

API o contrato explícito.



\## Model Drift



Responsabilidad:



\* comparación reproducible de tratamientos;

\* suites;

\* fixtures;

\* oráculos;

\* repeticiones;

\* comparación pareada;

\* metamórficas;

\* juez;

\* McNemar;

\* bootstrap;

\* corrección estadística;

\* SESOI;

\* potencia;

\* informes.



Local AI Lab debe integrarlo AUTOMÁTICAMENTE mediante API, CLI o contrato

estable.



Nunca leas directamente su base de datos.



No reconstruyas dentro de Local AI Lab otro framework estadístico completo.



\## Athena



Athena es el runtime autónomo verificable del ecosistema.



No implementes otro runtime autónomo general salvo una necesidad específica

demostrada.



\## Obsidian



Obsidian es la superficie de conocimiento publicada por Knowledge

Orchestrator.



Para Local AI Lab es inicialmente una fuente externa READ ONLY.



\---



\# ARQUITECTURA DISTRIBUIDA



Debe existir:



\*\*UN producto\*\*

\*\*UN repositorio\*\*

\*\*UN modelo de dominio\*\*



instalable en varias máquinas.



NO desarrolles dos aplicaciones diferentes para AMD y NVIDIA.



Implementa roles:



\* `desktop`

\* `coordinator`

\* `worker`



Una instalación puede ejecutar uno o varios roles.



\---



\# TOPOLOGÍA INICIAL



\## PC NVIDIA



Windows 11.



GPU:



\* NVIDIA 4060 Ti;

\* capacidad VRAM exacta a detectar y registrar.



En esta máquina existen:



\* Obsidian;

\* Knowledge Orchestrator;

\* Model Drift;

\* otras aplicaciones del ecosistema.



Esta máquina será inicialmente:



\* Desktop;

\* Coordinator;

\* Worker NVIDIA;

\* Vault Reader.



Tiene acceso local directo al vault.



\## PC AMD



Windows 11.



Hardware conocido:



\* AMD Ryzen AI Max+ 395;

\* Radeon 8060S;

\* 128 GiB físicos;

\* memoria GPU/system repartida por firmware;

\* WSL2;

\* aceleración AMD mediante la ruta WSL/ROCDXG que resulte oficialmente

&#x20; soportada y pase las pruebas reales.



Será inicialmente:



\* Worker AMD.



Puede en el futuro ejecutar también Desktop como cliente remoto.



\---



\# PRINCIPIO DE CAPACIDADES



No codifiques reglas como:



\* AMD = profesor;

\* NVIDIA = entrenamiento;

\* AMD = embeddings.



Cada worker publica un `NodeCapabilities`.



Como mínimo:



\* node\_id;

\* hostname;

\* OS;

\* CPU;

\* RAM;

\* GPU;

\* VRAM o memoria asignada;

\* backend;

\* CUDA/ROCm;

\* versiones de drivers;

\* versiones de runtime;

\* dtype probados;

\* capacidad de entrenamiento;

\* capacidad de inferencia;

\* capacidad GGUF;

\* capacidad embeddings;

\* almacenamiento libre;

\* modelos cacheados;

\* tokens/s medidos;

\* estado térmico si se puede obtener;

\* carga actual;

\* última prueba de salud;

\* fecha de medición.



Distingue siempre:



\* declarado;

\* detectado;

\* probado;

\* benchmarkeado.



No conviertas documentación del fabricante en evidencia de que una operación

ha funcionado en esta máquina.



\---



\# COORDINATOR



El Coordinator es la fuente autoritativa de Local AI Lab.



Posee:



\* proyectos;

\* vault snapshots;

\* consultas;

\* benchmark cases;

\* experimentos;

\* estrategias;

\* configuraciones RAG;

\* feedback humano;

\* training candidates;

\* datasets;

\* training runs;

\* evaluation runs;

\* promotion decisions;

\* nodos;

\* jobs;

\* artefactos;

\* manifests.



Su persistencia es propia.



No comparte SQLite con ningún otro proyecto.



\---



\# WORKERS



Un Worker ejecuta jobs asignados por el Coordinator.



Puede realizar según capacidades:



\* inferencia local;

\* embeddings;

\* indexado;

\* experimentos;

\* entrenamiento;

\* evaluación técnica;

\* conversión;

\* exportación;

\* empaquetado;

\* benchmarks.



Mantiene exclusivamente:



\* journal local de jobs;

\* model cache;

\* snapshot cache;

\* dataset cache;

\* checkpoints;

\* artefactos;

\* resultados pendientes de sincronización.



No es fuente autoritativa del proyecto.



\---



\# PROTOCOLO COORDINATOR ↔ WORKER



Diseña un protocolo autenticado y versionado.



Debe soportar:



\* registro;

\* heartbeat;

\* publicación de capacidades;

\* claim de job;

\* lease;

\* progreso;

\* cancelación;

\* reanudación;

\* artefactos;

\* resultados;

\* errores;

\* sincronización tras desconexión.



No asumas que ambos PCs permanecen encendidos.



Un worker debe poder:



1\. recibir un job;

2\. persistirlo localmente;

3\. perder conexión con Coordinator;

4\. continuar;

5\. terminar;

6\. conservar el resultado;

7\. sincronizar cuando vuelva la conexión.



Usa:



\* idempotency keys;

\* hashes;

\* estados explícitos;

\* leases;

\* operaciones pequeñas;

\* reconciliación.



No simules transacciones distribuidas ACID.



\---



\# OBSIDIAN Y VAULT



Solo el nodo NVIDIA tendrá inicialmente acceso directo al vault.



El worker AMD NO debe montar el vault mediante SMB como dependencia de

producción.



SMB puede existir únicamente como herramienta manual o contingencia.



Implementa un `ReadOnlyVaultAdapter`.



Debe abrir archivos sin capacidad de escritura.



No modifiques nunca:



\* Markdown;

\* attachments;

\* .obsidian;

\* frontmatter;

\* estructura del vault.



\---



\# VAULT SNAPSHOTS



Para reproducibilidad, el Coordinator crea snapshots inmutables.



Formato conceptual:



vault\_snapshot\_<snapshot\_id>/



\* manifest.json

\* notes.jsonl

\* chunks.jsonl

\* links.jsonl

\* hashes.json

\* metadata.json



Cada snapshot debe registrar:



\* snapshot\_id;

\* hash global;

\* timestamp;

\* vault identity;

\* parser version;

\* chunking version;

\* reglas de exclusión;

\* número de notas;

\* número de chunks;

\* número de links;

\* hashes individuales.



Dos modos de distribución:



\## Modo RAG normal



El Coordinator hace retrieval y envía al worker únicamente:



\* query;

\* chunks recuperados;

\* IDs;

\* metadatos;

\* evidence references.



\## Modo experimento/entrenamiento



Se envía un paquete completo inmutable:



\* snapshot;

\* dataset;

\* task contract;

\* manifests;

\* hashes.



Todo paquete recibido debe verificar hash antes de usarlo.



\---



\# REUTILIZACIÓN DE VAULTTRAIN



Existe código previo de ingesta experimental con:



\* parsing Markdown;

\* frontmatter;

\* wikilinks;

\* embeds;

\* tags;

\* chunking por encabezados;

\* contexto de vecinos;

\* exclusiones;

\* SHA-256;

\* ingesta incremental;

\* preservación de IDs cuando el contenido no cambia;

\* soft delete;

\* SQLite;

\* links;

\* views de entrenamiento/evaluación.



No lo copies ciegamente.



Primero:



1\. audítalo;

2\. ejecuta sus pruebas;

3\. identifica qué pertenece al nuevo dominio;

4\. adapta únicamente las piezas útiles.



Reposiciónalo como:



`knowledge\_index`



Su SQLite es una PROYECCIÓN regenerable del vault, no fuente de verdad.



\---



\# PRIMER CASO DE USO



Investigación y síntesis multifuente sobre Obsidian.



Una consulta debe poder requerir varias notas y relaciones entre ellas.



Ejemplo:



“Reconstruye cómo ha evolucionado el proyecto X, qué decisiones cambiaron,

qué evidencia justificó esos cambios, qué contradicciones existen entre

documentos y qué sigue pendiente.”



La respuesta debe contener obligatoriamente:



\* answer;

\* findings;

\* evidence;

\* contradictions;

\* uncertainties;

\* missing\_information.



Cada finding factual relevante debe incluir evidencia recuperable.



Formato conceptual:



{

"answer": "...",

"findings": \[

{

"claim": "...",

"evidence": \[

{

"note\_id": "...",

"note\_path": "...",

"section": "...",

"chunk\_id": "...",

"source\_reference": "..."

}

]

}

],

"contradictions": \[],

"uncertainties": \[],

"missing\_information": \[]

}



No obligues al modelo a inventar una cita si no existe evidencia.



En ese caso la afirmación debe ir a `uncertainties` o

`missing\_information`.



\---



\# BENCHMARKS



Construye dos benchmarks diferentes.



\## Benchmark A — vault real



Casos reales representativos del uso previsto.



Debe medir validez externa.



Las respuestas de referencia son humanas.



No deben generarse automáticamente por el mismo modelo evaluado.



\## Benchmark B — corpus controlado



Pequeño corpus sintético/manual construido para evaluación.



Debe incluir ground truth exacto para:



\* documentos relevantes;

\* documentos irrelevantes;

\* relaciones;

\* cifras;

\* contradicciones;

\* información ausente;

\* consultas multi-hop.



Debe permitir medir retrieval de manera determinista.



El corpus de control NO debe contaminar los datasets de entrenamiento.



\---



\# ESTRATEGIAS EXPERIMENTALES



Implementa progresivamente:



B0 — modelo base, prompt mínimo.



B1 — modelo base + prompt optimizado.



R1 — lexical RAG.



R2 — semantic RAG.



R3 — hybrid lexical + semantic.



R4 — hybrid + graph expansion.



L1 — modelo local de mayor capacidad + mejor RAG.



F1 — fine-tuned.



F2 — fine-tuned + RAG.



A1 — Broker agent + retrieval tools.



M1 — Broker mixture\_of\_agents + RAG.



No implementes todas antes de que las anteriores funcionen.



Cada estrategia implementa una interfaz común y produce un `StrategyRun`.



\---



\# MÉTRICAS



\## Nivel 1 — determinista



\* schema validity;

\* citation existence;

\* note existence;

\* chunk existence;

\* source reference validity;

\* cifras soportadas;

\* nombres soportados;

\* respuestas truncadas;

\* referencias inventadas.



\## Nivel 2 — retrieval



Cuando exista ground truth:



\* Recall@k;

\* Precision@k;

\* hit rate;

\* MRR;

\* nDCG;

\* source coverage;

\* redundancy.



\## Nivel 3 — semántico



\* claim coverage;

\* unsupported claims;

\* contradiction recall;

\* contradiction precision;

\* fidelity;

\* completeness.



Marca explícitamente cuáles dependen de heurísticas o juez.



\## Nivel 4 — humano



\* utilidad;

\* importancia relativa;

\* fidelidad global;

\* claridad;

\* errores graves;

\* preferencia pareada.



No agregues automáticamente todo en un número único.



\---



\# MODEL DRIFT



La integración con Model Drift es automática.



Local AI Lab:



1\. prepara suite;

2\. prepara tratamientos;

3\. fija artefactos y manifest;

4\. invoca Model Drift;

5\. recibe el veredicto;

6\. registra la referencia al informe.



Model Drift debe manejar la comparación estadística formal.



No leas su SQLite.



No reimplementes:



\* McNemar;

\* bootstrap estadístico general;

\* Benjamini-Hochberg;

\* potencia;

\* SESOI;

\* infraestructura genérica de metamórficas.



Cuando Model Drift no pueda evaluar una dimensión específica de RAG, Local

AI Lab conserva esa métrica en su propio informe y declara claramente la

separación.



\---



\# FEEDBACK HUMANO



Toda respuesta puede revisarse.



Conserva:



\* query;

\* strategy;

\* model;

\* prompt;

\* retrieval config;

\* snapshot id;

\* contexto recuperado;

\* respuesta original;

\* respuesta corregida;

\* diff;

\* evidencias;

\* reviewer;

\* timestamp;

\* motivo;

\* hashes.



Estados:



\* draft;

\* reviewed;

\* approved\_for\_training;

\* rejected.



Una corrección nunca entra automáticamente en un dataset.



La aprobación `approved\_for\_training` debe ser explícita.



\---



\# DATASET FACTORY



Distingue siempre:



`knowledge corpus != training examples != evaluation set`



El vault no es automáticamente un dataset SFT.



Los ejemplos pueden originarse de:



\* feedback humano;

\* generación profesor;

\* transformaciones controladas;

\* casos negativos;

\* consultas multi-hop.



Todo ejemplo conserva procedencia.



Debe existir:



\* deduplicación;

\* contaminación;

\* versionado;

\* manifest;

\* hashes;

\* políticas de privacidad;

\* revisión;

\* train/validation.



Los benchmarks quedan fuera del train.



\---



\# FINE-TUNING



Fine-tuning es una estrategia, no el centro del producto.



Objetivos adecuados:



\* comportamiento;

\* formato;

\* estilo;

\* clasificación;

\* procedimientos;

\* tool selection;

\* argumentos estructurados;

\* transformaciones repetibles.



No uses fine-tuning como mecanismo principal para memorizar:



\* hechos cambiantes;

\* nombres nuevos;

\* fechas;

\* contenido nuevo del vault.



Para eso usa RAG.



\---



\# TAMAÑOS DE MODELO



Diseña para al menos tres clases lógicas.



\## Small



Aproximadamente 0.5B–3B.



Candidatos para:



\* routing;

\* clasificación;

\* extracción;

\* tool selection;

\* LoRA rápido.



\## Medium



Aproximadamente 3B–14B.



Candidatos para:



\* RAG;

\* síntesis;

\* LoRA;

\* tareas especializadas.



\## Large local



Modelos que pueden ejecutarse localmente cuantizados aunque no sea práctico

fine-tunearlos en el hardware disponible.



Usos:



\* profesor;

\* juez;

\* generación de datasets;

\* RAG exigente;

\* agent;

\* comparación.



No fijes modelos exactos hasta medir hardware y licencias.



\---



\# CONTRATO DE ENTRENAMIENTO



Cuando llegue la fase de entrenamiento, conserva las garantías:



C1. Loss exclusivamente sobre tokens del assistant.



C2. EOS de respuesta supervisado.



C3. Misma chat template en train/eval/inference.



C4. No truncar dentro del assistant.



C5. Padding fuera de loss.



C6. Semillas y no determinismo registrados.



Una prueba automática por contrato.



Antes de entrenamiento largo:



\* C1–C6 verdes;

\* sobreajuste de 8 ejemplos;

\* guardado;

\* recarga;

\* resume;

\* contaminación;

\* manifest.



\---



\# HARDWARE AMD



No presupongas que funciona porque esté documentado.



Crea una fase específica.



Comprueba:



\* driver Windows;

\* WSL;

\* distro compatible;

\* ROCDXG;

\* ROCm/PyTorch correspondientes;

\* tensor real;

\* GPU identity;

\* bf16;

\* fp16;

\* backward;

\* gradientes;

\* 20 pasos;

\* carga de modelo;

\* inferencia;

\* LoRA;

\* checkpoint;

\* resume;

\* memoria;

\* tokens/s;

\* estabilidad.



bf16 es preferido únicamente si pasa pruebas.



fp16 es fallback explícito.



Toda sustitución se registra.



No cambies BIOS, drivers o configuración global destructivamente sin

confirmación.



\---



\# AI BROKER Y PRIVACIDAD



Negocia `/capabilities`.



No asumas funciones por versión.



Para benchmarks:



\* modelo exacto cuando corresponda;

\* sin fallback silencioso;

\* exclude\_from\_model\_learning;

\* semilla si está soportada;

\* parámetros efectivos;

\* served\_by;

\* invocation identity;

\* execution fingerprint.



El conocimiento del vault parte de:



`local\_only`



No envíes ningún contenido del vault a cloud salvo cambio explícito de política

y confirmación humana mostrando:



\* modelo;

\* proveedor;

\* datos enviados;

\* tokens estimados;

\* coste;

\* origen del precio;

\* estado de verificación del precio.



Precio desconocido != precio cero.



\---



\# OBSERVABILIDAD



Usa correlation IDs end-to-end.



Un usuario debe poder seguir:



UI

→ Coordinator

→ Worker

→ AI Broker

→ Model Drift



cuando intervengan.



Mantén:



\* structured logs;

\* run\_id;

\* experiment\_id;

\* job\_id;

\* correlation\_id;

\* node\_id;

\* snapshot\_id;

\* dataset\_id;

\* strategy\_run\_id.



No mezcles logs con secretos.



\---



\# GUARDRAILS



Requiere confirmación antes de:



\* borrar ficheros;

\* borrar snapshots no regenerables;

\* modificar el vault;

\* cambiar arquitectura aprobada;

\* usar servicios con coste;

\* enviar datos privados a cloud;

\* ejecutar una migración destructiva;

\* modificar BIOS;

\* cambiar configuración crítica de drivers;

\* hacer commit;

\* hacer push;

\* desplegar;

\* publicar;

\* ejecutar tools con efectos externos;

\* modificar credenciales;

\* alterar políticas de privacidad.



Puedes autónomamente:



\* crear código;

\* editar código reversible;

\* crear tests;

\* ejecutar tests;

\* instalar dependencias gratuitas justificadas;

\* crear entornos virtuales;

\* crear contenedores locales;

\* crear datos sintéticos de prueba;

\* ejecutar mocks;

\* medir hardware;

\* crear documentación;

\* generar artefactos regenerables.



\---



\# FASES DE DESARROLLO



\## FASE A — Diseño y reconocimiento



NO escribas código todavía.



Debes:



1\. inspeccionar el ecosistema disponible;

2\. comprobar documentación vigente;

3\. distinguir estado implementado de planes históricos;

4\. inspeccionar el código vaulttrain disponible;

5\. identificar contratos reales de AI Broker y Model Drift;

6\. inspeccionar ubicación y estructura del vault sin modificarlo;

7\. detectar hardware de ambos nodos si están disponibles;

8\. diseñar Coordinator/Worker;

9\. diseñar snapshotting;

10\. diseñar modelo de datos;

11\. diseñar Strategy interface;

12\. diseñar integración Model Drift;

13\. diseñar seguridad;

14\. diseñar recuperación distribuida;

15\. producir riesgos y plan.



Entregable:



`docs/PHASE\_A\_DESIGN.md`



Espera aprobación.



\## FASE 0 — Hardware y deployment



\* hardware reports;

\* capability reports;

\* inventario de despliegue;

\* prueba AMD;

\* prueba NVIDIA;

\* red entre nodos;

\* autenticación;

\* throughput;

\* almacenamiento;

\* WSL AMD;

\* smoke Broker.



Puerta:



ambos nodos aparecen correctamente o el sistema degrada explícitamente a un

solo nodo.



\## FASE 1 — Esqueleto distribuido



\* monorepo;

\* Tauri + React + TypeScript;

\* backend Python;

\* Coordinator;

\* Worker;

\* registry;

\* heartbeat;

\* jobs;

\* leases;

\* persistence;

\* mocks;

\* dry-run.



Puerta:



job ficticio puede salir del Coordinator, ejecutarse en ambos workers y volver

con recuperación tras desconexión.



\## FASE 2 — Read-only Vault Index



\* adaptación de vaulttrain;

\* read-only guard;

\* snapshots;

\* incremental index;

\* graph;

\* exclusions;

\* hashes;

\* audit screen.



Puerta:



snapshot reproducible sin una sola modificación en Obsidian.



\## FASE 3 — Corpus controlado



Construye benchmark determinista pequeño con:



\* single-hop;

\* multi-hop;

\* contradicciones;

\* cifras;

\* entidades;

\* missing information;

\* distractores.



Puerta:



retrieval ground truth validado manualmente.



\## FASE 4 — Retrieval baseline



\* FTS;

\* lexical;

\* semantic;

\* hybrid;

\* métricas.



Puerta:



informe R1/R2/R3.



\## FASE 5 — Graph RAG



\* graph expansion;

\* wikilinks;

\* neighbor weighting;

\* reranking;

\* context assembly.



Puerta:



R4 comparado contra R3.



\## FASE 6 — Benchmark multifuente



\* formato con evidencia;

\* vault real;

\* corpus controlado;

\* deterministic verifiers;

\* revisión humana.



Puerta:



primer benchmark reproducible.



\## FASE 7 — Human feedback



\* review UI;

\* diff;

\* evidence editor;

\* training candidate states.



\## FASE 8 — Model Drift



Integración automática real.



Puerta:



comparación R3 vs R4 ejecutada formalmente por Model Drift y asociada al

experimento.



\## FASE 9 — Dataset Factory



\* examples;

\* provenance;

\* dedup;

\* contamination;

\* audit;

\* manifests.



\## FASE 10 — Fine-tuning



\* hardware resolver;

\* LoRA;

\* training contract;

\* checkpointing;

\* manifests.



\## FASE 11 — Fine-tune + RAG



Comparación F1 vs F2 vs mejor RAG sin fine-tuning.



\## FASE 12 — Strategy Comparison



Dashboard que compare:



\* calidad;

\* retrieval;

\* coste;

\* latencia;

\* memoria;

\* privacidad;

\* complejidad.



No escondas trade-offs detrás de un score global.



\## FASE 13 — Strategy Selector



Solo después de disponer de evidencia suficiente.



Aprende/decide qué estrategia usar.



Nunca debe convertir una predicción en certeza.



Debe poder explicar por qué seleccionó la estrategia.



\## FASE 14 — Agent/tool experiments



Usa las capacidades existentes de AI Broker/Athena cuando corresponda.



No construyas un runtime duplicado.



\## FASE 15 — Exportación y optimización



\* adapter;

\* merged model;

\* safetensors;

\* GGUF;

\* reproducible package;

\* model serving;

\* caches;

\* cleanup policy.



\---



\# CRITERIOS DE ACEPTACIÓN



Local AI Lab no estará completo porque “funciona una demo”.



Debe demostrar:



1\. un único producto funciona en dos nodos;

2\. Coordinator y workers sobreviven a desconexiones;

3\. no existe SQLite compartida por red;

4\. el AMD no depende de montar Obsidian;

5\. Obsidian permanece read-only;

6\. los snapshots son reproducibles;

7\. cada finding relevante tiene evidencia;

8\. retrieval se mide con ground truth;

9\. existe benchmark real y controlado;

10\. feedback humano es trazable;

11\. datasets no contaminan benchmarks;

12\. AI Broker no se duplica;

13\. Model Drift se usa para evaluación formal;

14\. fine-tuning debe ganarse su existencia;

15\. las estrategias se comparan por múltiples dimensiones;

16\. ningún resultado se declara verificado si no se ejecutó la prueba;

17\. toda capacidad crítica aparece como detectada/probada, no supuesta.



\---



\# VERIFICACIÓN



En cada fase informa:



\* qué se implementó;

\* qué se verificó;

\* qué comandos se ejecutaron;

\* qué tests pasaron;

\* qué tests fallaron;

\* qué evidencia existe;

\* qué no pudo verificarse;

\* qué supuestos siguen abiertos;

\* qué limitaciones quedan;

\* qué decisión recomienda;

\* qué necesita aprobación humana.



Nunca escribas:



“verificado”, “compatible”, “funciona”, “estable” o “reproducible”



si solo lo dedujiste de documentación.



Usa en su lugar:



\* documentado;

\* detectado;

\* pendiente de prueba;

\* probado;

\* benchmarkeado.



\---



\# PROCESO INICIAL



Empieza ahora únicamente por la FASE A.



No instales software.



No modifiques WSL.



No modifiques drivers.



No modifiques Obsidian.



No cambies configuraciones del Broker.



No escribas código.



Inspecciona, diseña y entrega `docs/PHASE\_A\_DESIGN.md`.



Antes de terminar, incluye una tabla con:



\* hechos confirmados;

\* hechos documentales;

\* inferencias;

\* supuestos;

\* decisiones pendientes;

\* prueba que resolverá cada pendiente.



Finaliza con una lista exacta de decisiones que necesita aprobar el usuario

antes de comenzar la Fase 0.



\## Por qué está diseñado así



El cambio principal es que el \*\*centro arquitectónico pasa del entrenamiento a la experimentación\*\*. El fine-tuning deja de ser el destino obligatorio y compite en igualdad con prompting, RAG y estrategias ya disponibles a través del Broker.



También evita crear un mini-ecosistema paralelo dentro de Local AI Lab. El informe concluye precisamente que la fortaleza actual está en que AI Broker concentra lo multi-modelo, Model Drift la evidencia y Knowledge Orchestrator la semántica/publicación, sin convertirlo todo en un monolito. 



La arquitectura Coordinator/Worker resuelve además la asimetría de tus dos PCs sin duplicar producto: las capacidades se descubren experimentalmente y los trabajos pueden moverse entre nodos.



\## Cómo verificar el prompt



Cuando lo ejecutes, la primera respuesta correcta debería:



\* \*\*no escribir código\*\*;

\* reconocer AI Broker 2.9;

\* reconocer Model Drift y evitar diseñar otro sistema estadístico;

\* tratar Knowledge Orchestrator como propietario de las escrituras de Obsidian;

\* diseñar un único producto Coordinator/Worker;

\* colocar inicialmente el Coordinator en el PC NVIDIA;

\* impedir que AMD dependa de montar el vault;

\* proponer snapshots inmutables;

\* separar fuente de verdad y cachés;

\* reutilizar/auditar `vaulttrain` en vez de reconstruirlo;

\* incluir benchmark real + corpus controlado;

\* mantener Local AI Lab como read-only respecto a Obsidian.



Hay otro criterio especialmente útil: \*\*si su Fase A vuelve a proponer implementar un router general, un agente genérico o un framework estadístico completo dentro de Local AI Lab, estará ignorando la infraestructura existente\*\*.



\## Variables reutilizables



Las principales variables que deberían permanecer configurables son:



`COORDINATOR\_NODE`, `WORKER\_NODES`, `VAULT\_PATH`, `KNOWLEDGE\_ORCHESTRATOR\_URL`, `AI\_BROKER\_URL`, `MODEL\_DRIFT\_ENDPOINT`, `DEFAULT\_DATA\_POLICY`, `SNAPSHOT\_STORAGE`, `ARTIFACT\_STORAGE`, `CONTROL\_CORPUS\_PATH`, `NODE\_AUTH\_MODE`, `RAG\_EMBEDDING\_MODEL`, `RERANKER\_MODEL`, `MAX\_CONTEXT\_BUDGET`, `JOB\_LEASE\_TIMEOUT` y `ARTIFACT\_RETENTION\_POLICY`.



No incluyo una versión compacta porque en este caso reducir el prompt significativamente eliminaría precisamente las fronteras arquitectónicas que evitan duplicar componentes existentes.



