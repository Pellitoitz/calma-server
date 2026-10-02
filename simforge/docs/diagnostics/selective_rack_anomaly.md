# Diagnóstico: selectiva — 2 bastidores = 136, 3 bastidores = 123

Estado: diagnóstico realizado con el motor **0.2.0** (§1–§16, CSV en `selective_rack_anomaly/engine_0.2.0/`). Los dos defectos encontrados están **corregidos en el motor 0.3.0**: ver §17 (reanálisis, CSV en `engine_0.3.0/`).
Reproducir todo: `python scripts/diagnostics/selective_racks.py` (CSV en `docs/diagnostics/selective_rack_anomaly/engine_<versión>/`).
Tests: `tests/test_selective_rack_diagnostics.py`.

Método: OBSERVAR → LOCALIZAR → EXPLICAR → DEMOSTRAR. Toda la instrumentación es de **sólo lectura** (traza de eventos y
log de decisiones que el motor ya tenía, más dos *probes* de diagnóstico en el script). Los contrafactuales se ejecutan
sobre copias del modelo; el modelo oficial y el motor no se han tocado.

## 1. Configuración exacta

Modelo: el que usa `tests/test_nl_selective.py` (`SELECTIVE_TEXT` + `ANSWERS`), sin cambios salvo
`parameters.racks_count.value`. Volcado: `selective_rack_anomaly/model_as_generated.yaml` y `model_resolved.yaml`.

| Elemento | Valor real | ¿Coincide con la descripción? |
|---|---|---|
| Circuitos por bastidor | 4 | sí |
| Montaje | 30 s/circuito × 4 = **120 s/bastidor**, operario | sí |
| Transporte | carga 5 s + 10 m a 1,2 m/s (8,333 s) + descarga 5 s, operario, 1 bastidor/viaje, `reserve_destination=true`, `return_empty=false` | sí |
| Buffer de entrada | capacidad 3 | sí |
| Selectiva | **20 s/bastidor**, automática | sí |
| Revisión y limpieza | 15 s/circuito × 4 = **60 s/bastidor**, operario; libera el bastidor al terminar | sí |
| Distancias | montaje↔buffer 10 m; buffer↔revisión 5 m; **montaje↔revisión 15 m (CALCULADA: supuesto de layout lineal)** | la de 15 m no estaba en la descripción |
| Velocidad operario | 1,2 m/s | sí |
| Retorno de bastidor | inmediato (al terminar la revisión) | sí |
| Operario | 1, compartido por montaje, transporte y revisión; empieza en montaje | sí |
| Estrategia | `wip_target`: `protected_node=selective_soldering`, `feed_nodes=[buffer_de_entrada]`, `feeder_nodes=[manual_assembly, transport_1]`, `target=2`, `count_feeder_in_process=true`, `unblock_protected=true`, sin preemption | sí |
| Simulación | 8 h, 1 réplica, seed 12345, `dispatch_timing=end_of_timestep`, `check_invariants=true`, todos los tiempos constantes | sí |
| Versiones | engine 0.2.0 (`ENGINE_VERSION`), regla `wip_target_priority` 1.0.0, componentes 1.0.0, compilador `compiler_v2` | — |

Única diferencia relevante con la descripción: la distancia montaje↔revisión (15 m) **no la dio el usuario**; la calcula el
compilador como suma de tramos (supuesto visible en el modelo). Es la distancia que más pesa en el resultado (ver §13).

Fase 0: suite completa en verde antes de empezar (152 tests). Se detectó y corrigió un test *flaky* ajeno al motor
(`test_offline_generation_is_deterministic` comparaba timestamps de procedencia con resolución de 1 s), commit `7ff93fd`.

## 2. Resultados reproducidos (`01_reproduction_1_to_10_racks.csv`)

| Bastidores | Prod. | Selectiva util. | Selectiva STARVED (s) | Selectiva BLOCKED (s) | Operario util. | Op. idle (s) | Op. montaje (s) | Op. revisión (s) | Op. carga/descarga (s) | Op. andando (s) | Op. transportando (s) | Viajes | Distancia (m)* | Buffer medio / máx | Buffer vacío / lleno (s)* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 122 | 8,5 % | 26 360 | 0 | 91,5 % | 2 440 | 14 760 | 7 320 | 1 225 | 2 033 | 1 022 | 122 | 3 670 | 0,00 / 1 | 28 800 / 0 |
| 2 | **136** | 9,4 % | 23 077 | 3 003 | 100 % | 0 | 16 440 | 8 160 | 1 365 | **1 700** | 1 135 | 136 | 3 410 | 0,00 / 1 | 28 800 / 0 |
| 3 | **123** | 8,7 % | 4 058 | **22 243** | 100 % | 0 | 15 012 | 7 380 | 1 250 | **4 117** | 1 042 | 125 | 6 190 | 0,00 / 1 | 28 800 / 0 |
| 4 | 123 | idéntico a 3 | | | | | | | | | | | | | |

\* derivado de la traza (andando × 1,2 m/s + 10 m por viaje cargado; buffer vacío/lleno de la serie del nivel).
5–10 bastidores: 123 (idéntico a 3). Con 4 o más, `max in_use:racks = 3`: **el 4º bastidor nunca sale del pool.**

Observaciones que ya contradicen la hipótesis inicial:
- La selectiva **no es el recurso limitante** (20 s/bastidor frente a 198,3 s de trabajo puro del operario por bastidor).
- Con 3 bastidores la selectiva casi no está *starved*: está **BLOCKED** el 77 % del tiempo (no puede soltar el bastidor
  porque la revisión tiene otro bastidor esperando al operario).
- El buffer de entrada **nunca acumula** (máx. 1 durante 0 s): el bastidor pasa directo a la selectiva.

## 3. Comparación 2 vs 3

Balance del operario (idle = 0 en ambos casos):

| | trabajo (s) | andando (s) | total |
|---|---|---|---|
| 2 bastidores | 27 100,0 | 1 700,0 | 28 800 |
| 3 bastidores | 24 683,3 | 4 116,7 | 28 800 |
| diferencia | **−2 416,7** | **+2 416,7** | 0 |

El tiempo de trabajo perdido es **exactamente** el tiempo extra andando. 2 416,7 s / 198,33 s de trabajo por bastidor =
12,2 bastidores; la diferencia observada es 13: el resto es trabajo parcial en curso al final del horizonte
(27 100/198,33 = 136,6 → 136 terminados; 24 683/198,33 = 124,5 → 123 terminados).

## 4. Primer punto de divergencia causal

Hasta **t = 285,0 s (00:04:45)** ambas ejecuciones son idénticas (montaje, transporte, montaje, transporte).
En t = 285,0 s el operario acaba de descargar el 2º bastidor en el buffer (está en `buffer_de_entrada`):

| | Bastidores libres | Candidatos | feed WIP | Decisión |
|---|---|---|---|---|
| 2 bastidores | 0 (uno en revisión, otro en selectiva) | `inspection` | 0 | `inspection` (NO_FEEDER_WAITING) → anda 5 m |
| 3 bastidores | 1 → el montaje ya pide operario | `manual_assembly`, `inspection` | 0 < 2 | `manual_assembly` (WIP_BELOW_TARGET) → anda 10 m |

Con 3 bastidores, mientras el operario monta (293–413 s), la selectiva termina en 305 s y queda **BLOCKED** (la revisión
tiene un bastidor esperando al operario). En 413 s la regla 1 (PROTECTED_BLOCKED) envía al operario a revisión (15 m),
y a partir de ahí se instala el ciclo `A-I-T`.

Con 2 bastidores el montaje **no puede competir** en 285 s porque no hay bastidor libre: el operario revisa, y en
349,167 s revisa el segundo bastidor seguido (ver §10: esta segunda revisión depende del orden de eventos).

## 5. Timeline (primeros 30 min)

`03_timeline_first30min_{2,3}racks.csv`: estado del operario, ubicación, estado de la selectiva, feed WIP, objetivo, nivel del
buffer, bastidores libres / en montaje / transporte / buffer / selectiva / revisión, candidatos, tarea elegida y motivo.
Decisiones completas de las 8 h: `02_operator_decisions_{2,3}racks.csv`.
Nota: la reconstrucción del timeline redondea a 1e-3 s los tiempos de andar de la traza; aparecen filas `idle` de
0,0003 s que son artefacto del redondeo, no inactividad real (el motor mide idle = 0).

## 6. Análisis de `feeding_wip` (implementación real)

Código: `src/simforge/engine/des/dispatch.py:66-76` (`WipTargetPriority.feed_wip`) y `:88-101` (`choose`).

```
feed_wip = occupancy(buffer_de_entrada)                                  # unidades en el buffer
         + manual_assembly.state_counts()[BUSY] + [BLOCKED]              # montando, o montado esperando recogida
         + transport_1.state_counts()[BUSY] + [BLOCKED]                  # reservando destino / cargando / viajando / descargando
```

| Pregunta | Respuesta (con evidencia) |
|---|---|
| 1. ¿Cuenta el bastidor dentro de la selectiva? | **No** (no está en `feed_nodes`). |
| 2. ¿Cuenta un bastidor reservado pero no transportado? | Sí, **dos veces**: el montaje sigue BLOCKED (el bastidor conserva su sitio hasta cargarse, `nodes.py:470`) y el transporte está BLOCKED reservando destino (`nodes.py:505`) y luego BUSY cargando. Ver §12. |
| 3. ¿Montaje en curso? | Sí (BUSY). No cuenta un puesto en WAITING_RESOURCE (esperando bastidor u operario). |
| 4. ¿Transporte? | Sí, BUSY o BLOCKED; no mientras espera al operario (WAITING_RESOURCE). |
| 5. ¿Buffer? | Sí (`occupancy`). En este modelo vale siempre 0 en el instante de decidir. |
| 6. ¿Downstream? | No. |
| 7. ¿Cuándo aumenta? | Al empezar el montaje (+1); al entrar en el buffer (+1). |
| 8. ¿Cuándo disminuye? | Cuando la selectiva acepta el bastidor del buffer (−1, inmediato: la selectiva está libre); cuando el transporte termina (STARVED). |
| 9. ¿`<` o `<=`? | `feed < target` → tarea alimentadora (`dispatch.py:95`); `feed >= target` → la otra. Sin hueco ni solape. |
| 10. ¿Cuándo se reevalúa? | En cada dispatch del pool del operario: al llegar una petición, al liberarse el operario y cuando cambia un nodo vigilado (`runtime.py:70`), siempre al final del instante (`runtime.py:387-399`). Sólo se decide si hay operario libre. |
| 11. ¿Preemption? | No (`preempt_below=None`, `dispatch.py:103-105`). |
| 12. ¿Selectiva BLOCKED? | Regla 1: si hay una tarea no alimentadora esperando, va primero (`dispatch.py:92`), **sin mirar el WIP**. |
| 13–14. ¿Empate / desempate? | Dentro de cada clase, FIFO por número de petición (`dispatch.py:91`). |
| 15. ¿Puede empezar una revisión justo antes de que el WIP caiga? | Sí (NO_FEEDER_WAITING o PROTECTED_BLOCKED). |
| 16. ¿Termina antes de poder reaccionar? | Sí: sin preemption, termina los 60 s (+ andar). |

**Hecho clave** (`02_operator_decisions_*.csv`): en los instantes de decisión, `feed_wip` vale **sólo 0 o 1**
(2 bastidores: 273×0, 137×1; 3 bastidores: 126×0, 248×1). La rama `WIP_AT_OR_ABOVE_TARGET` **no se ejecuta nunca**.
Con un solo operario, en el instante de decidir hay como mucho un bastidor en montaje o transporte, y el buffer está vacío
porque la selectiva es mucho más rápida que el operario. Por eso los objetivos 2, 3 y 4 dan resultados idénticos
(contrafactual F). En esta configuración la estrategia se reduce a: *si la selectiva está bloqueada → revisión; si no, alimentar si hay algo que alimentar*.

## 7. Starvation de la selectiva (`04_selective_starvation_*.csv`, `04b_…`)

| | Periodos | Starved total | …mientras el operario montaba | revisaba | andaba | transportaba (carga+viaje+descarga) | idle |
|---|---|---|---|---|---|---|---|
| 2 bastidores | 137 | 23 077 s | 15 647 | 4 080 | 850 | 2 500 | 0 |
| 3 bastidores | 125 | 4 058 s | 228 | 0 | 1 538 | 2 292 | 0 |

La starvation **no** explica la pérdida: con 3 bastidores la selectiva está *menos* starved. Lo que cambia es que pasa a
estar BLOCKED (22 243 s). Ni la starvation ni el bloqueo de la selectiva limitan la producción, porque el recurso limitante
es el operario (idle 0 en ambos casos). Las dos son síntomas del orden de tareas del operario.

## 8. Utilización y ciclo del operario (`06_cycles.csv`)

Régimen estacionario (medido tras la primera hora; ciclos idénticos: 46 con 2 bastidores, 84 con 3):

| | Patrón | Duración | Unidades | s/unidad | Trabajo/unidad | Andar/unidad | Selectiva en el ciclo | 8 h a ese ritmo |
|---|---|---|---|---|---|---|---|---|
| 2 bastidores | `A T A T I I` | 421,667 s | 2 | 210,833 | 198,333 | **12,5 s** | busy 40 / blocked 44 / starved 337,5 | 136,6 |
| 3 bastidores | `A I T` | 231,667 s | 1 | 231,667 | 198,333 | **33,333 s** | busy 20 / blocked 180,8 / starved 30,8 | 124,3 |

Andar en cada ciclo:
- 2 bastidores (por 2 unidades): buffer→montaje 8,333 + buffer→revisión 4,167 + revisión→montaje 12,5 = **25 s**.
  Las dos revisiones van seguidas (un solo cruce montaje↔revisión por cada 2 bastidores).
- 3 bastidores (por unidad): buffer→montaje 8,333 + montaje→revisión 12,5 (PROTECTED_BLOCKED) + revisión→montaje 12,5
  (ir a cargar el transporte) = **33,333 s**. Un cruce de ida y vuelta de 15 m **por cada bastidor**.

Diferencia: 33,333 − 12,5 = **20,833 s/unidad** = exactamente 231,667 − 210,833.

## 9. Conservación de bastidores (`07_rack_conservation_*.csv`)

- La invariante del motor (`SimContext.check_carriers`, que cruza ubicaciones, entidades, transportes y pool) **se ejecuta**
  en este escenario: 820 comprobaciones con 2 bastidores y 749 con 3, sin ninguna violación (una violación aborta la ejecución).
- Comprobación independiente a partir de la traza: en cada evento de bastidor, libres + montaje + transporte + buffer +
  selectiva + revisión = total, y en cada toma de bastidor coincide con el contador `available` del propio motor.
  819 filas (2 bastidores) y 748 filas (3 bastidores): todas correctas.
- Ningún bastidor desaparece, se duplica, queda reservado ni atrapado. El 4º bastidor no se usa porque el ciclo `A-I-T` deja
  como mucho 3 bastidores en el sistema: uno en montaje, uno en selectiva (bloqueado) y uno en revisión.

## 10. Orden de eventos

Contrato documentado (`docs/benchmark_operator_logic.md:27`): *"after all events of the same timestamp… so every request
created at that instant competes"*.

**Violación demostrada** (2 bastidores, t = 349,167 s):
1. Termina la revisión del bastidor 1: se libera el operario (`nodes.py:289`) → dispatch del operario programado a final de instante.
2. Se libera el bastidor 1 (`nodes.py:291`) → dispatch del pool de bastidores programado a final de instante, **después**.
3. El bastidor 2 pasa de la selectiva a la revisión y pide el operario (prioridad normal, antes del final de instante).
4. Se ejecuta el dispatch del operario: el único candidato es `inspection` → la elige.
5. Se ejecuta el dispatch de bastidores: el bastidor 1 va al montaje, que **entonces** pide el operario (mismo instante),
   pero ya está asignado.

`09_missed_simultaneous_requests_2racks.csv`: **68 peticiones** creadas en el instante de una decisión no compitieron en
ella. Todas son del montaje, todas en la segunda `I` del ciclo `ATATII`. Con 1, 3 o 4 bastidores: 0. Con la variante de
diagnóstico "final de instante asentado" (el operario decide sólo cuando no queda ningún otro evento en ese instante): 0.

Sensibilidad (contrafactual G):

| `dispatch_timing` | 2 bastidores | 3 bastidores |
|---|---|---|
| `end_of_timestep` (actual) | **136** (`ATATII`) | 123 (`AIT`) |
| final de instante asentado (parche de diagnóstico) | **133** (`TIA`: andar 16,7 s/unidad) | 123 |
| `immediate` | **123** (`TAI`) | 123 |

**3 bastidores es robusto (123 en los tres modos). 2 bastidores depende del orden de eventos: 136 / 133 / 123.**

## 11. Contrafactuales (`05_counterfactuals.csv`, sólo diagnóstico)

| Variante | 1 | 2 | 3 | 4 | Lectura |
|---|---|---|---|---|---|
| A. WIP_TARGET_PRIORITY actual | 122 | 136 | 123 | 123 | base |
| B. FIFO | 122 | 123 | 123 | 123 | sin la regla, 2 = 3 |
| C. prioridad fija: alimentar primero (transporte > montaje > revisión) | 122 | 136 | 135 | 134 | sin la regla 1 no hay caída |
| C2. prioridad fija: revisión primero | 122 | 123 | 123 | 123 | |
| D. operario independiente para la revisión | 127 | 195 | 195 | 195 | sin compartir operario, la caída desaparece |
| E. transporte ≈ 0 (carga/descarga 0, 0,001 m) | 132 | 148 | 133 | 133 | la caída persiste: no es el transporte |
| F. objetivo WIP 1 / 2 / 3 / 4 | 122 / 122 / 122 / 122 | 123 / 136 / 136 / 136 | 123 / 123 / 123 / 123 | igual que 3 | objetivo ≥ 2 inerte (§6) |
| G. decisiones inmediatas | 122 | 123 | 123 | 123 | §10 |
| G'. final de instante asentado | 122 | 133 | 123 | 123 | §10 |
| H. andar gratis (1 000 m/s, sólo el operario) | 131 | 144 | 143 | 143 | **la caída desaparece → el mecanismo es andar** |
| I. WIP target sin regla 1 (`unblock_protected=false`) | 122 | 136 | 135 | 122 | sin la regla 1, 3 bastidores no cae; con 4 aparece otra dinámica (no analizada) |

## 12. Hipótesis falsadas

| Hipótesis | Evidencia a favor | Evidencia en contra | Test | Resultado | Conclusión |
|---|---|---|---|---|---|
| Más starvation de la selectiva con 3 | intuición | starvation 23 077 s (2) frente a 4 058 s (3) | tabla §2 / §7 | inversa | **Falsada** |
| El transporte causa la caída | el transporte es una tarea del operario | E: con transporte ≈ 0, 148 → 133 | E | la caída persiste | **Falsada** |
| `<` frente a `<=` / off-by-one en el objetivo | — | feed ∈ {0,1}; objetivos 2–4 idénticos | F, §6 | el umbral no interviene | **Falsada** |
| Pérdida o retención de bastidores | 4 = 3 bastidores | invariantes sin violaciones; el 4º sigue en el pool | §9 | conservación correcta | **Falsada** (el 4º no se usa por la dinámica, no por un fallo) |
| La regla 1 (PROTECTED_BLOCKED) fuerza un cruce por bastidor | todas las revisiones con 3 bastidores son PROTECTED_BLOCKED (123/123) | — | I, C | 3 bastidores: 123 → 135 sin la regla | **Confirmada** |
| Andar es el mecanismo de la pérdida | Δtrabajo = −Δandar exacto, idle 0 | — | H | 144 frente a 143 | **Confirmada** |
| 136 depende del orden de eventos | 68 peticiones simultáneas excluidas | — | G, G' | 136 / 133 / 123 | **Confirmada** |
| Doble conteo de `feed_wip` causa el fenómeno | existe (§13.3) | nunca coincide con una decisión (feed en decisiones ≤ 1) | probe 08 | sin efecto aquí | **Falsada como causa**; existe como defecto latente |

## 13. Causa raíz

1. **El operario es el cuello de botella** (198,3 s de trabajo por bastidor, idle 0 con 2 o más bastidores). La producción la
   fija cuánto anda por bastidor.
2. **Con 3 o más bastidores siempre hay un bastidor libre**, así que tras cada transporte el montaje compite y gana
   (`feed 0 < 2`). Mientras monta, la selectiva termina y queda BLOCKED porque la revisión tiene un bastidor esperando
   al operario. La **regla 1 (PROTECTED_BLOCKED)** lo manda a revisión (15 m) y después la alimentación lo devuelve al
   montaje para cargar el transporte (15 m). Resultado: un cruce de ida y vuelta por bastidor, ciclo `A-I-T`,
   33,3 s andando por unidad → 231,7 s/unidad → **123**.
3. **Con 2 bastidores**, después de cada transporte **no hay bastidor libre**: el montaje no puede competir y el operario
   revisa. La segunda revisión seguida sale **sólo porque la petición del montaje, creada en el mismo instante, no compite**
   (violación del contrato de final de instante). Ciclo `ATATII`, 12,5 s andando por unidad → **136**. Si se cumpliera el
   contrato, el ciclo sería `TIA` (16,7 s/unidad) → **133**.
4. El **objetivo WIP no interviene**: `feed_wip` nunca llega a 2 en un instante de decisión. La estrategia no "mantiene
   alimentada" la selectiva con un colchón (el buffer nunca se usa); actúa como "alimentar si se puede, y desbloquear
   la selectiva antes que nada", y **no tiene en cuenta el coste de andar** al elegir tarea.

Diferencia 136 → 123: **3 unidades** por el orden de eventos (136 → 133) y **10 unidades** por la dinámica de la
política (133 → 123).

## 14. Clasificación

- **A. EXPECTED_POLICY_BEHAVIOR** — con 3 bastidores (123), el resultado es consecuencia coherente de las reglas
  documentadas de WIP_TARGET_PRIORITY. Es el mismo en todos los modos de orden de eventos.
- **B. MODEL_SEMANTICS_ISSUE** — la política, tal como está configurada, no representa la intención industrial
  "mantener alimentada la selectiva con WIP objetivo": el objetivo es inalcanzable e inerte, la selectiva no es el cuello de
  botella y la regla ignora el coste de andar. **Necesita decisión del ingeniero.**
- **C. ENGINE_BUG** — `end_of_timestep` no cumple su contrato documentado: las peticiones generadas en cascada por otro
  dispatch de final de instante no compiten. Afecta al 136 (+3 unidades).
- **F. EVENT_ORDER_SENSITIVITY** — 2 bastidores: 136 / 133 / 123 según la semántica de simultaneidad.
- **D. RULE_IMPLEMENTATION_BUG (latente)** — `feed_wip` cuenta dos veces el mismo bastidor mientras espera la recogida y
  se carga (montaje BLOCKED + transporte BLOCKED/BUSY): 274 muestras con 2 bastidores, 250 con 3, siempre la misma entidad.
  **Sin efecto en este resultado**: ninguna decisión cae en esas ventanas con un solo operario. Lo tendría con varios operarios.

## 15. Correcciones propuestas (NO implementadas)

No se ha implementado ninguna: las dos cambian resultados existentes y la semántica es una decisión tuya.

1. **Orden de eventos (C/F).** Opción: decisiones de recursos "asentadas", es decir, se decide cuando no queda ningún otro
   evento en el instante, incluidas las cascadas de otros pools. El script incluye una versión de diagnóstico
   (`settled_operator_dispatch`). Efecto medido: 2 bastidores 136 → 133. Riesgos: varios pools que se esperan mutuamente
   (hay que definir un orden de asentamiento) y el impacto en la comparación con AnyLogic, cuya semántica de
   simultaneidad aún no conocemos. Test que lo vigila: `test_end_of_timestep_every_simultaneous_request_competes`
   (xfail estricto).
2. **Doble conteo (D).** Opción: contar entidades distintas (un bastidor en espera de recogida cuenta una vez, en el montaje
   o en el transporte). Requiere decidir **dónde** cuenta un bastidor montado que espera transporte: ¿es "WIP que
   alimenta"? Test: `test_feed_wip_counts_each_physical_unit_once` (xfail estricto).
3. **Semántica de la política (B).** Preguntas para ti, no para el motor:
   - ¿Debe la regla 1 (desbloquear la protegida) aplicarse cuando la protegida no es el cuello de botella?
   - ¿Debe el WIP que alimenta incluir el bastidor dentro de la selectiva o el buffer de salida?
   - ¿Debe la decisión considerar la distancia (agrupar tareas en el mismo puesto)?
   - ¿Qué objetivo tiene sentido si el buffer nunca se llena?

## 16. Riesgos restantes

- La distancia montaje↔revisión (15 m) es **CALCULADA** con un supuesto de layout lineal y es la que más pesa: el ciclo
  `A-I-T` la recorre dos veces por bastidor. Hay que medirla.
- Los valores son de prueba (no medidos). La conclusión (el resultado depende del orden de tareas del operario y del
  andar) es estructural, pero las cifras no.
- Variante I con 4 bastidores (122) muestra otra dinámica que no se ha analizado.
- Cualquier comparación con AnyLogic con 2 bastidores es sensible al orden de eventos: hay que fijar la semántica antes
  de comparar.

## Ficheros

`scripts/diagnostics/selective_racks.py` · `tests/test_selective_rack_diagnostics.py` ·
`docs/diagnostics/selective_rack_anomaly/`: `01_reproduction_1_to_10_racks.csv`, `02_operator_decisions_{2,3}racks.csv`,
`03_timeline_first30min_{2,3}racks.csv`, `04_selective_starvation_{2,3}racks.csv`, `04b_starvation_by_operator_activity.csv`,
`05_counterfactuals.csv`, `06_cycles.csv`, `07_rack_conservation_{2,3}racks.csv`, `08_feed_wip_probe_{2,3}racks.csv`,
`09_missed_simultaneous_requests_{2,3}racks.csv`, `model_as_generated.yaml`, `model_resolved.yaml`.


## 17. Corrección y reanálisis con el motor 0.3.0

Cambios (detalle en `docs/simulation_engine.md`: "Resolución de un instante", "Estados físicos de los carriers",
"WIP que alimenta", "Historial de versiones del motor"):

1. **Contrato del instante**: resolución a punto fijo, una decisión cada vez, con las consecuencias procesadas entre
   decisiones; orden técnico entre pools: carriers y después el resto. Test mínimo que fallaba con 0.2.0 y pasa con 0.3.0:
   `tests/test_engine_same_instant.py::test_cascaded_same_instant_request_competes`. Comportamiento anterior
   documentado en `tests/data/same_instant_engine_0_2_0.json`.
2. **Desempate explícito**: momento de la petición → unidad más antigua (sin unidad al final) → orden de declaración
   del nodo → secuencia. Sustituye al orden interno de SimPy.
3. **Estado físico único de carrier**, con `reserved:<transporte>` desde que el transporte toma la unidad; invariante
   unidad a unidad (tests de duplicación, desaparición, sin propietario y concesión no recogida).
4. **`feed_wip` cuenta unidades distintas** (misma inclusión que el contrato de 0.2.0, sin doble conteo).

### Antes / después (`engine_0.3.0/10_before_after_engine_0.2.0_vs_0.3.0.csv`)

Medido ejecutando el mismo script sobre el commit `0805c75` (0.2.0) y sobre 0.3.0
(`scripts/diagnostics/engine_before_after.py`):

| Modelo | 0.2.0 | 0.3.0 | Diferencia | Causa (atribución medida) |
|---|---|---|---|---|
| 01–04, MVP generado | 59 / 359 / 1 889,05 / 477,5 / 359 | igual | 0 | — |
| `05_selective_soldering` | 132 | 130 | −2 | contrato del instante: 132 peticiones de montaje en cascada no competían en 0.2.0 (0 en 0.3.0) |
| selectiva (test), 1 bastidor | 122 | 122 | 0 | — |
| selectiva (test), 2 bastidores | 136 | **133** | −3 | contrato del instante (68 peticiones excluidas en 0.2.0) |
| selectiva (test), 3–10 bastidores | 123 | 123 | 0 | — |
| benchmark sintético (con reserva), 3/4/5/6–10 | 248 / 227 / 219 / 218 | 234 / 233 / 222 / 217–216 | −14 / +6 / +3 / −1…−2 | **sólo el desempate** (ver abajo) |
| benchmark sintético (sin reserva), 3–10 | DEADLOCK | 234 / 233 / … | — | el interbloqueo de 0.2.0 dependía del orden interno de SimPy |

Atribución (`11_attribution.txt`): revertir los tres mecanismos sobre 0.3.0 reproduce **exactamente** todos los
valores de 0.2.0. `05` y la selectiva de 2 bastidores cambian sólo por el contrato del instante; el benchmark sintético
cambia sólo por el desempate. La deduplicación de `feed_wip` no cambia ningún modelo.

Censo de empates (`12_tie_census.txt`): **0 empates** en 01–05, en el MVP y en la selectiva de test (1–4 bastidores).
En el benchmark sintético, con 3 o 4 bastidores, unas 236 decisiones del operario se resuelven por desempate; ~234 son
`transport_to_review` (lleva un bastidor cargado) frente a `rack_return` (retorno de bastidor vacío, sin unidad).
0.2.0 elegía siempre `rack_return` (248 de 248, por orden interno de SimPy); 0.3.0 elige `transport_to_review`
(criterio "sin unidad al final"). **Esto es de facto una prioridad del operario: queda pendiente de decisión.**

### Curva 1–10 con 0.3.0 (`engine_0.3.0/01_…`, `06_cycles.csv`)

| Bastidores | Producción | Ciclo (detectado) | Andar/unidad | Inactivo/unidad | s/unidad |
|---|---|---|---|---|---|
| 1 | 122 | `ATI` | 16,7 s | 20 s (espera a la selectiva) | 235,0 |
| 2 | **133** | `ATI` | 16,7 s | 0 | 215,0 |
| 3–10 | 123 | `AIT` | 33,3 s | 0 | 231,7 |

**El comportamiento no monótono sigue existiendo (133 → 123)** y ahora se explica completamente por la política:
- No quedan peticiones excluidas del instante: 0 con 1–10 bastidores.
- No hay empates en este modelo.
- El balance es exacto: trabajo + andar + inactivo = horizonte.
- Con 3 o más bastidores, la regla 1 (PROTECTED_BLOCKED) fuerza un cruce de ida y vuelta montaje↔revisión por
  bastidor. Sin la regla 1 da 132; con FIFO, 123 plano; con el andar gratis, 144 frente a 143.
- `immediate` da 123 con 2 bastidores. Es otra semántica documentada (el primero que llega se decide primero),
  no un defecto.

Clasificación con 0.3.0: **EXPECTED_POLICY_BEHAVIOR** (el resultado sigue el contrato de WIP_TARGET_PRIORITY) más
**MODEL_SEMANTICS_ISSUE** (si esa política representa la intención industrial sigue siendo una decisión del
ingeniero: §15.3). Ya no es ENGINE_BUG ni RULE_IMPLEMENTATION_BUG. La diferencia `end_of_timestep` frente a
`immediate` (133 frente a 123) es la sensibilidad documentada entre los dos modos (EVENT_ORDER_SENSITIVITY entre
modos, no dentro del modo por defecto).
