---
type: "query"
date: "2026-10-03T20:50:01.969743+00:00"
question: "Como se inicia el escritorio portable de Local AI Lab?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["start_coordinator", "resolve_coordinator_executable"]
---

# Q: Como se inicia el escritorio portable de Local AI Lab?

## Answer

Expanded from original query via vocab: desktop portable sidecar start. start_coordinator and resolve_coordinator_executable in apps/desktop/src-tauri/src/coordinador.rs show the desktop automatically starts the Coordinator and resolves resources/local-ai-lab-coordinator.exe for portable builds. Added iniciar_local_ai_lab.bat to select the newest complete candidate directory, with fallback to apps/desktop/src-tauri/target/release. Launcher check resolved candidate-system1-20261003; observed Application startup complete and a fresh coordinator/state.db. The smoke helper could not use taskkill, so closed the test desktop using CloseMainWindow and verified the test process IDs were gone.

## Outcome

- Signal: useful

## Source Nodes

- start_coordinator
- resolve_coordinator_executable