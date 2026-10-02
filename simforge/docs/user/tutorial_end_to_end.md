# Tutorial de punta a punta

Caso didáctico, sintético y no confidencial (`examples/1_0_golden_project/`):

**llegadas → montaje manual (1 operario) → buffer (5) → máquina de test → producto terminado**

Pregunta: ¿compensa una máquina de test más rápida? Cada paso de este tutorial lo ejecuta
`tests/test_release_golden_workflow.py`, en procesos separados.

```bash
export SIMFORGE_WORKSPACE=~/simforge-tutorial
G=examples/1_0_golden_project
```

## 1. Crear el proyecto con un dato pendiente

```bash
simforge project new "Golden" --model $G/model_with_missing.yaml
simforge validate $G/model_with_missing.yaml     # ERROR MISSING [parameters.test_cycle.value] → INCOMPLETE
simforge project run golden                      # MODEL_VALIDATION_ERROR … MISSING: no se ejecuta con un hueco
```

El tiempo de ciclo del test todavía no se ha medido. SimForge **no** pone un valor por defecto.

## 2. Resolver el MISSING y verificar

Cuando ya se ha medido (46 s), se guarda una versión nueva:

```bash
simforge project save golden $G/model.yaml -m "test cycle measured: 46 s"
simforge validate $G/model.yaml                  # EXECUTABLE
```

## 3. Revisar supuestos y aprobar

```bash
simforge economics show $G/model.yaml            # los precios son ASSUMED (valores didácticos): visibles como tales
simforge project approve golden --by "process engineer"
simforge project versions golden                 # v3 approved=True
```

## 4. Ejecutar y leer los KPIs

```bash
simforge project run golden                      # 5 réplicas, semillas 1000..1004
```

Resultado esperado (`expected.json`):

| KPI | Valor |
|---|---|
| Unidades completadas | 532 |
| Throughput | ≈ 70,9 units/h |
| Utilización del test | ≈ 91 % (cuello de botella) |
| Utilización del montaje | ≈ 78 % |

## 5. Escenario alternativo

```bash
simforge project baseline golden
simforge project scenario golden faster_test $G/alternative.yaml   # test de 40 s, tarifa 21 €/h, CAPEX 24 000 €
simforge project approve golden --by "process engineer"
simforge project run golden
```

## 6. Evaluación económica y comparación (hechos, no recomendación)

```bash
simforge project runs golden                                  # ids de los dos runs
simforge project evaluate golden <run_baseline> --from-run    # COMPLETE_FOR_REQUESTED_SCOPE
simforge project evaluate golden <run_alternativa> --from-run
simforge project compare golden <eval_baseline> <eval_alternativa>
```

Lo que muestra:

- **Comparación emparejada:** mismas semillas.
- **Producción:** +1,8 unidades.
- **Ahorro por run:** −8,84 € (la alternativa cuesta más).
- **Payback:** `NOT_REACHED`.

Lectura: la demanda (una llegada cada 50 s) limita la producción, así que una máquina más rápida apenas produce más.
SimForge muestra los hechos; **decide el ingeniero**.

## 7. Informe, manifiesto y exportación

```bash
simforge project report golden --run-id <run_baseline>        # Markdown + HTML + CSV, con estado de validación
simforge project manifest golden <run_baseline> -o manifest.json
simforge project export golden golden.simproject
```

## 8. Reabrir en otra máquina y reproducir

```bash
SIMFORGE_WORKSPACE=~/otra-maquina simforge project import golden.simproject
SIMFORGE_WORKSPACE=~/otra-maquina simforge run ~/otra-maquina/projects/golden/versions/v0003.yaml --json
```

La salida tiene las mismas `per_replication` que el run original: mismo modelo, mismas semillas y mismo motor, sin
caché. La UI (`simforge ui`) permite hacer lo mismo en las pestañas Model → Run & results → Economics → Report.
