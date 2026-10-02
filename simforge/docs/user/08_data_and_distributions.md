# 8. Datos y distribuciones

Flujo sin IA y determinista (requiere el extra `data`):

**importar CSV/XLSX → validar fila a fila → estadística → ajuste → decisión del ingeniero → aplicar**

```bash
simforge data import <slug> tiempos.xlsx ...      # simforge data --help para todas las opciones
simforge data inspect <slug> <dataset>
simforge data fit <slug> <dataset> ...
simforge data decide <slug> ...                   # DETERMINISTIC / EMPIRICAL / FITTED / no aplicar / rechazar
simforge data apply <slug> ...                    # versión nueva con procedencia `data` y aprobación invalidada
```

- Nada se borra ni se rellena: los outliers son **candidatos** y la decisión es del ingeniero.
- La procedencia queda en el parámetro (dataset, versión, hash, columna, decisión, ajuste, quién y cuándo) y en el
  manifiesto.
- Distribuciones: constant, uniform, triangular, normal, lognormal, exponential, gamma, weibull y empírica, con
  truncamiento explícito.
- Una muestra negativa es un error: no se vuelve a muestrear en silencio.

Detalle: `docs/data_import.md` y `docs/distribution_fitting.md`.
