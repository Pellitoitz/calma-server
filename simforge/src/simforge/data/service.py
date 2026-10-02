"""Data workflow on a project: import -> validate -> profile -> outliers -> fit -> engineer decision -> apply to model.

Used by the CLI (`simforge data ...`) and the UI (Data tab). Never calls an LLM. Every step that changes the
interpretation of data or the model is an explicit call with `by` (who) and a reason, logged append-only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from ..domain.isms import Approval, ISMSModel
from ..domain.paths import diff, get_value, set_value
from ..domain.values import DataLink, Duration, Provenance, ValueStatus
from ..library.registry import ComponentRegistry
from ..persistence.project import Project
from ..validation.verifier import verify
from . import fitting, outliers, stats
from .dataset import (
    ApplyEvent,
    ColumnMapping,
    Decision,
    DecisionEvent,
    DatasetMeta,
    FitEvent,
    Observation,
    RowEvent,
    RowStatus,
    content_hash,
    now_utc,
)
from .importers import read_table
from .quantities import SUPPORT, UNKNOWN_UNIT, Basis, QuantityType, base_unit, normalize_unit
from .store import DatasetError, DatasetStore, slug
from .validation import interpret

_DURATION = TypeAdapter(Duration)


class DataDecisionRequired(DatasetError):
    """The engineer must decide something explicitly (group pooling, warnings, basis...)."""


@dataclass
class DatasetState:
    meta: DatasetMeta
    observations: list[Observation]
    used: list[int]  # observation indexes used for statistics/fitting
    excluded: list[int]  # EXCLUDE_FROM_FIT (restorable)
    marked_invalid: list[int]  # MARK_INVALID by the engineer (restorable)
    pending_review: list[int]  # REQUIRES_REVIEW not yet accepted
    invalid: list[int]  # INVALID at import (never usable)
    row_log: list[RowEvent]
    fits: list[FitEvent]
    decisions: list[DecisionEvent]
    applications: list[ApplyEvent]
    state_hash: str

    def obs(self, i: int) -> Observation:
        return self.observations[i]


@dataclass
class ImportResult:
    meta: DatasetMeta
    duplicate_of: str | None = None  # existing dataset returned instead of creating a new one
    same_file_other_settings: list[str] = field(default_factory=list)


class DataService:
    def __init__(self, project: Project, registry: ComponentRegistry):
        self.project = project
        self.registry = registry
        self.store = DatasetStore(project.root)

    # ================================================================== import
    def import_file(self, path: Path, name: str, value_column: str, quantity: QuantityType | str, basis: Basis | str,
                    unit: str | None = None, unit_column: str | None = None, sheet: str | None = None,
                    delimiter: str | None = None, decimal: str | None = None, header_row: int = 1,
                    groups: dict[str, str] | None = None, timestamp: str | None = None, by: str = "engineer",
                    description: str = "", synthetic: bool = False, measurement_status: str = "measured",
                    basis_note: str = "", force_new_version: bool = False) -> ImportResult:
        quantity, basis = QuantityType(quantity), Basis(basis)
        synthetic = synthetic or "synthetic" in path.name.lower()  # a file named SYNTHETIC_* can never be imported as measured
        mapping = ColumnMapping(value=value_column, unit=unit, unit_column=unit_column, timestamp=timestamp, **(groups or {}))
        if mapping.unit:
            mapping = mapping.model_copy(update={"unit": normalize_unit(mapping.unit, SUPPORT[quantity]["dimension"])})
        table = read_table(path, sheet=sheet, delimiter=delimiter, decimal=decimal, header_row=header_row)
        name = slug(name)
        settings = {"sheet": table.sheet, "delimiter": table.delimiter, "decimal": table.decimal, "header_row": header_row,
                    "mapping": mapping.model_dump(), "quantity_type": quantity.value, "basis": basis.value}
        same, other = self.store.find_duplicates(table.file_sha256, settings)
        if same and not force_new_version:
            return ImportResult(self.store.meta(same[0]), duplicate_of=same[0], same_file_other_settings=other)
        obs, analysis_unit, transformations, notes = interpret(table, mapping, quantity)
        counts = {s.value: sum(1 for o in obs if o.status is s) for s in RowStatus}
        version = self.store.next_version(name)
        meta = DatasetMeta(dataset_id=f"{name}@v{version}", name=name, version=version, imported_by=by, description=description,
                           synthetic=synthetic, measurement_status=measurement_status, source_file=table.source_file,
                           stored_file=f"source/{path.name}", file_sha256=table.file_sha256, file_bytes=table.file_bytes,
                           file_format=table.file_format, sheet=table.sheet, encoding=table.encoding, delimiter=table.delimiter,
                           decimal=table.decimal, header_row=header_row, mapping=mapping, quantity_type=quantity, basis=basis,
                           basis_note=basis_note, analysis_unit=analysis_unit,
                           normalized_unit=base_unit(SUPPORT[quantity]["dimension"]), n_rows=len(obs), counts=counts,
                           import_notes=table.notes + notes + ([f"mismo archivo importado antes con otra interpretación: {other}"]
                                                               if other else []),
                           transformations=transformations, content_hash=content_hash(table.file_sha256, settings, obs))
        self.store.create(meta, path, obs)
        self.project.log(by, "data_import", request=str(path.name),
                         result=f"{meta.label}: {counts} ({quantity.value}, {basis.value}, unidad {analysis_unit})")
        return ImportResult(meta, same_file_other_settings=other)

    def list(self) -> list[DatasetMeta]:
        return self.store.list()

    # =================================================================== state
    def state(self, dataset_id: str) -> DatasetState:
        meta = self.store.meta(dataset_id)
        obs = self.store.observations(dataset_id)
        events = self.store.events(dataset_id)
        usable = {o.index for o in obs if o.status in (RowStatus.VALID, RowStatus.WARNING)}
        review = {o.index for o in obs if o.status is RowStatus.REQUIRES_REVIEW}
        invalid = {o.index for o in obs if o.status is RowStatus.INVALID}
        accepted: set[int] = set()
        excluded: set[int] = set()
        marked: set[int] = set()
        row_log, fits, decisions, apps = [], [], [], []
        for e in events:
            if isinstance(e, RowEvent):
                rows = set(e.rows)
                if e.action == "EXCLUDE_FROM_FIT":
                    excluded |= rows
                elif e.action == "MARK_INVALID":
                    marked |= rows
                elif e.action == "ACCEPT_REVIEWED":
                    accepted |= rows
                elif e.action == "RESTORED":
                    excluded -= rows
                    marked -= rows
                row_log.append(e)
            elif isinstance(e, FitEvent):
                fits.append(e)
            elif isinstance(e, DecisionEvent):
                decisions.append(e)
            elif isinstance(e, ApplyEvent):
                apps.append(e)
        used = sorted(((usable | accepted) - excluded - marked))
        h = hashlib.sha256(f"{meta.content_hash}|{used}".encode()).hexdigest()[:16]
        return DatasetState(meta, obs, used, sorted(excluded), sorted(marked), sorted(review - accepted), sorted(invalid),
                            row_log, fits, decisions, apps, h)

    def _select(self, st: DatasetState, group: dict[str, str] | None, pooled: bool) -> list[Observation]:
        group = group or {}
        roles = st.meta.mapping.group_columns()
        for k in group:
            if k not in roles:
                raise DatasetError(f"'{k}' no es una columna de grupo de este dataset (grupos: {list(roles)}).")
        rows = [st.obs(i) for i in st.used if all(st.obs(i).groups.get(k) == v for k, v in group.items())]
        mixed = {r: sorted({o.groups.get(r) for o in rows}) for r in roles if r not in group}
        mixed = {r: v for r, v in mixed.items() if len(v) > 1}
        if mixed and not pooled:
            comp = {r: stats.group_comparison(self._by_group(rows, r)) for r in mixed}
            raise DataDecisionRequired(
                f"Los datos mezclan grupos {mixed}. Elige un grupo (p. ej. --group {next(iter(mixed))}={next(iter(mixed.values()))[0]}) "
                f"o declara explícitamente que los mezclas (--pooled). Comparación: "
                + "; ".join(f"{r}: {c.get('flag')}" for r, c in comp.items()))
        if st.meta.mapping.timestamp and rows and all(o.timestamp for o in rows):
            rows = sorted(rows, key=lambda o: (o.timestamp, o.index))
        return rows

    @staticmethod
    def _by_group(rows: list[Observation], role: str) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        for o in rows:
            out.setdefault(o.groups.get(role, "?"), []).append(o.value)
        return out

    # ================================================================= profile
    def profile(self, dataset_id: str, group: dict[str, str] | None = None, pooled: bool = False, seed: int = 12345) -> dict:
        st = self.state(dataset_id)
        m = st.meta
        out: dict[str, Any] = {
            "dataset": m.model_dump(mode="json"), "label": m.label, "state_hash": st.state_hash,
            "quantity_support": SUPPORT[m.quantity_type]["note"],
            "simulation_use": "SUPPORTED" if SUPPORT[m.quantity_type]["targets"] else "SIMULATION_USE_NOT_YET_SUPPORTED",
            "validation": {"counts": m.counts, "invalid": [self._row_brief(st.obs(i)) for i in st.invalid],
                           "requires_review": [self._row_brief(st.obs(i)) for i in st.pending_review],
                           "warnings": [self._row_brief(o) for o in st.observations if o.status is RowStatus.WARNING]},
            "exclusions": {"excluded_from_fit": st.excluded, "marked_invalid": st.marked_invalid,
                           "log": [e.model_dump(mode="json") for e in st.row_log]},
            "groups": {}, "group": group or {}, "pooled": pooled,
        }
        roles = m.mapping.group_columns()
        all_used = [st.obs(i) for i in st.used]
        for r in roles:
            out["groups"][r] = stats.group_comparison(self._by_group(all_used, r))
        try:
            rows = self._select(st, group, pooled)
        except DataDecisionRequired as e:
            out["selection_error"] = str(e)
            return out
        x = [o.value for o in rows]
        n_missing = len(st.invalid) + len(st.pending_review) + len(st.marked_invalid)
        out["stats"] = stats.describe(x, n_missing=n_missing, n_excluded=len(st.excluded))
        out["serial"] = stats.lag1(x)
        out["trend"] = stats.trend(x)
        out["order"] = "timestamp" if m.mapping.timestamp and rows and all(o.timestamp for o in rows) else "file order"
        out["bootstrap"] = stats.bootstrap(x, seed=seed)
        out["outliers"] = outliers.detect(x, [o.index for o in rows])
        acted = {i for e in st.row_log for i in e.rows}
        out["outliers"]["unreviewed"] = [c["index"] for c in out["outliers"]["candidates"] if c["index"] not in acted]
        out["status"] = self._status(st, out)
        out["plots"] = stats.plot_data(x, [o.timestamp for o in rows])
        out["unit"] = m.analysis_unit
        return out

    @staticmethod
    def _status(st: DatasetState, prof: dict) -> str:
        last = st.decisions[-1] if st.decisions else None
        if last and last.decision is Decision.REJECT:
            return "REJECTED"
        if st.applications and last and st.applications[-1].decision_id == last.decision_id:
            return f"APPLIED (model v{st.applications[-1].project_model_version})"
        if st.pending_review or prof.get("outliers", {}).get("unreviewed"):
            return "REQUIRES_ENGINEER_REVIEW"
        if last and last.state_hash == st.state_hash:
            return f"DECIDED ({last.decision.value})"
        return "READY_FOR_ENGINEER_DECISION"

    @staticmethod
    def _row_brief(o: Observation) -> dict:
        return {"index": o.index, "row": o.row, "original": o.original_value, "unit": o.original_unit, "value": o.value,
                "status": o.status.value, "issues": o.issues}

    # ============================================================= row actions
    def act_rows(self, dataset_id: str, action: str, rows: list[int], reason: str, by: str, method: str | None = None) -> RowEvent:
        st = self.state(dataset_id)
        n = len(st.observations)
        bad = [r for r in rows if r < 0 or r >= n]
        if bad:
            raise DatasetError(f"Filas inexistentes: {bad} (índices 0..{n - 1}).")
        if action in ("EXCLUDE_FROM_FIT", "MARK_INVALID"):
            not_used = [r for r in rows if r not in st.used]
            if not_used:
                raise DatasetError(f"Las filas {not_used} no están en uso (inválidas, pendientes de revisión o ya excluidas).")
        elif action == "RESTORED":
            not_out = [r for r in rows if r not in st.excluded and r not in st.marked_invalid]
            if not_out:
                raise DatasetError(f"Las filas {not_out} no estaban excluidas por el ingeniero (las INVALID de importación no se restauran).")
        elif action == "ACCEPT_REVIEWED":
            not_rev = [r for r in rows if r not in st.pending_review]
            if not_rev:
                raise DatasetError(f"Las filas {not_rev} no están pendientes de revisión.")
        elif action != "KEEP":
            raise DatasetError(f"Acción desconocida '{action}'.")
        ev = RowEvent(action=action, rows=sorted(set(rows)), reason=reason, method=method, by=by)
        self.store.append(dataset_id, ev)
        self.project.log(by, "data_rows", request=f"{dataset_id} {action} {ev.rows}", result=reason)
        return ev

    # ===================================================================== fit
    def fit(self, dataset_id: str, by: str = "engineer", group: dict[str, str] | None = None, pooled: bool = False,
            physical_min: float | None = None, physical_max: float | None = None) -> dict:
        st = self.state(dataset_id)
        rows = self._select(st, group, pooled)
        notes = [n for n in st.meta.import_notes if n.startswith("ROUNDED_DATA")]
        if st.meta.synthetic:
            notes.insert(0, "SYNTHETIC TEST DATA: no son medidas de planta")
        report = fitting.fit_candidates([o.value for o in rows], st.meta.analysis_unit, physical_min, physical_max, notes=notes)
        report["fit_id"] = "fit_" + hashlib.sha256(f"{report.get('fit_id')}|{st.state_hash}|{sorted((group or {}).items())}|{pooled}".encode()).hexdigest()[:12]
        report["dataset_id"], report["state_hash"], report["group"], report["pooled"] = dataset_id, st.state_hash, group or {}, pooled
        report["serial"] = stats.lag1([o.value for o in rows])
        if report["serial"].get("flag") == "POSSIBLE_SERIAL_DEPENDENCE":
            report["notes"].append("POSSIBLE_SERIAL_DEPENDENCE: el motor muestrea i.i.d.; la dependencia entre ciclos no se reproduce")
        if not any(f.fit_id == report["fit_id"] for f in st.fits):
            self.store.append(dataset_id, FitEvent(fit_id=report["fit_id"], by=by, group=group or {}, pooled=pooled,
                                                   state_hash=st.state_hash, result=report))
            self.project.log(by, "data_fit", request=dataset_id,
                             result=f"{report['fit_id']}: sugerido {report['suggested']['family'] if report['suggested'] else 'ninguno'}")
        return report

    def get_fit(self, dataset_id: str, fit_id: str) -> FitEvent:
        for f in self.state(dataset_id).fits:
            if f.fit_id == fit_id:
                return f
        raise DatasetError(f"No existe el ajuste '{fit_id}' en {dataset_id}.")

    # ================================================================ decision
    def decide(self, dataset_id: str, decision: Decision | str, by: str, reason: str = "", group: dict[str, str] | None = None,
               pooled: bool = False, derivation: str | None = None, engineer_value: float | None = None,
               fit_id: str | None = None, candidate: str | None = None, truncation: dict | None = None,
               accept_warnings: list[str] | None = None) -> DecisionEvent:
        decision = Decision(decision)
        accept = list(accept_warnings or [])
        st = self.state(dataset_id)
        m = st.meta
        dist: dict | None = None
        rows: list[Observation] = []
        if decision in (Decision.USE_DETERMINISTIC, Decision.USE_EMPIRICAL, Decision.USE_FITTED):
            rows = self._select(st, group, pooled)
            if not rows and not (decision is Decision.USE_DETERMINISTIC and derivation == "ENGINEER_VALUE"):
                raise DatasetError("No hay filas en uso para decidir.")
            x = [o.value for o in rows]
            n = len(x)
            if decision is Decision.USE_DETERMINISTIC:
                if derivation not in ("MEAN", "MEDIAN", "ENGINEER_VALUE"):
                    raise DataDecisionRequired("Determinista: indica el origen del valor: MEAN, MEDIAN o ENGINEER_VALUE.")
                if derivation == "ENGINEER_VALUE":
                    if engineer_value is None or engineer_value < 0:
                        raise DataDecisionRequired("ENGINEER_VALUE requiere un valor >= 0 (en la unidad del dataset).")
                    v = float(engineer_value)
                else:
                    d = stats.describe(x)
                    v = d["mean"] if derivation == "MEAN" else d["median"]
                dist = {"dist": "constant", "value": v, "unit": m.analysis_unit}
            elif decision is Decision.USE_EMPIRICAL:
                if n < 10 and "VERY_SMALL_SAMPLE" not in accept:
                    raise DataDecisionRequired(f"Empírica con n = {n} < 10: solo reproduce {n} valores. Acéptalo explícitamente "
                                               "(accept_warnings=['VERY_SMALL_SAMPLE']) o mide más.")
                dist = {"dist": "empirical", "values": x, "unit": m.analysis_unit}
            else:
                if not fit_id or not candidate:
                    raise DataDecisionRequired("Ajustada: indica fit_id y candidato.")
                fe = self.get_fit(dataset_id, fit_id)
                if fe.state_hash != st.state_hash or fe.group != (group or {}) or fe.pooled != pooled:
                    raise DataDecisionRequired(f"El ajuste {fit_id} se hizo sobre otro estado de los datos (exclusiones o grupo "
                                               "distintos): vuelve a ajustar.")
                if fe.result["n"] < 10 and "VERY_SMALL_SAMPLE" not in accept:
                    raise DataDecisionRequired(f"Ajuste con n = {fe.result['n']} < 10 (VERY_SMALL_SAMPLE): acéptalo explícitamente "
                                               "(accept_warnings=['VERY_SMALL_SAMPLE']) o usa determinista/empírica.")
                c = fitting.candidate(fe.result, candidate)
                if c.get("status") not in ("OK", "REQUIRES_TRUNCATION"):
                    raise DatasetError(f"Candidato '{candidate}' no utilizable: {c.get('status')} {c.get('reason', '')}")
                if c["status"] == "REQUIRES_TRUNCATION" and not (truncation and truncation.get("lower") is not None
                                                                   and truncation["lower"] >= 0):
                    raise DataDecisionRequired(f"'{candidate}' tiene masa negativa: solo con truncamiento explícito "
                                               "(truncation={'lower': 0, 'reason': '...'}).")
                flags = c["plausibility"]["flags"]
                pending = [f["code"] for f in flags if f["severity"] in ("WARNING", "CRITICAL")
                           and f["code"] not in accept and not (f["code"] == "NEGATIVE_SUPPORT" and truncation)]
                if pending:
                    raise DataDecisionRequired(f"Avisos de plausibilidad sin aceptar para '{candidate}': {pending}. "
                                               "Revísalos y acéptalos explícitamente (accept_warnings) o elige otra opción.")
                dist = {**c["params"], "unit": m.analysis_unit}
                if truncation:
                    dist["truncation"] = truncation
            if SUPPORT[m.quantity_type]["dimension"].value == "time" and m.analysis_unit != UNKNOWN_UNIT:
                _DURATION.validate_python(dist)  # the engine must accept it as is
        ev = DecisionEvent(decision_id=f"dec_{len(st.decisions) + 1:03d}", decision=decision, by=by, reason=reason, group=group or {},
                           pooled=pooled, derivation=derivation, engineer_value=engineer_value, fit_id=fit_id, candidate=candidate,
                           truncation=truncation, accepted_warnings=accept, distribution=dist, rows_used=[o.index for o in rows],
                           n_used=len(rows), n_excluded=len(st.excluded) + len(st.marked_invalid), state_hash=st.state_hash)
        self.store.append(dataset_id, ev)
        self.project.log(by, "data_decision", request=dataset_id, result=f"{ev.decision_id}: {decision.value} {candidate or derivation or ''}")
        return ev

    def get_decision(self, dataset_id: str, decision_id: str) -> DecisionEvent:
        for d in self.state(dataset_id).decisions:
            if d.decision_id == decision_id:
                return d
        raise DatasetError(f"No existe la decisión '{decision_id}' en {dataset_id}.")

    # =================================================================== apply
    def check_target(self, model: ISMSModel, meta: DatasetMeta, target: str) -> tuple[str, Any]:
        """Return (node id, current value) or raise with the reason the target cannot take this quantity."""
        sup = SUPPORT[meta.quantity_type]
        if not sup["targets"]:
            raise DatasetError(f"{meta.quantity_type.value}: SIMULATION_USE_NOT_YET_SUPPORTED. {sup['note']}")
        parts = target.split(".")
        if len(parts) < 4 or parts[0] != "nodes":
            raise DatasetError(f"Destino '{target}': debe ser nodes.<id>.{' | '.join(sup['targets'])}")
        node_id, rest = parts[1], ".".join(parts[2:])
        if rest not in sup["targets"]:
            raise DatasetError(f"{meta.quantity_type.value} solo puede aplicarse a nodes.<id>.{' | '.join(sup['targets'])} "
                               f"(recibido '{rest}').")
        node = next((n for n in model.nodes if n.id == node_id), None)
        if node is None:
            raise DatasetError(f"No existe el nodo '{node_id}'.")
        beh = self.registry.get(node.component).behavior.value
        if beh not in sup["behaviors"]:
            raise DatasetError(f"El nodo '{node_id}' ({node.component}, comportamiento {beh}) no admite {meta.quantity_type.value}.")
        if rest.startswith("params.failures.") and not node.params.get("failures"):
            raise DatasetError(f"El nodo '{node_id}' no declara averías (failures): defínelas antes (mtbf y mttr).")
        if rest == "params.interarrival" and node.params.get("arrival") != "interarrival":
            raise DatasetError(f"La fuente '{node_id}' no usa arrival: interarrival; cámbialo explícitamente antes de aplicar.")
        try:
            current = get_value(model, target)
        except KeyError:
            current = None
        return node_id, current

    def apply(self, dataset_id: str, decision_id: str, target: str, target_basis: Basis | str, by: str,
              conversion: dict | None = None, acknowledge: list[str] | None = None) -> dict:
        """Write the decided value into the CURRENT model as a NEW version (approval invalidated). Returns a summary."""
        ack = list(acknowledge or [])
        target_basis = Basis(target_basis)
        st = self.state(dataset_id)
        meta = st.meta
        dec = self.get_decision(dataset_id, decision_id)
        if dec.decision not in (Decision.USE_DETERMINISTIC, Decision.USE_EMPIRICAL, Decision.USE_FITTED):
            raise DatasetError(f"La decisión {decision_id} es {dec.decision.value}: no se aplica nada al modelo.")
        if dec.state_hash != st.state_hash:
            raise DataDecisionRequired("Los datos (exclusiones/restauraciones) cambiaron después de esta decisión: decide de nuevo.")
        model = self.project.current_model()
        if model is None:
            raise DatasetError("El proyecto no tiene modelo al que aplicar el dato.")
        if meta.analysis_unit == UNKNOWN_UNIT:
            raise DataDecisionRequired("Unidad UNKNOWN: los datos no pueden aplicarse al modelo. Reimporta indicando la unidad.")
        node_id, current = self.check_target(model, meta, target)
        dist = dict(dec.distribution or {})
        warnings: list[str] = []
        # ---- basis: never converted silently
        if meta.basis is Basis.UNKNOWN or target_basis is Basis.UNKNOWN:
            raise DataDecisionRequired("Base desconocida (UNKNOWN): no se puede aplicar sin saber a qué se refiere cada medida "
                                       "(por circuito, por bastidor...). Reimporta declarando la base.")
        if meta.basis is not target_basis:
            if not conversion or "factor" not in conversion or not conversion.get("formula") or "inputs" not in conversion:
                raise DataDecisionRequired(f"Base del dato {meta.basis.value} ≠ base del destino {target_basis.value}. Indica una "
                                           "conversión explícita: {'factor': k, 'formula': '...', 'inputs': {...}}.")
            k = float(conversion["factor"])
            if k <= 0:
                raise DatasetError("El factor de conversión debe ser > 0.")
            if dist["dist"] not in ("constant",) and "SCALING_IS_NOT_SUM" not in ack:
                raise DataDecisionRequired(
                    "Escalar una distribución por k modela k·X (una muestra multiplicada), NO la suma de k tiempos independientes: "
                    "la media coincide pero la variabilidad es mayor (desv. ×k en lugar de ×√k). Confírmalo con "
                    "acknowledge=['SCALING_IS_NOT_SUM'] o ajusta datos medidos en la base del destino.")
            dist = _scale(dist, k)
            warnings.append(f"CONVERSION: {meta.basis.value} -> {target_basis.value}: {conversion['formula']} (×{k:g})")
        # ---- engine semantics the engineer must know about
        if target.endswith("params.process_time"):
            node = next(n for n in model.nodes if n.id == node_id)
            wu = node.params.get("work_units", 1)
            if wu != 1 and dist["dist"] != "constant":
                if "WORK_UNITS_SCALING" not in ack:
                    raise DataDecisionRequired(
                        f"El nodo '{node_id}' tiene work_units = {wu}: el motor multiplica UNA muestra por work_units "
                        "(variabilidad ×k, no ×√k). Confírmalo con acknowledge=['WORK_UNITS_SCALING'].")
                warnings.append(f"WORK_UNITS_SCALING: work_units = {wu} multiplica una única muestra")
        if meta.quantity_type is QuantityType.DISTANCE:
            if dist["dist"] != "constant":
                raise DatasetError("DISTANCE: el motor solo admite una distancia fija; aplica una decisión determinista.")
            dist = {"value": dist["value"], "unit": dist["unit"]}
        st_lag = stats.lag1([st.obs(i).value for i in dec.rows_used]) if dec.rows_used else {}
        if st_lag.get("flag") == "POSSIBLE_SERIAL_DEPENDENCE":
            warnings.append("POSSIBLE_SERIAL_DEPENDENCE: el motor muestrea de forma independiente")
        # ---- provenance
        if meta.synthetic:
            status = ValueStatus.ASSUMED
        elif conversion or dec.derivation in ("MEAN", "MEDIAN"):
            status = ValueStatus.CALCULATED
        elif dec.derivation == "ENGINEER_VALUE":
            status = ValueStatus.PROVIDED_BY_CLIENT
        else:
            status = ValueStatus(meta.measurement_status)
        fit_summary = None
        if dec.decision is Decision.USE_FITTED:
            c = fitting.candidate(self.get_fit(dataset_id, dec.fit_id).result, dec.candidate)
            fit_summary = (f"{dec.candidate} {c['method']}; AIC {c['aic']:.1f} (ΔAIC {c['delta_aic']:.2f}); "
                           f"KS {c['gof']['ks_stat']:.3f}; n={dec.n_used}")
        link = DataLink(dataset_id=dataset_id, dataset_version=meta.version, content_hash=meta.content_hash,
                        source_file=meta.source_file, column=meta.mapping.value, original_unit=meta.analysis_unit,
                        basis=meta.basis.value, n_used=dec.n_used, n_excluded=dec.n_excluded,
                        decision={"USE_DETERMINISTIC": "DETERMINISTIC", "USE_EMPIRICAL": "EMPIRICAL", "USE_FITTED": "FITTED"}[dec.decision.value],
                        derivation=dec.derivation, fit_id=dec.fit_id, fit_summary=fit_summary,
                        conversion=({**conversion, "from_basis": meta.basis.value, "to_basis": target_basis.value}
                                    if conversion else None),
                        decided_by=dec.by, decided_at=dec.at)
        note = (("[SYNTHETIC TEST DATA] " if meta.synthetic else "") + f"{dataset_id} ({meta.source_file}:{meta.mapping.value}) "
                f"{dec.decision.value} {dec.candidate or dec.derivation or ''} decided by {dec.by}; state {dec.state_hash}")
        prov = Provenance(status=status, source=meta.source_file, note=note, timestamp=now_utc(), data=link)
        new_value = {**dist, "provenance": prov.model_dump(mode="json")}
        new_model = set_value(model, target, new_value)
        new_model = new_model.model_copy(update={"approval": Approval(note=f"invalidated: {target} changed from data {dataset_id}")})
        rep, _ = verify(new_model, self.registry)
        if not rep.ok:
            raise DatasetError("El modelo resultante no verifica:\n" + "\n".join(str(i) for i in rep.errors))
        parent = self.project.meta.current_version
        v = self.project.save_version(new_model, message=f"data {dataset_id} -> {target} ({dec.decision.value})", author=by)
        changes = [list(c) for c in diff(model, new_model, ignore_provenance=True)]
        self.project.log(by, "data_apply", request=f"{dataset_id}:{decision_id} -> {target}", change=changes,
                         result=f"v{v} (approval invalidated; was approved: {model.is_approved})")
        self.store.append(dataset_id, ApplyEvent(decision_id=decision_id, project_model_version=v, parent_model_version=parent,
                                                 target=target, target_basis=target_basis.value, conversion=conversion, by=by,
                                                 warnings_acknowledged=ack))
        return {"version": v, "parent": parent, "target": target, "previous": current, "new": dist, "provenance": status.value,
                "warnings": warnings, "was_approved": model.is_approved, "approval": "INVALIDATED (new version, re-approval needed)",
                "changes": changes}

    # ========================================================== reproducibility
    def trace_parameter(self, model: ISMSModel, path: str) -> dict:
        """Reconstruct where a parameter value came from: dataset version + hash + fit + decision."""
        v = get_value(model, path)
        link = (v or {}).get("provenance", {}) or {}
        data = link.get("data")
        if not data:
            return {"path": path, "value": v, "data_link": None}
        out = {"path": path, "value": {k: x for k, x in v.items() if k != "provenance"}, "data_link": data}
        try:
            meta = self.store.meta(data["dataset_id"])
            out["dataset_present"] = True
            out["dataset_hash_matches"] = meta.content_hash == data["content_hash"]
        except DatasetError:
            out["dataset_present"] = False
        return out


def _scale(dist: dict, k: float) -> dict:
    d = dict(dist)
    t = d["dist"]
    if t == "constant":
        d["value"] *= k
    elif t == "empirical":
        d["values"] = [x * k for x in d["values"]]
    elif t in ("normal", "lognormal"):
        d["mean"] *= k
        d["std"] *= k
    elif t == "exponential":
        d["mean"] *= k
    elif t in ("gamma", "weibull"):
        d["scale"] *= k
    elif t == "uniform":
        d["low"] *= k
        d["high"] *= k
    elif t == "triangular":
        d["low"], d["mode"], d["high"] = d["low"] * k, d["mode"] * k, d["high"] * k
    else:  # pragma: no cover
        raise DatasetError(f"No sé escalar '{t}'.")
    if d.get("truncation"):
        tr = dict(d["truncation"])
        for b in ("lower", "upper"):
            if tr.get(b) is not None:
                tr[b] *= k
        d["truncation"] = tr
    return d


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False, default=str)
