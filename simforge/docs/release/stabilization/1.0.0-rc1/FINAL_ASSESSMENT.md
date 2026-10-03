# Evaluación final — estabilización 1.0.0-rc1

**Estado: PENDING.** Se completa al final de la ventana, con evidencia; no antes.

Estados posibles:

- `RC1_STABILIZATION_IN_PROGRESS`
- `RC1_STABILIZATION_COMPLETE`
- `RC2_REQUIRED`
- `FINAL_PROMOTION_REVIEW_READY`
- `NOT_READY`

Esta evaluación **no promociona**: crear `v1.0.0`, cambiar la versión a 1.0.0 o crear una GitHub Release requiere una
nueva autorización explícita.

## Criterios de promoción

Los criterios son los de `../../1.0_stabilization_policy.md` § 4. No se modifican para pasar.

| # | Criterio | PASS/FAIL | Evidencia |
|---|---|---|---|
| 1 | 0 S0 abiertos | PENDING | |
| 2 | 0 S1 abiertos | PENDING | |
| 3 | 0 S2 incompatibles con la final | PENDING | |
| 4 | S3 restantes documentados y aceptados | PENDING | |
| 5 | FREEZE intacto | PENDING | |
| 6 | Regresión 01–05 exactamente idéntica | PENDING | |
| 7 | Suite completa pasando | PENDING | |
| 8 | Tests de release pasando | PENDING | |
| 9 | Ruff limpio | PENDING | |
| 10 | Instalación limpia pasando | PENDING | |
| 11 | Workflow golden reproducible | PENDING | |
| 12 | Export/import reproducible | PENDING | |
| 13 | Sin defectos de linaje o reproducibilidad incompatibles | PENDING | |
| 14 | Rendimiento dentro del criterio (≤ 10×) | PENDING | |
| 15 | KNOWN_LIMITATIONS.md actualizado | PENDING | |
| 16 | Matriz de capacidades coherente | PENDING | |
| 17 | CHANGELOG coherente | PENDING | |
| 18 | Release notes coherentes | PENDING | |
| 19 | Uso real suficiente (≥ 8 sesiones, cobertura colectiva de SESSION_PLAN.md) | PENDING | |
| 20 | `check_release.py` en PASS sobre el commit exacto candidato con el árbol limpio | PENDING | |

## Resumen (a completar)

- Sesiones: — (PASS — / PASS_WITH_FRICTION — / FAIL —)
- Incidencias abiertas: —
- Limitaciones aceptadas: —
- ¿RC2 requerida?: —
- ¿Lista para la revisión de promoción final?: —
- Validación industrial: sin cambios salvo que un protocolo formal lo establezca (evidencia separada)
