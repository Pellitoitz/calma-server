# Ajuste de distribuciones: cómo leerlo y cómo decidir

> SimForge propone **candidatos** con evidencia. La distribución que entra en el modelo la elige el ingeniero.
> No hay "BEST DISTRIBUTION = X" ni "p > 0.05 = correcta".

Importación, validación y aplicación al modelo: [`data_import.md`](data_import.md).

## Las opciones

| Opción | Qué simula | Cuándo tiene sentido |
|---|---|---|
| **DETERMINISTIC** (MEAN / MEDIAN / ENGINEER_VALUE) | siempre el mismo tiempo | variabilidad despreciable frente al resto (caso A: N(120, 0.8) s, CV < 1 %), o cuando sólo interesa capacidad media. Ojo: quitar variabilidad sobreestima el throughput en líneas con colas o recursos compartidos |
| **EMPIRICAL** | re-muestrea los valores medidos, con la misma probabilidad cada uno | muchos datos (≥ 100), forma rara (bimodal, colas irregulares) o ninguna familia encaja. No genera nada fuera del rango medido |
| **FITTED** (normal, lognormal, exponential, gamma, weibull, triangular, uniform) | una familia paramétrica | forma razonable y conocida del proceso; suaviza y extrapola algo la cola (puede ser bueno o malo: mira la plausibilidad) |
| KEEP_WITHOUT_APPLYING | nada | datos útiles pero incompletos (falta un turno, un producto) |
| REJECT | nada | estudio mal hecho o no representativo |

## Cómo se ajusta

* Estimación por máxima verosimilitud con `scipy.stats` (librería madura; nada implementado a mano), con
  localización fija en 0 para lognormal, exponencial, gamma y weibull (el motor no tiene desplazamiento).
* Uniforme y triangular: soporte = rango observado ampliado (máx − mín)/(n − 1) a cada lado (sin bajar de 0);
  la moda de la triangular por momentos (3·media − mín − máx).
* Se ajusta sobre las filas **en uso** (VALID, WARNING, revisadas aceptadas, no excluidas) del subconjunto elegido.
  El informe registra n usadas, excluidas, grupo, `fit_id` (determinista: mismo dato y estado → mismo id) y el hash
  del estado de los datos. Si las exclusiones cambian, el ajuste anterior deja de servir para decidir.
* Una familia que no se puede ajustar aparece como `FIT_FAILED` con el motivo; con valores 0 las familias de soporte
  (0, ∞) aparecen como `NOT_APPLICABLE`. No se ocultan.

## Cómo leer el ranking

```
#  distribution status                     AIC   ΔAIC      BIC     KS      AD     CvM       P50     P95     P99   P99.9  warnings
1  lognormal    OK                       625.8   0.00    630.8  0.111    1.34   0.188     29.64   48.83   60.04    75.7  -
2  gamma        OK                       634.8   8.93    639.7  0.131    1.83   0.245     30.15   48.84   58.36   70.33  -
4  normal       REQUIRES_TRUNCATION      669.6  43.77    674.5  0.185    4.45   0.657     31.17   50.25   58.15   67.01  NEGATIVE_SUPPORT,...
   OBSERVED                                                                                31.2   41.42       —       —
```

| Columna | Lectura |
|---|---|
| **AIC / ΔAIC** | criterio de ordenación (menor = mejor compromiso ajuste/nº de parámetros). **ΔAIC ≤ 2: prácticamente equivalentes**; 2–10: algo de evidencia a favor del primero; > 10: clara |
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
| BOUNDED_SUPPORT | info | uniforme/triangular: nunca supera el rango observado ampliado |

Para usar un candidato con avisos hay que aceptarlos uno a uno (`--accept CÓDIGO`), y quedan registrados en la
decisión. Los CRÍTICOS no se sugieren nunca.

## Truncamiento

Nunca automático. Si decides truncar (típicamente una normal en 0), lo declaras con límites y motivo:
`--trunc-lower 0 --trunc-reason "tiempos no negativos"`. El motor muestrea por rechazo dentro de la ventana (la
distribución resultante es la condicionada, no una normal con los negativos puestos a 0) y la media del modelo pasa a
ser la media truncada. El truncamiento forma parte del parámetro, de su hash y de su procedencia. No existe
`max(0, x)` en ninguna parte del motor.

## Tamaño de muestra

Criterios usados (avisos, no leyes universales; no bloquean el análisis):

| Clase | n | Por qué |
|---|---|---|
| VERY_SMALL_SAMPLE | < 10 | con < 5 no se ajusta (2 parámetros sobre 4 puntos es degenerado). Entre 5 y 9 se muestra, pero usar FITTED o EMPIRICAL exige aceptar `VERY_SMALL_SAMPLE`. Mejor: valor determinista justificado y medir más |
| SMALL_SAMPLE | 10–29 | los tests apenas distinguen familias (casi todas "pasan"); decide con conocimiento del proceso y plausibilidad |
| USABLE_WITH_CAUTION | 30–99 | el cuerpo de la distribución está bien informado; P99 y superiores son extrapolación |
| LARGER_SAMPLE | ≥ 100 | ajuste y bondad de ajuste informativos; P99.9 sigue extrapolado salvo con miles de datos |

Los percentiles descriptivos sólo se calculan si hay al menos una observación a cada lado (n·min(q, 1−q) ≥ 1).

## Incertidumbre: bootstrap

El DATA PROFILE incluye intervalos bootstrap percentil al 95 % (2000 remuestreos, semilla fija 12345, reproducibles)
de la media, la mediana y el P95. Un IC del P95 ancho (en el ejemplo, 37–78 s) indica que la cola está poco
informada: elegir entre familias por su P99 no tiene base. La incertidumbre de los parámetros ajustados no se
propaga todavía a la simulación (ver limitaciones).

## Dependencia e independencia

El motor muestrea cada tiempo de forma independiente. Si los datos tienen orden (marca de tiempo o, en su defecto, el
orden del archivo), se calcula la correlación lag-1 y una tendencia (Spearman). `POSSIBLE_SERIAL_DEPENDENCE`
(|r1| > 2/√n) avisa de aprendizaje, desgaste, lotes o turnos: la distribución reproducirá la forma pero no las rachas.
No se modelan series temporales.

## Grupos y multimodalidad

Datos de dos operarios o dos productos mezclados producen una distribución ancha o bimodal que no describe a
ninguno. SimForge no mezcla grupos sin decisión explícita: ajusta por grupo (`--group operator=A`) o declara
`--pooled`. La comparación por grupo (medias, medianas, Kruskal-Wallis como información) ayuda a decidir; el modelo
actual no tiene mix de productos, así que un ajuste por producto sólo puede aplicarse a nodos distintos o a
escenarios distintos.

## Base y escalado

Una distribución por circuito aplicada a un nodo con `work_units: 4` simula `4 · X` (una muestra multiplicada), no
la suma de 4 tiempos independientes: misma media, desviación 4× en lugar de 2×. Lo mismo ocurre con una conversión
explícita de base (`--factor 4`). SimForge exige reconocerlo (`WORK_UNITS_SCALING`, `SCALING_IS_NOT_SUM`). Si la
variabilidad por bastidor importa, mide por bastidor.

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
* Sin mezclas de distribuciones ni ajuste por máxima verosimilitud con datos censurados (p. ej. tiempos cortados por
  fin de turno).
* Sin propagación de la incertidumbre de parámetros (bootstrap paramétrico → réplicas): preparado (bootstrap de
  estadísticos), no conectado a experimentos.
* Datos redondeados (pocos valores distintos) sesgan KS/AD/CvM; se avisa (`ROUNDED_DATA`, `TIES`) pero no se corrige.
