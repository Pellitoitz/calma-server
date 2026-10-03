# 7. Experimentos

Un experimento ejecuta una rejilla de factores sobre el modelo, con **las mismas semillas** en cada escenario (números
aleatorios comunes):

```bash
simforge experiment modelo.yaml                                  # el experimento declarado en el modelo
simforge experiment modelo.yaml --factor resources.operator_1.quantity=1,2,3 --csv resultados.csv
```

- Los experimentos de un proyecto (pestaña **Experiments**) quedan ligados a la versión del modelo base que usaron.
- SimForge **no** busca el óptimo ni ordena los escenarios: muestra cada uno con sus intervalos. Revisa los IC antes de
  sacar conclusiones.
- Comparar baseline y alternativa en dinero se hace en la guía 12.

### Experimentos sobre un proyecto y deltas frente a una referencia (1.1-A, línea de desarrollo)

```bash
simforge project experiment linea --factor resources.operator_1.quantity=1,2,3 --reps 5 --reference 0
```

- Se ejecuta sobre el modelo **actual** del proyecto, con la misma puerta de aprobación que `project run`, y queda
  guardado en el proyecto.
- Cada escenario muestra su valor y su **delta frente al escenario de referencia**: `escenario − referencia`,
  emparejado porque todos usan las mismas semillas.
- Se mantiene el orden del experimento: no hay ranking ni «mejor escenario».
- En la UI (pestaña Experiments), el selector *Reference scenario for deltas* elige la referencia.
- La comparación entre dos runs cualesquiera, la convención de deltas y los estados de comparabilidad se describen en
  la guía 16.
