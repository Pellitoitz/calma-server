// Ajuste de distribuciones a partir de tiempos cronometrados (estudio de tiempos).
// Estima parámetros por máxima verosimilitud o momentos y ordena los candidatos
// por el estadístico de Kolmogorov-Smirnov.

import { cdf, moments } from './distributions.js';
import { ksPValue } from './special.js';

export function parseSamples(input) {
  if (Array.isArray(input)) return input.map(Number).filter(Number.isFinite);
  return String(input)
    .split(/[\s;,\t]+/)
    .map((t) => Number(t.replace(',', '.')))
    .filter(Number.isFinite);
}

export function summary(values) {
  const n = values.length;
  const sorted = [...values].sort((a, b) => a - b);
  const m = values.reduce((a, b) => a + b, 0) / n;
  const v = n > 1 ? values.reduce((a, b) => a + (b - m) ** 2, 0) / (n - 1) : 0;
  return { n, mean: m, sd: Math.sqrt(v), min: sorted[0], max: sorted[n - 1], sorted };
}

function ksStatistic(spec, sorted) {
  const n = sorted.length;
  let d = 0;
  for (let i = 0; i < n; i++) {
    const f = cdf(spec, sorted[i]);
    d = Math.max(d, Math.abs(f - i / n), Math.abs((i + 1) / n - f));
  }
  return d;
}

function fitWeibull(values) {
  const logs = values.map(Math.log);
  const meanLog = logs.reduce((a, b) => a + b, 0) / values.length;
  const g = (k) => {
    let a = 0;
    let b = 0;
    for (let i = 0; i < values.length; i++) {
      const xk = Math.pow(values[i], k);
      a += xk * logs[i];
      b += xk;
    }
    return a / b - 1 / k - meanLog;
  };
  let lo = 0.05;
  let hi = 100;
  for (let i = 0; i < 100; i++) {
    const mid = (lo + hi) / 2;
    if (g(mid) > 0) hi = mid;
    else lo = mid;
  }
  const k = (lo + hi) / 2;
  const scale = Math.pow(values.reduce((a, x) => a + Math.pow(x, k), 0) / values.length, 1 / k);
  return { type: 'weibull', shape: k, scale, location: 0 };
}

/** Ajusta varias familias y las devuelve ordenadas de mejor a peor. */
export function fitDistributions(input) {
  const values = parseSamples(input);
  if (values.length < 5) throw new Error('Se necesitan al menos 5 observaciones para ajustar');
  const st = summary(values);
  const positive = st.min > 0;
  const candidates = [];
  const range = st.max - st.min || Math.abs(st.mean) * 0.01 || 1;
  const margin = range / (st.n - 1);

  candidates.push({ type: 'normal', mean: st.mean, sd: st.sd });
  candidates.push({ type: 'uniform', min: st.min - margin / 2, max: st.max + margin / 2 });
  {
    const a = st.min - margin / 2;
    const b = st.max + margin / 2;
    const c = Math.min(b, Math.max(a, 3 * st.mean - a - b));
    candidates.push({ type: 'triangular', min: a, mode: c, max: b });
    const pc = Math.min(b, Math.max(a, (6 * st.mean - a - b) / 4));
    candidates.push({ type: 'pert', min: a, mode: pc, max: b, lambda: 4 });
  }
  if (positive) {
    const logs = values.map(Math.log);
    const mu = logs.reduce((a, b) => a + b, 0) / st.n;
    const s2 = logs.reduce((a, b) => a + (b - mu) ** 2, 0) / st.n;
    const lm = Math.exp(mu + s2 / 2);
    candidates.push({ type: 'lognormal', mean: lm, sd: lm * Math.sqrt(Math.exp(s2) - 1) });
    // gamma: aproximación MLE de Minka
    const s = Math.log(st.mean) - mu;
    const k = s > 0 ? (3 - s + Math.sqrt((s - 3) ** 2 + 24 * s)) / (12 * s) : 1e6;
    candidates.push({ type: 'gamma', mean: st.mean, sd: st.mean / Math.sqrt(k) });
    candidates.push({ type: 'exponential', mean: st.mean });
    try {
      candidates.push(fitWeibull(values));
    } catch {
      /* sin ajuste Weibull */
    }
  }

  const results = candidates
    .filter((c) => Object.values(c).every((v) => typeof v !== 'number' || Number.isFinite(v)))
    .map((spec) => {
      const d = ksStatistic(spec, st.sorted);
      return { spec: roundSpec(spec), ks: d, pValue: ksPValue(d, st.n), ...moments(spec) };
    })
    .sort((a, b) => a.ks - b.ks);

  return {
    summary: { n: st.n, mean: st.mean, sd: st.sd, min: st.min, max: st.max, cv: st.sd / st.mean },
    results,
    best: results[0],
  };
}

function roundSpec(spec) {
  const out = {};
  for (const [k, v] of Object.entries(spec)) out[k] = typeof v === 'number' ? Number(v.toPrecision(5)) : v;
  return out;
}
