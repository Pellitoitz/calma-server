"""Reports: every number comes from engine results; text is deterministic.

Output: Markdown (source), HTML (printable -> PDF from the browser), CSV.
Native PDF/PowerPoint: NOT IMPLEMENTED yet.
"""

from __future__ import annotations

import csv
import html
import io
import re
from datetime import datetime, timezone

from ..analytics.kpis import OEE_DEFINITION, metric_info
from ..domain.isms import ISMSModel
from ..experiments.runner import ExperimentResult, SimulationResult
from ..validation.verifier import VerificationReport

HEADLINE = ["units_completed", "throughput_per_hour", "avg_wip", "avg_lead_time_s", "p90_lead_time_s", "units_scrapped"]


def fmt(key: str, v: float | None) -> str:
    if v is None or v != v:
        return "—"
    _, unit, _ = metric_info(key)
    if key.endswith("_s"):
        return f"{v:,.0f} s" if v < 120 else f"{v / 60:,.1f} min"
    if unit == "" and key.split(".")[-1] in ("utilization", "blocked", "starved", "waiting_resource", "down", "yield",
                                              "working", "walking", "oee", "availability", "performance", "quality"):
        return f"{v:.1%}"
    if float(v).is_integer():
        return f"{int(v):,}"
    return f"{v:,.2f}"


def flow_text(model: ISMSModel) -> str:
    order, cur, seen = [], next((n.id for n in model.nodes if n.component == "source"), None), set()
    while cur and cur not in seen:
        seen.add(cur)
        n = model.node(cur)
        order.append(n.name or n.id)
        succ = model.successors(cur)
        cur = succ[0].target if len(succ) == 1 else None
        if len(succ) > 1:
            order.append("{" + " | ".join(f"{e.target} ({e.probability if isinstance(e.probability, str) else format(e.probability, '.0%')})"
                                          for e in succ) + "}")
    return " → ".join(order)


def kpi_rows(res: SimulationResult, keys: list[str] | None = None) -> list[dict]:
    rows = []
    for k, st in res.kpis.stats.items():
        if keys and k not in keys:
            continue
        label, unit, definition = metric_info(k)
        rows.append({"metric": k, "label": label, "unit": unit, "mean": st.mean, "std": st.std, "min": st.min,
                     "max": st.max, "ci95_low": st.ci95_low, "ci95_high": st.ci95_high, "n": st.n, "definition": definition})
    return rows


def results_csv(res: SimulationResult) -> str:
    buf = io.StringIO()
    rows = kpi_rows(res)
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def experiment_csv(exp: ExperimentResult, metrics: list[str] | None = None) -> str:
    metrics = metrics or ["throughput_per_hour", "units_completed", "avg_wip", "avg_lead_time_s"]
    rows = exp.table(metrics)
    keys: list[str] = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=keys)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def build_markdown(model: ISMSModel, report: VerificationReport, run: SimulationResult | None,
                   experiment: ExperimentResult | None = None, project_name: str = "") -> str:
    L: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L += [f"# Simulation report — {model.meta.name}", "", f"*Project:* {project_name} · *Generated:* {now} · "
          f"*Model readiness:* **{report.readiness.value}**", ""]
    if not model.is_approved:
        L += ["> ⚠️ **Model not approved by an engineer.** Results show the behaviour of the model, "
              "not necessarily of the real system (validation pending).", ""]

    # 1. executive summary (facts only)
    L += ["## 1. Executive summary", ""]
    if run:
        k = run.kpis
        n = k.n
        ci = k.stats["throughput_per_hour"]
        ci_txt = f" (95% CI {ci.ci95_low:.2f}–{ci.ci95_high:.2f}, {n} replications)" if n > 1 else " (1 replication, deterministic or indicative)"
        L.append(f"- Throughput: **{k.mean('throughput_per_hour'):.2f} units/h**{ci_txt}.")
        L.append(f"- Units completed in the measured window: **{fmt('units_completed', k.mean('units_completed'))}**; "
                 f"average WIP **{k.mean('avg_wip'):.2f}**; average lead time **{fmt('avg_lead_time_s', k.mean('avg_lead_time_s'))}**.")
        for f in run.findings:
            if f.code in ("THEORETICAL_CONSTRAINT", "BOTTLENECK_CANDIDATE", "SANITY_THROUGHPUT", "DEMAND_EXCEEDS_CAPACITY"):
                L.append(f"- {f.message}")
    else:
        L.append("- No simulation run attached.")
    if experiment:
        best = _best_scenarios(experiment)
        if best:
            top = best[0].result.kpis.mean("throughput_per_hour")  # type: ignore[union-attr]
            desc = "; ".join(", ".join(f"{k.split('.')[-2]}={v}" for k, v in s.factors.items()) for s in best[:5])
            tie = f" ({len(best)} scenarios within 0.5% of the maximum — choose on secondary criteria such as WIP or cost)" if len(best) > 1 else ""
            L.append(f"- Experiment '{experiment.spec.name}': max mean throughput {top:.2f} u/h at {desc}{tie}. "
                     "Check confidence intervals before concluding.")
    L.append("")

    # 2. current state / model
    L += ["## 2. Model", "", f"**Flow:** {flow_text(model)}", "",
          f"Horizon: {model.simulation.horizon.value:g} {model.simulation.horizon.unit} · warm-up: "
          f"{model.simulation.warmup.value:g} {model.simulation.warmup.unit} · type: {model.simulation.kind} · "
          f"replications: {model.simulation.replications}", ""]
    rows = []
    for n in model.nodes:
        if n.component in ("source", "sink"):
            continue
        p = n.params
        pt = p.get("process_time")
        pt_txt = "—"
        if isinstance(pt, dict):
            prov = (pt.get("provenance") or {}).get("status", "")
            vals = ", ".join(f"{k}={v}" for k, v in pt.items() if k not in ("dist", "unit", "provenance"))
            pt_txt = f"{pt['dist']}({vals}) {pt.get('unit', 's')}" + (f" [{prov}]" if prov else "")
        if p.get("work_units", 1) != 1:
            agg = p.get("work_units_aggregation")
            pt_txt += f" × {p['work_units']} units ({agg or 'UNDECLARED: legacy scale_sample k·X'})"
        res = ", ".join(r["resource"] for r in p.get("resources", []))
        rows.append([n.name or n.id, f"`{n.component}`", pt_txt, str(p.get("capacity", 1 if n.component != "buffer" else "∞")),
                     res or "—", str(n.priority) if res else "—"])
    L += [_table(["Node", "Component", "Process time", "Capacity", "Resources", "Priority"], rows), ""]
    if model.resources:
        L += [_table(["Resource", "Kind", "Qty", "Dispatch"],
                     [[r.name or r.id, r.kind.value, str(r.quantity), r.dispatch.value] for r in model.resources]), ""]

    if model.parameters:
        L += ["**Model parameters**", "", _table(["Parameter", "Value", "Unit", "Role", "Source / status", "Description"],
              [[f"`{p.id}`", "⛔ REQUIRED" if p.value is None else f"{p.value:g}", p.unit or "", p.role,
                (f"{p.provenance.status.value}" + (f" ({p.provenance.source})" if p.provenance.source else "")) if p.provenance else "—",
                p.description] for p in model.parameters]), ""]

    # 3. assumptions & missing data
    L += ["## 3. Assumptions and missing data", ""]
    if model.assumptions:
        L += [f"- {'✅' if a.accepted else '❓'} {a.text}" + (f" (`{a.path}`)" if a.path else "") for a in model.assumptions]
    else:
        L.append("- No recorded assumptions.")
    for m in model.missing:
        L.append(f"- ⛔ MISSING{'' if m.required else ' (optional)'}: {m.question}")
    L.append("")

    # 4. verification & validation
    L += ["## 4. Verification and validation", "",
          "*Verification* = the model is built correctly (automatic). *Validation* = the model represents the real "
          "system well enough (engineer).", ""]
    L.append(f"- Verification: {report.summary()}")
    for i in report.errors + report.warnings:
        L.append(f"  - {i.level.value.upper()} {i.code}: {i.message}")
    L.append(f"- Engineer approval: **{'YES — ' + str(model.approval.by) if model.is_approved else 'NO'}**")
    L.append("")

    # 5. results
    if run:
        L += ["## 5. Results", "", _table(["KPI", "Mean", "Std", "95% CI", "n"],
              [[metric_info(r['metric'])[0], fmt(r["metric"], r["mean"]), fmt(r["metric"], r["std"]) if r["n"] > 1 else "—",
                f"{fmt(r['metric'], r['ci95_low'])} – {fmt(r['metric'], r['ci95_high'])}" if r["n"] > 1 else "—", str(r["n"])]
               for r in kpi_rows(run, HEADLINE)]), ""]
        node_rows = []
        for n in model.nodes:
            if f"node.{n.id}.utilization" in run.kpis.stats:
                vals = [fmt(f"node.{n.id}.{m}", run.kpis.mean(f"node.{n.id}.{m}"))
                        for m in ("utilization", "waiting_resource", "blocked", "starved", "down", "oee")]
                node_rows.append([n.name or n.id, *vals])
        if node_rows:
            L += ["### Stations", "", _table(["Station", "Busy", "Wait resource", "Blocked", "Starved", "Down", "OEE*"], node_rows), "",
                  f"*{OEE_DEFINITION}", ""]
        res_rows = [[r.name or r.id, fmt("resource.x.utilization", run.kpis.mean(f"resource.{r.id}.utilization")),
                     fmt("resource.x.walking", run.kpis.mean(f"resource.{r.id}.walking"))] for r in model.resources]
        if res_rows:
            L += ["### Resources", "", _table(["Resource", "Utilization", "Walking"], res_rows), ""]
        L += ["## 6. Diagnostics (rule-based, with evidence)", ""]
        for f in run.findings:
            ev = ", ".join(f"{k}={v}" for k, v in f.evidence.items())
            L.append(f"- **{f.code}** [{f.severity}] {f.message}" + (f"  \n  *Evidence:* {ev}" if ev else ""))
        L.append("")

    if experiment:
        metrics = ["throughput_per_hour", "avg_wip", "avg_lead_time_s"]
        rows = []
        for s in experiment.scenarios:
            f = ", ".join(f"{k.split('.')[-2] if k.endswith(('capacity', 'quantity', 'value')) else k}={v}" for k, v in s.factors.items())
            if s.result:
                rows.append([str(s.index), f] + [fmt(m, s.result.kpis.mean(m)) for m in metrics])
            else:
                rows.append([str(s.index), f, "ERROR", s.error or "", ""])
        L += [f"## 7. Experiment: {experiment.spec.name}", "", _table(["#", "Factors", "Throughput/h", "Avg WIP", "Avg lead time"], rows), ""]

    L += ["## 8. Economic impact", "", "NOT IMPLEMENTED in v0.1 (economics layer pending). No monetary figures are reported.", "",
          "## 9. Risks and next steps", ""]
    if not model.is_approved:
        L.append("- Validate the model against real data (throughput, WIP, utilisations) and approve it.")
    if any(not a.accepted for a in model.assumptions):
        L.append("- Confirm or correct the open assumptions listed in section 3.")
    if run and run.kpis.n < 10 and any(i.code == "FEW_REPLICATIONS" for i in report.warnings):
        L.append("- Increase replications (stochastic model).")
    L.append("- Recommendations must be evaluated as scenarios (compare against baseline) before acting.")
    if run:
        L += ["", "## Reproducibility", "", f"model_hash `{run.model_hash}` · engine {run.engine} {run.engine_version} · "
              f"app {run.app_version} · seeds {run.seeds[0]}..{run.seeds[-1]} · components "
              + ", ".join(f"{k}@{v}" for k, v in sorted(run.component_versions.items())) + f" · run `{run.run_id}`"]
    return "\n".join(L) + "\n"


def _best_scenarios(exp: ExperimentResult, metric: str = "throughput_per_hour", tol: float = 0.005):
    ok = [s for s in exp.scenarios if s.result]
    if not ok:
        return []
    top = max(s.result.kpis.mean(metric) for s in ok)  # type: ignore[union-attr]
    return [s for s in ok if s.result.kpis.mean(metric) >= top * (1 - tol)]  # type: ignore[union-attr]


def markdown_to_html(md: str, title: str = "SimForge report") -> str:
    """Tiny converter for our own report subset (headings, tables, lists, quotes, bold/italic/code)."""
    def inline(t: str) -> str:
        t = html.escape(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)\*(?!\w)", r"<em>\1</em>", t)
        return re.sub(r"`(.+?)`", r"<code>\1</code>", t)

    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("#"):
            lvl = len(ln) - len(ln.lstrip("#"))
            out.append(f"<h{lvl}>{inline(ln[lvl:].strip())}</h{lvl}>")
        elif ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.fullmatch(r"\|(---\|)+", lines[i]):
                    rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in rows[0]) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:]) + "</tbody></table>")
            continue
        elif ln.lstrip().startswith("- "):
            items = []
            while i < len(lines) and lines[i].lstrip().startswith("- "):
                items.append(inline(lines[i].lstrip()[2:]).replace("  \n", "<br>"))
                i += 1
            out.append("<ul>" + "".join(f"<li>{x}</li>" for x in items) + "</ul>")
            continue
        elif ln.startswith(">"):
            out.append(f"<blockquote>{inline(ln[1:].strip())}</blockquote>")
        elif ln.strip():
            out.append(f"<p>{inline(ln)}</p>")
        i += 1
    css = ("body{font-family:system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 16px;color:#1f2328;line-height:1.45}"
           "table{border-collapse:collapse;margin:.5rem 0 1rem;font-size:.9rem}td,th{border:1px solid #d0d7de;padding:4px 8px;text-align:left}"
           "th{background:#f6f8fa}blockquote{border-left:4px solid #d4a72c;background:#fff8c5;margin:0;padding:.5rem 1rem}"
           "code{background:#f6f8fa;padding:0 3px}h1{border-bottom:2px solid #d0d7de}@media print{body{margin:0}}")
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{css}</style></head><body>{''.join(out)}</body></html>"
