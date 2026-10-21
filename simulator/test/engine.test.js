import test from 'node:test';
import assert from 'node:assert/strict';
import { simulate } from '../src/engine/simulator.js';
import { runExperiment, contributionAnalysis, compareScenarios } from '../src/analytics/experiment.js';
import { exampleModel } from '../src/model/examples.js';
import { validateModel } from '../src/model/schema.js';

const noBreaks = { shift: { lengthHours: 8, breaks: [] } };

test('M/M/1: el motor reproduce la teoría de colas', () => {
  // λ = 1/60, μ = 1/45 ⇒ ρ = 0,75, W = 1/(μ-λ) = 180 s, L = 3
  const model = {
    id: 'mm1',
    settings: { horizonHours: 400, warmupHours: 20, replications: 4, seed: 7, ...noBreaks },
    arrivals: { mode: 'interarrival', interarrival: { type: 'exponential', mean: 60 } },
    operations: [{ id: 'srv', type: 'drying', duration: { type: 'exponential', mean: 45 } }],
    stations: [{ id: 'S', operationIds: ['srv'], bufferCapacity: 1e9 }],
  };
  const r = runExperiment(model);
  const W = r.scalars.leadTimeMean;
  const L = r.scalars.wipMean;
  assert.ok(W.ciLow < 180 * 1.05 && W.ciHigh > 180 * 0.95, `W ${W.mean} [${W.ciLow}, ${W.ciHigh}]`);
  assert.ok(Math.abs(L.mean - 3) < 0.3, `L ${L.mean}`);
  assert.ok(Math.abs(r.stations[0].working.mean - 0.75) < 0.02);
  assert.ok(Math.abs(r.scalars.littleDeviation.mean) < 0.03);
});

test('línea determinista: la producción la marca el cuello de botella', () => {
  const ops = [30, 50, 40].map((t, i) => ({ id: `o${i}`, type: 'drying', duration: { type: 'constant', value: t } }));
  const model = {
    id: 'det',
    settings: { horizonHours: 10, warmupHours: 1, seed: 1, ...noBreaks },
    arrivals: { mode: 'push' },
    operations: ops,
    stations: ops.map((o, i) => ({ id: `S${i}`, operationIds: [o.id], bufferCapacity: 1 })),
  };
  const raw = simulate(model);
  const th = raw.totals.completed / 9;
  assert.ok(Math.abs(th - 72) <= 0.2, `throughput ${th}`);
});

test('bloqueo: buffer 0 entre estaciones', () => {
  const model = {
    id: 'blk',
    settings: { horizonHours: 5, warmupHours: 0.5, seed: 1, ...noBreaks },
    arrivals: { mode: 'push' },
    operations: [
      { id: 'a', type: 'drying', duration: { type: 'constant', value: 10 } },
      { id: 'b', type: 'drying', duration: { type: 'constant', value: 20 } },
    ],
    stations: [
      { id: 'A', operationIds: ['a'], bufferCapacity: 0 },
      { id: 'B', operationIds: ['b'], bufferCapacity: 0 },
    ],
  };
  const raw = simulate(model);
  const a = raw.stations[0].states;
  assert.ok(a.blocked / raw.observedSeconds > 0.45, 'A debe estar bloqueada ~50 %');
});

test('el modelo de ejemplo es válido y produce KPIs coherentes', () => {
  const m = exampleModel();
  assert.deepEqual(validateModel(m).errors, []);
  const r = runExperiment(m, { replications: 3, trace: true, traceHours: 1 });
  const S = r.scalars;
  assert.ok(S.throughputPerHour.mean > 10 && S.throughputPerHour.mean < 40);
  assert.ok(S.fpy.mean > 0.8 && S.fpy.mean <= 1);
  assert.ok(Math.abs(S.littleDeviation.mean) < 0.15);
  assert.ok(r.trace.length > 100);
  assert.ok(r.trace.some((e) => e.k === 'walk'));
  const probs = r.stations.reduce((a, s) => a + s.bottleneckProbability, 0);
  assert.ok(Math.abs(probs - 1) < 1e-9);
  for (const o of r.operators) assert.ok(o.utilization.mean > 0 && o.utilization.mean <= 1.0001);
});

test('reproducibilidad: misma semilla ⇒ mismos resultados', () => {
  const a = simulate(exampleModel(), { replication: 2 });
  const b = simulate(exampleModel(), { replication: 2 });
  assert.deepEqual(a.totals, b.totals);
  assert.equal(a.leadTime.mean, b.leadTime.mean);
});

test('eliminar toda la variabilidad no reduce la producción de una línea saturada', () => {
  const c = contributionAnalysis(exampleModel(), { replications: 2 });
  assert.ok(c.sources.length > 5);
  assert.ok(c.allDeterministic.effects.throughputPerHour.mean > -0.5);
});

test('comparación pareada detecta una mejora clara', () => {
  const a = exampleModel();
  const b = exampleModel();
  // todos los operarios un 30 % más rápidos
  for (const o of b.operators) o.performance = { default: 130 };
  const cmp = compareScenarios(a, b, { replications: 5 });
  const d = cmp.kpis.throughputPerHour.difference;
  assert.ok(d.mean > 0 && d.significant, `Δ ${d.mean}`);
});

test('la validación detecta errores típicos', () => {
  const { errors } = validateModel({
    stations: [{ id: 'S', operationIds: ['x', 'm'] }],
    operations: [{ id: 'm', type: 'manual_assembly' }],
  });
  assert.ok(errors.some((e) => e.includes('inexistente')));
  assert.ok(errors.some((e) => e.includes('necesita operario')));
});
