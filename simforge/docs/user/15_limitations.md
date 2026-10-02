# 15. Limitaciones

La lista completa y clasificada (BLOCKER / MAJOR / MINOR / DEFERRED) está en
[`KNOWN_LIMITATIONS.md`](../../KNOWN_LIMITATIONS.md). Lo esencial para un usuario:

- **Validación.** Ninguna capacidad está validada con datos reales. Los resultados describen el **modelo**; la
  validación contra la planta es responsabilidad del ingeniero.
- **Optimización y decisiones.** SimForge no optimiza, no ordena alternativas, no recomienda y no toma decisiones.
- **Economics.** No incluye NPV/IRR, divisas, impuestos, amortización, overhead, reparto de costes compartidos, lost
  revenue ni una física de energía (sólo potencia declarada).
- **Uso local.** Un solo usuario; sin cloud, MES/ERP ni tiempo real.
- **Informes.** HTML/Markdown/CSV; para PDF, imprimir el HTML.
- **Python.** Sólo 3.11.
