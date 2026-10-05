---
type: "query"
date: "2026-10-03T21:01:46.059116+00:00"
question: "Por que Configuracion muestra http://127.0.0.1:8000 en vez del Broker del PC IA?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["BrokerCompatibilityPanel", "BrokerTaskClient"]
---

# Q: Por que Configuracion muestra http://127.0.0.1:8000 en vez del Broker del PC IA?

## Answer

Expanded from original query via vocab: broker endpoint connection config. Reproduced the actual BrokerCompatibilityPanel render showing the literal loopback address and ignoring a saved preference. experiments.tsx had three independent useState loopback defaults and datasets.tsx had one. The user confirmed PC IA endpoint http://192.168.1.52:8765. Added a shared persistent brokerEndpoint.ts preference for settings and experiments; distillation defaults to that preference while respecting the selected Broker report. Relabeled settings Direccion de AI Broker. All 23 frontend tests passed, including five regression scenarios, and the offline Tauri build passed. Packaged dist/candidate-broker-endpoint-20261003; the unchanged BAT selects it. Desktop and Coordinator startup and cleanup passed using isolated test data. Live PC IA health could not be verified from this environment.

## Outcome

- Signal: useful

## Source Nodes

- BrokerCompatibilityPanel
- BrokerTaskClient