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


# ------------------------------------------------------------------------------------------------ 1.1-E (C17)
# Visible productivity: ONLY metrics already recorded by SimForge, verbatim. Nothing is reconstructed from timestamps,
# nothing is scored or compared against an invented baseline. A metric that is not recorded is NOT_AVAILABLE (never 0).
from typing import Literal  # noqa: E402

from pydantic import BaseModel, ConfigDict  # noqa: E402

RECORDED: dict[str, tuple[str, str, str]] = {  # key -> (unit, source, definition)
    "time_to_first_run_s": ("s", "MEASURED", "first saved model version -> first stored run (stored runs are completed "
                                         "runs of a model that passed the verifier)"),
    "time_to_engineer_approval_s": ("s", "MEASURED", "first saved model version -> first engineer approval"),
    "engineer_review_s": ("s", "MEASURED", "last AI generation -> approval (upper bound: includes corrections and pauses)"),
    "ai_generation_s": ("s", "MEASURED", "interpreter + compiler wall clock of the last AI generation"),
    "engineer_review_s_user": ("s", "USER_PROVIDED", "engineer review time entered by the engineer"),
    "correction_s_user": ("s", "USER_PROVIDED", "correction time entered by the engineer"),
    "reuse_ratio": ("", "MEASURED", "share of process steps matched to library components (last AI generation)"),
    "custom_logic_count": ("count", "MEASURED", "custom rule candidates in the last AI generation"),
    "ai_questions": ("count", "MEASURED", "questions asked by the last AI generation"),
}
# requested by the 1.1 roadmap -> recorded key ONLY with a contractually identical definition, else None (NOT_AVAILABLE)
ROADMAP: dict[str, tuple[str | None, str]] = {
    "TIME_TO_FIRST_VALID_RUN": (None, "not instrumented: 'valid run' has no contractual definition; related recorded "
                                "metric: time_to_first_run_s (first completed run of a verifier-passing model; approval "
                                "and real-world validity are not guaranteed)"),
    "TIME_TO_VALID_MODEL": (None, "not instrumented; related recorded metric: time_to_engineer_approval_s (approval, not validity)"),
    "TIME_TO_DECISION_READY_COMPARISON": (None, "not instrumented"),
    "ACTIVE_ENGINEERING_TIME": (None, "not instrumented (wall-clock windows include idle time)"),
    "NUMBER_OF_CORRECTION_LOOPS": (None, "not instrumented; related recorded count: corrections of AI values"),
}


class ProductivityMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    key: str | None
    status: Literal["AVAILABLE", "NOT_AVAILABLE"]
    value: float | None
    unit: str
    source: str
    definition: str


class ProductivityPanel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str
    recorded: list[ProductivityMetric]
    counts: list[ProductivityMetric]
    roadmap: list[ProductivityMetric]
    note: str = ("Recorded values only: nothing is reconstructed, rated or compared with an invented baseline. "
                 "Human productivity sessions have not been measured yet.")


def productivity_panel(project: Project) -> ProductivityPanel:
    def rec(key: str, name: str | None = None, definition: str | None = None) -> ProductivityMetric:
        unit, source, d = RECORDED[key]
        v = project.metric(key)
        return ProductivityMetric(name=name or key, key=key, status="AVAILABLE" if v is not None else "NOT_AVAILABLE",
                                  value=v, unit=unit, source=source if v is not None else "MISSING", definition=definition or d)
    m = project.metrics()
    counts = [ProductivityMetric(name=k, key=k, status="AVAILABLE", value=float(m[k]), unit="count", source="COUNT",
                                 definition=d) for k, d in (("versions", "model versions saved"), ("runs", "completed runs stored"),
                                                            ("ai_edits", "history entries by the AI"))]
    counts.append(ProductivityMetric(name="ai_value_corrections", key=None, status="AVAILABLE",
                                     value=float(len(project.corrections())), unit="count", source="COUNT",
                                     definition="engineer corrections of AI-proposed values"))
    roadmap = []
    for name, (key, note) in ROADMAP.items():
        if key is None:
            roadmap.append(ProductivityMetric(name=name, key=None, status="NOT_AVAILABLE", value=None, unit="", source="NOT_INSTRUMENTED",
                                              definition=note))
        else:
            roadmap.append(rec(key, name, note))
    return ProductivityPanel(project=project.meta.slug, recorded=[rec(k) for k in RECORDED], counts=counts, roadmap=roadmap)
