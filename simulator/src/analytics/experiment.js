// Diseño de experimentos: réplicas independientes, agregación con intervalos de
// confianza, análisis de contribución de cada fuente de variabilidad y
// comparación de escenarios con números aleatorios comunes.

import { Simulation } from '../engine/simulator.js';
import { normalizeModel, validateModel } from '../model/schema.js';
import { replicationKpis, KPI_LABELS } from './kpis.js';
import { summarize, pairedDifference, histogram, meanOf, sdOf } from './stats.js';
import { moments } from '../stochastic/distributions.js';
import { studentTQuantile } from '../stochastic/special.js';

function lite(s) {
  const { values, ...rest } = s;
  return rest;
}

function aggregateList(lists, confidence) {
  const byId = new Map();
  for (const list of lists) {
    for (const item of list) {
      if (!byId.has(item.id)) byId.set(item.id, []);
      byId.get(item.id).push(item);
    }
  }
  return [...byId.entries()].map(([id, items]) => {
    const out = { id, name: items[0].name };
    for (const [k, v] of Object.entries(items[0])) {
      if (typeof v === 'number') out[k] = lite(summarize(items.map((i) => i[k]), confidence, 0));
      else if (k === 'type') out[k] = v;
      else if (k === 'byType') {
        const keys = new Set(items.flatMap((i) => Object.keys(i.byType)));
        out.byType = Object.fromEntries([...keys].map((t) => [t, meanOf(items.map((i) => i.byType[t] || 0))]));
      }
    }
    return out;
  });
}

/** Ejecuta las réplicas y devuelve KPIs agregados con su incertidumbre. */
export function runExperiment(rawModel, opts = {}) {
  const t0 = Date.now();
  const { errors, warnings } = validateModel(rawModel);
  if (errors.length) {
    const err = new Error('El modelo tiene errores');
    err.details = errors;
    throw err;
  }
  const model = normalizeModel(rawModel);
  const n = Math.max(1, Math.floor(opts.replications ?? model.settings.replications));
  const conf = model.settings.confidence;
  const target = model.settings.targetRelativePrecision;
  const reps = [];
  let trace = null;
  let layout = null;
  for (let r = 0; r < n; r++) {
    const wantTrace = opts.trace && r === 0;
    const raw = new Simulation(model, {
      replication: r,
      trace: wantTrace,
      traceHours: opts.traceHours,
      deterministic: opts.deterministic,
    }).run();
    if (wantTrace) {
      trace = raw.trace;
      layout = raw.layout;
    }
    reps.push(replicationKpis(raw, model));
    opts.onProgress?.((r + 1) / n);
  }

  const scalars = {};
  for (const key of Object.keys(reps[0].scalars)) scalars[key] = summarize(reps.map((r) => r.scalars[key]), conf, target);

  const bottleneckCount = {};
  for (const r of reps) if (r.bottleneck) bottleneckCount[r.bottleneck] = (bottleneckCount[r.bottleneck] || 0) + 1;
  const stations = aggregateList(reps.map((r) => r.stations), conf).map((s) => ({
    ...s,
    bottleneckProbability: (bottleneckCount[s.id] || 0) / n,
  }));

  const pooledLt = reps.flatMap((r) => r.leadTimeValues);
  const hours = reps[0].hourly.length;
  const tq = n > 1 ? studentTQuantile(n - 1, conf) : 0;
  const hourly = Array.from({ length: hours }, (_, h) => {
    const xs = reps.map((r) => r.hourly[h]);
    const m = meanOf(xs);
    const hw = n > 1 ? (tq * sdOf(xs)) / Math.sqrt(n) : 0;
    return { hour: h, mean: m, low: m - hw, high: m + hw, min: Math.min(...xs), max: Math.max(...xs) };
  });
  const wipSeries = reps[0].wipSeries.map(([t], i) => {
    const xs = reps.map((r) => r.wipSeries[i]?.[1]).filter(Number.isFinite);
    return { t, mean: meanOf(xs), min: Math.min(...xs), max: Math.max(...xs) };
  });

  const demand = model.settings.demandPerHour;
  const risk = {
    probabilityMeetDemand: demand ? reps.filter((r) => r.scalars.throughputPerHour >= demand).length / n : null,
    throughputP10: scalars.throughputPerHour.p10,
    throughputP90: scalars.throughputPerHour.p90,
    leadTimeP95Pooled: pooledLt.length ? [...pooledLt].sort((a, b) => a - b)[Math.floor(pooledLt.length * 0.95)] : null,
  };

  const precisionWarnings = Object.entries(scalars)
    .filter(([k, s]) => ['throughputPerHour', 'leadTimeMean', 'wipMean'].includes(k) && s.replicationsNeeded > n)
    .map(([k, s]) => `${KPI_LABELS[k].label}: precisión ±${(s.relativePrecision * 100).toFixed(1)} %; harían falta ${s.replicationsNeeded} réplicas para ±${(target * 100).toFixed(0)} %`);

  return {
    meta: {
      modelId: model.id,
      modelName: model.name,
      replications: n,
      confidence: conf,
      targetRelativePrecision: target,
      horizonHours: model.settings.horizonHours,
      warmupHours: model.settings.warmupHours,
      demandPerHour: demand,
      runtimeMs: Date.now() - t0,
      createdAt: new Date().toISOString(),
      warnings: [...warnings, ...precisionWarnings],
    },
    scalars,
    stations,
    operators: aggregateList(reps.map((r) => r.operators), conf),
    machines: aggregateList(reps.map((r) => r.machines), conf),
    operations: aggregateList(reps.map((r) => r.operations), conf).map((o) => {
      const def = model.operations.find((x) => x.id === o.id);
      return { ...o, specified: def ? moments(def.duration) : null };
    }),
    hourly,
    wipSeries,
    leadTimeHistogram: histogram(pooledLt, 30),
    risk,
    trace,
    layout,
  };
}

/** Fuentes de variabilidad que pueden anularse individualmente. */
export function variabilitySources(rawModel) {
  const m = normalizeModel(rawModel);
  const sources = [];
  const usedOps = new Set(m.stations.flatMap((s) => [...s.operationIds, s.setup?.operationId, s.transportOperationId].filter(Boolean)));
  for (const s of m.stations) for (const id of s.operationIds) {
    const op = m.operations.find((o) => o.id === id);
    if (op?.isInspection && op.quality.reworkOperationId) usedOps.add(op.quality.reworkOperationId);
  }
  for (const op of m.operations) {
    if (!usedOps.has(op.id)) continue;
    const { sd } = moments(op.duration);
    if (sd > 0 || op.distanceBased) sources.push({ key: `op:${op.id}`, label: `Tiempo de «${op.name}»` });
  }
  if (m.operations.some((o) => o.modifiers.interruptions && o.interruptions?.ratePerHour > 0)) sources.push({ key: 'interruptions', label: 'Interrupciones y microparadas' });
  if (m.operators.length) sources.push({ key: 'learning', label: 'Curva de aprendizaje' }, { key: 'fatigue', label: 'Fatiga' });
  if (m.machines.some((x) => x.failures?.enabled)) sources.push({ key: 'failures', label: 'Averías de máquina' });
  if (m.arrivals.mode === 'interarrival') sources.push({ key: 'arrivals', label: 'Llegadas' });
  return sources;
}

/**
 * Análisis de contribución: anula cada fuente de variabilidad (sustituyéndola por
 * su media) y mide el efecto pareado sobre los KPIs. Responde a «¿qué
 * variabilidad me está costando más producción?».
 */
export function contributionAnalysis(rawModel, opts = {}) {
  const model = normalizeModel(rawModel);
  const n = Math.max(2, opts.replications ?? Math.min(5, model.settings.replications));
  const conf = model.settings.confidence;
  const keys = ['throughputPerHour', 'leadTimeMean', 'wipMean'];
  const runSet = (det) => {
    const out = [];
    for (let r = 0; r < n; r++) {
      out.push(replicationKpis(new Simulation(model, { replication: r, deterministic: det }).run(), model).scalars);
    }
    return out;
  };
  const sources = variabilitySources(model);
  const total = sources.length + 2;
  let done = 0;
  const tick = () => opts.onProgress?.(++done / total);
  const base = runSet(null);
  tick();
  const results = [];
  for (const src of [...sources, { key: '*', label: 'Toda la variabilidad (modelo determinista)' }]) {
    const alt = runSet(new Set([src.key]));
    tick();
    const effects = {};
    for (const k of keys) effects[k] = lite(pairedDifference(base.map((x) => x[k]), alt.map((x) => x[k]), conf));
    results.push({ ...src, effects });
  }
  const all = results.pop();
  results.sort((a, b) => Math.abs(b.effects.throughputPerHour.mean) - Math.abs(a.effects.throughputPerHour.mean));
  return {
    replications: n,
    baseline: Object.fromEntries(keys.map((k) => [k, lite(summarize(base.map((x) => x[k]), conf, 0))])),
    sources: results,
    allDeterministic: all,
  };
}

/** Compara dos escenarios con las mismas semillas (diferencias pareadas). */
export function compareScenarios(modelA, modelB, opts = {}) {
  const a = normalizeModel(modelA);
  const b = normalizeModel({ ...modelB, settings: { ...modelB.settings, seed: a.settings.seed } });
  const n = Math.max(2, opts.replications ?? a.settings.replications);
  const conf = a.settings.confidence;
  const run = (m) => Array.from({ length: n }, (_, r) => replicationKpis(new Simulation(m, { replication: r }).run(), m).scalars);
  const ra = run(a);
  const rb = run(b);
  const kpis = {};
  for (const k of Object.keys(ra[0])) {
    kpis[k] = {
      a: lite(summarize(ra.map((x) => x[k]), conf, 0)),
      b: lite(summarize(rb.map((x) => x[k]), conf, 0)),
      difference: lite(pairedDifference(ra.map((x) => x[k]), rb.map((x) => x[k]), conf)),
    };
  }
  return { replications: n, a: { id: a.id, name: a.name }, b: { id: b.id, name: b.name }, kpis };
}
