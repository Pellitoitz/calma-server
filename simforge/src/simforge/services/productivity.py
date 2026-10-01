"""Productivity: how much engineer time does AI-assisted model building save?

    TIME SAVED   = manual_model_build_time - total_AI_assisted_time
    TIME SAVED % = TIME SAVED / manual_model_build_time

Every figure carries its source. Nothing is invented:
  * manual_model_build_time   USER_PROVIDED (the engineer's estimate or measurement of building it by hand)
  * AI_initial_generation_time MEASURED (interpreter + compiler wall clock, all interpretations incl. re-compilations)
  * engineer_review_time       MEASURED wall clock from the first AI generation to the engineer approval
                               (an UPPER BOUND: it includes corrections and any idle time), or USER_PROVIDED
  * correction_time            USER_PROVIDED only; when not given it is included in the measured review window
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..persistence.project import Project

USER_KEYS = {"engineer_review_min": "engineer_review_s_user", "correction_min": "correction_s_user"}


@dataclass
class TimeItem:
    name: str
    minutes: float | None
    source: str  # MEASURED | USER_PROVIDED | MISSING | INCLUDED_IN_REVIEW
    note: str = ""


@dataclass
class ProductivityReport:
    items: list[TimeItem] = field(default_factory=list)
    total_ai_assisted_min: float | None = None
    time_saved_min: float | None = None
    time_saved_pct: float | None = None
    reuse_ratio: float | None = None
    custom_logic_count: float | None = None

    def item(self, name: str) -> TimeItem:
        return next(i for i in self.items if i.name == name)

    def to_text(self) -> str:
        def fmt(v: float | None) -> str:
            return "—" if v is None else f"{v:.1f} min"
        L = ["PRODUCTIVITY", ""]
        L += [f"{i.name:<30}{fmt(i.minutes):>12}  {i.source}" + (f"  ({i.note})" if i.note else "") for i in self.items]
        L += ["", f"{'total_AI_assisted_time':<30}{fmt(self.total_ai_assisted_min):>12}",
              f"{'TIME SAVED':<30}{fmt(self.time_saved_min):>12}",
              f"{'TIME SAVED %':<30}{'—' if self.time_saved_pct is None else f'{self.time_saved_pct:.1%}':>12}"]
        if self.reuse_ratio is not None:
            L += ["", f"REUSE RATIO: {self.reuse_ratio:.0%}   CUSTOM LOGIC: {int(self.custom_logic_count or 0)}"]
        return "\n".join(L)


def record_engineer_time(project: Project, key: str, minutes: float) -> None:
    """Engineer-entered times: manual_model_build_min, engineer_review_min, correction_min."""
    if minutes < 0:
        raise ValueError("el tiempo no puede ser negativo")
    if key == "manual_model_build_min":
        project.meta.manual_model_estimated_hours = minutes / 60
        project.save_meta()
    elif key in USER_KEYS:
        project.record_metric(USER_KEYS[key], minutes * 60, "entered by the engineer")
    else:
        raise KeyError(f"clave desconocida '{key}' (manual_model_build_min, engineer_review_min, correction_min)")


def productivity(project: Project) -> ProductivityReport:
    rep = ProductivityReport(reuse_ratio=project.metric("reuse_ratio"), custom_logic_count=project.metric("custom_logic_count"))
    manual = project.meta.manual_model_estimated_hours
    rep.items.append(TimeItem("manual_model_build_time", manual * 60 if manual is not None else None,
                              "USER_PROVIDED" if manual is not None else "MISSING",
                              "" if manual is not None else "indica cuánto te costaría construirlo a mano"))
    interps = project.interpretations()
    gen = sum((i["generation_ms"] or 0) for i in interps) / 60000 if interps else None
    rep.items.append(TimeItem("AI_initial_generation_time", gen, "MEASURED" if gen is not None else "MISSING"))

    review_user, corr_user = project.metric("engineer_review_s_user"), project.metric("correction_s_user")
    approval = project.first_event("approve_model")
    measured = None
    if interps and approval:
        start = datetime.fromisoformat(interps[0]["created_at"])
        measured = max(0.0, (datetime.fromisoformat(approval["ts"]) - start).total_seconds() / 60)
    if review_user is not None:
        rep.items.append(TimeItem("engineer_review_time", review_user / 60, "USER_PROVIDED"))
    elif measured is not None:
        rep.items.append(TimeItem("engineer_review_time", measured, "MEASURED",
                                  "generación → aprobación; incluye correcciones y pausas (cota superior)"))
    else:
        rep.items.append(TimeItem("engineer_review_time", None, "MISSING", "el modelo aún no está aprobado"))
    if corr_user is not None:
        rep.items.append(TimeItem("correction_time", corr_user / 60, "USER_PROVIDED"))
    else:
        rep.items.append(TimeItem("correction_time", None, "INCLUDED_IN_REVIEW", "no se mide por separado"))

    review = rep.item("engineer_review_time").minutes
    corr = rep.item("correction_time").minutes
    if gen is not None and review is not None:
        # a user-provided review time does not include corrections; the measured window already does
        rep.total_ai_assisted_min = gen + review + ((corr or 0.0) if review_user is not None else 0.0)
        if manual is not None and manual > 0:
            rep.time_saved_min = manual * 60 - rep.total_ai_assisted_min
            rep.time_saved_pct = rep.time_saved_min / (manual * 60)
    return rep
