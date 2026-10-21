// Esquema del modelo: valores por defecto, normalización y validación.
// El modelo guardado contiene solo lo que el usuario ha introducido; normalize()
// produce la versión completa (con los valores por defecto de cada tipo de
// operación) que consume el motor.

import { OPERATION_TYPES, typeDef } from '../stochastic/variability.js';
import { validate as validateDist } from '../stochastic/distributions.js';

export const DEFAULT_SETTINGS = {
  horizonHours: 8,
  warmupHours: 0.5,
  replications: 10,
  seed: 12345,
  confidence: 0.95,
  targetRelativePrecision: 0.05,
  layout: 'u',
  spacing: 3.5,
  shift: {
    lengthHours: 8,
    breaks: [
      { atHours: 2, durationMin: 10 },
      { atHours: 4, durationMin: 30 },
      { atHours: 6, durationMin: 10 },
    ],
  },
  demandPerHour: null,
};

export const DEFAULT_OPERATOR = {
  performance: { default: 100, byType: {}, byOperation: {} },
  consistency: 1,
  walkSpeed: { type: 'normal', mean: 1.2, sd: 0.15, truncate: { min: 0.5, max: 2 } },
  learning: { rate: 0.9, experienceUnits: 500, standardUnits: 500, plateau: 1 },
  fatigue: { maxIncrease: 0.08, timeConstantH: 3, recoveryH: 0.25 },
  qualityFatigueSensitivity: 0,
  dispatch: 'nearest',
};

export const DEFAULT_MACHINE = {
  speedFactor: 1,
  consistency: 1,
  failures: {
    enabled: true,
    mtbf: { type: 'exponential', mean: 4 * 3600 },
    mttr: { type: 'lognormal', mean: 600, sd: 300 },
  },
};

export const DEFAULT_QUALITY = {
  defectProb: 0,
  detectionProb: 0.95,
  falseRejectProb: 0.01,
  onReject: 'rework',
  reworkOperationId: null,
  maxReworks: 2,
  repairProb: 0.9,
};

const clone = (v) => (v === undefined ? v : JSON.parse(JSON.stringify(v)));

function merge(base, over) {
  if (over === undefined || over === null) return clone(base);
  if (typeof base !== 'object' || base === null || Array.isArray(base)) return clone(over);
  const out = clone(base);
  for (const [k, v] of Object.entries(over)) {
    out[k] = typeof v === 'object' && v !== null && !Array.isArray(v) && typeof base[k] === 'object' && base[k] !== null && !Array.isArray(base[k]) && !('type' in v)
      ? merge(base[k], v)
      : clone(v);
  }
  return out;
}

export function normalizeOperation(op) {
  const def = typeDef(op.type);
  return {
    id: op.id,
    name: op.name || def.label,
    type: OPERATION_TYPES[op.type] ? op.type : 'manual_assembly',
    duration: clone(op.duration || def.duration),
    distanceBased: op.distanceBased === null ? null : merge(def.distanceBased || null, op.distanceBased),
    modifiers: merge(def.modifiers, op.modifiers),
    requires: merge(def.requires, op.requires),
    interruptions: merge(def.interruptions, op.interruptions),
    learning: op.learning ? clone(op.learning) : null,
    quality: merge(DEFAULT_QUALITY, { detectionProb: def.inspection ? 0.95 : 0, ...op.quality }),
    isInspection: op.isInspection ?? Boolean(def.inspection),
    operatorIds: Array.isArray(op.operatorIds) ? [...op.operatorIds] : null,
    notes: op.notes || '',
  };
}

export function normalizeModel(model) {
  if (model.__normalized) return model;
  const settings = merge(DEFAULT_SETTINGS, model.settings);
  const operations = (model.operations || []).map(normalizeOperation);
  return {
    __normalized: true,
    id: model.id,
    name: model.name || 'Modelo sin nombre',
    settings,
    arrivals: merge({ mode: 'push', interarrival: { type: 'exponential', mean: 60 }, batchSize: 1 }, model.arrivals),
    products: (model.products?.length ? model.products : [{ id: 'P1', name: 'Producto estándar', mix: 1 }]).map((p) => ({
      timeFactor: 1,
      timeFactorsByType: {},
      timeFactors: {},
      color: '#2a78d6',
      ...clone(p),
    })),
    operators: (model.operators || []).map((o) => ({ ...merge(DEFAULT_OPERATOR, o), id: o.id, name: o.name || o.id })),
    machines: (model.machines || []).map((m) => ({ ...merge(DEFAULT_MACHINE, m), id: m.id, name: m.name || m.id })),
    stations: (model.stations || []).map((s) => ({
      workplaces: 1,
      bufferCapacity: 2,
      operationIds: [],
      operatorIds: [],
      machineId: null,
      setup: { operationId: null, trigger: 'none', everyN: 0 },
      transportOperationId: null,
      ...clone(s),
    })),
    operations,
  };
}

/** Valida el modelo y devuelve { errors, warnings } con mensajes legibles. */
export function validateModel(raw) {
  const errors = [];
  const warnings = [];
  const m = normalizeModel(raw);
  const opIds = new Set(m.operations.map((o) => o.id));
  const operatorIds = new Set(m.operators.map((o) => o.id));
  const machineIds = new Set(m.machines.map((o) => o.id));

  const dupes = (list, what) => {
    const seen = new Set();
    for (const x of list) {
      if (!x.id) errors.push(`${what} sin identificador`);
      else if (seen.has(x.id)) errors.push(`${what} duplicado: ${x.id}`);
      seen.add(x.id);
    }
  };
  dupes(m.operations, 'Operación');
  dupes(m.operators, 'Operario');
  dupes(m.machines, 'Máquina');
  dupes(m.stations, 'Estación');

  if (!m.stations.length) errors.push('El modelo no tiene estaciones');
  if (!(m.settings.horizonHours > 0)) errors.push('El horizonte debe ser > 0 horas');
  if (m.settings.warmupHours < 0 || m.settings.warmupHours >= m.settings.horizonHours) errors.push('El calentamiento debe estar entre 0 y el horizonte');
  if (!(m.settings.replications >= 1)) errors.push('Se necesita al menos 1 réplica');
  if (m.settings.replications < 5) warnings.push('Menos de 5 réplicas: los intervalos de confianza serán muy anchos');

  for (const op of m.operations) {
    for (const e of validateDist(op.duration)) errors.push(`Operación ${op.name}: ${e}`);
    if (op.distanceBased?.speed) for (const e of validateDist(op.distanceBased.speed)) errors.push(`Operación ${op.name} (velocidad): ${e}`);
    if (op.interruptions?.ratePerHour > 0) for (const e of validateDist(op.interruptions.duration)) errors.push(`Operación ${op.name} (interrupciones): ${e}`);
    const q = op.quality;
    for (const k of ['defectProb', 'detectionProb', 'falseRejectProb', 'repairProb']) {
      if (q[k] < 0 || q[k] > 1) errors.push(`Operación ${op.name}: ${k} debe estar entre 0 y 1`);
    }
    if (op.isInspection && q.onReject === 'rework') {
      if (!q.reworkOperationId) warnings.push(`Inspección ${op.name}: sin operación de retrabajo, los rechazos se desecharán`);
      else if (!opIds.has(q.reworkOperationId)) errors.push(`Inspección ${op.name}: operación de retrabajo inexistente`);
    }
    for (const id of op.operatorIds || []) if (!operatorIds.has(id)) errors.push(`Operación ${op.name}: operario ${id} inexistente`);
  }

  for (const s of m.stations) {
    if (!s.operationIds.length) warnings.push(`Estación ${s.name || s.id}: sin operaciones`);
    for (const id of s.operationIds) if (!opIds.has(id)) errors.push(`Estación ${s.name || s.id}: operación ${id} inexistente`);
    for (const id of s.operatorIds) if (!operatorIds.has(id)) errors.push(`Estación ${s.name || s.id}: operario ${id} inexistente`);
    if (s.machineId && !machineIds.has(s.machineId)) errors.push(`Estación ${s.name || s.id}: máquina inexistente`);
    if (!(s.workplaces >= 1)) errors.push(`Estación ${s.name || s.id}: al menos 1 puesto`);
    if (s.bufferCapacity < 0) errors.push(`Estación ${s.name || s.id}: buffer negativo`);
    const ops = s.operationIds.map((id) => m.operations.find((o) => o.id === id)).filter(Boolean);
    if (s.setup?.operationId) ops.push(m.operations.find((o) => o.id === s.setup.operationId));
    for (const op of ops.filter(Boolean)) {
      if (op.requires.operator && !s.operatorIds.length && !(op.operatorIds?.length)) errors.push(`Estación ${s.name || s.id}: la operación ${op.name} necesita operario y no hay ninguno asignado`);
      if (op.requires.machine && !s.machineId) errors.push(`Estación ${s.name || s.id}: la operación ${op.name} necesita máquina y no hay ninguna asignada`);
    }
  }

  for (const o of m.operators) {
    for (const e of validateDist(o.walkSpeed)) errors.push(`Operario ${o.name} (velocidad de marcha): ${e}`);
  }
  for (const mc of m.machines) {
    if (mc.failures?.enabled) {
      for (const e of validateDist(mc.failures.mtbf)) errors.push(`Máquina ${mc.name} (MTBF): ${e}`);
      for (const e of validateDist(mc.failures.mttr)) errors.push(`Máquina ${mc.name} (MTTR): ${e}`);
    }
  }
  const mixTotal = m.products.reduce((a, p) => a + (p.mix || 0), 0);
  if (!(mixTotal > 0)) errors.push('La mezcla de productos debe sumar > 0');
  if (m.arrivals.mode === 'interarrival') for (const e of validateDist(m.arrivals.interarrival)) errors.push(`Llegadas: ${e}`);

  return { errors, warnings, normalized: m };
}
