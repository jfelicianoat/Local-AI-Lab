---
type: "query"
date: "2026-08-24T21:26:20.022454+00:00"
question: "Porque en las Dependencias externas aparece como desconocido?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["BrokerCompatibilityChecker", "CoordinatorService", "App"]
---

# Q: Porque en las Dependencias externas aparece como desconocido?

## Answer

Expanded from original query via vocab: [broker, compatibility, capabilities, overview, external, dependencies, unknown, status, record, evidence, endpoint, token]. CAPABILITIES_UNKNOWN is caused by connection refusal at the configured default endpoint http://127.0.0.1:8000, so neither health nor capabilities is observed. Separately, CoordinatorRepository.overview currently returns ai_broker, vault, and model_drift as hard-coded unknown values, so the sidebar does not reflect compatibility records even after refresh.

## Outcome

- Signal: useful

## Source Nodes

- BrokerCompatibilityChecker
- CoordinatorService
- App