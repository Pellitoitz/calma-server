# Ajuste de distribuciones: cómo leerlo y cómo decidir

> SimForge propone **candidatos** con evidencia. La distribución que entra en el modelo la elige el ingeniero.
> No hay "BEST DISTRIBUTION = X" ni "p > 0.05 = correcta".

Importación, validación y aplicación al modelo: [`data_import.md`](data_import.md).

## Las opciones

| Opción | Qué simula | Cuándo tiene sentido |
|---|---|---|
| **DETERMINISTIC** (MEAN / MEDIAN / ENGINEER_VALUE) | siempre el mismo tiempo | variabilidad despreciable frente al resto (caso A: N(120, 0.8) s, CV < 1 %), o cuando sólo interesa capacidad media. Ojo: quitar variabilidad sobreestima el throughput en líneas con colas o recursos compartidos |
| **EMPIRICAL** | re-muestrea los valores medidos, con la misma probabilidad cada uno | muchos datos, forma rara (bimodal, colas irregulares) o ninguna familia encaja. **Nunca genera valores fuera de [observed_min, observed_max] ni valores intermedios no medidos** (sin KDE ni extrapolación). Se muestran observed_min, observed_max y sample_size; con muestra pequeña se avisa (`EMPIRICAL_SMALL_SAMPLE`) y queda registrado en la decisión, pero no se bloquea |
| **FITTED** (normal, lognormal, exponential, gamma, weibull, triangular, uniform) | una familia paramétrica | forma razonable y conocida del proceso; suaviza y extrapola algo la cola (puede ser bueno o malo: mira la plausibilidad) |
| KEEP_WITHOUT_APPLYING | nada | datos útiles pero incompletos (falta un turno, un producto) |
| REJECT | nada | estudio mal hecho o no representativo |

## Cómo se ajusta

* Estimación por máxima verosimilitud con `scipy.stats` (librería madura; nada implementado a mano).
* Cada parámetro de cada candidato lleva su procedencia (`parameter_sources`): `ESTIMATED_FROM_DATA` (con el
  estimador), `CALCULATED_BOUNDS` (con la fórmula), o `ENGINEER_BOUNDS` / `PROCESS_SPECIFICATION` si los das tú. Se
  conserva en la decisión y en `provenance.data.parameter_sources` del parámetro aplicado.

### Uso de `loc` por familia (auditado)

| Familia | `loc` | Significado |
|---|---|---|
| normal | **estimado** (= μ, MLE) | nunca se fuerza a 0; si la normal ajustada tiene P(t<0) > 1e-9 queda `REQUIRES_TRUNCATION` |
| lognormal, exponencial, gamma, weibull | **fijado en 0** | modelos **sin desplazamiento**: soporte desde 0. El motor no tiene parámetro de localización; no se inventa uno. Un proceso con mínimo duro (nunca < 40 s) queda aproximado: mira `MASS_BELOW_OBSERVED_MIN` |
| uniforme | límites (no `loc` de scipy) | ver abajo |
| triangular | límites + moda | ver abajo |

### Uniforme y triangular: de dónde salen los límites

* **Uniforme por defecto**: `low = mínimo observado`, `high = máximo observado` (`OBSERVED_RANGE`, es el MLE). Sin
  ampliaciones ocultas: la uniforme no genera nada fuera del rango medido.
* **Triangular por defecto**: una triangular con `low` = mínimo observado da densidad 0 a ese dato (log-verosimilitud
  −∞), así que los límites son `CALCULATED_BOUNDS`: `low = mín − (máx − mín)/(n − 1)`, `high = máx + (máx − mín)/(n − 1)`
  (una separación media a cada lado, la misma corrección que el estimador insesgado de los extremos de una uniforme;
  para la triangular es una heurística documentada, no un MLE). Si `low` saldría negativo se recorta a 0 y queda
  escrito (`RECORTADO A 0`). Moda por momentos: `3·media − low − high`, recortada al intervalo si cae fuera (escrito).
* **Con límites de ingeniería**: `--bound-low/--bound-high --bound-source ENGINEER_BOUNDS|PROCESS_SPECIFICATION`.
  Sólo se usan en uniforme/triangular, cuentan como parámetros no estimados (no suman en AIC) y si hay observaciones
  fuera la familia queda `NOT_APPLICABLE` (o el límite o el dato está mal). SimForge nunca inventa límites físicos.
* Se ajusta sobre las filas **en uso** (VALID, WARNING, revisadas aceptadas, no excluidas) del subconjunto elegido.
  El informe registra n usadas, excluidas, grupo, `fit_id` (determinista: mismo dato y estado → mismo id) y el hash
  del estado de los datos. Si las exclusiones cambian, el ajuste anterior deja de servir para decidir.
* Una familia que no se puede ajustar aparece como `FIT_FAILED` con el motivo; con valores 0 las familias de soporte
  (0, ∞) aparecen como `NOT_APPLICABLE`. No se ocultan.

## Cómo leer el STATISTICAL RANKING

**Menor AIC = mejor compromiso estadístico entre los candidatos probados, NO "la distribución verdadera".** La decisión
considera además plausibilidad industrial, soporte, colas, límites físicos, estabilidad (holdout) y el criterio del
ingeniero.


```
#  distribution status                     AIC   ΔAIC      BIC     KS      AD     CvM       P50     P95     P99   P99.9  warnings
1  lognormal    OK                       625.8   0.00    630.8  0.111    1.34   0.188     29.64   48.83   60.04    75.7  -
2  gamma        OK                       634.8   8.93    639.7  0.131    1.83   0.245     30.15   48.84   58.36   70.33  -
4  normal       REQUIRES_TRUNCATION      669.6  43.77    674.5  0.185    4.45   0.657     31.17   50.25   58.15   67.01  NEGATIVE_SUPPORT,...
   OBSERVED                                                                                31.2   41.42       —       —
```

| Columna | Lectura |
|---|---|
| **AIC / ΔAIC** | criterio de ordenación (menor = mejor compromiso ajuste/nº de parámetros). ΔAIC ≤ 2 = soporte estadístico similar; es una **heurística interpretativa habitual**, no una prueba |
| BIC | como AIC con más penalización por parámetros; si discrepan, mira la plausibilidad |
| KS, AD, CvM | estadísticos de distancia entre datos y modelo (menor = más cerca). AD pesa más las colas. Sus p-valores se guardan como **nominales**: los parámetros se estimaron con los mismos datos, así que son optimistas. Nunca deciden por sí solos |
| Q-Q | (UI / `--json`) cuantiles teóricos frente a observados; la correlación y la desviación máxima en el 10 % superior resumen si la cola se parece |
| P50…P99.9 | cuantiles del candidato frente a los observados (fila OBSERVED; `—` si no hay datos suficientes para observarlo) |

**SUGGESTED CANDIDATE** = el menor AIC entre los candidatos `OK` sin avisos CRÍTICOS de plausibilidad. Viene marcado
`REQUIRES ENGINEER ACCEPTANCE` y lista las alternativas equivalentes (ΔAIC ≤ 2). Si todas las familias tienen KS
nominal < 0.01, el informe sugiere considerar la empírica o revisar grupos mezclados / dependencia serial.

## Plausibilidad industrial (separada del ajuste estadístico)

Una distribución puede ajustar bien y aun así generar tiempos absurdos. Para cada candidato:

| Aviso | Severidad | Significado |
|---|---|---|
| NEGATIVE_SUPPORT | CRÍTICO | P(t < 0) > 1e-9: generaría tiempos negativos. Sólo usable con truncamiento explícito (`REQUIRES_TRUNCATION`) |
| MEAN_MISMATCH | AVISO (> 2 %) / CRÍTICO (> 10 %) | la media del modelo no es la observada: afecta directamente al throughput |
| TAIL_EXTRAPOLATION | AVISO | P99.9 > 1.5 × máximo observado: ciclos más largos que ninguno medido |
| EXTREME_TAIL | AVISO | P(t > 3 × máximo observado) > 1e-4 |
| MASS_BELOW_OBSERVED_MIN | AVISO | más del 5 % (o 3/n) de las muestras serían menores que el mínimo medido |
| BELOW_PHYSICAL_MIN / ABOVE_PHYSICAL_MAX | AVISO | si indicas `--physical-min/--physical-max`: probabilidad > 0.1 % fuera de lo físicamente posible |
| BOUNDED_SUPPORT | info | uniforme/triangular: nunca supera su límite superior (observado, calculado o declarado) |

Para usar un candidato con avisos hay que aceptarlos uno a uno (`--accept CÓDIGO`), y quedan registrados en la
decisión. Los CRÍTICOS no se sugieren nunca.

## Truncamiento

Nunca automático. No existe `max(0, x)` ni re-muestreo que el modelo no conozca. Se declara con
`--trunc-lower/--trunc-upper`, `--trunc-reason` y `--trunc-bound-type` (obligatorio) y queda en el parámetro:

```yaml
truncation: {lower: 0, upper: null, reason: "evitar tiempos negativos", bound_type: MODELLING_BOUND,
             method: FIT_THEN_TRUNCATE, provenance: {status: provided_by_client, source: "engineer:ana", ...}}
```

| `bound_type` | Ejemplo | Comprobación |
|---|---|---|
| `PHYSICAL_BOUND` | "la operación nunca dura menos de 8 s" | si hay observaciones fuera, se detiene: o el límite o los datos están mal (`DATA_OUTSIDE_PHYSICAL_BOUND` para aceptarlo) |
| `MODELLING_BOUND` | normal truncada en 0 para impedir tiempos imposibles | se avisa si deja fuera valores observados |

**Método actual: `FIT_THEN_TRUNCATE`.** Los parámetros se ajustan *sin* truncamiento y la distribución se trunca
después. El motor muestrea por rechazo dentro de la ventana (distribución condicionada) y la media pasa a ser la media
truncada, que puede alejarse de la observada: si difiere > 2 % hay que aceptarlo (`TRUNCATION_SHIFTS_MEAN`) o elegir
otra familia. **No es** un ajuste de distribución truncada (`TRUNCATED_DISTRIBUTION_FIT`, estimar los parámetros
sabiendo que la distribución está truncada): eso no está implementado y queda como capacidad futura. El truncamiento
sólo se aplica a decisiones `USE_FITTED`. Forma parte del parámetro, de su hash y de su procedencia.

## Tamaño de muestra

Son **heurísticas de SimForge** (`size_class_kind: SIMFORGE_HEURISTIC`), no fronteras universales de validez
estadística. Dan contexto y avisos; pasar de n = 29 a n = 30 no convierte los datos en "suficientes" (la
representatividad depende de cómo se midió: turnos, operarios, productos, periodo). No bloquean el análisis.

| Clase | n | Por qué |
|---|---|---|
| VERY_SMALL_SAMPLE | < 10 | con < 5 no se ajusta (2 parámetros sobre 4 puntos es degenerado). Entre 5 y 9 se muestra, pero usar FITTED exige aceptar `VERY_SMALL_SAMPLE`; EMPIRICAL sólo avisa. Mejor: valor determinista justificado y medir más |
| SMALL_SAMPLE | 10–29 | los tests apenas distinguen familias (casi todas "pasan"); decide con conocimiento del proceso y plausibilidad |
| USABLE_WITH_CAUTION | 30–99 | el cuerpo de la distribución está bien informado; P99 y superiores son extrapolación |
| LARGER_SAMPLE | ≥ 100 | ajuste y bondad de ajuste discriminan mejor; no implica datos suficientes ni representativos; P99.9 sigue extrapolado salvo con miles de datos |

Los percentiles descriptivos sólo se calculan si hay al menos una observación a cada lado (n·min(q, 1−q) ≥ 1).

## Incertidumbre: bootstrap

El DATA PROFILE incluye intervalos bootstrap percentil al 95 % (2000 remuestreos, semilla fija 12345, reproducibles)
de la media, la mediana y el P95. Un IC del P95 ancho (en el ejemplo, 37–78 s) indica que la cola está poco
informada: elegir entre familias por su P99 no tiene base. La incertidumbre de los parámetros ajustados no se
propaga todavía a la simulación (ver limitaciones).

## Dependencia e independencia

El motor muestrea cada tiempo de forma independiente. Si los datos tienen orden (marca de tiempo o, en su defecto, el
orden del archivo), se calcula la correlación lag-1 y una tendencia (Spearman). `|r1| > 2/√n` es un **cribado
heurístico**: da `POSSIBLE_SERIAL_DEPENDENCE` (nunca "confirmada") o `NO_LAG1_EVIDENCE`. Sólo mira el retardo 1: no
descarta dependencia en otros retardos (p. ej. cada 4 piezas de un bastidor) ni estacionalidad por turno. Avisa de
aprendizaje, desgaste, lotes o turnos: la distribución reproducirá la forma pero no las rachas. No se modelan series
temporales (ni ACF multi-retardo, ni ARIMA).

## Holdout temporal

`simforge data holdout <p> <dataset> [--train 0.7]` ajusta con la primera parte de las filas (orden temporal; si no
hay marca de tiempo, orden del archivo, y se dice) y compara con la parte final, que el ajuste no ha visto:
log-verosimilitud media por observación, KS contra la parte final (aquí los p-valores no son optimistas, aunque
suponen independencia), media/P50/P95 predichos frente a observados, cuántos valores finales superan el máximo de
ajuste (una empírica no los generaría) y un KS de dos muestras entre ambas partes (`POSSIBLE_DRIFT`: el proceso pudo
cambiar). 70/30 es una propuesta, no una ley. No cambia nada ni registra decisiones.

## Grupos y multimodalidad

Datos de dos operarios o dos productos mezclados producen una distribución ancha o bimodal que no describe a
ninguno. SimForge no mezcla grupos sin decisión explícita: ajusta por grupo (`--group operator=A`) o declara
`--pooled`. La comparación por grupo (medias, medianas, Kruskal-Wallis como información) ayuda a decidir; el modelo
actual no tiene mix de productos, así que un ajuste por producto sólo puede aplicarse a nodos distintos o a
escenarios distintos.

## Base, `work_units` y agregación (motor ≥ 0.5.0)

Tiempo medido por circuito, `X ~ distribución(...)`; un bastidor lleva 4 circuitos (`work_units: 4`). El nodo declara
`work_units_aggregation`:

| Política | Tiempo del bastidor | Varianza | Cuándo |
|---|---|---|---|
| `sum_iid` | T = X1 + X2 + X3 + X4 (una muestra independiente por circuito) | Var(T) = 4·Var(X) | cada circuito se trabaja por separado (caso típico de montaje por circuito) |
| `scale_sample` | T = 4·X (una muestra multiplicada) | Var(T) = 16·Var(X) | sólo si los 4 circuitos están perfectamente correlacionados (mismo operario lento/rápido para todo el bastidor, mismo ajuste de máquina) y lo sabes |
| `single_sample` | T = X | Var(T) = Var(X) | la muestra ya es el bastidor completo (dato medido por bastidor); `work_units` no multiplica |

Misma media en `sum_iid` y `scale_sample` (4·E[X]), pero `scale_sample` tiene el doble de desviación típica: más
colas, más bloqueos, menos producción. En el ejemplo end-to-end: `sum_iid` 127.2 ± 1.0 unidades/8 h frente a
124.6 ± 1.4 con `scale_sample` (k·X).

Reglas:
* Forma parte del modelo (`nodes.<id>.params.work_units_aggregation`), del `content_hash` y del YAML; cambiarla es un
  cambio semántico (nueva versión, aprobación invalidada). Con la misma semilla da exactamente los mismos números
  (`sum_iid` toma k muestras seguidas del stream del nodo).
* `sum_iid` exige un número entero de unidades.
* **No declarada** = comportamiento histórico `k·X` (los modelos existentes no cambian), con el aviso
  `WORK_UNITS_AGGREGATION_UNDECLARED` en la verificación y en los informes cuando el tiempo es aleatorio. Con un tiempo
  fijo `sum_iid` y `scale_sample` coinciden (k·c).
* `simforge data apply` exige `--aggregation` cuando el nodo tiene `work_units ≠ 1`, el tiempo decidido es aleatorio y
  el nodo no la declara. Si la base del dato coincide con la del destino (dato por circuito → tiempo por circuito)
  **propone** `sum_iid`, pero no la aplica sin confirmación.
* Una conversión de base con factor (`--factor 4`) sólo puede representar `k·X`: para una distribución hay que
  declararlo (`--conversion-mode scale_sample`); si lo que quieres es la suma de tiempos independientes, aplica el dato
  en su base a un nodo con `work_units` y `sum_iid`.

## Reproducibilidad del muestreo

* Cada réplica usa la semilla `base_seed + i` (guardadas en el run) y cada nodo tiene streams propios por
  (semilla, nodo, propósito): misma versión de modelo + mismas semillas + misma versión del motor ⇒ mismos números.
* Escenarios de un experimento usan las mismas semillas por réplica, y como los streams son por nodo, los nodos que
  no cambian reciben la misma secuencia de números (números aleatorios comunes, CRN). La sincronización es por stream
  (la k-ésima muestra del nodo X), no por entidad: es la forma estándar y suficiente para comparar escenarios.
* El empírico usa el mismo stream (`rng.choice`), y el muestreo por rechazo del truncamiento consume números del
  stream de ese nodo solamente.

## Limitaciones

* Sin parámetro de localización (familias desplazadas, p. ej. 40 s + gamma): no soportado por el motor todavía.
* Truncamiento sólo `FIT_THEN_TRUNCATE`; `TRUNCATED_DISTRIBUTION_FIT` pendiente.
* Sin bootstrap paramétrico de la bondad de ajuste (p-valores corregidos por estimación): mejora futura.
* Dependencia serial: sólo cribado lag-1.
* Sin mezclas de distribuciones ni ajuste por máxima verosimilitud con datos censurados (p. ej. tiempos cortados por
  fin de turno).
* Sin propagación de la incertidumbre de parámetros (bootstrap paramétrico → réplicas): preparado (bootstrap de
  estadísticos), no conectado a experimentos.
* Datos redondeados (pocos valores distintos) sesgan KS/AD/CvM; se avisa (`ROUNDED_DATA`, `TIES`) pero no se corrige.
