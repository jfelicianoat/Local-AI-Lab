# Estado de la revisión del 29 de septiembre de 2026

**Estado:** candidato local en un árbol de trabajo con cambios sin confirmar; **no
distribuir aún como release cerrada**. Base Git: `ad9bd34`. El informe de
[`Auditoria 20260929`](<Auditoria 20260929/INFORME_COMPLETO.md>) enumera H01–H26;
este documento distingue las correcciones verificadas de las puertas abiertas.
Versiones declaradas: Desktop/Tauri/Rust 0.1.1; paquete Python Coordinator/Worker 0.1.0.

## Comprobaciones de este árbol de trabajo

| Comprobación | Resultado observado |
|---|---|
| Python | Suite completa de la revisión 7 en el checkout independiente: 371 pasadas y 2 omitidas por permiso de symlink. Las 62 pruebas de contratos de resultados pasan también en el proyecto principal. |
| Frontend | Fuentes sin cambios desde R6 (16 pruebas y build comprobados entonces). Instalación inicial desde caché con `npm ci --offline`. Pasan 16 pruebas, incluidas cuatro de renderizado estático para estados pendientes y conservación de descarga; cinco comprueban borradores de revisión. La construcción principal pasa. La del candidato se ejecuta en el checkout independiente. |
| Rust | Fuentes sin cambios desde R6: `cargo test --offline`, 3 pruebas pasan en esa revisión. |
| Escritorio portable | Sidecar y portable construidos desde el checkout independiente. El smoke de la construcción anterior arrancó con base nueva; su repetición posterior no pudo cerrar el árbol de procesos. El candidato nuevo no tiene un smoke completo ni prueba visual. |
| Backup/restore | Copia SQLite y artefactos, verificación de hashes y restauración en carpeta nueva: 2 pruebas pasan. |
| Uso visual | La autorización del navegador local fue denegada. No hay captura ni prueba interactiva visual de esta revisión. |
| WSL | El sistema devuelve `E_ACCESSDENIED` al consultar WSL; el flujo real AMD/WSL no está probado. |
| Agora, 2026-10-01 | HTTPS con la CA local instalada y bearer: health, profiles, contracts y board devuelven 200. Publica 5 perfiles y 4 contratos; lectura del tablero sin errores. No se crearon trabajos. |
| AI Broker, 2026-09-30 | El endpoint documentado de red no se pudo consultar: Windows rechazó la conexión con `WinError 10013`. En loopback no hay servicio en el puerto documentado. No es una comprobación de incompatibilidad ni de token inválido. |
| GPU local, 2026-10-01 | NVIDIA RTX 4060 Ti, 16.380 MiB, driver 616.56. No se hallaron torch/transformers/peft/accelerate en los entornos revisados. Se creó un entorno de prueba aislado; la descarga de PyTorch desde su índice oficial fue bloqueada por `WinError 10013`. No se ejecutó entrenamiento real. |

Se han corregido rutas reproducidas de build, selección de suite real, evaluación
del adaptador entrenado, decisiones sin evidencia, validación de citas,
contaminación, cancelación, idempotencia, leases, autorización de artefactos,
revocación, identidad de modelos, protección de secretos Linux, métricas,
revisión humana y salida de resultados. Las pruebas de integración son locales y
sintéticas salvo la evidencia histórica citada en los informes de agosto.

## Instalación independiente corregida el 2026-10-01

La comprobación de un checkout nuevo descubrió otro bloqueo de H01/H26: el lock
de npm contenía enlaces a `../../../ChatyGPT/node_modules/.pnpm/`. Además,
`lucide-react` 0.344.0 declaraba soporte hasta React 18, mientras la app usa React
19.2.7. Esas dependencias permitían construir en el equipo original y ocultaban
el fallo de una instalación independiente.

Se regeneró un lock portable con referencias de registry e integridad, sin enlaces
a otros proyectos. Los iconos usan 0.577.0, con React 19 declarado en sus peers;
Vite usa 7.3.1 y su plugin React 5.1.4. Node admitido: `^20.19.0 || >=22.12.0`,
conforme a los requisitos de [Vite 7](https://v7.vite.dev/guide/migration).
La configuración mantiene el target explícito `es2022` del proyecto.

Los paquetes y metadatos necesarios se prepararon a partir de tarballs ya presentes
en la caché local: no se consultó un registry en vivo. El lock resultante fue
comprobado con una instalación real de 73 paquetes en un checkout independiente
y en el proyecto principal, sin heredar su directorio de dependencias anterior.
Este corte verifica Windows x64; no valida instalaciones de escritorio en otros
sistemas ni garantiza que una caché distinta tenga todos los paquetes.

El checkout se creó desde el repositorio local en `ad9bd34` y recibió el parche de
las correcciones. Usó Python 3.14.0, Node 24.11.1 y Cargo 1.97.1. Python pasó
253 pruebas; la interfaz pasó su construcción y sus 7 pruebas iniciales; Rust, PyInstaller y
Tauri completaron sus pasos. Los caches de paquetes ya existentes se reutilizaron,
pero los directorios de instalación y de construcción se crearon nuevos. No
equivale a probar la descarga de dependencias en una máquina nueva.

El usuario ha indicado mantener el trabajo en local. No se publicó ninguna rama,
commit ni propuesta en GitHub; la verificación remota no se ejecutará como parte
de este encargo.

## Correcciones adicionales de Revisiones

La revisión del código encontró otra brecha de H20: la advertencia sobre cambios
sin guardar solo cubría el cambio entre revisiones, y la navegación principal
descartaba la corrección al desmontar el editor. Además, una actualización del
registro podía sustituir el texto local. La navegación consulta ahora al editor;
se exige confirmar el descarte de una corrección o motivo de rechazo pendiente y
se impide salir mientras termina una operación. Se registra también el aviso
`beforeunload`; su efecto en el cierre de la ventana nativa sigue sin comprobarse.

Una actualización periódica conserva el borrador. Si el contenido guardado cambió,
se mantiene el texto local, se muestra el conflicto y se bloquea la sobrescritura.
La versión guardada solo se recarga tras confirmación. Cuatro pruebas de la lógica
cubren refresco, conflicto externo, confirmación del guardado y cambio de revisión;
construcción TypeScript/Vite correcta y 11 pruebas frontend pasan. El detector
mecánico de Impeccable no produjo hallazgos en los dos componentes modificados.
Estas comprobaciones no prueban los clics, el foco ni los diálogos de la app nativa.

El caso 16 del manual describe el editor de respuesta y afirmaciones, el JSON
avanzado opcional y los conflictos. La sesión visual de H20 sigue pendiente junto
con los recorridos de misiones y entrenamiento.

## Guardado y aprobación concurrentes de Revisiones

Se reprodujo otra pérdida de correcciones con el código del candidato anterior:
dos sesiones enviaban su corrección sobre el mismo registro y ambas obtenían 200;
la segunda sobrescribía el texto de la primera. El aviso de conflicto de la interfaz
no cubría un cambio posterior a su última lectura. Además, se podía aceptar una
respuesta distinta de la que se había revisado.

Cada revisión tiene ahora una versión entera que avanza al guardar, cambiar su
estado o decidir sobre entrenamiento. La migración asigna versión 1 a los registros
anteriores sin cambiar su contenido. Los tres endpoints de decisión del escritorio
exigen la versión leída; su comparación, la escritura y el evento ocurren bajo la
misma transacción SQLite. Una petición antigua devuelve 409 sin cambios ni eventos.
El escritorio envía esa versión, solicita datos actuales tras el conflicto y
conserva la corrección local. Los workflows internos serializados conservan su
contrato; el nuevo requisito es obligatorio para las decisiones por la API de la app.

Seis pruebas Python nuevas comprueban guardados concurrentes, aceptación y aprobación
antiguas, falta de versión en los tres endpoints y cambios que vuelven al mismo
contenido con timestamps idénticos. La migración se prueba con un registro existente
y reapertura. Una quinta prueba de borrador conserva texto local ante un cambio de
versión sin cambio de texto. En el checkout independiente: 259 Python pasan y 2
se omiten por symlink; frontend 12 y Rust 3 pasan. Sidecar y portable se reconstruyeron;
su prueba visual y de arranque/cierre sigue pendiente.

## Puertas abiertas de la auditoría

- **H12:** hay fencing, renovación independiente, recuperación de leases y
  reenvío durable del Worker. LoRA y destilación publican checkpoints con estado
  del entrenador, hashes y procedencia de job/intento; destilación incluye las
  respuestas exactas del profesor. La app permite reanudar en un Worker
  compatible, reiniciar desde cero o descartar un trabajo `needs_review`, con
  una sola decisión de recuperación por trabajo. Pruebas sintéticas inyectan
  pérdida de respuesta al publicar, reenvío, cambio de Worker y reinicio sin
  checkpoint. Falta ejecutar una recuperación con entrenamiento real en GPU y
  recorrer esa decisión visualmente en el escritorio autorizado.
- **H16:** se exige un baseline B1 o R4 completado con informe íntegro, casos,
  métricas y el mismo snapshot que el dataset. LoRA y destilación exigen una
  mejora numérica positiva y alcanzable y confirmación explícita de que el
  objetivo no memoriza hechos cambiantes. F1 debe repetir B1 y F2 debe repetir
  R4 con la misma suite, casos, snapshot, benchmark e índice; F2 conserva
  embedding y k. Al completar la evaluación se calcula la ganancia de
  verificación determinista y se registra si alcanza la meta. No se promociona
  automáticamente: formato y citas no prueban fidelidad de respuesta. Los
  trabajos F1/F2 antiguos sin evidencia comparable quedan marcados como no
  verificables. Falta una
  evaluación humana de calidad y una ejecución real de entrenamiento + F1/F2.
- **H19:** las misiones son registros del Coordinator, se reabren por ID y
  admiten vínculos explícitos a productos, jobs y revisiones por etapa. El
  estado se deriva de la evidencia actual; visitar una pantalla no lo altera.
  Se comprobó y corrigió otra brecha: una categoría y un estado de éxito no
  bastan para avanzar. Se verifica la cadena snapshot/índice/benchmark,
  experimento/revisión/comparación y dataset/preflight/entrenamiento/evaluación/
  exportación; el profesor y el alumno deben coincidir con el plan de
  destilación. Un vínculo incompatible se rechaza; la falta de un requisito
  conserva el resultado como configurado y explica el vínculo pendiente.
  Retirar un requisito o cambiar los modelos invalida el avance derivado, y
  una comparación exige sus experimentos completos vinculados. Las pruebas
  cubren dos misiones, reapertura, resultados ajenos, pérdida de evidencia y
  propagación hasta la exportación. Falta una sesión visual autorizada con
  dos misiones y revisión humana de la coherencia entre tarea, criterios y
  contenido de los resultados.
- **H20:** el editor de revisión muestra respuesta, afirmaciones, contexto y
  cambios. La corrección local se conserva ante refrescos y se protege al navegar;
  los cambios externos se presentan como conflictos. Las decisiones exigen la versión
  leída y se rechazan si quedó antigua. La lógica pasa cinco pruebas
  nuevas, pero falta recorrer con la app la selección de citas, corrección,
  guardado, aprobación, salida con cambios y cierre de la ventana nativa.
- **H24:** descarga streaming, reanudación tras desconexión simulada de 24 MiB
  con menos de 12 MiB de pico Python adicional, rotación de log y backup/restore
  están probados. Tras confirmar un artefacto CAS, sus chunks temporales se
  eliminan sin perder la idempotencia de la confirmación. El almacén CAS tiene
  cuota configurable (100 GiB por defecto), reserva las cargas pendientes y
  rechaza fragmentos fuera del tamaño declarado; **Configuración** muestra su
  uso y el espacio libre del disco.
  El escritorio carga páginas de 50 productos, jobs y revisiones por grupo y
  permite solicitar las siguientes sin descartar las anteriores. Con 10.000
  registros sintéticos, la primera página tardó 10,82 ms, ocupó 30.373 bytes
  de JSON y alcanzó 116.065 bytes de memoria Python medida; la lectura completa
  anterior tardó 109,69 ms, ocupó 2.962.970 bytes de JSON y alcanzó
  12.255.285 bytes. Medición reproducible en
  `scripts/benchmark_workspace_paging.py`. Con 10.000 jobs y 10.000 revisiones
  sintéticos, la primera página tardó 3,77 ms y 2,29 ms respectivamente;
  el resumen tardó 2,50 ms, con picos de memoria Python de 57.108, 91.866 y
  3.920 bytes. Medición reproducible en `scripts/benchmark_history_paging.py`;
  no representa resúmenes grandes ni una carga real de varios equipos. La cuota
  cubre solo CAS, no snapshots, índices, base de datos ni temporales externos.
  Los empaquetadores de resultados y checkpoints transmiten los archivos por
  bloques; la extracción rechaza rutas inseguras, duplicados y tamaños que
  superan el presupuesto de disco, y elimina la carpeta parcial al fallar.
  **Configuración → Liberar espacio** propone como máximo 200 archivos CAS
  huérfanos o transferencias inactivas antiguas, con confirmación de la lista y
  revalidación de referencias. Protege evidencia, trabajos, datasets y
  checkpoints; conserva transferencias de trabajos pendientes o `needs_review`.
  La aprobación es durable y retira las identidades de subida antes de borrar;
  una interrupción durante el borrado se recupera desde la app. El espacio
  pendiente de limpieza sigue contado en la cuota. Las pruebas comprueban
  referencia nueva, cambios de archivos, caducidad, reintentos y cierre parcial.
  Una conexión HTTPS local real corta y reanuda 128 MiB, conserva el parcial ante
  un EOF prematuro, verifica el hash final y mantiene menos de 16 MiB de pico
  Python adicional. Falta una transferencia interrumpida de tamaño de modelo
  entre equipos reales.
- **H25:** el protocolo implementa HTTPS de servidor, bearer revocable y permisos
  por artefacto/job. No implementa mTLS, identidad Ed25519 ni manifests firmados;
  véase [frontera de seguridad actual](SECURITY_BOUNDARY_CURRENT.md).
  Conexiones HTTPS locales reales prueban revocación y sustitución de identidad,
  y rechazan CA no confiable, nombre incorrecto y caducidad antes del pairing.
  El cliente rechaza redirecciones para no reenviar credenciales; los errores
  de certificado son permanentes y las respuestas HTTP de error se cierran.
  Falta validar la instalación con terminador TLS entre equipos físicos.
- **H26:** CI versionada y manual actualizado. Graphify se regeneró con los
  cambios de recuperación, limpieza y transporte: JSON, informe e HTML
  exportados, sin endpoints ausentes ni relaciones colgantes en su diagnóstico.
  Un checkout independiente completó las comprobaciones locales de instalación,
  Python, frontend, Rust, sidecar y portable. La CI remota queda sin ejecutar por
  la decisión de mantener todo en local. Faltan la prueba visual y el smoke completo
  del candidato actualizado; Windows denegó el cierre de la instancia anterior. El
  grafo incorpora la invalidación de entorno y el manual 1.6 de la revisión 4:
  se actualizaron 18 archivos de código y 3 documentos, con JSON, informe e HTML
  exportados. El diagnóstico posterior no encuentra referencias colgantes, pero
  no acredita una extracción sin pérdida: el fragmento AST tiene 39 relaciones
  adicionales sobre pares repetidos, incluidos 18 duplicados exactos. El grafo
  simple representa una conexión por par. Se conserva el fragmento original en
  `graphify-out/EXTRACTION_R4.json` para consultar la procedencia completa; esta
  limitación impide usar el HTML como prueba de todas las relaciones entre símbolos.
  La actualización de la revisión 5 comprende 25 archivos de código y los tres
  documentos vigentes. Conserva el fragmento de relaciones originales en
  `graphify-out/EXTRACTION_R5.json`; el diagnóstico del grafo simple sigue sin
  acreditar que todas las relaciones originales se representen por separado.
  La revisión 6 actualiza 14 archivos de código y los tres documentos vigentes;
  el fragmento original se conserva en `graphify-out/EXTRACTION_R6.json`, con la
  misma limitación de representación de relaciones paralelas.
  R7 actualiza cuatro archivos de código y los tres documentos vigentes; el fragmento
  original se conserva en `graphify-out/EXTRACTION_R7.json`, con esa misma limitación.

## Corrección adicional de capacidades del Worker (H23)

La reproducción encontró que declarar ROCm conservaba el valor CUDA probado y
que cambiar el driver permitía reclamar entrenamiento usando evidencia anterior.
Ahora el Coordinator distingue las observaciones del entorno de la prueba medida.
Un cambio estable invalida hechos y cargas probados y el preflight anterior; no
se despacha entrenamiento hasta obtener evidencia nueva. Temperatura, memoria
disponible, espacio libre, ID y fecha del informe no invalidan por sí solos.

La generación de entorno se guarda con cada lease. La publicación de capacidades
y del preflight comprueba esa generación bajo la escritura de SQLite: ni un
resultado tardío ni un cambio que vuelva al entorno inicial recuperan una prueba
antigua. El resultado histórico sigue disponible. La migración conserva jobs y
credenciales, pero retira de la planificación pruebas antiguas sin identidad de
entorno. Volver a emparejar la misma identidad retira sus capacidades anteriores.

El Worker observa el intérprete real y versiones de torch/transformers/peft/
accelerate sin importar esos paquetes, y repite la sonda al iniciar y cada 30
segundos entre trabajos. La observación no continúa durante un job bloqueante.
El escritorio muestra el motivo y la acción necesaria. Solo resultados aceptados
pueden registrar cargas probadas; un heartbeat no acredita su ejecución.

Dieciséis pruebas nuevas cubren cambio de backend/driver/dependencia, ausencia
en una sonda completa, informes parciales, cambios volátiles, hechos ML que una
sonda no mide, reapertura, reemparejamiento, migración, resultados tardíos,
publicación antes/durante/después del heartbeat y refresco del Worker.
Son pruebas locales con evidencia sintética; falta cambiar un entorno real y
recorrer el aviso visualmente. La inspección también encontró que los formatos de
exportación distintos de adapter necesitan un recorrido inicial de verificación
que no tenía entrada en la interfaz. La revisión 6 añade ese recorrido; su ejecución
con conversiones reales sigue pendiente.

## Validación adicional de resultados (H14) y reenvío (H11), revisión 5

La comprobación negativa de H14 aceptó como preflight superado un archivo de
42 bytes que no era un ZIP ni un manifiesto válido. Las pruebas anteriores
contenían resultados sintéticos sin contrato completo y no detectaban esta ruta.
Se reprodujeron 18 fallos de protocolo antes de corregirla: diecisiete variantes
invalidaban una prueba y el caso válido fallaba al reenviarse después del éxito.

El Coordinator exige ahora el paquete declarado para preflight, LoRA,
destilación, exportación y los tres tipos de experimentos. Comprueba existencia,
propiedad del intento, tamaño y hash CAS; valida esquema y valores del informe
antes de publicar éxito o promover capacidades. En los paquetes ML verifica la
identidad del job/intento/generación de lease y el fingerprint del contrato,
el hash canónico del manifiesto, configuración aprobada y cada archivo por
bloques. El preflight exige seis checks y C1–C6 booleanos verdaderos, pérdidas
finitas decrecientes, ocho ejemplos, veinte pasos, reanudación y checkpoint.
LoRA y destilación comparan métricas y manifiesto; exportación compara formatos,
origen, licencia, configuración y fingerprint del paquete.

Los informes de retrieval, agentes y estrategias también comparan las métricas
publicadas con el archivo recibido. Los candidatos de revisión de agentes y
estrategias se incorporan al informe y se comprueba su correspondencia. Un
payload no puede añadir una revisión diferente de la que contiene ese informe.

La validación se ejecuta dentro de la operación idempotente: reenviar un resultado
aceptado recupera su confirmación. Las pruebas de interrupción tras la finalización
durable reabren el Coordinator, reenvían y conservan exactamente una revisión por
caso de agentes/estrategias. Los resultados de versiones anteriores quedan como
`RESULT_REQUIRES_VALIDATION`: se conservan archivos, jobs y credenciales, pero sus
pruebas no autorizan trabajos ni reaparecen al reenviar una confirmación antigua.
Los informes y exportaciones históricos siguen disponibles para guardar.

Pasan 62 pruebas nuevas de contratos, incluido el caso válido, archivo ajeno al
formato, ausencia de paquete/manifiesto, esquema/hash/configuración/identidad
incorrectos, checks inventados, pérdidas inválidas, archivos alterados, duplicados,
métricas discordantes, migración y recuperación. Dos pruebas de renderizado
estático comprueban el mensaje de validación pendiente y la acción de guardar.
No equivalen a una prueba visual ni a ejecución ML: verifican la integridad y
consistencia de un resultado entregado por un Worker autenticado. La ejecución
GPU y la valoración humana F1/F2 siguen pendientes.

## Verificación inicial y conservación de metadata al exportar, revisión 6

La exportación tenía una dependencia circular: para probar merged_model,
safetensors o GGUF se exigía previamente una exportación completada del formato.
La revisión 6 incorpora **Comprobar y crear primer paquete**. Exige un resultado
de entrenamiento validado, un Worker activo, licencia y dependencias ML detectadas;
GGUF requiere la ruta del conversor en ese Worker. Esta operación ejecuta el mismo
conversor y contrato de resultados, sin conceder capacidad anticipadamente. La
exportación ordinaria sigue exigiendo formatos probados. Un fallo o paquete inválido
no registra prueba; un cambio de entorno conserva la invalidación de la revisión 4.

La pantalla muestra qué formatos faltan por comprobar, excluye Workers desconectados
y resultados históricos sin validación, y explica el coste de la conversión completa.
No obliga a declarar una capacidad en el heartbeat para desbloquear el primer uso.

Se corrigió también la pérdida del tokenizer y de la plantilla al exportar.
El paquete incluye su archivo de metadata, con configuración del modelo cuando
hay fusión. Antes de empaquetar o ejecutar llama.cpp, la carpeta fusionada recibe
el tokenizer entrenado y se recarga sin discrepancias de pesos; se verifica la
plantilla. La salida GGUF vacía o con cabecera incompatible se rechaza. La cabecera
no demuestra por sí sola que todos los tensores o la inferencia sean correctos.

Pasan 10 pruebas del recorrido por HTTP (primer uso de los cuatro formatos,
publicación después de validar y rechazo de requisitos ausentes) y 9 del ejecutor
(metadata, plantilla, recarga y GGUF inválido). Usan paquetes sintéticos y bibliotecas
ML simuladas; no prueban una conversión real. Dos pruebas nuevas de renderizado
estático comprueban la entrada inicial y los estados sin requisitos. El manual 1.8
describe este recorrido. El candidato se construyó desde la copia independiente:
356 pruebas Python, 16 de interfaz y 3 de Rust pasan; dos pruebas Python se omiten
por permisos de symlink. Sidecar y portable se reconstruyeron con los mismos fuentes.

## Autorización de respuestas guardadas (H11/H13), revisión 7

Se reprodujo una brecha adicional: otro Worker autenticado recibió `accepted=true`
al repetir una finalización ya aceptada con la misma clave, aunque presentara un
token de lease incorrecto y otra generación. El progreso guardado tenía el mismo
problema; ack, renovación y checkpoint podían reutilizar una respuesta con la
credencial del lease equivocada. Una finalización ajena enviada primero también
podía ocupar la clave del propietario con un rechazo guardado.

La autorización ahora se ejecuta antes de consultar o escribir la caché idempotente.
Comprueba Worker, token del lease, generación e intento cuando corresponde. Un
rechazo de finalización se registra como intento obsoleto y no ocupa la clave del
propietario ni vuelve a publicar éxito. Los otros reintentos rechazan credenciales
ajenas. La comprobación de vencimiento se conserva en las operaciones nuevas;
el propietario original puede recuperar una confirmación ya aceptada tras el
vencimiento y un reinicio, mientras no se haya reasignado el lease o revocado al nodo.

Pasan 15 pruebas nuevas con dos Workers locales: confirmaciones con Worker/token/
generación incorrectos, claves ocupadas por peticiones ajenas, reinicio y vencimiento,
ack/progreso/renovación/checkpoint, reasignación y revocación. Las regresiones de
resultados y recuperación anteriores siguen pasando. La suite independiente de la
revisión 7 completa 371 pruebas y omite dos por permisos de symlink. El Coordinator
se reconstruyó; el escritorio, sus fuentes de interfaz y Rust coinciden con R6,
por lo que se conserva su binario ya comprobado (16 pruebas de interfaz y 3 de Rust).
Esta revisión no repite ni acredita pruebas visuales o de GPU.

## Verificación de la auditoría original y cobertura actual

Se recuperó una copia aislada de la versión `ad9bd34370dccf38c6896564f58e3e6535ab6848`
examinada por la auditoría y se ejecutó su script original sin cambiarlo. Los doce
escenarios vuelven a reproducir los defectos descritos: cancelación, confirmación,
artefactos, selector, F1, citas inexistentes, contaminación, identidad Broker,
respuesta sin evidencia, JSON inválido, lease vencido y reasignación. Son pruebas
sintéticas sin red, GPU ni datos del usuario. Respaldan los hallazgos reproducibles
para aquella versión; los catorce restantes incluyen inspección estática y criterios
que necesitan validación visual, equipos o modelos reales.

| Hallazgo | Cobertura disponible | Verificación aún necesaria |
|---|---|---|
| H01 · Construcción | Frontend, Rust y portable R6; Coordinator actualizado R7, fuentes y hashes locales | Arranque/cierre nativos completos |
| H02 · Conocimiento privado | Snapshot, benchmark real, experimentos y dataset cubiertos con datos sintéticos | Recorrido visual con integraciones reales |
| H03 · Pesos entrenados F1/F2 | Identidad del adaptador, carga local y rechazos cubiertos | Inferencia con los pesos entrenados reales |
| H04 · Alumno destilado | Destilación aceptada como origen F1/F2 y exportación; contratos cubiertos | Destilación y evaluación reales |
| H05 · Selector | Rechazo de evidencia incompleta, umbrales y preferencia de complejidad cubiertos | Calidad de las respuestas según revisión humana |
| H06 · Comparación formal | Relación entre veredicto, versiones y artefactos cubierta | Integración real y recorrido de selección |
| H07 · Verificador | Forma JSON, evidencia y errores deterministas cubiertos; límites de fidelidad explícitos | Verificación humana de soporte semántico |
| H08 · Citas del benchmark | Rechazo de referencias inexistentes, ajenas o discordantes cubierto | Uso visual del editor |
| H09 · Contaminación | Benchmarks controlados y reales, IDs y consultas excluidos en pruebas | Inspección del dataset real aprobado |
| H10 · Cancelación | Controles renovados, cancelación y estado final cubiertos con ejecutores simulados | Latencia durante carga ML y espera Broker reales |
| H11 · Reenvío | Confirmación, interrupción de publicación, una revisión por caso y permisos cubiertos | Desconexión real prolongada |
| H12 · Recuperación | Fencing, journal, checkpoint, reinicio y decisiones cubiertos | Recuperación real de entrenamiento y uso visual |
| H13 · Autorización | Artefactos por job/intento, lease, revocación y respuestas guardadas cubiertos | Prueba distribuida entre equipos físicos |
| H14 · Resultados | Paquete, esquema, hashes, identidad, archivos y métricas cubiertos | Ejecución ML real; el protocolo no atestigua GPU independientemente |
| H15 · Modelos y endpoint | Fingerprints y exigencia de identidad de servicio cubiertos | Broker real accesible y mutación de un modelo real |
| H16 · Baseline | B1/R4 válidos y comparables, meta alcanzable y F1/F2 vinculados cubiertos | Entrenamiento y valoración humana reales |
| H17 · Secretos WSL | Cifrado Linux/WSL y exigencia de passphrase cubiertos | Pair/reinicio/job mínimo en WSL autorizado |
| H18 · Métricas | Contratos de costes, latencia y calidad cubiertos con informes sintéticos | Telemetría Broker y presentación visual reales |
| H19 · Misiones | Dos misiones persistidas, vínculos y estados derivados cubiertos | Navegación y cierre/reapertura visual |
| H20 · Revisión humana | Evidencia, editor, diff, borradores y conflictos implementados y cubiertos parcialmente | Recorrido con un revisor y cierre nativo |
| H21 · Destinos | Etiquetas y destino del Worker derivados de la ejecución | Uso visual local/remoto y confinamiento físico si se exige |
| H22 · Seguimiento y salida | Refresco, reintento, historial y descarga de informes/paquetes cubiertos | Seguimiento visual y desconexión de la app |
| H23 · Estado y entorno | Dependencias, disponibilidad e invalidación de pruebas cubiertas | Cambio de entorno real y comprensión del aviso |
| H24 · Escala | Streaming local, reanudación, paginación, cuota, limpieza y restauración cubiertos | Transferencias de tamaño de modelo y operación prolongada entre PCs |
| H25 · Seguridad distribuida | TLS, revocación, contratos y autorización cubiertos en pruebas locales | Instalación y certificados entre equipos físicos |
| H26 · Manual y verificación | Manual 1.9, copia independiente, parche, inventario y Graphify actualizados | Recorrido mínimo nativo completo; GitHub excluido por decisión del usuario |

No se declara cerrada la auditoría con esta tabla: distingue cobertura local de
los criterios que todavía requieren evidencia real o visual.

## Antes de cerrar una release

Las comprobaciones locales de Python, TypeScript, Rust, sidecar y portable pasan
desde el checkout independiente. El candidato actualizado está en
`dist/candidate-20261001-r7`, con su carpeta `resources`; no se reemplazó el portable
antiguo que sigue abierto. El escritorio reutiliza el binario R6 sin cambios de interfaz/Rust; el sidecar
se reconstruyó desde los fuentes R7. Hashes SHA-256 del candidato: sidecar
`8911f9cf8f886dc71f280bb0fede9355f614ddbafb27526574b776362d03c429`;
portable `7a9345dc0b83874daeff18a6928de051947e4c61ebbaef831d6cd00bd19fde23`.
El smoke anterior no certifica este candidato. La instancia de prueba anterior
tiene PID de escritorio `89584` y Coordinators `76116` y `77452`; Windows rechazó
su cierre. El script ahora limita el cierre a su árbol de procesos, restaura la
configuración temporal y falla si no puede limpiarlo. Esas garantías se verificaron
con procesos simulados, pero el cierre real sigue pendiente.
El árbol sigue sin commit final. Probar
desde la app los recorridos de benchmark, revisión, descarga y reanudación en un
Windows autorizado; ejecutar pair/run y una carga mínima en WSL y entre dos
equipos TLS. No convertir una prueba antigua de un servicio externo en evidencia
del endpoint o modelo que se seleccione hoy.
