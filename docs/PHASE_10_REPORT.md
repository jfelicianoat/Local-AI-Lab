# Fase 10 — Fine-tuning

El resolver de hardware solo selecciona nodos con backward, LoRA, 20 pasos, checkpoint/resume,
backend, memoria y dtype en estado `tested` o `benchmarked`. Prefiere bf16 únicamente si fue
probado y usa fp16 como fallback explícito.

El validador prueba C1–C6 por lote tokenizado. El plan largo exige además sobreajuste de ocho
ejemplos, guardado, recarga, resume, contaminación y manifest. Rechaza objetivos que pretendan
memorizar hechos cambiantes y requiere aprobación humana. No se ha ejecutado entrenamiento
real ni se han supuesto capacidades del hardware.

El ejecutor `training.lora.v1` carga únicamente artefactos locales, aplica la chat template,
enmascara la loss fuera del assistant, supervisa EOS, rechaza truncado del assistant, permite
resume y verifica la recarga del adapter safetensors. Su existencia no convierte ninguna
capacidad NVIDIA o AMD en probada.
