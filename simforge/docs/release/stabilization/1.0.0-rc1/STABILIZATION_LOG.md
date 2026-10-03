# Registro de estabilización — SimForge 1.0.0-rc1

## Baseline inmutable de RC1

| | |
|---|---|
| RC1_BASELINE_COMMIT | `1b283a7` (1b283a7edd1bfa1c5317d10b490fc050bd855ed5) |
| RC1_TAG | `v1.0.0-rc1`: tag anotado, «SimForge 1.0.0-rc1 — Release candidate 1», apunta a 1b283a7 |
| PRODUCT_VERSION | `1.0.0rc1` |
| DES_ENGINE | `0.9.0` |
| ECONOMICS_ENGINE | `0.9.0` |
| Preflight del tag | HEAD = 1b283a7, árbol limpio, 711 tests, ruff PASS, FREEZE [] (18), 01–05 = [59, 359, 1889.05, 477.5, 130], `check_release.py` PASS 11/11 (manifiesto: working_tree_dirty false), criterios RC 16/16, S0/S1/S2 = 0/0/0 |
| Estado del tag en el remoto | **RC1_TAG_STATUS = LOCAL_CORRECT_REMOTE_PUBLICATION_BLOCKED** (`REMOTE_TAG_PUBLICATION = BLOCKED_BY_REMOTE_PERMISSION`). El tag local es correcto: anotado, peeled = 1b283a7edd1bfa1c5317d10b490fc050bd855ed5. El push sólo del tag (`git push origin refs/tags/v1.0.0-rc1`) se rechazó con HTTP 403 en los dos intentos (apertura de la ventana y 2026-10-03, intento único autorizado). `refs/tags/v1.0.0-rc1` **no existe** en origin. No es un bug de SimForge. Publicación manual desde un entorno autorizado: `git fetch origin && git tag -a v1.0.0-rc1 1b283a7 -m "SimForge 1.0.0-rc1 — Release candidate 1" && git push origin refs/tags/v1.0.0-rc1`, y verificación con `git ls-remote origin 'refs/tags/v1.0.0-rc1^{}'` → 1b283a7edd1bfa1c5317d10b490fc050bd855ed5 |

**Reglas:**

- El tag RC1 **no se mueve nunca**: nada de retag, force o move.
- Los bugs se corrigen en commits posteriores (`fixed_in`).
- Una nueva RC (`v1.0.0-rc2`) sólo con autorización explícita.

## Estado

**Estado actual:** `RC1_STABILIZATION_IN_PROGRESS`. La ventana se abrió formalmente; cuenta el uso real, no los días.

| | |
|---|---|
| Sesiones ejecutadas | 0 (S-001 preparada como plantilla vacía, `sessions/S-001.md`: NOT_EXECUTED / READY_FOR_HUMAN_EXECUTION) |
| Incidencias | 0 |
| RC2_REQUIRED | NO (por ahora) |

**Validación industrial (dimensión separada, sin cambios):**

- capacidades: SYNTHETICALLY_VALIDATED;
- ninguna REAL_DATA_VALIDATED;
- economics real: NOT_EXECUTED;
- protocolo: READY_FOR_REAL_ECONOMIC_VALIDATION.

Si llegan datos de planta, el piloto real se ejecuta en paralelo con su protocolo. Su evidencia **no** se mezcla con
la de estabilización.

## Sesiones

| SESSION_ID | Fecha | Workflow(s) | Modo | Interfaz | Resultado | Incidencias | RC2 |
|---|---|---|---|---|---|---|---|

*(ninguna sesión ejecutada todavía; el detalle de cada sesión va en `sessions/S-NNN.md`)*

## Correcciones durante la RC

| ISSUE_ID | Severidad | fixed_in | test | `check_release.py` | ¿Nueva RC? |
|---|---|---|---|---|---|

## Rama de estabilización frente al baseline etiquetado

- `v1.0.0-rc1` = 1b283a7: lo que se probó y etiquetó.
- La rama `claude/industrial-simulation-ai-platform-90oov0` continúa con los commits de estabilización (registro y
  correcciones). El CHANGELOG distingue la RC1 etiquetada de los cambios posteriores.
