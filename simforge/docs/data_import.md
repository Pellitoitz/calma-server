# Importar datos medidos (CSV / XLSX)

> **Los datos miden · el sistema analiza · el ingeniero decide · el motor simula.**
> SimForge no "adivina la distribución": convierte mediciones en una decisión de modelado informada, reproducible
> y firmada por el ingeniero. Todo funciona sin IA y sin conexión.

Estado: **SYNTHETICALLY_VALIDATED** (sólo datos sintéticos). Para validarlo con el primer estudio real:
[`real_data_validation_protocol.md`](real_data_validation_protocol.md).

Este documento explica el flujo completo para un ingeniero de procesos. El ajuste estadístico y cómo leerlo están en
[`distribution_fitting.md`](distribution_fitting.md).

```
archivo  →  PREVIEW  →  IMPORT (versión inmutable)  →  VALIDATE (fila a fila)  →  ANALYZE (estadística, outliers)
        →  FIT (candidatos)  →  DECIDE (ingeniero)  →  APPLY (nueva versión del modelo, aprobación invalidada)
        →  APPROVE  →  RUN
```

## Qué hace y qué NO hace

| Hace | NO hace nunca |
|---|---|
| Lee CSV (`;` `,` tab `|`, coma o punto decimal) y XLSX (hoja y columna elegidas) | Ejecutar macros, fórmulas, vínculos externos u objetos incrustados |
| Detecta separador y decimal; **pregunta** si hay dos lecturas posibles | Elegir entre dos lecturas plausibles por su cuenta |
| Clasifica cada fila VALID / WARNING / INVALID / REQUIRES_REVIEW con el motivo | Borrar filas, rellenar vacíos, inventar observaciones |
| Convierte unidades guardando valor y unidad **originales** y **normalizados** | Suponer una unidad (`m` en un tiempo es ambiguo: se rechaza) |
| Señala outliers **candidatos** (IQR y MAD) | Excluir un outlier sin acción explícita del ingeniero |
| Ajusta 7 familias y propone un **candidato sugerido** | Aplicar una distribución sin decisión del ingeniero |
| Conserva la base (por circuito, por bastidor...) | Convertir entre bases sin factor, fórmula y entradas explícitas |
| Versiona cada importación con hash; detecta duplicados | Sobrescribir un dataset ya importado |

## 1. Mirar el archivo antes de importarlo

```bash
simforge data preview tiempos_montaje.xlsx                  # hojas del libro (no se asume la primera)
simforge data preview tiempos_montaje.xlsx --sheet Hoja1    # columnas, tipo detectado, primeras filas
```

Para cada columna se muestra el tipo detectado (`number`, `text`, `datetime`, `duration`, `empty`, con cuántas celdas
no encajan). Si la cabecera sugiere una unidad (`tiempo (min)`) se muestra como **pista**; no se aplica: la unidad la
indicas tú.

**CSV europeo.** `12,4;13,7` con `;` se lee como decimal coma. Si un archivo mezcla `12,5` y `13.25`, o varios
separadores dan columnas coherentes, SimForge se detiene con `Formato ambiguo` y las opciones: repite con
`--delimiter ';'` y/o `--decimal ','`. Los separadores de miles (`1.250,5`) se aceptan sólo si encajan exactamente
y la fila queda en WARNING (`THOUSANDS_SEPARATOR_REMOVED`).

**XLSX.** Se abre en modo sólo-datos. Una celda con fórmula aporta el valor que Excel guardó la última vez (nunca se
recalcula) y la fila queda en REQUIRES_REVIEW; si no hay valor guardado, INVALID. Las celdas con formato de duración
(`00:02:30`) se convierten a segundos con WARNING. Macros (`.xlsm`), vínculos externos y objetos incrustados se
ignoran y se indica en las notas. `.xls` (Excel 97-2003) no se admite: guárdalo como `.xlsx`.

**Límites** (archivo no confiable): 50 MB de archivo, 300 MB descomprimido y ratio de compresión ≤ 200 (bombas ZIP),
1 000 000 filas, 1 000 columnas. Están pensados para estudios de tiempos (decenas a decenas de miles de filas).

## 2. Importar

```bash
simforge data import <proyecto> tiempos_montaje.xlsx --name montaje --sheet Hoja1 --column Tiempo \
    --unit s --timestamp Fecha --quantity PROCESSING_TIME --basis PER_CIRCUIT --by ana
```

| Opción | Significado |
|---|---|
| `--column` | columna VALUE (obligatoria) |
| `--unit` / `--unit-column` | unidad de toda la columna, o columna con la unidad de cada fila. **Obligatoria**; `UNKNOWN` se admite para analizar la forma de los datos, pero entonces no se pueden aplicar al modelo |
| `--quantity` | qué se midió (tabla abajo) |
| `--basis` | a qué se refiere cada medida (abajo). `UNKNOWN` impide aplicarla al modelo |
| `--timestamp` | conserva el orden temporal (secuencia, dependencia serial) |
| `--group role=columna` | columnas categóricas: `operator`, `product`, `shift`, `machine`, `batch` |
| `--synthetic` | datos sintéticos de prueba: nunca se presentan como medidos (un archivo `SYNTHETIC_*` lo es siempre) |
| `--imported` | valores exportados de un sistema (procedencia IMPORTED) en lugar de un estudio (MEASURED) |

### Magnitudes: importar ≠ poder simular

`simforge data quantities` muestra la tabla viva. Cualquier magnitud se puede importar y analizar
(DATA_IMPORT_SUPPORTED); sólo algunas tienen un parámetro del motor donde aplicarse:

| Magnitud | Uso en simulación | Destino |
|---|---|---|
| PROCESSING_TIME | sí | `nodes.<id>.params.process_time` (máquina, montaje, inspección...) |
| ARRIVAL_INTERVAL | sí | `nodes.<fuente>.params.interarrival` (con `arrival: interarrival`) |
| REPAIR_TIME / FAILURE_INTERVAL | sí, si el nodo ya declara averías | `params.failures.mttr` / `params.failures.mtbf` |
| LOAD_TIME / UNLOAD_TIME | sí | `params.load_time` / `params.unload_time` de un transporte (por viaje) |
| DISTANCE | sólo un valor fijo (el motor no admite distancias aleatorias) | `params.distance` de un transporte |
| TRANSPORT_TIME | **SIMULATION_USE_NOT_YET_SUPPORTED**: el motor calcula el viaje con distancia/velocidad + carga/descarga; mide esas partes por separado | — |
| SETUP_TIME | **SIMULATION_USE_NOT_YET_SUPPORTED** (no hay setups en el motor) | — |

### Unidades

Tiempo: `ms`, `s`, `min`, `h` (también `seg`, `minutos`, `horas`...). Distancia: `mm`, `cm`, `m`, `km`. Cada
observación guarda **ORIGINAL_VALUE / ORIGINAL_UNIT** (tal cual el archivo) y **NORMALIZED_VALUE / NORMALIZED_UNIT**
(s o m). Si toda la columna tiene una unidad, el análisis se hace en esa unidad (minutos se quedan en minutos); si
hay mezcla, en la unidad base, y queda anotado (`MIXED_UNITS`).

### Base (entity basis)

`PER_CIRCUIT`, `PER_RACK`, `PER_PANEL`, `PER_UNIT`, `PER_BATCH`, `PER_CYCLE`, `PER_OPERATION`, `PER_TRIP`, `UNKNOWN`.
**30 s/circuito no es 30 s/bastidor.** La base se declara al importar y no cambia nunca; la conversión sólo ocurre al
aplicar, de forma explícita (ver §6).

### Validación fila a fila

| Estado | Se usa en el análisis | Ejemplos |
|---|---|---|
| VALID | sí | número correcto |
| WARNING | sí, con la interpretación anotada | miles eliminados, unidad dentro del valor (`12 min`), duración Excel, marca de tiempo repetida |
| REQUIRES_REVIEW | **no**, hasta `ACCEPT_REVIEWED` | `0` (¿dato real o "sin dato"?), valor de fórmula |
| INVALID | nunca | vacío, `n/a`, texto, negativo, unidad desconocida o en conflicto, fecha en la columna de valores |

Además se anotan a nivel de dataset: datos redondeados (pocos valores distintos), marcas de tiempo duplicadas,
unidades mezcladas.

### Versiones y duplicados

Cada importación es `nombre@vN`, inmutable: copia byte a byte del archivo (sólo lectura), observaciones interpretadas
y `dataset.json` con hash del archivo y **hash del dataset** (archivo + configuración + observaciones). Importar el
mismo archivo con la misma configuración devuelve el existente (`DUPLICATE`); con otra configuración, o un archivo
modificado, crea `vN+1`. Lo que haga el ingeniero después (exclusiones, ajustes, decisiones, aplicaciones) se añade a
un registro **append-only** (`events.jsonl`).

```
<proyecto>/datasets/montaje/v0001/source/tiempos_montaje.xlsx   copia intacta del archivo
                                 /dataset.json                  metadatos + hash (sólo lectura)
                                 /observations.json             filas interpretadas (sólo lectura)
                                 /events.jsonl                  acciones del ingeniero (sólo se añade)
```

## 3. Analizar: DATA PROFILE

```bash
simforge data inspect <proyecto> montaje@v1            # -o perfil.md para guardarlo
```

Muestra origen, magnitud, unidad, base, recuento por estado y motivo de cada fila no usada, estadística descriptiva
(n, media con IC95, mediana, desviación, varianza, mín/máx, rango, Q1/Q3, IQR, P5…P99, CV, asimetría, curtosis),
bootstrap reproducible (semilla 12345) de media, mediana y P95, orden usado (marca de tiempo o archivo), correlación
lag-1 (`POSSIBLE_SERIAL_DEPENDENCE` si |r1| > 2/√n) y tendencia, outliers candidatos y un **STATUS**:
`REQUIRES_ENGINEER_REVIEW` → `READY_FOR_ENGINEER_DECISION` → `DECIDED` → `APPLIED` (o `REJECTED`).

Un percentil sólo se muestra si hay datos a ambos lados (P99 necesita ≥ 100 observaciones); si no, aparece `—`.

**Tamaño de muestra.** Avisos, no leyes: `VERY_SMALL_SAMPLE` (n < 10), `SMALL_SAMPLE` (10–29),
`USABLE_WITH_CAUTION` (30–99), `LARGER_SAMPLE` (≥ 100). Significado en
[`distribution_fitting.md`](distribution_fitting.md#tamaño-de-muestra).

**Grupos.** Si el dataset tiene columnas de grupo (operario, producto, turno...) y en las filas usadas hay más de un
valor, el análisis y el ajuste **se detienen** hasta que elijas un subconjunto (`--group operator=A`) o declares que
los mezclas (`--pooled`, queda registrado). Se muestra una comparación por grupo (Kruskal-Wallis como información).

**Gráficos** (pestaña Data de la UI, o `--json`): histograma (Freedman-Diaconis), ECDF, boxplot, secuencia en el orden
original y Q-Q contra cada candidato. El orden de los datos nunca se altera.

## 4. Revisar filas y outliers

Un outlier es un **candidato**, no un error: en tiempos industriales la cola derecha suele ser real (atascos,
retrabajos) y quitarla hace la simulación optimista.

```bash
simforge data rows <p> montaje@v1 KEEP 20 61 --reason "caída de tornillo anotada en el parte" --by ana
simforge data rows <p> montaje@v1 EXCLUDE_FROM_FIT 70 --reason "lector duplicado: 5 s imposible" --by ana --method MAD
simforge data rows <p> montaje@v1 RESTORED 70 --reason "revisado: era real" --by luis
simforge data rows <p> montaje@v1 ACCEPT_REVIEWED 33 --reason "0 s real: pieza ya montada" --by ana
```

`EXCLUDE_FROM_FIT` y `MARK_INVALID` no borran nada y se deshacen con `RESTORED`. Cada acción guarda filas, motivo,
método, quién y cuándo. Las filas INVALID de importación (vacías, negativas, texto) no se pueden "restaurar": no
tienen un valor válido.

## 5. Ajustar y decidir

```bash
simforge data fit <p> montaje@v1 --by ana [--physical-min 10]
simforge data decide <p> montaje@v1 USE_FITTED --fit fit_… --candidate lognormal --by ana --reason "..."
simforge data decide <p> montaje@v1 USE_EMPIRICAL --by ana
simforge data decide <p> montaje@v1 USE_DETERMINISTIC --derivation MEDIAN --by ana      # MEAN | MEDIAN | ENGINEER_VALUE --value 30
simforge data decide <p> montaje@v1 KEEP_WITHOUT_APPLYING --by ana --reason "falta el turno de tarde"
simforge data decide <p> montaje@v1 REJECT --by ana --reason "estudio mal planteado"
```

Cómo leer el ranking y cuándo elegir empírica o determinista: [`distribution_fitting.md`](distribution_fitting.md).
Reglas que SimForge impone:

* Un ajuste vale sólo para el estado de datos sobre el que se hizo: si después excluyes o restauras filas, hay que
  volver a ajustar.
* Los avisos de plausibilidad (cola extrapolada, masa por debajo del mínimo, media desplazada...) hay que aceptarlos
  explícitamente (`--accept TAIL_EXTRAPOLATION`), o elegir otra opción.
* `normal` con masa negativa sólo con truncamiento declarado (`--trunc-lower 0 --trunc-reason "..."
  --trunc-bound-type MODELLING_BOUND`); el tipo de límite (PHYSICAL_BOUND / MODELLING_BOUND) es obligatorio y el método
  queda registrado como `FIT_THEN_TRUNCATE`.
* Con n < 10, `USE_FITTED` exige `--accept VERY_SMALL_SAMPLE`; `USE_EMPIRICAL` sólo avisa (y lo registra), mostrando
  observed_min, observed_max y n: la empírica nunca genera nada fuera de ese rango.
* Antes de decidir puedes comprobar la estabilidad con `simforge data holdout` (ajuste con el 70 % inicial, validación
  con el 30 % final; ver [`distribution_fitting.md`](distribution_fitting.md#holdout-temporal)).
* Un valor determinista registra si es MEAN, MEDIAN o ENGINEER_VALUE: una media no se etiqueta como medida individual.

## 6. Aplicar al modelo

```bash
simforge data apply <p> montaje@v1 dec_001 --target nodes.assembly.params.process_time \
    --target-basis PER_CIRCUIT --aggregation sum_iid --by ana
```

Comprobaciones antes de escribir nada:

* la magnitud se puede usar en simulación y el destino es del tipo correcto (un tiempo de proceso no va a un buffer;
  un MTTR requiere que el nodo tenga averías; una distancia sólo admite un valor fijo);
* unidad conocida y **base del dato = base del destino**. Si difieren, conversión explícita:
  `--factor 4 --formula "t_rack = 4 · t_circuito" --inputs '{"circuits_per_rack": 4}'`. El valor resultante queda
  como CALCULATED con la fórmula y las entradas en su procedencia;
* **agregación de `work_units`** (decisión estructurada, guardada en el modelo): si el nodo tiene `work_units ≠ 1`, el
  tiempo es aleatorio y el nodo no la declara, hay que elegir `--aggregation sum_iid` (X1+…+Xk, una muestra
  independiente por unidad), `scale_sample` (k·X) o `single_sample` (X, la muestra ya es la entidad completa). Si la
  base del dato coincide con la del destino, SimForge **propone** `sum_iid` pero no la aplica sola. Detalle y
  varianzas: [`distribution_fitting.md`](distribution_fitting.md#base-work_units-y-agregación-motor--050);
* **escalar una distribución con un factor de base es `k·X`**, no la suma de k tiempos independientes: sólo se permite
  declarándolo (`--conversion-mode scale_sample`); para sumar tiempos independientes usa `work_units` + `sum_iid`;
* el modelo resultante debe verificar sin errores.

Resultado: **nueva versión del modelo** (la anterior queda intacta) con `approval` invalidada, y en el parámetro:

```yaml
process_time:
  dist: lognormal
  mean: 31.04
  std: 9.637
  unit: s
  provenance:
    status: measured            # measured | imported | calculated (media/mediana o conversión) | provided_by_client (valor del ingeniero) | assumed (datos sintéticos)
    source: tiempos_montaje.xlsx
    note: "montaje@v1 (tiempos_montaje.xlsx:Tiempo) USE_FITTED lognormal decided by ana; state 9c1f…"
    data:
      dataset_id: montaje@v1
      dataset_version: 1
      content_hash: e9be4f5edb30f744
      column: Tiempo
      original_unit: s
      basis: PER_CIRCUIT
      n_used: 86
      n_excluded: 0
      decision: FITTED
      fit_id: fit_9b3e929cd03d
      fit_summary: "lognormal MLE (loc=0); AIC 625.8 (ΔAIC 0.00); KS 0.111; n=86"
      parameter_sources: {mean: {source: ESTIMATED_FROM_DATA, method: "MLE, loc fijado en 0 ..."}, std: {...}}
      decided_by: ana
      decided_at: 2026-10-02T09:30:48Z
# y en el mismo nodo, en la misma versión:
work_units: 4
work_units_aggregation: sum_iid   # decisión estructurada (parte del hash del modelo)
```

Los datos sintéticos (`--synthetic`) se aplican con estado `assumed`: nunca aparecen como medidos.

## 7. Aprobar y ejecutar

Un modelo con parámetros derivados de datos **no se ejecuta** si su versión actual no está aprobada:

```bash
simforge project run <p>               # rechazado: "parámetros derivados de datos importados ... no está aprobada"
simforge project approve <p> --by ana  # la aprobación queda ligada al hash exacto de esta versión
simforge project run <p> --reps 10
```

Cualquier cambio posterior del modelo cambia su hash e invalida de nuevo la aprobación.

## Trazabilidad y reproducibilidad

* `simforge data trace <p> nodes.assembly.params.process_time [--version N]` reconstruye el origen: dataset, versión,
  hash (y si el dataset guardado sigue coincidiendo), ajuste, decisión, quién y cuándo.
* Un run guarda versión del modelo, hash del modelo, semillas de cada réplica y versión del motor. Los parámetros
  (incluidos los valores empíricos) están **dentro** de la versión del modelo: si el Excel cambia después, se importa
  como `montaje@v2` y los runs históricos no cambian (test `test_historical_run_is_reproducible_after_source_changes`).
* El historial del proyecto registra `data_import`, `data_rows`, `data_fit`, `data_decision`, `data_apply`.

## Ejemplo completo (reproducible)

`bash examples/data/run_e2e.sh` ejecuta, en un workspace temporal y sin IA, el flujo entero con
`examples/data/synthetic/tiempos_montaje.xlsx` (**SYNTHETIC TEST DATA**: 87 tiempos de montaje por circuito generados
con Gamma(k=16, θ=1.875) s, una celda vacía y dos ciclos largos de 95 y 88.5 s) sobre
`examples/data/e2e_selective_per_circuit.yaml` (la línea de soldadura selectiva con el montaje por circuito,
`work_units: 4`):

| Paso | Resultado |
|---|---|
| preview | hojas `LEEME`, `Hoja1`; columnas `Fecha`, `Operario`, `Tiempo` |
| import | `montaje@v1`: 86 VALID, 1 INVALID (vacía, no se rellena) |
| inspect | media 31.17 s, mediana 31.2 s, CV 0.37; 2 outliers candidatos (idx 20 y 61); STATUS REQUIRES_ENGINEER_REVIEW |
| rows KEEP 20 61 | se conservan: ciclos largos reales |
| fit | lognormal (AIC 625.8), gamma (ΔAIC 8.9), weibull, normal (REQUIRES_TRUNCATION), triangular, exponencial, uniforme; sugerido: lognormal |
| decide + apply | `dec_001` lognormal por circuito, `--aggregation sum_iid` (propuesta por SimForge, confirmada por la ingeniera) → modelo v3, aprobación invalidada; run rechazado |
| approve + run (5 réplicas) | 127.2 ± 1.0 unidades en 8 h (frente a 130 con 30 s/circuito fijos): la variabilidad del montaje, que comparte operario con la revisión, cuesta ~2 % de producción. Con `scale_sample` (4·X, el comportamiento anterior a 0.5.0) salía 124.6 ± 1.4 |

Los generadores de todos los datos sintéticos (casos A–H: constantes, sesgados, llegadas exponenciales, vacíos,
outliers, coma decimal, XLSX con varias hojas, por operario/producto) están en
`examples/data/make_synthetic_data.py`; ver `examples/data/synthetic/README.md`.

## UI

Pestaña **Data**: subir archivo → hoja y separadores → vista previa con tipos → formulario de importación (columna,
magnitud, base, unidad, grupos) → DATA PROFILE con histograma/ECDF/boxplot/secuencia → acciones sobre filas → ajuste
con Q-Q → decisión → aplicación al modelo. Son las mismas llamadas que la CLI (`simforge.data.service.DataService`).

## Limitaciones conocidas

* Lognormal, exponencial, gamma y weibull no tienen parámetro de desplazamiento (localización): empiezan en 0. Un proceso con un mínimo
  físico duro (nunca menos de 40 s) se aproxima; la plausibilidad muestra la masa por debajo del mínimo observado.
* La distribución empírica re-muestrea los valores observados: no genera nada fuera del rango medido ni valores
  intermedios.
* El motor muestrea de forma independiente (i.i.d.): una dependencia serial detectada se avisa, no se modela.
* Excel con fórmulas: se usa el valor guardado por Excel; un libro generado por otra herramienta puede no tenerlo.
* Distancias aleatorias, tiempos de transporte puerta a puerta y setups: importables y analizables, no aplicables.
