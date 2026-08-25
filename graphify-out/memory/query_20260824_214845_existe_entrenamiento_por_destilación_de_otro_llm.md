---
type: "query"
date: "2026-08-24T21:48:45.077149+00:00"
question: "¿Existe entrenamiento por destilación de otro LLM en Local AI Lab?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["FineTuningProposal", "TrainingPlanBuilder", "TransformersLoraExecutor", "DatasetFactory"]
---

# Q: ¿Existe entrenamiento por destilación de otro LLM en Local AI Lab?

## Answer

Expanded from original query via graph vocab: [training, strategies, strategy, model, modelo, dataset, fine, tune, lora, workflow, workflows, knowledge]. Local AI Lab currently implements approved local supervised fine-tuning through training.lora.v1 using TransformersLoraExecutor. Documentation mentions teacher generation as a possible dataset source and large local models as teacher/judge, but no executable distillation job, teacher-student loss, logits transfer, synthetic teacher-generation pipeline, API, worker executor, or desktop flow exists. Therefore model distillation is a planned/new capability, not currently implemented.

## Outcome

- Signal: useful

## Source Nodes

- FineTuningProposal
- TrainingPlanBuilder
- TransformersLoraExecutor
- DatasetFactory