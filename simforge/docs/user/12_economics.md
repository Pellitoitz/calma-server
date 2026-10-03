# 12. Economics

Es una capa **posterior al run**: valora un run guardado con supuestos explícitos, sin volver a simular y sin tocar el
DES.

```bash
simforge economics show modelo.yaml                       # supuestos, economic_hash, avisos (ASSUMED, MISSING...)
simforge project evaluate <slug> <run_id> --from-run      # usa el bloque economics de la versión del run
simforge project evaluate <slug> <run_id>                 # usa el de la versión ACTUAL (como la UI); siempre se imprime cuál
simforge project compare <slug> <eval_base> <eval_alt>    # deltas, ahorro, payback simple, retorno (hechos)
```

## Reglas

- **Moneda.** Una por evaluación; sin conversión de divisas.
- **MISSING ≠ 0.** Un CAPEX no declarado no es 0: declara una partida explícita de 0 si no hay inversión.
- **`evaluated_total_cost`.** Suma de las líneas INCLUDED de las categorías evaluadas. **No** es un coste completo de
  producción.
- **`COMPLETE_FOR_REQUESTED_SCOPE`.** Sólo significa que las categorías pedidas están completas.
- **Anualización.** Sólo con `runs_per_year` explícito; el CAPEX nunca se anualiza.
- **Payback.** `NOT_REACHED` si no hay ahorro y `UNDEFINED_METRIC` si faltan datos; nunca es negativo.
- **Recomendación.** SimForge no ordena alternativas ni recomienda: el ingeniero decide.

## Estado

- SYNTHETICALLY_VALIDATED.
- Validación con datos reales: protocolo listo (`docs/validation/economic_real_data_validation.md`), **NOT_EXECUTED**.

Detalle: `docs/economics_and_decision_support.md`.

## Editor de supuestos económicos (1.1-E, línea de desarrollo)

> Línea de desarrollo 1.1, no parte de 1.0.0-rc1. Estado: CODE_COMPLETE + SYNTHETICALLY_VALIDATED.

En la pestaña **Economics**, sección *Edit economic assumptions*, se puede crear y editar el bloque `economics` sin
YAML:

- moneda y alcance;
- líneas de labor, machine, material, scrap, maintenance, downtime, revenue y capex;
- anualización (`runs_per_year`).

Reglas:

- **Bases.** Sólo se ofrecen las bases que el verificador de economics 0.9 ya admite para cada categoría.
  `PER_UNIT` y `FIXED_PER_PERIOD` (declaradas pero no calculables) se rechazan. No hay bases ni fórmulas nuevas.
- **Valores.** Un valor vacío es **MISSING**, nunca 0. Un 0 escrito explícitamente es un dato. Un CAPEX o una
  anualización no declarados siguen sin declararse.
- **Procedencia, referencia y fecha efectiva.** Se conservan tal como se declaran. Un valor ASSUMED sigue siendo
  ASSUMED.
- **Versiones.** Cada guardado crea una **versión nueva** del modelo (con su versión padre). La versión anterior no
  cambia.
- **Identidad física.** El hash físico del modelo es idéntico antes y después. Por tanto, la identidad de caché del
  DES y la aprobación física no cambian. El servicio rechaza cualquier edición que alteraría la física. Sólo cambia el
  `economic_hash`.
- **Evaluar.** *Evaluar (sin re-simular)* aplica los supuestos actuales a un run ya guardado con el servicio de
  economics 0.9. No se ejecuta el DES.
- **Valores que el editor no puede editar.** Si una línea guardada tiene una base que el editor no ofrece para su categoría (por ejemplo `PER_UNIT`), se muestra **solo lectura** con un aviso. Se conserva sin cambios: nunca se cambia de base en silencio. Puedes quitarla explícitamente o editar el YAML.
- **Avisos.** Los del verificador (doble conteo, bases solapadas, REQUIRES_ENGINEER_DECISION) se muestran tal cual.
  El editor no los resuelve.
