# Protocolo de validación con el primer estudio de tiempos real

Estado del módulo de datos: **SYNTHETICALLY_VALIDATED** (probado sólo con datos sintéticos de distribución conocida).
Este protocolo define qué hay que hacer para pasar a **REAL_DATA_VALIDATED**. Hasta completarlo, ningún resultado
obtenido con datos importados debe presentarse como validado frente a la planta.

| Estado | Significa | Cómo se alcanza |
|---|---|---|
| CODE_COMPLETE | el flujo existe de punta a punta | CLI/UI + tests |
| SYNTHETICALLY_VALIDATED | recupera parámetros conocidos y no corrompe datos sintéticos | tests con semillas y tolerancias (estado actual) |
| REAL_DATA_VALIDATED | con un estudio real, los cuatro niveles A–D de abajo se cumplen y están firmados por el ingeniero | este protocolo |

## 0. Elegir el caso

Empieza por **una sola operación sencilla y conocida, preferiblemente manual** (p. ej. montaje de circuitos en
bastidor): alguien de planta sabe cuánto suele tardar, qué incidencias tiene y puede revisar los ciclos raros.
No empieces por una máquina con averías ni por un proceso con mezcla de productos.

## 1. Recogida

Ciclos **consecutivos** (no seleccionados), idealmente varias horas, más de un operario y de un turno si existen.
Columnas recomendadas (sólo VALUE es obligatoria):

| Columna | Por qué |
|---|---|
| timestamp | orden temporal, dependencia serial, holdout |
| measured_value | el tiempo |
| unit | evita adivinar (s / min) |
| operator | diferencias entre operarios (no se mezclan sin decidirlo) |
| product | idem por producto |
| machine_or_station | idem por puesto |
| batch | rachas por lote |
| shift | diferencias por turno |
| observation | qué pasó: ciclo normal, falta de material, conversación, microparada, retrabajo, error de medición… |

**No limpies el archivo antes de importarlo**, salvo por privacidad/confidencialidad (anonimiza nombres; no borres
filas ni "corrijas" valores). Las observaciones de texto son las que permiten decidir después qué es un ciclo real.

## 2. Nivel A — Importación (¿llegan los datos intactos?)

| Comprobación | Cómo | Criterio |
|---|---|---|
| mismo número de registros | contar filas en Excel vs `OBSERVATIONS` del DATA PROFILE | igual (las vacías aparecen como INVALID, no desaparecen) |
| valores sin alteración | 10–20 filas al azar: valor original del archivo vs `original_value` y `value` (`inspect --json`) | idénticos; conversiones de unidad correctas |
| unidades | revisar `UNIT`, `transformations` (MIXED_UNITS, DECIMAL_COMMA…) | ninguna interpretación inesperada |
| orden temporal | `ORDER: timestamp` en el perfil; secuencia (UI) | coincide con el archivo |
| hash reproducible | importar dos veces el mismo archivo | la segunda vez `DUPLICATE` del mismo dataset |
| archivo original preservado | `datasets/<nombre>/v0001/source/` | byte a byte igual (sha256 del perfil = sha256 del archivo) |

## 3. Nivel B — Estadística (¿son correctos los números?)

Calcula **de forma independiente** (Excel, R o Python a mano) y compara con el DATA PROFILE:
n, filas vacías/invalid, media, mediana, desviación típica, P50, P95, outliers por IQR (Q1 − 1.5·IQR, Q3 + 1.5·IQR).
Ajusta en otra herramienta al menos la lognormal y la gamma (MLE, loc = 0) y compara parámetros y AIC.

Criterio: coincidencia hasta redondeo; los percentiles pueden diferir ligeramente según el método de interpolación
(SimForge usa la interpolación lineal de numpy): anota la diferencia, no la "arregles".

## 4. Nivel C — Interpretación industrial (¿tiene sentido para la planta?)

Con alguien que conozca la operación, revisa:

* **cada outlier candidato** con su `observation`: ¿atasco real, falta de material, retrabajo, error de medición?
  Un valor estadísticamente extremo **no se elimina sólo por ser extremo**: si es un evento que ocurre en la operación
  real, se queda (`KEEP`). Sólo los errores de medición o eventos ajenos a la operación se excluyen, con motivo.
* microparadas y conversaciones: ¿forman parte del tiempo de ciclo que quieres simular o se modelan aparte?
  (Hoy el motor no modela microparadas aparte: si las excluyes, la simulación será optimista; anótalo.)
* cambios de producto y diferencias por operario / turno / lote: comparación por grupos; decidir explícitamente
  si se ajusta por grupo o se mezcla (`--pooled`, queda registrado).
* dependencia temporal: `POSSIBLE_SERIAL_DEPENDENCE` o tendencia → ¿aprendizaje, fatiga, lotes? El motor muestrea
  de forma independiente.
* base de la medida (por circuito / por bastidor) y agregación (`sum_iid` / `scale_sample` / `single_sample`):
  confirmarla con quien hizo el estudio.

Resultado: lista de decisiones (KEEP/EXCLUDE con motivo) firmada; todo queda en el log del dataset.

## 5. Nivel D — Validación con el simulador (¿reproduce la realidad?)

1. **Holdout temporal**: `simforge data holdout <p> <dataset> --train 0.7`. Ajusta con el primer 70 % y comprueba con
   el 30 % final (70/30 es una propuesta, no una ley; con pocos datos usa 60/40). Mira:
   * `POSSIBLE_DRIFT` entre ambas partes → el proceso cambió durante el estudio: ninguna distribución lo representa
     bien; entiende la causa antes de seguir;
   * qué candidatos predicen mejor la parte final (log-verosimilitud por observación, KS de validación, P50/P95);
   * cuántos valores finales superan el máximo de la parte de ajuste (una empírica no los generaría).
   El objetivo es comprobar que el modelo representa observaciones **posteriores**, no sólo los datos con los que se
   ajustó.
2. **Distribución simulada vs real**: decide y aplica (con el ajuste del 70 % o con todo, decidiéndolo), aprueba y
   ejecuta con ≥ 10 réplicas. Compara la distribución de tiempos de esa operación en el log de eventos
   (`simforge run <proyecto>/versions/vNNNN.yaml --trace-dir trazas/`, sobre la versión aprobada) con los datos:
   P50 y P95 dentro de los intervalos bootstrap del perfil.
3. **Producción**: producción por hora simulada frente a la real del mismo periodo (si hay registro), y variabilidad
   entre réplicas frente a variabilidad entre turnos/días reales.
4. **Si aplica**: WIP, tiempo en starvation y blocking frente a observación en planta.

Criterio de aceptación: lo fija el ingeniero antes de mirar los resultados (p. ej. producción simulada dentro de ±5 %
de la real, P95 dentro del IC bootstrap). Anótalo en el informe junto con el resultado, sea positivo o negativo.

## 6. Registro

Un informe breve (markdown) con: archivo y su sha256, dataset `nombre@vN`, decisiones de filas, `fit_id`, decisión,
versión del modelo aprobada, versión del motor, semillas, resultados de A–D y la firma del ingeniero. Sólo entonces
el módulo puede marcarse **REAL_DATA_VALIDATED para esa operación**; otras operaciones (máquinas, averías, llegadas)
requieren su propio estudio.

## Qué puede salir mal (y cómo se nota)

| Problema | Síntoma |
|---|---|
| unidad mal declarada (min como s) | media absurda en el perfil; producción simulada ×60 |
| base mal declarada (por bastidor como por circuito) | tiempo de entidad ×k; el `apply` pide conversión o agregación |
| datos "limpiados" antes de importar | menos outliers de lo esperado; P95 bajo; simulación optimista |
| grupos mezclados | distribución ancha o bimodal; `GROUPS_DIFFER` |
| proceso que cambia durante el estudio | `POSSIBLE_TREND`, `POSSIBLE_DRIFT` en el holdout |
| redondeo del cronómetro | `ROUNDED_DATA` / `TIES`; KS/AD poco fiables |
| microparadas fuera del tiempo medido | producción simulada por encima de la real |
