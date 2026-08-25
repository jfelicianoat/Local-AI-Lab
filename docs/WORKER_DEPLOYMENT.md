# Despliegue del Worker

Local AI Lab usa el mismo paquete para los roles `coordinator` y `worker`. Cada Worker
mantiene su propio journal y sus cachés locales; nunca comparte la SQLite del Coordinator.

## Instalación

En una copia local del repositorio:

```powershell
.\scripts\install_worker.ps1 -Profile Core
```

Perfiles disponibles:

- `Core`: protocolo, journal y trabajos que no requieren ML.
- `Nvidia`: añade el entorno de entrenamiento documentado; sus capacidades siguen siendo
  `detected` hasta ejecutar el probe y `tested` solo después de los smoke tests reales.
- `AMD/WSL`: se prepara dentro de WSL con `bash scripts/install_worker_wsl.sh`. Instala las
  dependencias comunes, pero PyTorch/ROCm queda deliberadamente fuera hasta seleccionar una
  combinación oficialmente soportada y probarla en ese nodo.

## Emparejamiento

El Coordinator genera un código de un solo uso. En el Worker:

```powershell
.\.venv-worker\Scripts\local-ai-lab-worker.exe `
  --endpoint "https://coordinator.lan" `
  --node-id "worker-amd" `
  --data-root ".local-worker" `
  pair --pairing-code "<codigo>"
```

La credencial devuelta se protege con DPAPI en Windows y no se imprime. Una conexión remota
por HTTP plano se rechaza; el endpoint debe estar protegido por TLS.

## Ejecución

```powershell
.\.venv-worker\Scripts\local-ai-lab-worker.exe `
  --endpoint "https://coordinator.lan" `
  --node-id "worker-amd" `
  --data-root ".local-worker" `
  run --capability-report "artifacts\phase0\node-report.json"
```

El Worker verifica el hash del informe, publica heartbeat, renueva leases, consulta
cancelaciones y conserva progreso/resultados en su outbox si pierde conexión.
