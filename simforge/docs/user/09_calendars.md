# 9. Calendarios

Bloque `availability`: turnos, descansos y excepciones (festivos, horas extra). Cada máquina declara su política al
acabar el turno: `FINISH_CURRENT`, `PAUSE_RESUME` o `STOP_RESTART`. Sin calendario, todo está siempre disponible.

```bash
simforge calendar show modelo.yaml
simforge calendar validate modelo.yaml
simforge calendar --help        # setup, create, exception, assign, policy, remove, list
```

La pestaña **Calendars** muestra la disponibilidad planificada.

- KPIs propios: tiempo planificado disponible, descansos, fuera de turno y trabajo fuera de lo planificado.
- Estado: SYNTHETICALLY_VALIDATED.
- Protocolo de validación con datos reales: `docs/real_calendar_validation.md`.
- Detalle: `docs/calendars_and_shifts.md`.
