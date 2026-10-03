# 16. Escenarios y comparación de runs (1.1-A, línea de desarrollo)

> **Línea de desarrollo 1.1, no parte de 1.0.0-rc1.** Estado: CODE_COMPLETE + SYNTHETICALLY_VALIDATED (tests
> sintéticos). No hay validación con datos ni uso reales.

El flujo es:

**baseline → clonar → modificar → verificar → aprobar → ejecutar → comparar**

SimForge **describe** las diferencias entre dos runs guardados. No elige escenario, no ordena y no recomienda: el
ingeniero decide.

## Flujo en la UI (pestaña **Project**, sección *Scenarios & run comparison*)

1. **Baseline.** Si el proyecto aún no tiene baseline, elige la versión y pulsa *SET BASELINE*.
2. **Clonar.** Indica el nombre del escenario, la versión de partida (por defecto, el baseline) y los cambios
   (parámetro + nuevo valor). Pulsa *CLONE SCENARIO*.
   - Se crea una versión nueva e inmutable con `parent` = versión de partida y etiqueta `scenario:<nombre>`, y pasa
     a ser la versión actual.
   - El baseline no se modifica.
3. **Modificar.** En *Modify this scenario*, cada cambio crea otra versión, cuyo `parent` es la anterior del
   escenario. El nombre del escenario apunta a la versión más reciente.
4. **Verificar.** Se muestra el resumen de verificación y el diff frente al baseline.
5. **Aprobar.** Es la misma aprobación de 1.0: queda ligada al hash de contenido. Un escenario con cambios reales
   **no** hereda la aprobación del baseline. Al aprobar se guarda una versión aprobada y el escenario pasa a apuntar
   a ella.
6. **Ejecutar.** *RUN SCENARIO* aplica la misma puerta que la pestaña Run. Si las reglas de 1.0 exigen aprobación
   (modelo generado por IA aún no aprobado, o valores derivados de datos importados), el botón queda desactivado
   hasta que se aprueba.
7. **Comparar.** Se eligen el run baseline y el run alternativo. Por defecto se proponen el último run de la versión
   baseline y el último run del escenario seleccionado. Cualquier par de runs guardados se puede comparar.

## Flujo en la CLI

```bash
simforge project baseline linea                                   # versión actual -> baseline
simforge project scenario-clone linea dos_operarios --set resources.operator_1.quantity=2
simforge project scenario-set linea dos_operarios --set nodes.buffer_1.params.capacity=10
simforge project scenarios linea                                  # baseline, escenarios, versión, padre, aprobación
simforge project approve linea --by ana                           # si las reglas de aprobación lo exigen
simforge project run linea
simforge project runs linea
simforge project compare-runs linea <run_baseline> <run_alternativo>          # cabecera + utilizaciones
simforge project compare-runs linea <run_b> <run_a> --all                     # todas las métricas
simforge project compare-runs linea <run_b> <run_a> --metric avg_wip --json   # salida estable en JSON
```

- `--set` admite `ruta=valor`. El valor se interpreta como JSON cuando es posible (`2`, `1.5`, `null`,
  `{"dist": ...}`); si no, como texto. Una ruta o un valor no válidos se rechazan y no se guarda nada.
- Códigos de salida de `compare-runs`:
  - `0`: COMPARABLE o COMPARABLE_WITH_WARNINGS;
  - `1`: NOT_COMPARABLE o error (por ejemplo, `PERSISTENCE_ERROR: No existe la ejecución '...'`);
  - `2`: uso incorrecto.
- `simforge project scenario <slug> <nombre> fichero.yaml` (1.0) sigue funcionando igual.

## Convención y lectura de la comparación

- **delta = alternativa − baseline**, para **todas** las métricas. No se invierte el signo según el KPI. Un delta
  positivo de lead time significa que la alternativa tiene más lead time; no es «mejor» ni «peor».
- `sign` (POSITIVE / NEGATIVE / ZERO) es el signo matemático del delta medio. No es un juicio.
- Se muestran valores absolutos y deltas absolutos, en la unidad de la métrica. **No hay porcentajes.**
- **PAIRED** solo si hay evidencia de números aleatorios comunes. Se exige todo lo siguiente:
  - mismo motor y versión de motor;
  - mismas semillas, en el mismo orden (por tanto, mismo número de réplicas);
  - mismo horizonte y warm-up.

  En ese caso se resumen los deltas por réplica `delta_i = alt_i − base_i` (media, desviación típica e IC95 con t
  de Student). Tener el mismo número de réplicas **no** basta.
- **UNPAIRED:** diferencia de medias, **sin** intervalo. No se introduce ningún método estadístico nuevo.
- **NOT_DETERMINABLE:** los runs no guardan semillas coherentes con sus réplicas. Se muestra la diferencia de
  medias, con un aviso.
- **n = 1:** sin desviación típica ni IC (nunca se inventan).
- **Ausente ≠ cero:**
  - una métrica que no existe en uno de los runs es `NOT_AVAILABLE`;
  - una métrica indefinida (NaN) en alguna réplica es `NOT_COMPARABLE`.

  En ninguno de los dos casos se calcula un delta.

### Comprobaciones de comparabilidad

| Nivel | Comprobación | Efecto |
|---|---|---|
| HARD_INCOMPATIBILITY | horizonte o warm-up distintos (ventana medida distinta); un run sin réplicas | estado NOT_COMPARABLE: se ven los valores absolutos, pero **ningún** delta. Sin normalización por hora |
| WARNING | versión de motor distinta; versiones de componentes distintas; calendarios distintos; demanda (fuentes) distinta; mix de producto distinto; run de un modelo no guardado como versión (sin linaje); emparejamiento NOT_DETERMINABLE | se compara y se avisa |
| INFORMATIONAL | mismo run; mismo modelo (las diferencias vienen solo de semillas o réplicas); modelos distintos (es lo que se compara); comparación no emparejada | se informa |

Las diferencias intencionadas del escenario (por ejemplo, otro calendario) **no** bloquean la comparación: se
marcan.

### Trazabilidad

Cada lado de la comparación muestra:

- run, versión del modelo y escenario o baseline;
- hash físico;
- motor y versión;
- horizonte, warm-up, réplicas y semillas;
- hash de calendarios.

La comparación se calcula **bajo demanda** a partir de los runs guardados:

- no se guarda en la base de datos (sin migración);
- no simula y no modifica runs, trazas, semillas ni hashes;
- se puede exportar como JSON desde la UI o con `--json`.

## Experimentos: deltas frente a un escenario de referencia

En la pestaña **Experiments**, y con `simforge project experiment` (ver guía 7), cada escenario del experimento se
compara con un escenario de referencia elegido por el ingeniero (por defecto, el #0):

- todos usan las mismas semillas, así que la comparación es PAIRED;
- se mantiene el orden del experimento; no hay ranking.

## Limitaciones (1.1-A)

- No se comparan runs con distinto horizonte o warm-up (HARD_INCOMPATIBILITY). Un escenario que cambia el horizonte
  solo se puede comparar con un baseline del mismo horizonte. 1.1 no introduce normalización por hora.
- El emparejamiento se decide a partir de las semillas (contrato de 1.0: réplica i = `base_seed + i`). SimForge no
  afirma nada sobre la sincronización interna de los flujos aleatorios cuando cambia la estructura del modelo.
- La modificación de escenarios en la UI y la CLI se limita a rutas de parámetros existentes, igual que en
  experimentos. Los cambios estructurales (nodos y conexiones) llegan en 1.1-B.
- La comparación no se guarda. El informe de comparación es 1.1-D.
- Los deltas de experimento son frente a un escenario del propio experimento, no frente al run baseline del proyecto.
  El candidato C09 completo sigue diferido.
- `project runs` ordena por fecha con resolución de segundos: dos runs del mismo segundo pueden aparecer en
  cualquier orden. La UI propone los runs por defecto según la versión, no según ese orden.
