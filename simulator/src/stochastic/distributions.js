// Catálogo de distribuciones de probabilidad para tiempos, velocidades, fallos, etc.
//
// Una distribución se describe con un objeto JSON serializable:
//   { type: 'lognormal', mean: 60, sd: 9, truncate: { min: 30, max: 120 } }
// Todas las funciones son puras: sample(spec, rng), mean(spec), sd(spec), cdf(spec, x).

import { gammaFn, normalCdf, gammaP, betaI } from './special.js';
import { RandomStream } from './rng.js';

export const DISTRIBUTIONS = {
  constant: {
    label: 'Constante (determinista)',
    params: [{ key: 'value', label: 'Valor' }],
  },
  uniform: {
    label: 'Uniforme',
    params: [
      { key: 'min', label: 'Mínimo' },
      { key: 'max', label: 'Máximo' },
    ],
  },
  triangular: {
    label: 'Triangular',
    params: [
      { key: 'min', label: 'Mínimo' },
      { key: 'mode', label: 'Más probable' },
      { key: 'max', label: 'Máximo' },
    ],
  },
  pert: {
    label: 'Beta-PERT',
    params: [
      { key: 'min', label: 'Optimista' },
      { key: 'mode', label: 'Más probable' },
      { key: 'max', label: 'Pesimista' },
      { key: 'lambda', label: 'Forma λ', default: 4 },
    ],
  },
  normal: {
    label: 'Normal',
    params: [
      { key: 'mean', label: 'Media' },
      { key: 'sd', label: 'Desv. típica' },
    ],
  },
  lognormal: {
    label: 'Lognormal',
    params: [
      { key: 'mean', label: 'Media' },
      { key: 'sd', label: 'Desv. típica' },
    ],
  },
  exponential: {
    label: 'Exponencial',
    params: [{ key: 'mean', label: 'Media' }],
  },
  gamma: {
    label: 'Gamma',
    params: [
      { key: 'mean', label: 'Media' },
      { key: 'sd', label: 'Desv. típica' },
    ],
  },
  erlang: {
    label: 'Erlang',
    params: [
      { key: 'mean', label: 'Media' },
      { key: 'k', label: 'Fases k' },
    ],
  },
  weibull: {
    label: 'Weibull',
    params: [
      { key: 'shape', label: 'Forma β' },
      { key: 'scale', label: 'Escala η' },
      { key: 'location', label: 'Localización γ', default: 0 },
    ],
  },
  beta: {
    label: 'Beta (escalada)',
    params: [
      { key: 'alpha', label: 'α' },
      { key: 'beta', label: 'β' },
      { key: 'min', label: 'Mínimo' },
      { key: 'max', label: 'Máximo' },
    ],
  },
  empirical: {
    label: 'Empírica (datos medidos)',
    params: [{ key: 'values', label: 'Valores observados', kind: 'list' }],
  },
};

const num = (v, d = NaN) => (typeof v === 'number' && Number.isFinite(v) ? v : d);

/** Devuelve la lista de errores de una especificación (vacía si es válida). */
export function validate(spec) {
  const errors = [];
  if (!spec || typeof spec !== 'object') return ['Distribución ausente'];
  const def = DISTRIBUTIONS[spec.type];
  if (!def) return [`Tipo de distribución desconocido: ${spec.type}`];
  for (const p of def.params) {
    if (p.kind === 'list') {
      if (!Array.isArray(spec[p.key]) || spec[p.key].length === 0) errors.push(`${p.label}: lista vacía`);
      else if (spec[p.key].some((v) => !Number.isFinite(v))) errors.push(`${p.label}: valores no numéricos`);
    } else if (p.default === undefined && !Number.isFinite(spec[p.key])) {
      errors.push(`${p.label}: debe ser un número`);
    }
  }
  if (errors.length) return errors;
  const s = spec;
  switch (s.type) {
    case 'uniform':
      if (s.max < s.min) errors.push('Máximo < mínimo');
      break;
    case 'triangular':
    case 'pert':
      if (!(s.min <= s.mode && s.mode <= s.max)) errors.push('Debe cumplirse mínimo ≤ más probable ≤ máximo');
      if (s.max === s.min) errors.push('Rango nulo: usa una constante');
      break;
    case 'normal':
    case 'lognormal':
    case 'gamma':
      if (s.sd < 0) errors.push('Desviación negativa');
      if (s.type !== 'normal' && s.mean <= 0) errors.push('La media debe ser > 0');
      break;
    case 'exponential':
      if (s.mean <= 0) errors.push('La media debe ser > 0');
      break;
    case 'erlang':
      if (s.mean <= 0) errors.push('La media debe ser > 0');
      if (!Number.isInteger(s.k) || s.k < 1) errors.push('k debe ser un entero ≥ 1');
      break;
    case 'weibull':
      if (s.shape <= 0 || s.scale <= 0) errors.push('Forma y escala deben ser > 0');
      break;
    case 'beta':
      if (s.alpha <= 0 || s.beta <= 0) errors.push('α y β deben ser > 0');
      if (s.max <= s.min) errors.push('Máximo ≤ mínimo');
      break;
    default:
  }
  if (s.truncate) {
    const { min, max } = s.truncate;
    if (Number.isFinite(min) && Number.isFinite(max) && max < min) errors.push('Truncado: máximo < mínimo');
  }
  return errors;
}

function sampleGamma(shape, scale, rng) {
  // Marsaglia-Tsang
  if (shape < 1) {
    const u = rng.randomOpen();
    return sampleGamma(shape + 1, scale, rng) * Math.pow(u, 1 / shape);
  }
  const d = shape - 1 / 3;
  const c = 1 / Math.sqrt(9 * d);
  for (;;) {
    let x, v;
    do {
      x = rng.normal();
      v = 1 + c * x;
    } while (v <= 0);
    v = v * v * v;
    const u = rng.randomOpen();
    if (u < 1 - 0.0331 * x * x * x * x) return d * v * scale;
    if (Math.log(u) < 0.5 * x * x + d * (1 - v + Math.log(v))) return d * v * scale;
  }
}

function lognormalParams(mean, sd) {
  const sigma2 = Math.log(1 + (sd * sd) / (mean * mean));
  return { mu: Math.log(mean) - sigma2 / 2, sigma: Math.sqrt(sigma2) };
}

function pertAB(s) {
  const lambda = num(s.lambda, 4);
  const range = s.max - s.min;
  return {
    a: 1 + (lambda * (s.mode - s.min)) / range,
    b: 1 + (lambda * (s.max - s.mode)) / range,
  };
}

function sampleRaw(s, rng) {
  switch (s.type) {
    case 'constant':
      return s.value;
    case 'uniform':
      return s.min + (s.max - s.min) * rng.random();
    case 'triangular': {
      const u = rng.random();
      const fc = (s.mode - s.min) / (s.max - s.min);
      return u < fc
        ? s.min + Math.sqrt(u * (s.max - s.min) * (s.mode - s.min))
        : s.max - Math.sqrt((1 - u) * (s.max - s.min) * (s.max - s.mode));
    }
    case 'pert': {
      const { a, b } = pertAB(s);
      const x = sampleGamma(a, 1, rng);
      const y = sampleGamma(b, 1, rng);
      return s.min + (s.max - s.min) * (x / (x + y));
    }
    case 'normal':
      return s.mean + s.sd * rng.normal();
    case 'lognormal': {
      if (s.sd === 0) return s.mean;
      const { mu, sigma } = lognormalParams(s.mean, s.sd);
      return Math.exp(mu + sigma * rng.normal());
    }
    case 'exponential':
      return -s.mean * Math.log(rng.randomOpen());
    case 'gamma': {
      if (s.sd === 0) return s.mean;
      const shape = (s.mean / s.sd) ** 2;
      return sampleGamma(shape, s.mean / shape, rng);
    }
    case 'erlang': {
      let prod = 1;
      for (let i = 0; i < s.k; i++) prod *= rng.randomOpen();
      return (-s.mean / s.k) * Math.log(prod);
    }
    case 'weibull':
      return num(s.location, 0) + s.scale * Math.pow(-Math.log(rng.randomOpen()), 1 / s.shape);
    case 'beta': {
      const x = sampleGamma(s.alpha, 1, rng);
      const y = sampleGamma(s.beta, 1, rng);
      return s.min + (s.max - s.min) * (x / (x + y));
    }
    case 'empirical':
      return s.values[Math.floor(rng.random() * s.values.length)];
    default:
      throw new Error(`Distribución desconocida: ${s.type}`);
  }
}

/** Genera una muestra. Respeta el truncado (rechazo, con recorte como último recurso). */
export function sample(spec, rng) {
  const t = spec.truncate;
  if (!t || (!Number.isFinite(t.min) && !Number.isFinite(t.max))) return sampleRaw(spec, rng);
  const lo = Number.isFinite(t.min) ? t.min : -Infinity;
  const hi = Number.isFinite(t.max) ? t.max : Infinity;
  for (let i = 0; i < 200; i++) {
    const x = sampleRaw(spec, rng);
    if (x >= lo && x <= hi) return x;
  }
  return Math.min(hi, Math.max(lo, sampleRaw(spec, rng)));
}

function rawMoments(s) {
  switch (s.type) {
    case 'constant':
      return [s.value, 0];
    case 'uniform':
      return [(s.min + s.max) / 2, (s.max - s.min) ** 2 / 12];
    case 'triangular': {
      const { min: a, mode: c, max: b } = s;
      return [(a + b + c) / 3, (a * a + b * b + c * c - a * b - a * c - b * c) / 18];
    }
    case 'pert': {
      const { a, b } = pertAB(s);
      const r = s.max - s.min;
      return [s.min + (r * a) / (a + b), (r * r * a * b) / ((a + b) ** 2 * (a + b + 1))];
    }
    case 'normal':
    case 'lognormal':
    case 'gamma':
      return [s.mean, s.sd * s.sd];
    case 'exponential':
      return [s.mean, s.mean * s.mean];
    case 'erlang':
      return [s.mean, (s.mean * s.mean) / s.k];
    case 'weibull': {
      const g1 = gammaFn(1 + 1 / s.shape);
      const g2 = gammaFn(1 + 2 / s.shape);
      return [num(s.location, 0) + s.scale * g1, s.scale * s.scale * (g2 - g1 * g1)];
    }
    case 'beta': {
      const { alpha: a, beta: b } = s;
      const r = s.max - s.min;
      return [s.min + (r * a) / (a + b), (r * r * a * b) / ((a + b) ** 2 * (a + b + 1))];
    }
    case 'empirical': {
      const n = s.values.length;
      const m = s.values.reduce((x, y) => x + y, 0) / n;
      const v = s.values.reduce((x, y) => x + (y - m) ** 2, 0) / n;
      return [m, v];
    }
    default:
      return [NaN, NaN];
  }
}

const momentCache = new Map();

/** Media y desviación típica. Si hay truncado se estiman por Monte Carlo (con caché). */
export function moments(spec) {
  const t = spec.truncate;
  if (!t || (!Number.isFinite(t.min) && !Number.isFinite(t.max))) {
    const [m, v] = rawMoments(spec);
    return { mean: m, sd: Math.sqrt(Math.max(0, v)) };
  }
  const key = JSON.stringify(spec);
  if (momentCache.has(key)) return momentCache.get(key);
  const rng = new RandomStream(12345);
  const n = 20000;
  let s1 = 0;
  let s2 = 0;
  for (let i = 0; i < n; i++) {
    const x = sample(spec, rng);
    s1 += x;
    s2 += x * x;
  }
  const mean = s1 / n;
  const res = { mean, sd: Math.sqrt(Math.max(0, s2 / n - mean * mean)) };
  if (momentCache.size > 500) momentCache.clear();
  momentCache.set(key, res);
  return res;
}

export const mean = (spec) => moments(spec).mean;
export const sd = (spec) => moments(spec).sd;

/** Función de distribución acumulada (sin truncado). */
export function cdf(s, x) {
  switch (s.type) {
    case 'constant':
      return x >= s.value ? 1 : 0;
    case 'uniform':
      return clamp01((x - s.min) / (s.max - s.min));
    case 'triangular': {
      if (x <= s.min) return 0;
      if (x >= s.max) return 1;
      if (x <= s.mode) return (x - s.min) ** 2 / ((s.max - s.min) * (s.mode - s.min));
      return 1 - (s.max - x) ** 2 / ((s.max - s.min) * (s.max - s.mode));
    }
    case 'pert': {
      const { a, b } = pertAB(s);
      return betaI(clamp01((x - s.min) / (s.max - s.min)), a, b);
    }
    case 'normal':
      return s.sd === 0 ? (x >= s.mean ? 1 : 0) : normalCdf((x - s.mean) / s.sd);
    case 'lognormal': {
      if (x <= 0) return 0;
      const { mu, sigma } = lognormalParams(s.mean, s.sd);
      return normalCdf((Math.log(x) - mu) / sigma);
    }
    case 'exponential':
      return x <= 0 ? 0 : 1 - Math.exp(-x / s.mean);
    case 'gamma': {
      const shape = (s.mean / s.sd) ** 2;
      return gammaP(shape, x / (s.mean / shape));
    }
    case 'erlang':
      return gammaP(s.k, x / (s.mean / s.k));
    case 'weibull': {
      const z = x - num(s.location, 0);
      return z <= 0 ? 0 : 1 - Math.exp(-Math.pow(z / s.scale, s.shape));
    }
    case 'beta':
      return betaI(clamp01((x - s.min) / (s.max - s.min)), s.alpha, s.beta);
    case 'empirical':
      return s.values.filter((v) => v <= x).length / s.values.length;
    default:
      return NaN;
  }
}

function clamp01(v) {
  return Math.min(1, Math.max(0, v));
}

/** Crea una distribución a partir de media y coeficiente de variación (entrada rápida). */
export function fromMeanCv(type, meanValue, cv) {
  const sdv = Math.abs(meanValue * cv);
  switch (type) {
    case 'constant':
      return { type, value: meanValue };
    case 'normal':
      return { type, mean: meanValue, sd: sdv, truncate: { min: 0 } };
    case 'lognormal':
    case 'gamma':
      return { type, mean: meanValue, sd: sdv };
    case 'exponential':
      return { type, mean: meanValue };
    case 'erlang':
      return { type, mean: meanValue, k: Math.max(1, Math.round(1 / (cv * cv))) };
    case 'uniform': {
      const h = sdv * Math.sqrt(3);
      return { type, min: Math.max(0, meanValue - h), max: meanValue + h };
    }
    case 'triangular': {
      const h = sdv * Math.sqrt(6);
      return { type, min: Math.max(0, meanValue - h), mode: meanValue, max: meanValue + h };
    }
    case 'pert': {
      // PERT simétrica: sd ≈ rango/6 con λ=4
      const h = sdv * 3;
      return { type, min: Math.max(0, meanValue - h), mode: meanValue, max: meanValue + h, lambda: 4 };
    }
    case 'weibull': {
      // búsqueda de la forma que da ese CV
      let lo = 0.2;
      let hi = 50;
      for (let i = 0; i < 80; i++) {
        const k = (lo + hi) / 2;
        const g1 = gammaFn(1 + 1 / k);
        const c = Math.sqrt(gammaFn(1 + 2 / k) - g1 * g1) / g1;
        if (c > cv) lo = k;
        else hi = k;
      }
      const k = (lo + hi) / 2;
      return { type, shape: k, scale: meanValue / gammaFn(1 + 1 / k), location: 0 };
    }
    default:
      throw new Error(`fromMeanCv no soporta ${type}`);
  }
}

/** Copia la distribución sustituyéndola por su media (para análisis de contribución). */
export function deterministic(spec) {
  return { type: 'constant', value: mean(spec) };
}

/** Texto corto legible: tipo, media, desviación y CV. */
export function describe(spec) {
  if (!spec) return '—';
  const { mean: m, sd: s } = moments(spec);
  const def = DISTRIBUTIONS[spec.type];
  const cv = m ? s / m : 0;
  return `${def ? def.label : spec.type} · μ=${fmt(m)} σ=${fmt(s)} CV=${(cv * 100).toFixed(1)}%`;
}

function fmt(v) {
  if (!Number.isFinite(v)) return '—';
  return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2);
}
