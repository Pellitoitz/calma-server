import test from 'node:test';
import assert from 'node:assert/strict';
import { RandomStream, StreamFactory } from '../src/stochastic/rng.js';
import { sample, moments, validate, cdf, fromMeanCv, DISTRIBUTIONS } from '../src/stochastic/distributions.js';
import { fitDistributions } from '../src/stochastic/fitting.js';
import { learningFactor, fatigueFactor, skillFactor, computeDuration } from '../src/stochastic/variability.js';
import { normalizeOperation } from '../src/model/schema.js';
import { studentTQuantile } from '../src/stochastic/special.js';

const empirical = (spec, n = 40000, seed = 1) => {
  const rng = new RandomStream(seed);
  let s1 = 0;
  let s2 = 0;
  for (let i = 0; i < n; i++) {
    const x = sample(spec, rng);
    s1 += x;
    s2 += x * x;
  }
  const m = s1 / n;
  return { mean: m, sd: Math.sqrt(s2 / n - m * m) };
};

test('los flujos aleatorios son reproducibles e independientes', () => {
  const a = new StreamFactory(42, 0).get('op:x');
  const b = new StreamFactory(42, 0).get('op:x');
  const c = new StreamFactory(42, 1).get('op:x');
  const va = [a.random(), a.random()];
  assert.deepEqual(va, [b.random(), b.random()]);
  assert.notDeepEqual(va, [c.random(), c.random()]);
});

const specs = [
  { type: 'uniform', min: 10, max: 20 },
  { type: 'triangular', min: 5, mode: 8, max: 15 },
  { type: 'pert', min: 300, mode: 420, max: 900, lambda: 4 },
  { type: 'normal', mean: 50, sd: 5 },
  { type: 'lognormal', mean: 60, sd: 9 },
  { type: 'exponential', mean: 30 },
  { type: 'gamma', mean: 30, sd: 6 },
  { type: 'erlang', mean: 40, k: 3 },
  { type: 'weibull', shape: 1.5, scale: 100 },
  { type: 'beta', alpha: 2, beta: 5, min: 10, max: 50 },
];

for (const spec of specs) {
  test(`muestreo coherente con los momentos teóricos: ${spec.type}`, () => {
    assert.deepEqual(validate(spec), []);
    const th = moments(spec);
    const emp = empirical(spec);
    assert.ok(Math.abs(emp.mean - th.mean) / th.mean < 0.02, `media ${emp.mean} vs ${th.mean}`);
    assert.ok(Math.abs(emp.sd - th.sd) / th.sd < 0.04, `sd ${emp.sd} vs ${th.sd}`);
    // la CDF evaluada en la mediana empírica debe valer ≈ 0,5
    const rng = new RandomStream(9);
    const xs = Array.from({ length: 20001 }, () => sample(spec, rng)).sort((a, b) => a - b);
    assert.ok(Math.abs(cdf(spec, xs[10000]) - 0.5) < 0.02);
  });
}

test('el truncado se respeta', () => {
  const spec = { type: 'normal', mean: 10, sd: 10, truncate: { min: 0, max: 15 } };
  const rng = new RandomStream(3);
  for (let i = 0; i < 5000; i++) {
    const x = sample(spec, rng);
    assert.ok(x >= 0 && x <= 15);
  }
});

test('validación de parámetros', () => {
  assert.ok(validate({ type: 'triangular', min: 5, mode: 2, max: 10 }).length);
  assert.ok(validate({ type: 'lognormal', mean: -1, sd: 1 }).length);
  assert.ok(validate({ type: 'inventada' }).length);
  for (const type of Object.keys(DISTRIBUTIONS)) assert.ok(DISTRIBUTIONS[type].label);
});

test('fromMeanCv reproduce media y CV', () => {
  for (const type of ['lognormal', 'gamma', 'uniform', 'triangular', 'weibull', 'erlang']) {
    const s = fromMeanCv(type, 100, 0.2);
    const m = moments(s);
    assert.ok(Math.abs(m.mean - 100) < 1, `${type} media ${m.mean}`);
    assert.ok(Math.abs(m.sd / m.mean - 0.2) < 0.03, `${type} cv ${m.sd / m.mean}`);
  }
});

test('el ajuste identifica la familia correcta', () => {
  const rng = new RandomStream(11);
  const data = Array.from({ length: 400 }, () => sample({ type: 'lognormal', mean: 60, sd: 20 }, rng));
  const fit = fitDistributions(data);
  assert.ok(['lognormal', 'gamma', 'weibull'].includes(fit.best.spec.type), fit.best.spec.type);
  assert.ok(Math.abs(fit.best.mean - 60) < 4);
  assert.ok(fit.best.pValue > 0.05);
});

test('curva de aprendizaje, fatiga y ritmo', () => {
  const lc = { rate: 0.9, experienceUnits: 0, standardUnits: 512 };
  assert.ok(Math.abs(learningFactor(lc, 0) - Math.pow(1 / 512, Math.log2(0.9))) < 1e-9);
  assert.ok(learningFactor(lc, 255) > learningFactor(lc, 511));
  assert.equal(learningFactor({ ...lc, experienceUnits: 1000 }, 0), 1);
  assert.equal(fatigueFactor({ maxIncrease: 0.1, timeConstantH: 2 }, 0), 1);
  assert.ok(fatigueFactor({ maxIncrease: 0.1, timeConstantH: 2 }, 100) <= 1.1 + 1e-12);
  assert.equal(skillFactor({ performance: { default: 125 } }, { type: 'x' }), 0.8);
  assert.equal(skillFactor({ performance: { default: 100, byType: { wiring: 80 } } }, { type: 'wiring', id: 'w' }), 1.25);
});

test('computeDuration combina factores e interrupciones', () => {
  const op = normalizeOperation({ id: 'a', type: 'manual_assembly', duration: { type: 'constant', value: 100 }, interruptions: { ratePerHour: 0 } });
  const streams = new StreamFactory(1, 0);
  const operator = { id: 'o', performance: { default: 125 }, learning: { experienceUnits: 1e6 }, fatigue: { maxIncrease: 0 } };
  const r = computeDuration({ op, operator, operatorState: { repetitions: new Map(), fatigueH: 0 }, streams });
  assert.equal(r.total, 80);
  const walk = normalizeOperation({ id: 'w', type: 'walking' });
  const rw = computeDuration({ op: walk, operator: { id: 'o', walkSpeed: { type: 'constant', value: 1 } }, distance: 12, streams, overrides: {} });
  assert.ok(Math.abs(rw.total - 12) < 1e-9);
});

test('cuantiles t de Student', () => {
  assert.ok(Math.abs(studentTQuantile(9, 0.95) - 2.262) < 0.002);
  assert.ok(Math.abs(studentTQuantile(1000, 0.95) - 1.962) < 0.003);
});
