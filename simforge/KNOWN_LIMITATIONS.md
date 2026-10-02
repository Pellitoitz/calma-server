# Known limitations — SimForge 1.0 (release readiness)

Clasificación:

| Clase | Significado |
|---|---|
| **BLOCKER** | impide la release |
| **MAJOR** | limita usos importantes; conocida y aceptada para 1.0 |
| **MINOR** | molestia o alcance reducido |
| **DEFERRED** | planificada después de 1.0 |

Una limitación conocida no es un bug. **No hay ningún BLOCKER abierto.**

| Área | Limitación | Clase |
|---|---|---|
| Validación | Ninguna capacidad está REAL_DATA_VALIDATED. Todas están SYNTHETICALLY_VALIDATED. Protocolo de calendarios READY; protocolo económico READY_FOR_REAL_ECONOMIC_VALIDATION, **NOT_EXECUTED** | MAJOR (por diseño: la madurez del software y la validación industrial van separadas) |
| Validación | El benchmark contra AnyLogic está BLOCKED hasta recibir los datos de referencia | MINOR |
| Datos | Sin el extra `data`, la media de una distribución truncada se estima con Monte Carlo determinista, en lugar de con scipy (sólo afecta a valores derivados como el rendimiento OEE, no al muestreo) | MINOR |
| Datos | El ajuste de distribuciones truncadas a datos truncados (TRUNCATED_DISTRIBUTION_FIT) no está implementado | MINOR |
| Calendarios | Sólo patrón semanal y excepciones por fecha. La validación real del protocolo no se ha ejecutado | MINOR |
| Setups | Las semánticas de 0.7 están cerradas: el estado cambia al completar el setup y no hay optimización de secuencia | MINOR |
| Mantenimiento | La reparación correctiva sólo es RESET; no hay mantenimiento predictivo | MINOR |
| Economics | Sin NPV/IRR, FX, impuestos, amortización, financiación, overhead, reparto de costes compartidos, lost revenue ni coste de oportunidad. Sin scrap por producto. La energía sale sólo de la potencia declarada | MAJOR (fuera de alcance de 1.0) |
| Economics | Un solo periodo por evaluación; la incertidumbre es sólo la derivada de la simulación (no la de los precios) | MINOR |
| Economics | `simforge economics validate-real` necesita el checkout del código (no funciona desde un paquete instalado) | MINOR |
| Persistencia | Sólo se guardan los runs COMPLETED; los fallidos o interrumpidos quedan en el historial (`run_failed`, `run_interrupted`), sin una fila de estado | DEFERRED |
| Persistencia | Un solo usuario y local; sin bloqueo de concurrencia entre dos UIs abiertas sobre el mismo proyecto | MINOR |
| Portabilidad | La librería de componentes del usuario (`~/.simforge/library`) no viaja dentro del `.simproject`: hay que copiarla a mano. El manifiesto revela las diferencias | MINOR |
| UI | Streamlit, un solo usuario. Sin porcentaje de progreso (sólo RUNNING / COMPLETED / FAILED). Textos mezclados en español e inglés | MINOR |
| Informes | HTML / Markdown / CSV; sin PDF ni PowerPoint nativos | MINOR |
| IA | El asistente (NL → modelo) es EXPERIMENTAL. Funciona sin conexión con reglas. Con `ANTHROPIC_API_KEY`, el texto del asistente se envía al proveedor (la UI lo avisa). Su salida siempre exige aprobación | MINOR |
| Plataforma | Sólo Python 3.11. Probado en Linux; otros sistemas no se han probado en esta etapa | MINOR |
| CI | No hay CI remota; la puerta de release es `scripts/release/check_release.py` en local | DEFERRED |
| Rendimiento | Línea base sólo indicativa (`docs/release/performance_baseline.json`), sin afirmaciones comerciales; sin ejecución distribuida | MINOR |
