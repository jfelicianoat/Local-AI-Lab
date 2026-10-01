# Frontera de seguridad distribuida actual

**Corte:** 29 de septiembre de 2026. Este documento describe el código actual;
[`PHASE_A_DESIGN.md`](PHASE_A_DESIGN.md) conserva el diseño aspiracional.

| Control | Implementación actual | Límite |
|---|---|---|
| Escritorio → Coordinator propio | HTTP en loopback con token de aplicación generado al arrancar | No da identidad a un equipo remoto. |
| Worker → Coordinator remoto | HTTPS obligatorio; validación normal del certificado del servidor por Python | El operador debe desplegar un certificado confiable y proteger su clave. No hay CA privada administrada por la app. |
| Identidad del Worker | Código de emparejamiento de uso limitado, token bearer almacenado protegido, estado revocable | No hay clave Ed25519 por dispositivo ni certificado cliente mTLS. |
| Acceso a jobs y artefactos | Lease con token, intento, generación, vencimiento y autorización de descarga/subida según nodo y job | Un Coordinator o Worker comprometido sigue siendo una frontera de confianza importante. |
| Integridad de datos | SHA-256 de blobs, hashes en manifiestos e informes, validación del resultado antes de promover éxito | SHA-256 no es firma de procedencia; los manifests no están firmados. |

La revocación invalida el token del nodo para heartbeat, claim, renovación,
subida, descarga y finalización. Un intento vencido o reasignado no promueve su
resultado; queda registrado como obsoleto. Hay pruebas automatizadas de estas
reglas. Las pruebas locales con conexiones HTTPS reales verifican pairing,
claim, identidad ajena, revocación y emparejamiento de un Worker de sustitución.
El cliente rechaza certificados de servidor no confiables, caducados o con
nombre incorrecto antes de enviar una petición de pairing. Estos fallos exigen
corregir la configuración; no se tratan como desconexiones transitorias.
Se rechazan las redirecciones HTTP para evitar reenviar bearer o pairing a otro
destino. **No se ha verificado una instalación TLS entre dos equipos físicos**;
la app no implementa certificados cliente mTLS.

Para datos privados entre equipos, mantenga el Coordinator en una red controlada,
publique únicamente el endpoint TLS con un certificado válido, limite el acceso
de red a Workers autorizados, rote los códigos de emparejamiento y revoque de
inmediato un nodo perdido. La validación del certificado del servidor permanece
activada; no use opciones globales que desactiven la verificación TLS. La
gestión automática de una CA privada, certificados cliente y manifests firmados
requiere implementación y pruebas adicionales antes de afirmar conformidad con
el diseño de Fase A.

## Certificados, rotación y recuperación

El terminador TLS es responsabilidad del operador. Debe presentar la cadena
completa de un certificado vigente para el nombre del endpoint. Python valida
la cadena, el nombre y la vigencia con su almacén de confianza predeterminado.
Para una CA privada, el operador debe provisionar esa confianza en cada Worker;
la app no distribuye raíces ni ofrece una opción para omitir su validación.
Use directamente el origen HTTPS final, sin redirecciones de un proxy.

Al renovar el certificado del servidor manteniendo nombre y CA confiable, el
Worker conserva su credencial. Para cambiar la CA, distribuya primero la nueva
confianza a los Workers y mantenga una transición en la que ambos certificados
puedan validarse. Compruebe una petición autenticada antes de retirar la CA
antigua. Proteja la clave privada del terminador y rote el certificado de forma
independiente de los tokens de dispositivos.

Para un Worker perdido, revoque su acceso desde **Configuración → Nodos**.
Empareje la sustitución con un código nuevo, un identificador de nodo nuevo y una
carpeta de datos nueva: el comando de pairing rechaza sobrescribir credenciales
existentes. Compruebe sus capacidades y seleccione el Worker de sustitución en
la recuperación del trabajo. Conserve el historial del intento anterior. Las
pruebas locales demuestran que el token anterior devuelve 401 y el nuevo Worker
puede consultar trabajo por el mismo endpoint HTTPS. Falta repetir este recorrido
en una instalación con terminador TLS y dos equipos físicos.

La prueba de transferencia local por HTTPS corta una descarga de 128 MiB,
reanuda con Range, verifica el SHA-256 final y limita el pico adicional de memoria
Python a menos de 16 MiB. No acredita rendimiento ni fiabilidad entre equipos.
