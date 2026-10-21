// Estadística descriptiva e inferencial para resultados de simulación.

import { studentTQuantile } from '../stochastic/special.js';

export function meanOf(xs) {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : NaN;
}

export function sdOf(xs) {
  if (xs.length < 2) return 0;
  const m = meanOf(xs);
  return Math.sqrt(xs.reduce((a, x) => a + (x - m) ** 2, 0) / (xs.length - 1));
}

export function quantile(xs, q) {
  if (!xs.length) return NaN;
  const s = [...xs].sort((a, b) => a - b);
  const pos = (s.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return s[lo] + (s[hi] - s[lo]) * (pos - lo);
}

/**
 * Resumen con intervalo de confianza t de Student sobre réplicas independientes,
 * precisión relativa y réplicas necesarias para alcanzar la precisión objetivo.
 */
export function summarize(values, confidence = 0.95, targetRelativePrecision = 0.05) {
  const xs = values.filter(Number.isFinite);
  const n = xs.length;
  const m = meanOf(xs);
  const s = sdOf(xs);
  const t = n > 1 ? studentTQuantile(n - 1, confidence) : NaN;
  const hw = n > 1 ? (t * s) / Math.sqrt(n) : NaN;
  const rel = m !== 0 && Number.isFinite(hw) ? hw / Math.abs(m) : NaN;
  let needed = null;
  if (n > 1 && Number.isFinite(rel) && targetRelativePrecision > 0) {
    needed = rel <= targetRelativePrecision ? n : Math.ceil(n * (rel / targetRelativePrecision) ** 2);
  }
  return {
    n,
    mean: m,
    sd: s,
    cv: m ? s / Math.abs(m) : NaN,
    ciLow: m - hw,
    ciHigh: m + hw,
    halfWidth: hw,
    relativePrecision: rel,
    replicationsNeeded: needed,
    min: n ? Math.min(...xs) : NaN,
    max: n ? Math.max(...xs) : NaN,
    p10: quantile(xs, 0.1),
    p50: quantile(xs, 0.5),
    p90: quantile(xs, 0.9),
    values: xs,
  };
}

/** Comparación pareada (números aleatorios comunes) entre dos series de réplicas. */
export function pairedDifference(a, b, confidence = 0.95) {
  const n = Math.min(a.length, b.length);
  const d = [];
  for (let i = 0; i < n; i++) if (Number.isFinite(a[i]) && Number.isFinite(b[i])) d.push(b[i] - a[i]);
  const s = summarize(d, confidence, 0);
  return {
    ...s,
    significant: s.n > 1 && (s.ciLow > 0 || s.ciHigh < 0),
    relative: meanOf(a) ? s.mean / Math.abs(meanOf(a)) : NaN,
  };
}

export function histogram(values, bins = 30) {
  const xs = values.filter(Number.isFinite);
  if (!xs.length) return { edges: [], counts: [] };
  let lo = Math.min(...xs);
  let hi = Math.max(...xs);
  if (hi === lo) {
    lo -= 0.5;
    hi += 0.5;
  }
  const w = (hi - lo) / bins;
  const counts = new Array(bins).fill(0);
  for (const x of xs) counts[Math.min(bins - 1, Math.floor((x - lo) / w))]++;
  return { edges: Array.from({ length: bins + 1 }, (_, i) => lo + i * w), counts, n: xs.length };
}
