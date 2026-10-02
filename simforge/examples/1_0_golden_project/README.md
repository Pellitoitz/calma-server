# Golden project (SimForge 1.0)

| Campo | Contenido |
|---|---|
| **Propósito** | recorrer el flujo canónico de 1.0: proyecto → MISSING → verificar → aprobar → run → escenario → economics → comparar → informe/manifiesto → exportar → reabrir → reproducir. Es el caso del [tutorial](../../docs/user/tutorial_end_to_end.md) y de `tests/test_release_golden_workflow.py` |
| **Proceso** | llegadas (exponencial, 50 s) → montaje manual (triangular 30/38/50 s, 1 operario) → buffer (5) → test (46 s) → terminado; 8 h, warm-up 30 min, 5 réplicas, semillas 1000…1004 |
| **Ficheros** | `model_with_missing.yaml` (paso 1: tiempo de test MISSING) · `model.yaml` (baseline) · `alternative.yaml` (test de 40 s, 21 €/h, CAPEX 24 000 €) · `expected.json` (resultados del motor) |
| **Capacidades** | fuente estocástica, recurso, buffer, MISSING, aprobación, réplicas con semillas, escenario, economics (labor PAID / CALENDAR_WINDOW, máquina por hora de proceso, energía con potencia declarada, material, CAPEX explícito, anualización), comparación emparejada, informe, manifiesto, export/import |
| **Resultado esperado** | baseline: 532 unidades, ≈70,9 units/h, test ≈91 % (cuello de botella). Alternativa: 533,8 unidades. Ahorro por run −8,84 €, payback `NOT_REACHED`: la demanda limita, así que un test más rápido apenas aporta |
| **Limitaciones** | caso didáctico pequeño; precios y anualización son valores ASSUMED (no reales); un solo recurso |
| **Estado de validación** | SYNTHETICALLY_VALIDATED. Es una referencia de regresión del software, **no** la validación de ninguna línea real |
