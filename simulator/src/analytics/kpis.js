// Indicadores de rendimiento (KPI) de una réplica.
// Todos los tiempos de estado se expresan como fracción del periodo observado.

import { quantile } from './stats.js';
import { OPERATION_TYPES } from '../stochastic/variability.js';

/** Tipos de operación que añaden valor al producto (clasificación Lean). */
export const VALUE_ADDING = new Set(['manual_assembly', 'screwing', 'wiring', 'machining', 'drying', 'packing']);

const sumStates = (states, pred) => Object.entries(states).reduce((a, [k, v]) => (pred(k) ? a + v : a), 0);

export function replicationKpis(raw, model) {
  const obs = raw.observedSeconds;
  const obsH = obs / 3600;
  const t = raw.totals;
  const demand = model.settings.demandPerHour;
  const lt = raw.leadTime.values;
  const throughput = t.completed / obsH;

  const stations = raw.stations.map((s) => {
    const f = (k) => (s.states[k] || 0) / obs;
    const active = f('working') + f('setup') + f('failure') + f('waiting');
    return {
      id: s.id,
      name: s.name,
      working: f('working'),
      setup: f('setup'),
      failure: f('failure'),
      waitingResource: f('waiting'),
      blocked: f('blocked'),
      starved: f('idle'),
      active,
      processed: s.processed,
      throughput: s.processed / obsH,
      cycleMean: s.cycle.mean,
      interDepartureMean: s.interDeparture.mean,
      interDepartureCv: s.interDeparture.mean ? s.interDeparture.sd / s.interDeparture.mean : 0,
      bufferMean: s.buffer.mean,
      bufferMax: s.buffer.max,
      bufferCapacity: s.bufferCapacity,
    };
  });
  // Cuello de botella por el método del periodo activo (estación más tiempo activa)
  const bottleneck = stations.reduce((b, s) => (!b || s.active > b.active ? s : b), null);

  const operators = raw.operators.map((o) => {
    const work = sumStates(o.states, (k) => k.startsWith('work:'));
    const walking = o.states.walking || 0;
    const setup = o.states.setup || 0;
    const brk = o.states.break || 0;
    const available = Math.max(1, obs - brk);
    const va = sumStates(o.states, (k) => k.startsWith('work:') && VALUE_ADDING.has(k.slice(5)));
    const byType = {};
    for (const [k, v] of Object.entries(o.states)) if (k.startsWith('work:')) byType[k.slice(5)] = v / obs;
    return {
      id: o.id,
      name: o.name,
      utilization: (work + walking + setup) / available,
      working: work / obs,
      walking: walking / obs,
      setup: setup / obs,
      idle: (o.states.idle || 0) / obs,
      break: brk / obs,
      valueAddedRatio: work + walking + setup > 0 ? va / (work + walking + setup) : 0,
      walkedMetersPerHour: o.walked / obsH,
      tasksPerHour: o.tasks / obsH,
      maxFatigueFactor: o.maxFatigueFactor,
      byType,
    };
  });

  const fpy = t.completed ? t.firstPass / t.completed : NaN;
  const machines = raw.machines.map((m) => {
    const busy = m.states.busy || 0;
    const down = m.states.down || 0;
    const setup = m.states.setup || 0;
    const availability = obs > 0 ? (obs - down) / obs : NaN;
    const operating = busy / obs;
    const performance = busy > 0 ? Math.min(1.5, m.idealTime / busy) : NaN;
    const quality = Number.isFinite(fpy) ? fpy : 1;
    return {
      id: m.id,
      name: m.name,
      busy: busy / obs,
      down: down / obs,
      setup: setup / obs,
      idle: (m.states.idle || 0) / obs,
      technicalAvailability: availability,
      failures: m.failures,
      mttrObserved: m.repair.mean,
      mtbfObserved: m.failures ? busy / m.failures : null,
      oeeAvailability: operating,
      oeePerformance: performance,
      oeeQuality: quality,
      oee: operating * (Number.isFinite(performance) ? performance : 0) * quality,
    };
  });

  const operations = Object.entries(raw.operations).map(([id, o]) => {
    const def = model.operations.find((x) => x.id === id);
    return {
      id,
      name: def?.name ?? id,
      type: def?.type,
      count: o.n,
      mean: o.mean,
      sd: o.sd,
      cv: o.mean ? o.sd / o.mean : 0,
      p90: quantile(o.values, 0.9),
      interruptionsPerUnit: o.n ? o.interruptions / o.n : 0,
      interruptionShare: o.n && o.mean ? o.interruptionTime / (o.mean * o.n) : 0,
      lossFactor: o.ideal > 0 ? (o.mean * o.n) / o.ideal : NaN,
    };
  });

  const wipMean = raw.wip.mean;
  const ltMean = raw.leadTime.mean;
  return {
    scalars: {
      throughputPerHour: throughput,
      completed: t.completed,
      leadTimeMean: ltMean,
      leadTimeP50: quantile(lt, 0.5),
      leadTimeP90: quantile(lt, 0.9),
      leadTimeP95: quantile(lt, 0.95),
      leadTimeMax: raw.leadTime.max,
      leadTimeSd: raw.leadTime.sd,
      wipMean,
      wipMax: raw.wip.max,
      backlogMean: raw.backlog.mean,
      cycleTime: throughput > 0 ? 3600 / throughput : NaN,
      fpy,
      scrapRate: t.completed + t.scrapped ? t.scrapped / (t.completed + t.scrapped) : 0,
      reworkPerUnit: t.completed ? t.reworkOps / t.completed : 0,
      escapedPpm: t.completed ? (t.escapedDefects / t.completed) * 1e6 : 0,
      falseRejects: t.falseRejects,
      setups: t.setups,
      demandFulfilment: demand ? throughput / demand : NaN,
      // Ley de Little: WIP = λ·W. Una desviación grande indica sesgo de calentamiento o horizonte corto
      littleDeviation: ltMean > 0 && throughput > 0 ? (wipMean - (throughput / 3600) * ltMean) / wipMean : NaN,
      operatorUtilizationMean: operators.length ? operators.reduce((a, o) => a + o.utilization, 0) / operators.length : NaN,
      walkedMetersPerHour: operators.reduce((a, o) => a + o.walkedMetersPerHour, 0),
      valueAddedRatio: operators.length ? operators.reduce((a, o) => a + o.valueAddedRatio, 0) / operators.length : NaN,
      oeeMean: machines.length ? machines.reduce((a, m) => a + m.oee, 0) / machines.length : NaN,
    },
    bottleneck: bottleneck?.id ?? null,
    stations,
    operators,
    machines,
    operations,
    products: raw.byProduct,
    hourly: raw.hourly,
    wipSeries: raw.wipSeries,
    leadTimeValues: lt,
  };
}

export const KPI_LABELS = {
  throughputPerHour: { label: 'Producción (uds/h)', unit: 'uds/h', better: 'higher' },
  completed: { label: 'Unidades terminadas', unit: 'uds', better: 'higher' },
  leadTimeMean: { label: 'Lead time medio', unit: 's', better: 'lower' },
  leadTimeP50: { label: 'Lead time P50', unit: 's', better: 'lower' },
  leadTimeP90: { label: 'Lead time P90', unit: 's', better: 'lower' },
  leadTimeP95: { label: 'Lead time P95', unit: 's', better: 'lower' },
  leadTimeMax: { label: 'Lead time máximo', unit: 's', better: 'lower' },
  leadTimeSd: { label: 'Dispersión lead time (σ)', unit: 's', better: 'lower' },
  wipMean: { label: 'WIP medio', unit: 'uds', better: 'lower' },
  wipMax: { label: 'WIP máximo', unit: 'uds', better: 'lower' },
  backlogMean: { label: 'Cola de pedidos media', unit: 'uds', better: 'lower' },
  cycleTime: { label: 'Tiempo de ciclo real', unit: 's', better: 'lower' },
  fpy: { label: 'First Pass Yield', unit: '%', better: 'higher' },
  scrapRate: { label: 'Tasa de desecho', unit: '%', better: 'lower' },
  reworkPerUnit: { label: 'Retrabajos por unidad', unit: '', better: 'lower' },
  escapedPpm: { label: 'Defectos escapados', unit: 'ppm', better: 'lower' },
  falseRejects: { label: 'Falsos rechazos', unit: 'uds', better: 'lower' },
  setups: { label: 'Setups realizados', unit: '', better: 'lower' },
  demandFulfilment: { label: 'Cumplimiento de demanda', unit: '%', better: 'higher' },
  littleDeviation: { label: 'Desviación Ley de Little', unit: '%', better: 'lower' },
  operatorUtilizationMean: { label: 'Utilización media operarios', unit: '%', better: 'neutral' },
  walkedMetersPerHour: { label: 'Metros andados / h (total)', unit: 'm/h', better: 'lower' },
  valueAddedRatio: { label: 'Ratio de valor añadido', unit: '%', better: 'higher' },
  oeeMean: { label: 'OEE medio máquinas', unit: '%', better: 'higher' },
};

export function operationTypeLabel(type) {
  return OPERATION_TYPES[type]?.label ?? type;
}
