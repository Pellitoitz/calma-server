"""Economic assumptions editor (1.1-E, C06): typed edits of the existing `economics` block (economics 0.9).

Every operation returns a NEW validated model and changes ONLY the economics block: the physical content hash is
checked to be identical (economics is excluded from it by the 0.9 contract), so the DES identity, its cache and the
physical approval are untouched and no simulation is needed. No basis, category or formula is added: the editor
offers the bases the existing verifier already accepts per category (validation.economics.ALLOWED / MAINT_BASIS) and
the 0.9 evaluation computes everything. value = None is MISSING (never 0); an explicit 0 is data.
"""

from __future__ import annotations

import copy
import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from ..domain.economics import UNSUPPORTED_BASES, Basis
from ..domain.isms import ISMSModel
from ..domain.isms_ext import SimModel
from ..validation.economics import ALLOWED, MAINT_BASIS

LINE_CATEGORIES = ("labor", "machine", "material", "scrap", "maintenance", "downtime", "revenue", "capex")
MONEY_FIELD = {c: ("amount" if c == "capex" else "rate") for c in LINE_CATEGORIES}


class EconomicsEditError(ValueError):
    """An edit was refused; the model is unchanged."""


class MoneyForm(BaseModel):
    """Editor form of one monetary value. value None = MISSING (stays MISSING)."""
    model_config = ConfigDict(extra="forbid")
    value: float | None
    currency: str
    basis: str
    provenance: dict[str, Any] | None = None  # existing Provenance shape (status, source, note...)
    reference: str | None = None
    effective_date: str | None = None  # ISO date


def basis_options(category: str, kind: str | None = None) -> list[str]:
    """Bases the existing verifier accepts for a category (maintenance: per kind). Non-calculable bases excluded."""
    if category == "maintenance":
        return [MAINT_BASIS[kind].value] if kind in MAINT_BASIS else sorted({b.value for b in MAINT_BASIS.values()})
    allowed = ALLOWED.get(category)
    if allowed is None:
        raise EconomicsEditError(f"Categoría desconocida '{category}'.")
    return sorted(b.value for b in allowed if b not in UNSUPPORTED_BASES)


def money_dict(form: MoneyForm) -> dict[str, Any]:
    """Only declared keys are written (reference / effective_date / provenance only when given)."""
    if form.basis not in {b.value for b in Basis}:
        raise EconomicsEditError(f"Base desconocida '{form.basis}'.")
    if Basis(form.basis) in UNSUPPORTED_BASES:
        raise EconomicsEditError(f"Base {form.basis} no calculable en 0.9: {UNSUPPORTED_BASES[Basis(form.basis)]}.")
    d: dict[str, Any] = {"value": form.value, "currency": form.currency, "basis": form.basis}
    if form.provenance:
        d["provenance"] = form.provenance
    if form.reference:
        d["reference"] = form.reference
    if form.effective_date:
        try:
            dt.date.fromisoformat(form.effective_date)
        except ValueError:
            raise EconomicsEditError(f"Fecha efectiva inválida '{form.effective_date}' (AAAA-MM-DD).") from None
        d["effective_date"] = form.effective_date
    return d


def money_form(raw: dict[str, Any]) -> MoneyForm:
    return MoneyForm(value=raw.get("value"), currency=raw["currency"], basis=raw["basis"], provenance=raw.get("provenance"),
                     reference=raw.get("reference"),
                     effective_date=str(raw["effective_date"]) if raw.get("effective_date") else None)


# ------------------------------------------------------------------------------------------------ core
def _apply(model: ISMSModel, mutate) -> SimModel:
    data = copy.deepcopy(model.model_dump(mode="json"))
    econ = data.get("economics")
    out = mutate(copy.deepcopy(econ) if econ is not None else None)
    data["economics"] = out
    try:
        new = SimModel.model_validate(data)
    except ValidationError as e:
        raise EconomicsEditError("; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())) from None
    if new.content_hash() != model.content_hash():  # contract of 0.9: economics never touches the physical identity
        raise EconomicsEditError("La edición alteraría el hash físico del modelo: rechazada.")
    return new


def _need(econ):
    if econ is None:
        raise EconomicsEditError("El modelo no tiene bloque 'economics': créalo primero (moneda y alcance).")
    return econ


def create_economics(model: ISMSModel, currency: str, scope: list[str]) -> SimModel:
    if getattr(model, "economics", None) is not None:
        raise EconomicsEditError("El modelo ya tiene supuestos económicos.")
    return _apply(model, lambda _: {"currency": currency, "scope": list(scope)})


def set_header(model: ISMSModel, currency: str | None = None, scope: list[str] | None = None) -> SimModel:
    def m(econ):
        econ = _need(econ)
        if currency is not None:
            econ["currency"] = currency
        if scope is not None:
            econ["scope"] = list(scope)
        return econ
    return _apply(model, m)


def add_line(model: ISMSModel, category: str, fields: dict[str, Any], money: MoneyForm) -> SimModel:
    """Append a line to labor / machine / material / scrap / maintenance / downtime / revenue / capex.
    `fields` = the category's own fields (resource, node, kind, product, category, paid_time, note...)."""
    if category not in LINE_CATEGORIES:
        raise EconomicsEditError(f"Categoría desconocida '{category}' ({', '.join(LINE_CATEGORIES)}).")

    def m(econ):
        econ = _need(econ)
        econ.setdefault(category, []).append({**{k: v for k, v in fields.items() if v is not None},
                                             MONEY_FIELD[category]: money_dict(money)})
        return econ
    return _apply(model, m)


def update_line_money(model: ISMSModel, category: str, index: int, money: MoneyForm) -> SimModel:
    def m(econ):
        econ = _need(econ)
        lines = econ.get(category) or []
        if not 0 <= index < len(lines):
            raise EconomicsEditError(f"No existe la línea {category}.{index}.")
        lines[index][MONEY_FIELD[category]] = money_dict(money)
        return econ
    return _apply(model, m)


def remove_line(model: ISMSModel, category: str, index: int) -> SimModel:
    def m(econ):
        econ = _need(econ)
        lines = econ.get(category) or []
        if not 0 <= index < len(lines):
            raise EconomicsEditError(f"No existe la línea {category}.{index}.")
        del lines[index]
        return econ
    return _apply(model, m)


def set_energy(model: ISMSModel, price: MoneyForm | None, power_kw: dict[str, dict[str, float]] | None = None) -> SimModel:
    """price None removes the energy block (not declared); power_kw = node -> {PROCESSING|SETUP: kW} (declared only)."""
    def m(econ):
        econ = _need(econ)
        if price is None:
            econ["energy"] = None
        else:
            econ["energy"] = {"price": money_dict(price), "power_kw": power_kw or {}}
        return econ
    return _apply(model, m)


def set_annualization(model: ISMSModel, runs_per_year: float | None, provenance: dict[str, Any] | None = None) -> SimModel:
    """None = annualization NOT DECLARED (never an assumed number of runs per year)."""
    def m(econ):
        econ = _need(econ)
        econ["annualization"] = None if runs_per_year is None else {
            "mode": "REPEAT_RUN", "runs_per_year": runs_per_year, **({"provenance": provenance} if provenance else {})}
        return econ
    return _apply(model, m)


def remove_economics(model: ISMSModel) -> SimModel:
    return _apply(model, lambda _: None)
