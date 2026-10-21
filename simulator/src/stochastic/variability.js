// Motor universal de variabilidad.
//
// El tiempo real de cada ejecución de una operación se compone así:
//
//   t = [ x_base(consistencia del recurso) · f_producto · f_ritmo · f_aprendizaje · f_fatiga ]
//       + d/v (si la operación depende de la distancia)
//       + Σ interrupciones (Poisson sobre el tiempo de ciclo)
//       + Σ averías de máquina (las añade el motor de eventos, en tiempo de máquina ocupada)
//
// Cada término es configurable por operación (y por tipo de operación como valor
// por defecto) y por recurso (operario o máquina). Cada fuente usa su propio flujo
// aleatorio para garantizar números aleatorios comunes entre escenarios.

import { sample, mean as distMean } from './distributions.js';

const MANUAL = { skill: true, learning: true, fatigue: true, interruptions: true };
const MACHINE = { skill: false, learning: false, fatigue: false, interruptions: false };

/**
 * Catálogo de tipos de operación. Los valores por defecto son puntos de partida
 * razonables (segundos) que el usuario sustituye por sus propios datos.
 */
export const OPERATION_TYPES = {
  manual_assembly: {
    label: 'Montaje manual',
    category: 'manual',
    color: '#2a78d6',
    duration: { type: 'lognormal', mean: 60, sd: 9 },
    modifiers: MANUAL,
    requires: { operator: true, machine: false },
    interruptions: { ratePerHour: 2, duration: { type: 'exponential', mean: 20 } },
  },
  screwing: {
    label: 'Atornillado',
    category: 'manual',
    color: '#1baf7a',
    duration: { type: 'lognormal', mean: 25, sd: 3 },
    modifiers: MANUAL,
    requires: { operator: true, machine: false },
    interruptions: { ratePerHour: 3, duration: { type: 'exponential', mean: 10 } },
  },
  wiring: {
    label: 'Cableado',
    category: 'manual',
    color: '#eda100',
    duration: { type: 'lognormal', mean: 90, sd: 18 },
    modifiers: MANUAL,
    requires: { operator: true, machine: false },
    interruptions: { ratePerHour: 2, duration: { type: 'exponential', mean: 25 } },
  },
  inspection: {
    label: 'Inspección',
    category: 'manual',
    color: '#6250d6',
    duration: { type: 'gamma', mean: 30, sd: 6 },
    modifiers: MANUAL,
    requires: { operator: true, machine: false },
    interruptions: { ratePerHour: 1, duration: { type: 'exponential', mean: 15 } },
    inspection: true,
  },
  handling: {
    label: 'Manipulación',
    category: 'manual',
    color: '#e87ba4',
    duration: { type: 'triangular', min: 5, mode: 8, max: 15 },
    modifiers: MANUAL,
    requires: { operator: true, machine: false },
    interruptions: { ratePerHour: 0, duration: { type: 'exponential', mean: 10 } },
  },
  loading: {
    label: 'Carga',
    category: 'manual',
    color: '#52514e',
    duration: { type: 'triangular', min: 8, mode: 12, max: 20 },
    modifiers: MANUAL,
    requires: { operator: true, machine: false },
    interruptions: { ratePerHour: 0, duration: { type: 'exponential', mean: 10 } },
  },
  unloading: {
    label: 'Descarga',
    category: 'manual',
    color: '#52514e',
    duration: { type: 'triangular', min: 6, mode: 10, max: 16 },
    modifiers: MANUAL,
    requires: { operator: true, machine: false },
    interruptions: { ratePerHour: 0, duration: { type: 'exponential', mean: 10 } },
  },
  auto_test: {
    label: 'Prueba automática',
    category: 'machine',
    color: '#008300',
    duration: { type: 'normal', mean: 45, sd: 1.5, truncate: { min: 0 } },
    modifiers: MACHINE,
    requires: { operator: false, machine: true },
    interruptions: { ratePerHour: 0, duration: { type: 'exponential', mean: 10 } },
    inspection: true,
  },
  machining: {
    label: 'Procesamiento en máquina',
    category: 'machine',
    color: '#eb6834',
    duration: { type: 'normal', mean: 50, sd: 1.5, truncate: { min: 0 } },
    modifiers: MACHINE,
    requires: { operator: false, machine: true },
    interruptions: { ratePerHour: 0, duration: { type: 'exponential', mean: 10 } },
  },
  drying: {
    label: 'Secado / curado',
    category: 'passive',
    color: '#c98500',
    duration: { type: 'uniform', min: 280, max: 340 },
    modifiers: MACHINE,
    requires: { operator: false, machine: false },
    interruptions: { ratePerHour: 0, duration: { type: 'exponential', mean: 10 } },
  },
  packing: {
    label: 'Embalaje',
    category: 'manual',
    color: '#9085e9',
    duration: { type: 'lognormal', mean: 40, sd: 6 },
    modifiers: MANUAL,
    requires: { operator: true, machine: false },
    interruptions: { ratePerHour: 1, duration: { type: 'exponential', mean: 15 } },
  },
  setup: {
    label: 'Setup / cambio de referencia',
    category: 'manual',
    color: '#e34948',
    duration: { type: 'pert', min: 300, mode: 420, max: 900, lambda: 4 },
    modifiers: { skill: true, learning: true, fatigue: false, interruptions: true },
    requires: { operator: true, machine: false },
    interruptions: { ratePerHour: 2, duration: { type: 'exponential', mean: 60 } },
  },
  walking: {
    label: 'Desplazamiento de operario',
    category: 'movement',
    color: '#86b6ef',
    duration: { type: 'constant', value: 0 },
    distanceBased: { speed: { type: 'normal', mean: 1.2, sd: 0.15, truncate: { min: 0.5, max: 2 } } },
    modifiers: { skill: false, learning: false, fatigue: true, interruptions: false },
    requires: { operator: true, machine: false },
    interruptions: { ratePerHour: 0, duration: { type: 'exponential', mean: 10 } },
  },
  transport: {
    label: 'Transporte (cinta / AGV)',
    category: 'movement',
    color: '#5598e7',
    duration: { type: 'constant', value: 3 },
    distanceBased: { speed: { type: 'uniform', min: 0.45, max: 0.55 } },
    modifiers: MACHINE,
    requires: { operator: false, machine: false },
    interruptions: { ratePerHour: 0, duration: { type: 'exponential', mean: 10 } },
  },
  rework: {
    label: 'Retrabajo',
    category: 'manual',
    color: '#d55181',
    duration: { type: 'lognormal', mean: 120, sd: 45 },
    modifiers: MANUAL,
    requires: { operator: true, machine: false },
    interruptions: { ratePerHour: 2, duration: { type: 'exponential', mean: 30 } },
  },
};

export function typeDef(type) {
  return OPERATION_TYPES[type] || OPERATION_TYPES.manual_assembly;
}

/** Factor de ritmo del operario: 100 % = estándar; 120 % ⇒ 1/1.2 del tiempo. */
export function skillFactor(operator, op) {
  if (!operator) return 1;
  const p = operator.performance || {};
  const perf = p.byOperation?.[op.id] ?? p.byType?.[op.type] ?? p.default ?? 100;
  return perf > 0 ? 100 / perf : 1;
}

/**
 * Curva de aprendizaje de Wright: cada vez que se duplica el número de
 * repeticiones el tiempo se multiplica por `rate`. El tiempo base representa el
 * tiempo estándar alcanzado tras `standardUnits` repeticiones, por eso el factor
 * es ≥ 1 para un operario novel y converge a 1 (o a `plateau`) con la práctica.
 */
export function learningFactor(learning, repetitions) {
  if (!learning) return 1;
  const rate = learning.rate ?? 0.9;
  if (rate >= 1 || rate <= 0) return 1;
  const b = Math.log2(rate);
  const nEff = Math.max(1, (learning.experienceUnits ?? 0) + repetitions + 1);
  const nStd = Math.max(1, learning.standardUnits ?? 500);
  const f = Math.pow(nEff / nStd, b);
  return Math.max(learning.plateau ?? 1, f);
}

/**
 * Fatiga: incremento exponencial saturado con las horas de trabajo efectivas
 * acumuladas. El descanso las reduce exponencialmente (lo gestiona el motor).
 */
export function fatigueFactor(fatigue, workedHours) {
  if (!fatigue || !(fatigue.maxIncrease > 0)) return 1;
  const tau = fatigue.timeConstantH > 0 ? fatigue.timeConstantH : 3;
  return 1 + fatigue.maxIncrease * (1 - Math.exp(-workedHours / tau));
}

/** Aplica la consistencia del recurso: <1 reduce la dispersión, >1 la amplía. */
function applyConsistency(x, spec, consistency) {
  if (consistency === undefined || consistency === 1) return x;
  const m = distMean(spec);
  return m + (x - m) * consistency;
}

/**
 * Calcula la duración de una ejecución concreta.
 *
 * @param {object} p
 * @param {object} p.op         operación normalizada
 * @param {object} [p.operator] definición del operario
 * @param {object} [p.operatorState] { repetitions: Map, fatigueH }
 * @param {object} [p.machine]  definición de la máquina
 * @param {object} [p.product]  producto (factores de tiempo por mezcla)
 * @param {number} [p.distance] metros a recorrer (operaciones basadas en distancia)
 * @param {object} p.streams    fábrica de flujos aleatorios
 * @param {object} [p.overrides] { deterministic: Set<string> } para análisis
 * @returns {{ total:number, parts:object }}
 */
export function computeDuration({ op, operator, operatorState, machine, product, distance = 0, streams, overrides }) {
  const det = overrides?.deterministic;
  const isDet = (key) => det && (det.has('*') || det.has(key));
  const mods = op.modifiers;
  const rng = streams.get(`op:${op.id}`);

  // 1. Tiempo base y consistencia del recurso que la ejecuta
  let base;
  if (isDet(`op:${op.id}`)) {
    base = distMean(op.duration);
  } else {
    base = sample(op.duration, rng);
    const consistency = op.requires.machine ? machine?.consistency : operator?.consistency;
    if (op.requires.operator || op.requires.machine) base = applyConsistency(base, op.duration, consistency);
  }
  base = Math.max(0, base);

  // 2. Factores multiplicativos
  const fProduct = product?.timeFactors?.[op.id] ?? product?.timeFactorsByType?.[op.type] ?? product?.timeFactor ?? 1;
  const fSkill = mods.skill && operator ? skillFactor(operator, op) : 1;
  const reps = operatorState?.repetitions?.get(op.id) ?? 0;
  const learningCfg = op.learning ? { ...operator?.learning, ...op.learning } : operator?.learning;
  const fLearn = mods.learning && operator && !isDet(`learning`) ? learningFactor(learningCfg, reps) : 1;
  const fFatigue = mods.fatigue && operator && !isDet(`fatigue`) ? fatigueFactor(operator.fatigue, operatorState?.fatigueH ?? 0) : 1;
  const fMachine = op.requires.machine && machine?.speedFactor ? 1 / machine.speedFactor : 1;

  let work = base * fProduct * fSkill * fLearn * fFatigue * fMachine;

  // 3. Componente por distancia (desplazamientos y transportes)
  let travel = 0;
  if (op.distanceBased && distance > 0) {
    let speedSpec = op.distanceBased.speed;
    if (op.type === 'walking' && operator?.walkSpeed) speedSpec = operator.walkSpeed;
    const speed = isDet(`op:${op.id}`) ? distMean(speedSpec) : sample(speedSpec, streams.get(`speed:${op.id}:${operator?.id ?? 'auto'}`));
    travel = (distance / Math.max(0.05, speed)) * fFatigue;
  }

  // 4. Interrupciones aleatorias (microparadas, consultas, falta de material...)
  let interruptions = 0;
  let interruptionCount = 0;
  const intr = op.interruptions;
  if (mods.interruptions && intr && intr.ratePerHour > 0 && !isDet('interruptions') && !isDet(`op:${op.id}`)) {
    const irng = streams.get(`intr:${op.id}`);
    interruptionCount = irng.poisson((intr.ratePerHour * (work + travel)) / 3600);
    for (let i = 0; i < interruptionCount; i++) interruptions += Math.max(0, sample(intr.duration, irng));
  }

  return {
    total: work + travel + interruptions,
    parts: {
      base,
      work,
      travel,
      interruptions,
      interruptionCount,
      factors: { product: fProduct, skill: fSkill, learning: fLearn, fatigue: fFatigue, machine: fMachine },
    },
  };
}

/** Tiempo estándar esperado (sin aprendizaje, fatiga ni interrupciones) para cálculos de OEE. */
export function idealDuration(op, product) {
  const fProduct = product?.timeFactors?.[op.id] ?? product?.timeFactorsByType?.[op.type] ?? product?.timeFactor ?? 1;
  return distMean(op.duration) * fProduct;
}
