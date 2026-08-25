# Local AI Lab contracts

Los JSON Schema de esta carpeta son la fuente canónica de los documentos intercambiados.
Los tipos Python, TypeScript y Rust deben corresponder a estos schemas y las pruebas de
contrato impiden cambios incompatibles silenciosos.

- `overview.v1.schema.json`: vista saneada para Desktop;
- `node-protocol.v1.schema.json`: registro, leases y mutaciones Worker/Coordinator;
- `phase-evidence.v1.schema.json`: evidencia recuperable de una puerta.

Los contratos crecen de forma aditiva dentro de la misma versión. Los cambios incompatibles
crean una nueva versión y se negocian durante el registro del nodo.
