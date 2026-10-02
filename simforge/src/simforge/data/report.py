"""DATA PROFILE: the text an engineer reads before deciding (CLI `simforge data inspect`, UI, markdown export)."""

from __future__ import annotations

from typing import Any


def _f(v: Any, unit: str = "") -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4g}{(' ' + unit) if unit else ''}"
    return f"{v}{(' ' + unit) if unit else ''}"


def profile_text(p: dict, fit: dict | None = None) -> str:
    d = p["dataset"]
    m = d["mapping"]
    u = p.get("unit", d["analysis_unit"])
    L: list[str] = []
    if d.get("synthetic"):
        L.append("*** SYNTHETIC TEST DATA — no son medidas de planta ***")
    L += [f"DATASET:      {d['dataset_id']}  {('— ' + d['description']) if d.get('description') else ''}",
          f"SOURCE:       {d['source_file']}" + (f"  | Sheet: {d['sheet']}" if d.get("sheet") else "") + f"  | Column: {m['value']}",
          f"FILE SHA256:  {d['file_sha256'][:16]}…   DATASET HASH: {d['content_hash']}",
          f"QUANTITY:     {d['quantity_type']}  ({p['simulation_use']}: {p['quantity_support']})",
          f"UNIT:         {u}  (normalizado: {d['normalized_unit']})",
          f"BASIS:        {d['basis']}" + (f"  — {d['basis_note']}" if d.get("basis_note") else ""),
          f"OBSERVATIONS: {d['n_rows']}"]
    c = d["counts"]
    L.append(f"VALID: {c.get('VALID', 0)}   WARNING: {c.get('WARNING', 0)}   INVALID: {c.get('INVALID', 0)}   "
             f"REQUIRES_REVIEW: {c.get('REQUIRES_REVIEW', 0)}")
    for n in d.get("import_notes", []):
        L.append(f"  note: {n}")
    for t in d.get("transformations", []):
        L.append(f"  transformation: {t}")
    v = p["validation"]
    for r in v["invalid"][:15]:
        L.append(f"  INVALID row {r['row']}: '{r['original']}' -> {'; '.join(r['issues'])}")
    if len(v["invalid"]) > 15:
        L.append(f"  ... {len(v['invalid']) - 15} INVALID más")
    for r in v["requires_review"][:15]:
        L.append(f"  REQUIRES_REVIEW row {r['row']} (idx {r['index']}): '{r['original']}' -> {'; '.join(r['issues'])}")
    ex = p["exclusions"]
    if ex["excluded_from_fit"] or ex["marked_invalid"]:
        L.append(f"EXCLUDED FROM FIT: {ex['excluded_from_fit']}   MARKED INVALID: {ex['marked_invalid']}")
    for e in ex["log"]:
        L.append(f"  {e['at']} {e['by']}: {e['action']} {e['rows']} ({e.get('method') or 'manual'}) — {e['reason']}")
    for role, g in p.get("groups", {}).items():
        L.append(f"GROUPS by {role}: {g.get('flag')}" + (f" (Kruskal-Wallis p={g['kruskal_wallis_p']:.3g})" if "kruskal_wallis_p" in g else ""))
        for row in g["groups"]:
            L.append(f"  {row['group']:<16} n={row['n']:<5} mean={_f(row['mean'])} median={_f(row['median'])}")
    if "selection_error" in p:
        L.append(f"SELECTION: {p['selection_error']}")
        L.append("STATUS:       REQUIRES_ENGINEER_REVIEW")
        return "\n".join(L)
    if p.get("group") or p.get("pooled"):
        L.append(f"SUBSET: {p.get('group') or 'todos'}{'  (grupos MEZCLADOS por decisión explícita)' if p.get('pooled') else ''}")
    s = p["stats"]
    L.append(f"USED FOR ANALYSIS: n = {s['n']}  ({s['size_class']} [heurística SimForge, no umbral de validez]: {s['size_class_meaning']})")
    if s["n"]:
        L += [f"MEAN:   {_f(s['mean'], u)}   (IC95 {_f(s.get('mean_ci95', [None])[0])} – {_f(s.get('mean_ci95', [None, None])[1])})",
              f"MEDIAN: {_f(s['median'], u)}   STD: {_f(s['std'], u)}   CV: {_f(s['cv'])}",
              f"MIN/MAX: {_f(s['min'])} / {_f(s['max'])}   Q1/Q3: {_f(s['q1'])} / {_f(s['q3'])}   IQR: {_f(s['iqr'])}",
              "PERCENTILES: " + "  ".join(f"P{k}={_f(s[f'p{k}'])}" for k in (5, 10, 25, 50, 75, 90, 95, 99)),
              f"SKEWNESS: {_f(s.get('skewness'))}   EXCESS KURTOSIS: {_f(s.get('kurtosis_excess'))}"]
        b = p.get("bootstrap", {})
        if b.get("evaluated"):
            L.append(f"BOOTSTRAP 95% (seed {b['seed']}): mean {_f(b['mean'][0])}–{_f(b['mean'][1])}  "
                     f"median {_f(b['median'][0])}–{_f(b['median'][1])}  P95 {_f(b['p95'][0])}–{_f(b['p95'][1])}")
        sr = p["serial"]
        L.append(f"ORDER: {p['order']}   LAG-1: {_f(sr.get('lag1'))} -> {sr['flag']} (screening, solo lag 1)   TREND: {p['trend'].get('flag')}")
        o = p["outliers"]
        if o.get("evaluated"):
            L.append(f"POTENTIAL OUTLIERS: {len(o['candidates'])} (IQR fences {_f(o['iqr_fences'][0])}–{_f(o['iqr_fences'][1])}, "
                     f"MAD z>{o['mad_z']}); sin revisar: {o['unreviewed']}")
            for cnd in o["candidates"][:20]:
                L.append(f"  idx {cnd['index']}: {_f(cnd['value'], u)} ({cnd['side']}) {', '.join(cnd['methods'])}")
    if fit:
        L.append("")
        L += fit_text(fit).splitlines()
    L.append(f"STATUS:       {p.get('status', 'REQUIRES_ENGINEER_REVIEW')}")
    return "\n".join(L)


def fit_text(r: dict) -> str:
    u = r["unit"]
    L = [f"STATISTICAL RANKING  (fit {r.get('fit_id')}, n = {r['n']}, {r['size_class']} [heurística SimForge])",
         "  orden por AIC: menor AIC = mejor compromiso estadístico entre candidatos, NO la distribución verdadera; "
         "ΔAIC ≤ 2 = soporte estadístico similar (heurística interpretativa)"]
    L.append(f"  {'#':<3}{'distribution':<13}{'status':<21}{'AIC':>9}{'ΔAIC':>7}{'BIC':>9}{'KS':>7}{'AD':>8}{'CvM':>8}  "
             f"{'P50':>8}{'P95':>8}{'P99':>8}{'P99.9':>8}  warnings")
    for c in r["candidates"]:
        if c.get("aic") is None:
            L.append(f"  {'-':<3}{c['family']:<13}{c['status']:<21}  {c.get('reason', '')}")
            continue
        g, q = c["gof"], c["plausibility"]["fitted_quantiles"]
        w = ",".join(f["code"] for f in c["plausibility"]["flags"] if f["severity"] != "INFO") or "-"
        L.append(f"  {c['rank']:<3}{c['family']:<13}{c['status']:<21}{c['aic']:>9.1f}{c['delta_aic']:>7.2f}{c['bic']:>9.1f}"
                 f"{g['ks_stat']:>7.3f}{g['ad_stat']:>8.2f}{g['cvm_stat']:>8.3f}  {q['P50']:>8.4g}{q['P95']:>8.4g}{q['P99']:>8.4g}"
                 f"{q['P99.9']:>8.4g}  {w}")
    ok = [c for c in r["candidates"] if c.get("aic") is not None]
    if ok:
        obs = ok[0]["plausibility"]["observed_quantiles"]
        L.append(f"  {'':<3}{'OBSERVED':<13}{'':<21}{'':>9}{'':>7}{'':>9}{'':>7}{'':>8}{'':>8}  "
                 + "".join(f"{_f(obs[k]):>8}" for k in ("P50", "P95", "P99", "P99.9")))
    L.append(f"  unidad: {u}. p-valores KS/CvM son NOMINALES (parámetros estimados con los mismos datos): no deciden nada.")
    for c in ok:
        for f in c["plausibility"]["flags"]:
            if f["severity"] != "INFO":
                L.append(f"  [{f['severity']}] {c['family']}: {f['code']} — {f['text']}")
    for c in ok:
        if c["family"] in ("uniform", "triangular"):
            L.append(f"  {c['family']} parámetros: " + "; ".join(f"{k}={_f(v.get('value'))} [{v['source']}: {v['method']}]"
                                                              for k, v in c["parameter_sources"].items()))
    if r.get("bounds"):
        b = r["bounds"]
        L.append(f"  límites declarados ({b['source']}): [{b.get('low')}, {b.get('high')}] — usados solo por uniforme/triangular")
    opts = r["options"]
    e = opts["EMPIRICAL"]
    L.append(f"OPTIONS: DETERMINISTIC mean={_f(opts['DETERMINISTIC']['MEAN'])} median={_f(opts['DETERMINISTIC']['MEDIAN'])} {u}")
    L.append(f"         EMPIRICAL n={e['sample_size']} soporte [{_f(e['observed_min'])}, {_f(e['observed_max'])}] {u}: {e['note']}")
    for w in e.get("warnings", []):
        L.append(f"         [WARNING] {w}")
    s = r.get("suggested")
    if s:
        L.append(f"SUGGESTED CANDIDATE: {s['family']} — {s['status']} — {s['why']}"
                 + (f"; equivalentes: {s['equivalent_alternatives']}" if s["equivalent_alternatives"] else ""))
    else:
        L.append("SUGGESTED CANDIDATE: ninguno (ver notas)")
    for n in r.get("notes", []):
        L.append(f"  note: {n}")
    return "\n".join(L)


def holdout_text(h: dict) -> str:
    u = h["unit"]
    L = [f"HOLDOUT TEMPORAL ({h['train_fraction']:.0%} ajuste / {1 - h['train_fraction']:.0%} validación, propuesta, no ley) — "
         f"orden: {h['order']}; corte en la fila {h['split_at_row']}",
         f"  n ajuste = {h['n_train']}, n validación = {h['n_test']}; validación observada: media {_f(h['test_observed']['mean'])}, "
         f"P50 {_f(h['test_observed']['P50'])}, P95 {_f(h['test_observed']['P95'])} {u}"]
    tt = h["train_vs_test"]
    L.append(f"  ajuste vs validación (KS 2 muestras): D={tt['ks_stat']:.3f} p={tt['p_value']:.3g} -> {tt['flag']}"
             + (f" — {tt['meaning']}" if tt["meaning"] else ""))
    L.append(f"  {'familia':<12}{'loglik/obs':>11}{'KS valid.':>10}{'p':>8}{'media pred':>11}{'P50 pred':>10}{'P95 pred':>10}")
    for c in sorted(h["candidates"], key=lambda c: c.get("holdout_rank", 99)):
        if c["status"] != "OK":
            L.append(f"  {c['family']:<12} {c['status']}: {c.get('reason', '')}")
            continue
        ll = f"{c['test_mean_loglik']:.3f}" if c["test_mean_loglik"] is not None else "−∞"
        L.append(f"  {c['family']:<12}{ll:>11}{c['test_ks_stat']:>10.3f}{c['test_ks_p']:>8.3g}{c['predicted']['mean']:>11.4g}"
                 f"{c['predicted']['P50']:>10.4g}{c['predicted']['P95']:>10.4g}")
    e = h["empirical_train"]
    L.append(f"  empírica (ajuste): P50 {_f(e['P50'])} P95 {_f(e['P95'])} máx {_f(e['max'])}; {e['test_above_train_max']} valores de "
             "validación por encima del máximo de ajuste")
    L.append("  p-valores de validación: parámetros no estimados con estos datos (no optimistas), pero suponen independencia.")
    return "\n".join(L)
