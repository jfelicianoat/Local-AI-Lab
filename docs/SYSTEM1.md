# Evaluación semántica con System 1

## Arquitectura y punto de integración

`StrategySuiteExecutor` ejecuta B0–F2 sobre una suite y un snapshot congelados,
aplica `ResearchResponseVerifier` y escribe `strategy-report.json`. El Coordinator
verifica el paquete y persiste su resumen; la aplicación muestra esos resúmenes.
La revisión humana y la evaluación formal con Model Drift son puertas separadas.
No había un judge semántico por respuesta configurado en este ejecutor.

La capa nueva se integra después de las comprobaciones deterministas. Consume
`POST /api/v1/system1/judge` a través del cliente Broker existente, contrato 2.11.
El Broker decide proveedores, modelos y fallback. El nuevo `Client_API.md` prima
sobre el orden de proveedores del prompt antiguo. No se contacta con LAYA,
Ollama ni LM Studio desde Local AI Lab.

Plan mínimo: ampliar el cliente; añadir evaluación y agregación; propagar la
configuración por el trabajo existente; guardar resultados en el informe y
mostrar sus métricas; verificar contrato, fallback y reejecución.

La función está desactivada por defecto. Al activarla se recomienda empezar en
modo sombra. El juez potente usa `BrokerTaskClient.invoke`, con un modelo exacto
configurado por el usuario. Si falta ese modelo o falla, el caso queda en el
flujo anterior de revisión, sin inventar una etiqueta. Las revisiones humanas,
los candidatos de entrenamiento y el estado formal no se autoaprueban.

## Ampliación del contrato del 3 de octubre de 2026

La versión sigue siendo 2.11, pero `system1_evaluation` anuncia la extensión.
Para `evaluation_semantic_label` se envía `threshold_profile: "default"` cuando
está disponible; los brokers 2.11 anteriores mantenían ese default implícito.
Se puede seleccionar otro perfil del operador mediante la configuración.

`system1_target` permite fijar proveedor y, opcionalmente, modelo para comparar
jueces. Se envía como `target` solo si el Broker anuncia `system1_evaluation`;
si no, se conserva el fallback de la aplicación y se informa de la capacidad
ausente. Con un target el Broker no cambia de proveedor. El informe conserva
el modelo devuelto, que puede ser la resolución canónica de un alias.

Se guardan `decision`, `confidence`, `alternatives` y `score_source` de cada
intento, incluidos los rechazados. Sirven para métricas por proveedor/modelo,
confusión contra gold y bins de confianza. Una nota de un intento no se usa
para aceptar una etiqueta: sigue siendo necesario el `accepted: true` de primer
nivel. Las puntuaciones `self_reported` nunca calibran al alumno ni permiten
autoaceptación; el juez potente del flujo existente sigue usando tareas del
Broker y su etiqueta, sin fingir que su confianza es una probabilidad medida.

## Configuración y uso

En Experimentos, dentro de B0–F2, selecciona el modo de evaluación. Desactivado
reproduce el informe previo. En sombra se consulta System 1 pero la etiqueta
final viene del juez potente configurado; sin juez sigue pendiente de revisión.
En activo se acepta una etiqueta cuando el Broker acepta el juicio y su score
alcanza el umbral del ensayo. El umbral local no puede rebajar el del Broker.

La API `/app/v1/strategy-runs` admite este objeto `evaluation`:

```json
{
  "enabled": true,
  "shadow_mode": true,
  "threshold": 0.95,
  "thresholds": {},
  "threshold_profile": "default",
  "http_timeout": 75.0,
  "require_calibrated": false,
  "system1_target": null,
  "strong_judge_model": null,
  "strong_judge_timeout": 300.0
}
```

Para configurar el juez potente, `strong_judge_model` contiene el
`provider`, `deployment` y `model` exactos de un modelo del catálogo del Broker.
F1/F2 también necesita un endpoint Broker si la evaluación está activada.
`thresholds` permite umbrales por `evaluator.id` de la suite. La configuración
completa queda en el JobSpec y en el informe, con su SHA-256 reproducible.
La credencial se lee en el Worker de `LOCAL_AI_LAB_BROKER_TOKEN`; no se guarda
en el trabajo ni en el informe.

Las suites pueden añadir un `evaluator` a cada caso. Están disponibles:
`semantic` (por defecto), `exact_match` con `expected`, `regex` con `pattern`
(full match), `json_schema` con `schema` y `numeric` con `expected` y `tolerance`.
La verificación canónica de esquema, citas y evidencia conserva prioridad.
No se sustituye ninguna comprobación de compilación o tests del proyecto por
IA; esta capa no ejecuta código generado.

## Golden set y reevaluación

Una etiqueta gold corresponde a una **respuesta concreta**, no solo a la pregunta.
Debe indicar `gold_label` y `gold_response_sha256`, calculado con SHA-256 del JSON
canónico de la respuesta (`sha256_json`). Si cambia la respuesta, la etiqueta
queda excluida de las métricas y se registra `response_mismatch`. Las etiquetas
pueden proceder de revisión humana o de un juez ya validado; eso no convierte
automáticamente el score del alumno en una probabilidad calibrada.

El comando siguiente vuelve a evaluar respuestas ya guardadas, con el mismo
snapshot y suite, sin volver a generar respuestas ni sustituir el informe:

```powershell
rtk proxy python scripts/reevaluate_system1.py --report RUTA/strategy-report.json --suite RUTA/SUITE --snapshot RUTA/SNAPSHOT --config RUTA/evaluation.json --broker-endpoint http://127.0.0.1:8000 --output RUTA/reevaluation.json
```

`--limit 120` selecciona los primeros 120 casos si el informe los contiene.
`--gold-labels RUTA/gold.json` acepta un mapa de case IDs a
`{"label":"correct","response_sha256":"SHA256_DE_LA_RESPUESTA"}`.
`--compare RUTA/reevaluation-anterior.json` mide estabilidad contra otra ejecución
de las mismas respuestas, casos y configuración. Las latencias son observadas;
la repetición de una llamada System 1 puede volver a ejecutar al proveedor,
porque el contrato no ofrece deduplicación para estos juicios.

El informe guarda origen, etiqueta final, score, proveedor/modelo devuelto,
escalado, errores, notas de todos los intentos, tokens si constan y latencias por
etapa. Agrega tasas por origen, escalado, acuerdo, matriz de confusión,
precision/recall/F1 por clase y falsos positivos. Los bins incluyen solo scores
`native` contra gold vinculado a la respuesta. Se muestran como evidencia para
calibrar; no se declara la confianza calibrada ni se modifica el umbral solo por
ejecutar el informe.

El Coordinator recalcula las métricas del artefacto antes de aceptar su resumen.
La interfaz distingue etapas y ausencia de gold/coste. `generation_cost_amount`
conserva el dato anterior de generación; el coste total es desconocido cuando
System 1 interviene, porque la API no proporciona su coste monetario.

## Verificación y límites de la demostración

Se incluye una prueba de contrato con 120 ejemplos **simulados**, no una medición
de la capacidad de un modelo real:

| Etapa | Casos | Tasa |
|---|---:|---:|
| Determinista | 40 | 33,3 % |
| System 1 autoaceptado | 40 | 33,3 % |
| Juez potente | 40 | 33,3 % |
| Pendientes | 0 | 0 % |

El acuerdo con las etiquetas de fixture es 100 % por construcción. Verifica
enrutado y agregación, **no prueba precisión, calibración ni ahorro real**. Las
latencias corresponden al transporte simulado; no son latencias de inferencia.
También se prueba una suite completa por el ejecutor real, empaquetado del
informe, validación del Coordinator, persistencia y reevaluación.

El Broker no estaba accesible en `127.0.0.1:8000` ni `127.0.0.1:8765` durante esta
verificación. Para el ensayo real de 100+ casos, ejecuta una suite aprobada de
esa longitud y reevalúa el informe en sombra contra gold/judge. La suite sintética
incluida tiene cinco casos y ground truth pendiente de aprobación; no se presenta
como un golden set humano. El contrato no anuncia una ruta batch: el ejecutor
mantiene el procesamiento por casos del framework existente.
