# Fase 15 — Exportación y optimización

Los jobs de adapter, merged model, safetensors y GGUF exigen capacidades de conversión
probadas. El paquete copia cada artefacto, verifica SHA-256, conserva licencia, procedencia,
training manifest y configuración de serving, y calcula un fingerprint reproducible.

La política de caché solo produce un plan revisable; la API no ofrece borrado. No se ha
convertido ni servido un modelo real porque no existe todavía un training run aprobado.

El ejecutor `model.export.v1` implementa archivo determinista del adapter, merge PEFT a
safetensors, conversión opcional mediante llama.cpp y empaquetado verificado. El camino
adapter-only está probado con artefactos controlados; merge y GGUF siguen pendientes de un
modelo y convertidor reales aprobados.
