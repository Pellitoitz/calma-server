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
