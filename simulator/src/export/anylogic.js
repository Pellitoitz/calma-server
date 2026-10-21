// Exportación a AnyLogic 8.9 (.alp) con la Process Modeling Library.
//
// Cada estación se traduce en una cadena de bloques:
//   Seize (puesto, su cola = buffer de entrada)
//   → [SelectOutput setup → Seize operario → Delay setup → Release]
//   → por cada operación: [Seize máquina] [Seize operario] Delay [Release operario] [Release máquina]
//     · inspecciones: SelectOutput aceptada / rechazada → retrabajo (vuelve a inspección) o desecho
//   → Queue salida (bloqueo si la siguiente está llena) → [transporte] → Release puesto
//
// Los tiempos se calculan con funciones Java generadas que reproducen el motor de
// variabilidad del simulador web: distribución base, consistencia, ritmo,
// aprendizaje, fatiga y recuperación, interrupciones Poisson, desplazamientos,
// averías por MTBF/MTTR, factores de producto, pausas del turno y calidad.
//
// El formato XML sigue el de los modelos de ejemplo oficiales de AnyLogic 8.9.

import { normalizeModel } from '../model/schema.js';
import { moments } from '../stochastic/distributions.js';
import { computeLayout, distanceMatrix } from '../layout/autoLayout.js';
import { HELPER_FUNCTIONS } from './anylogicJava.js';

const PML = 'com.anylogic.libraries.processmodeling';

// Identificadores de los parámetros genéricos de cada bloque en la librería
const GENERIC_ID = {
  Source: '1412336242928',
  Sink: '1412336242929',
  Delay: '1412336242930',
  SelectOutput: '1412336242931',
  Queue: '1412336242932',
  ResourcePool: '1412336243135',
  Seize: '1412336243147',
  Release: '1412336243154',
};

// Parámetros de cada bloque (los no indicados se dejan con su valor por defecto)
const BLOCK_PARAMS = {
  Source: ['newEntity', 'interarrivalTime', 'arrivalType', 'rate', 'entitiesPerArrival', 'limitArrivals', 'maxArrivals', 'onExit', 'rateSchedule', 'arrivalSchedule', 'modifyRate', 'rateExpression', 'multipleEntitiesPerArrival', 'locationType', 'locationX', 'locationY', 'locationZ', 'locationLatitude', 'locationLongitude', 'locationGeoPlaceName', 'locationXYZInNetwork', 'locationNetwork', 'locationNode', 'locationAttractor', 'speed', 'enableCustomStartTime', 'startTime', 'addToCustomPopulation', 'population', 'pushProtocol', 'discardHangingEntities', 'onBeforeArrival', 'onAtExit', 'onDiscard', 'setAgentParametersFromDB', 'databaseTable', 'arrivalDate', 'changeDimensions', 'length', 'width', 'height', 'firstArrivalMode', 'firstArrivalTime', 'locationLevel'],
  Queue: ['capacity', 'maximumCapacity', 'onEnter', 'onAtExit', 'onExit', 'enableTimeout', 'timeout', 'onExitTimeout', 'enablePreemption', 'priority', 'onExitPreempted', 'entityLocation', 'forceStatisticsCollection', 'queuing', 'comparison', 'restoreEntityLocationOnExit', 'onRemove'],
  Seize: ['seizeFromOnePool', 'onExit', 'entityLocationQueue', 'timeout', 'resourceQuantity', 'onEnter', 'resourcePool', 'capacity', 'maximumCapacity', 'enableTimeout', 'onExitTimeout', 'enablePreemption', 'priority', 'onExitPreempted', 'forceStatisticsCollection', 'resourceSets', 'seizePolicy', 'sendResources', 'destinationType', 'destinationNode', 'destinationAttractor', 'destinationResource', 'destinationX', 'destinationY', 'destinationZ', 'attachResources', 'taskMayPreemptOtherTasks', 'taskPreemptionPolicy', 'terminatedTaskProcessing', 'terminatedTasksEnter', 'suspendResumeEntities', 'customizeResourceChoice', 'resourceChoiceCondition', 'taskStartBlocksAreConnected', 'taskStartBlocks', 'canceledUnitsBehavior', 'canceledUnitsRelease', 'pushProtocol', 'restoreEntityLocationOnExit', 'onSeizeUnit', 'onPrepareUnit', 'onRemove', 'onTaskTerminated', 'comparison', 'onTaskSuspended', 'onTaskResumed', 'onUnitFinishedWrapUp', 'resourceSelectionMode', 'resourceRating', 'resourceComparison'],
  Delay: ['onExit', 'capacity', 'entityLocation', 'delayTime', 'maximumCapacity', 'onEnter', 'forceStatisticsCollection', 'type', 'pushProtocol', 'restoreEntityLocationOnExit', 'onAtExit', 'onRemove'],
  Release: ['releaseMode', 'resources', 'quantity', 'resourcePool', 'onEnter', 'onExit', 'seizeBlocks', 'movingGoHome', 'wrapUpTaskPolicyType', 'wrapUpTaskPriority', 'wrapUpTaskPreemptionPolicy', 'wrapUpUsageState', 'onReleaseUnit', 'onWrapUpTerminated', 'wrapUpTaskMayPreemptOtherTasks'],
  ResourcePool: ['newUnit', 'onNewUnit', 'capacity', 'forceStatisticsCollection', 'onSeize', 'onRelease', 'capacityDefinitionType', 'capacitySchedule', 'capacityScheduleOnOff', 'capacityOnValue', 'type', 'capacityBasedOnAttractors', 'shiftGroupSchedules', 'shiftGroupSizes', 'shiftGroupsPlan', 'destroyExcessUnits', 'speed', 'homeLocationType', 'homeNode', 'homeNodes', 'showDefaultAnimationStatic', 'endOfShiftTaskPriority', 'endOfShiftTaskPreemptionPolicy', 'endOfShiftTaskMayPreemptOtherTasks', 'enableBreaks', 'breaksSchedule', 'breakTaskPriority', 'breakTaskMayPreemptOtherTasks', 'breakTaskPreemptionPolicy', 'breakUsageState', 'enableFailuresRepairs', 'initialTimeToFailure', 'timeBetweenFailures', 'repairType', 'repairTime', 'repairTaskStart', 'repairUsageState', 'enableMaintenance', 'initialTimeToMaintenance', 'timeBetweenMaintenances', 'maintenanceTaskPriority', 'maintenanceTaskMayPreemptOtherTasks', 'maintenanceType', 'maintenanceTime', 'maintenanceTaskStart', 'maintenanceUsageState', 'enableCustomTasks', 'customTasks', 'addToCustomPopulation', 'population', 'onDestroyUnit', 'onWrapUp', 'onBreakStart', 'onBreakEnd', 'onBreakTerminated', 'onFailure', 'onRepair', 'onMaintenanceStart', 'onMaintenanceEnd', 'onUnitStateChange', 'downtimeSource', 'maintenanceProfile', 'downtimeList', 'countBusyOnlyTimeToFailure', 'customizeRequestChoice', 'requestChoiceCondition'],
  Sink: ['onEnter', 'destroyEntity'],
  SelectOutput: ['conditionIsProbabilistic', 'condition', 'probability', 'onAtEnter', 'onEnter', 'onExitTrue', 'onExitFalse'],
};

// Posición de los puertos respecto al bloque (para dibujar los conectores)
const PORTS = {
  default: { in: [0, 20], out: [40, 20] },
  Source: { out: [30, 10] },
  Sink: { in: [0, 10] },
  SelectOutput: { in: [10, 10], outT: [30, 10], outF: [20, 20] },
};

// ------------------------------------------------------------------ utilidades XML
const cdata = (s) => `<![CDATA[${String(s ?? '').replace(/]]>/g, ']]]]><![CDATA[>')}]]>`;
const code = (c) => ({ cls: 'CodeValue', code: c });
const codeUnit = (c, unitClass, unit) => ({ cls: 'CodeUnitValue', code: c, unitClass, unit });

function valueXml(v, tag = 'Value') {
  if (v.cls === 'CodeUnitValue') {
    return `<${tag} Class="CodeUnitValue"><Code>${cdata(v.code)}</Code><Unit Class="${v.unitClass}">${cdata(v.unit)}</Unit></${tag}>`;
  }
  return `<${tag} Class="CodeValue"><Code>${cdata(v.code)}</Code></${tag}>`;
}

/** Literal numérico Java seguro. */
function num(x) {
  if (x === Infinity) return 'Double.POSITIVE_INFINITY';
  if (x === -Infinity) return 'Double.NEGATIVE_INFINITY';
  if (!Number.isFinite(x)) return '0';
  const s = String(Number(x.toPrecision(12)));
  return /[.eE]/.test(s) ? s : `${s}.0`;
}
const int = (x) => String(Math.round(Number(x) || 0));
const jstr = (s) => JSON.stringify(String(s ?? ''));
const arr = (type, xs, f = num) => `new ${type}[]{${xs.map(f).join(', ')}}`;

function javaPackage(name) {
  let p = String(name || 'modelo')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
  if (!p || /^[0-9]/.test(p)) p = `m_${p}`;
  return p.slice(0, 60);
}

/** Expresión Java que muestrea la distribución (en segundos o en la unidad dada). */
export function distExpr(spec) {
  if (!spec) return '0.0';
  let e;
  switch (spec.type) {
    case 'constant':
      e = num(spec.value);
      break;
    case 'uniform':
      e = `dUniforme(${num(spec.min)}, ${num(spec.max)})`;
      break;
    case 'triangular':
      e = `dTriangular(${num(spec.min)}, ${num(spec.mode)}, ${num(spec.max)})`;
      break;
    case 'pert':
      e = `dPert(${num(spec.min)}, ${num(spec.mode)}, ${num(spec.max)}, ${num(spec.lambda ?? 4)})`;
      break;
    case 'normal':
      e = `dNormal(${num(spec.mean)}, ${num(spec.sd)})`;
      break;
    case 'lognormal':
      e = `dLognormal(${num(spec.mean)}, ${num(spec.sd)})`;
      break;
    case 'exponential':
      e = `dExponencial(${num(spec.mean)})`;
      break;
    case 'gamma':
      e = `dGamma(${num(spec.mean)}, ${num(spec.sd)})`;
      break;
    case 'erlang':
      e = `dErlang(${num(spec.mean)}, ${int(spec.k)})`;
      break;
    case 'weibull':
      e = `dWeibull(${num(spec.shape)}, ${num(spec.scale)}, ${num(spec.location ?? 0)})`;
      break;
    case 'beta':
      e = `dBeta(${num(spec.alpha)}, ${num(spec.beta)}, ${num(spec.min)}, ${num(spec.max)})`;
      break;
    case 'empirical':
      e = `dEmpirica(${arr('double', spec.values || [0])})`;
      break;
    default:
      e = '0.0';
  }
  const t = spec.truncate;
  if (t && (Number.isFinite(t.min) || Number.isFinite(t.max))) {
    e = `dTruncar(() -> ${e}, ${Number.isFinite(t.min) ? num(t.min) : '-Double.MAX_VALUE'}, ${Number.isFinite(t.max) ? num(t.max) : 'Double.MAX_VALUE'})`;
  }
  return e;
}

// ------------------------------------------------------------------ generador
class Ids {
  constructor() {
    this.n = 1729000000000;
  }
  next() {
    this.n += 1;
    return String(this.n);
  }
}

export function toAnyLogic(rawModel) {
  const m = normalizeModel(rawModel);
  const ids = new Ids();
  const pkg = javaPackage(m.name);
  const warnings = [];
  const S = m.settings;
  const nS = m.stations.length;
  const opIndex = new Map(m.operations.map((o) => [o.id, o]));
  const opIdx = new Map(m.operators.map((o, i) => [o.id, i]));
  const mcIdx = new Map(m.machines.map((x, i) => [x.id, i]));
  const stIdx = new Map(m.stations.map((s, i) => [s.id, i]));
  const jid = new Map();
  const used = new Set();
  for (const op of m.operations) {
    let base = `op_${String(op.id).replace(/[^A-Za-z0-9_]/g, '_')}`;
    let name = base;
    for (let k = 2; used.has(name); k++) name = `${base}_${k}`;
    used.add(name);
    jid.set(op.id, name);
  }
  const positions = computeLayout(m);
  const dist = distanceMatrix(m, positions);

  // ---------------------------------------------------------- funciones generadas
  const functions = [...HELPER_FUNCTIONS];
  const fn = (name, ret, params, body) => functions.push([name, ret, params, body]);

  // tiempo de cada operación
  for (const op of m.operations) {
    const mean = moments(op.duration).mean;
    const mods = op.modifiers;
    const intr = op.interruptions;
    const lines = [];
    lines.push(`// ${op.name} (${op.type})`);
    lines.push(`Operario o = ${op.requires.operator ? 'p.operario' : 'null'};`);
    lines.push(`int m = estMaquina[st];`);
    lines.push(`double espera = 0, caminar = 0;`);
    if (op.requires.operator) {
      lines.push(`if (o != null) {`, `\tespera = pausaPendiente(o);`, `\tcaminar = caminar(o, st);`, `\trecuperar(o);`, `}`);
    }
    lines.push(`double base = Math.max(0, ${distExpr(op.duration)});`);
    if (op.requires.operator) lines.push(`if (o != null) base = Math.max(0, ${num(mean)} + (base - ${num(mean)}) * opConsistencia[o.idx]);`);
    else if (op.requires.machine) lines.push(`if (m >= 0) base = Math.max(0, ${num(mean)} + (base - ${num(mean)}) * maqConsistencia[m]);`);
    lines.push(`double f = factorProducto(p.producto, ${jstr(op.id)}, ${jstr(op.type)});`);
    if (op.requires.operator) {
      const parts = [];
      if (mods.skill) parts.push(`\tf *= 100.0 / ritmo(o.idx, ${jstr(op.type)}, ${jstr(op.id)});`);
      if (mods.learning) parts.push(`\tf *= aprendizajeOp(o, ${jstr(op.id)});`);
      if (mods.fatigue) parts.push(`\tf *= fatiga(o);`);
      if (parts.length) lines.push('if (o != null) {', ...parts, '}');
    }
    if (op.requires.machine) lines.push(`if (m >= 0) f /= maqVelocidad[m];`);
    lines.push(`double trabajo = base * f;`);
    lines.push(`double viaje = 0;`);
    if (op.distanceBased?.speed) {
      lines.push(`int destino = Math.min(st + 1, distancia.length - 1);`);
      lines.push(`double v = Math.max(0.05, ${op.type === 'walking' ? '(o != null ? velocidadMarcha(o.idx) : ' + distExpr(op.distanceBased.speed) + ')' : distExpr(op.distanceBased.speed)});`);
      lines.push(`viaje = distancia[st][destino] / v${mods.fatigue && op.requires.operator ? ' * (o != null ? fatiga(o) : 1)' : ''};`);
    }
    if (mods.interruptions && intr?.ratePerHour > 0) {
      lines.push(`double interr = interrupciones(${num(intr.ratePerHour)}, trabajo + viaje, () -> ${distExpr(intr.duration)});`);
    } else lines.push(`double interr = 0;`);
    lines.push(op.requires.machine ? `double averia = averias(m, trabajo + viaje + interr);` : `double averia = 0;`);
    lines.push(`double total = espera + caminar + trabajo + viaje + interr + averia;`);
    if (op.requires.operator) lines.push(`if (o != null) registrarTrabajo(o, ${jstr(op.id)}, total, espera);`);
    lines.push(`return total;`);
    fn(jid.get(op.id), 'double', [['p', 'Pieza'], ['st', 'int']], lines.join('\n'));
  }

  // ritmo por operario
  {
    const b = ['switch (idx) {'];
    m.operators.forEach((o, i) => {
      b.push(`case ${i}:`);
      for (const [opId, v] of Object.entries(o.performance.byOperation || {})) b.push(`\tif (opId.equals(${jstr(opId)})) return ${num(v)};`);
      for (const [t, v] of Object.entries(o.performance.byType || {})) b.push(`\tif (tipo.equals(${jstr(t)})) return ${num(v)};`);
      b.push(`\treturn ${num(o.performance.default ?? 100)};`);
    });
    b.push('}', 'return 100.0;');
    fn('ritmo', 'double', [['idx', 'int'], ['tipo', 'String'], ['opId', 'String']], b.join('\n'));
  }
  // velocidad de marcha
  {
    const b = ['switch (idx) {'];
    m.operators.forEach((o, i) => b.push(`case ${i}: return ${distExpr(o.walkSpeed)};`));
    b.push('}', 'return 1.2;');
    fn('velocidadMarcha', 'double', [['idx', 'int']], b.join('\n'));
  }
  // aprendizaje con posible curva propia de la operación
  {
    const b = [
      'double tasa = opTasaAprendizaje[o.idx], exp = opExperiencia[o.idx], std = opUdsEstandar[o.idx], meseta = opMeseta[o.idx];',
      'switch (opId) {',
    ];
    for (const op of m.operations) {
      if (!op.learning) continue;
      b.push(`case ${jstr(op.id)}:`);
      if (op.learning.rate !== undefined) b.push(`\ttasa = ${num(op.learning.rate)};`);
      if (op.learning.standardUnits !== undefined) b.push(`\tstd = ${num(op.learning.standardUnits)};`);
      b.push('\tbreak;');
    }
    b.push('default: break;', '}', 'return aprendizaje(o, opId, tasa, exp, std, meseta);');
    fn('aprendizajeOp', 'double', [['o', 'Operario'], ['opId', 'String']], b.join('\n'));
  }
  // factores de producto
  {
    const b = ['switch (prod) {'];
    m.products.forEach((p, i) => {
      b.push(`case ${i}:`);
      for (const [opId, v] of Object.entries(p.timeFactors || {})) b.push(`\tif (opId.equals(${jstr(opId)})) return ${num(v)};`);
      for (const [t, v] of Object.entries(p.timeFactorsByType || {})) b.push(`\tif (tipo.equals(${jstr(t)})) return ${num(v)};`);
      b.push(`\treturn ${num(p.timeFactor ?? 1)};`);
    });
    b.push('}', 'return 1.0;');
    fn('factorProducto', 'double', [['prod', 'int'], ['opId', 'String'], ['tipo', 'String']], b.join('\n'));
  }
  // mezcla de productos
  {
    const w = m.products.map((p) => Math.max(0, p.mix ?? 1));
    const total = w.reduce((a, x) => a + x, 0) || 1;
    let acc = 0;
    const b = ['double r = uniform();'];
    w.forEach((x, i) => {
      acc += x / total;
      if (i < w.length - 1) b.push(`if (r < ${num(acc)}) return ${i};`);
    });
    b.push(`return ${w.length - 1};`);
    fn('elegirProducto', 'int', [], b.join('\n'));
  }
  // averías
  {
    const mt = ['switch (m) {'];
    const mr = ['switch (m) {'];
    m.machines.forEach((x, i) => {
      if (x.failures?.enabled) {
        mt.push(`case ${i}: return ${distExpr(x.failures.mtbf)};`);
        mr.push(`case ${i}: return ${distExpr(x.failures.mttr)};`);
      }
    });
    mt.push('}', 'return Double.POSITIVE_INFINITY;');
    mr.push('}', 'return 0.0;');
    fn('mtbf', 'double', [['m', 'int']], mt.join('\n'));
    fn('mttr', 'double', [['m', 'int']], mr.join('\n'));
  }
  // calidad por operación
  {
    const sw = (name, ret, pick, def) => {
      const b = ['switch (opId) {'];
      for (const op of m.operations) {
        const v = pick(op);
        if (v !== null && v !== undefined) b.push(`case ${jstr(op.id)}: return ${v};`);
      }
      b.push('default: break;', '}', `return ${def};`);
      fn(name, ret, [['opId', 'String']], b.join('\n'));
    };
    sw('probDefecto', 'double', (op) => (!op.isInspection && op.quality.defectProb > 0 ? num(op.quality.defectProb) : null), '0.0');
    sw('probDeteccion', 'double', (op) => (op.isInspection ? num(op.quality.detectionProb) : null), '1.0');
    sw('probFalsoRechazo', 'double', (op) => (op.isInspection ? num(op.quality.falseRejectProb) : null), '0.0');
    sw('retrabajaSiRechaza', 'boolean', (op) => (op.isInspection ? String(op.quality.onReject === 'rework' && Boolean(op.quality.reworkOperationId && opIndex.has(op.quality.reworkOperationId))) : null), 'false');
    sw('maxRetrabajos', 'int', (op) => (op.isInspection ? int(op.quality.maxReworks) : null), '0');
    sw('eficaciaRetrabajo', 'double', (op) => (op.isInspection ? num(op.quality.repairProb) : null), '1.0');
  }
  // quién puede hacer cada operación en cada estación
  {
    const b = ['switch (st) {'];
    m.stations.forEach((s, i) => {
      b.push(`case ${i}:`);
      for (const opId of [...s.operationIds, s.setup?.operationId, s.transportOperationId].filter(Boolean)) {
        const op = opIndex.get(opId);
        if (op?.operatorIds?.length) b.push(`\tif (opId.equals(${jstr(opId)})) return ${op.operatorIds.map((x) => `idx == ${opIdx.get(x) ?? -1}`).join(' || ')};`);
      }
      for (const opId of s.operationIds) {
        const op = opIndex.get(opId);
        const rw = op?.isInspection ? opIndex.get(op.quality.reworkOperationId) : null;
        if (rw?.operatorIds?.length) b.push(`\tif (opId.equals(${jstr(rw.id)})) return ${rw.operatorIds.map((x) => `idx == ${opIdx.get(x) ?? -1}`).join(' || ')};`);
      }
      const allowed = s.operatorIds.map((x) => opIdx.get(x)).filter((x) => x !== undefined);
      b.push(`\treturn ${allowed.length ? allowed.map((x) => `idx == ${x}`).join(' || ') : 'false'};`);
    });
    b.push('}', 'return false;');
    fn('puedeHacer', 'boolean', [['idx', 'int'], ['st', 'int'], ['opId', 'String']], b.join('\n'));
  }
  // nombres
  fn('nombreOperario', 'String', [['idx', 'int']], `String[] n = ${arr('String', m.operators.map((o) => o.name || o.id), jstr)};\nreturn idx >= 0 && idx < n.length ? n[idx] : "?";`);
  fn('nombreMaquina', 'String', [['m', 'int']], `String[] n = ${arr('String', m.machines.map((x) => x.name || x.id), jstr)};\nreturn m >= 0 && m < n.length ? n[m] : "?";`);
  if (m.arrivals.mode === 'interarrival') fn('tiempoEntreLlegadas', 'double', [], `return Math.max(0.001, ${distExpr(m.arrivals.interarrival)});`);

  // ---------------------------------------------------------- variables
  const D = (o, path, def) => path.split('.').reduce((a, k) => (a == null ? a : a[k]), o) ?? def;
  const homeIdx = m.operators.map((o) => {
    const home = o.homeStationId || m.stations.find((s) => s.operatorIds.includes(o.id))?.id;
    return stIdx.get(home) ?? 0;
  });
  const variables = [
    ['calentamientoH', 'double', num(S.warmupHours), 'param', 'Calentamiento (h)'],
    ['turnoH', 'double', num(S.shift?.lengthHours || 8)],
    ['pausaInicioH', 'double[]', arr('double', (S.shift?.breaks || []).map((b) => b.atHours))],
    ['pausaMin', 'double[]', arr('double', (S.shift?.breaks || []).map((b) => b.durationMin))],
    ['tamanoLote', 'int', int(Math.max(1, m.arrivals.batchSize || 1))],
    ['loteRestante', 'int', '0'],
    ['loteProducto', 'int', '0'],
    ['distancia', 'double[][]', `new double[][]{${m.stations.map((a) => `{${m.stations.map((b) => num(dist[a.id][b.id])).join(', ')}}`).join(', ')}}`],
    ['estMaquina', 'int[]', arr('int', m.stations.map((s) => (s.machineId ? mcIdx.get(s.machineId) ?? -1 : -1)), int)],
    ['setupModo', 'int[]', arr('int', m.stations.map((s) => (s.setup?.operationId ? (s.setup.trigger === 'changeover' ? 1 : s.setup.trigger === 'everyN' ? 2 : 0) : 0)), int)],
    ['setupCadaN', 'int[]', arr('int', m.stations.map((s) => s.setup?.everyN || 0), int)],
    ['ultimoProducto', 'int[]', arr('int', m.stations.map(() => -1), int)],
    ['desdeSetup', 'int[]', `new int[${nS}]`],
    ['opConsistencia', 'double[]', arr('double', m.operators.map((o) => o.consistency ?? 1))],
    ['opTasaAprendizaje', 'double[]', arr('double', m.operators.map((o) => D(o, 'learning.rate', 0.9)))],
    ['opExperiencia', 'double[]', arr('double', m.operators.map((o) => D(o, 'learning.experienceUnits', 500)))],
    ['opUdsEstandar', 'double[]', arr('double', m.operators.map((o) => D(o, 'learning.standardUnits', 500)))],
    ['opMeseta', 'double[]', arr('double', m.operators.map((o) => D(o, 'learning.plateau', 1)))],
    ['opFatigaMax', 'double[]', arr('double', m.operators.map((o) => D(o, 'fatigue.maxIncrease', 0)))],
    ['opFatigaTauH', 'double[]', arr('double', m.operators.map((o) => D(o, 'fatigue.timeConstantH', 3)))],
    ['opRecuperacionH', 'double[]', arr('double', m.operators.map((o) => D(o, 'fatigue.recoveryH', 0.25) || 0.25))],
    ['opSensCalidad', 'double[]', arr('double', m.operators.map((o) => o.qualityFatigueSensitivity || 0))],
    ['opCasa', 'int[]', arr('int', homeIdx, int)],
    ['maqConsistencia', 'double[]', arr('double', m.machines.map((x) => x.consistency ?? 1))],
    ['maqVelocidad', 'double[]', arr('double', m.machines.map((x) => x.speedFactor || 1))],
    ['maqAverias', 'boolean[]', arr('boolean', m.machines.map((x) => Boolean(x.failures?.enabled)), String)],
    ['maqUptime', 'double[]', `new double[${m.machines.length}]`],
    ['maqFallos', 'int[]', `new int[${m.machines.length}]`],
    ['maqTiempoCaido', 'double[]', `new double[${m.machines.length}]`],
    ['contadorOperarios', 'int', '0'],
    ['listaOperarios', 'java.util.ArrayList<Operario>', 'new java.util.ArrayList<Operario>()'],
    ['leadTimes', 'java.util.ArrayList<Double>', 'new java.util.ArrayList<Double>()'],
    ['wip', 'int', '0'],
    ['wipArea', 'double', '0'],
    ['wipT', 'double', '0'],
    ...['creadas', 'terminadas', 'desechadas', 'primeraPasada', 'rechazos', 'falsosRechazos', 'retrabajos', 'escapados', 'defectosCreados', 'setups'].map((n) => [n, 'int', '0']),
  ];

  // ---------------------------------------------------------- diagrama de flujo
  const blocks = [];
  const blockClass = new Map();
  const conns = [];
  const block = (name, cls, x, y, params = {}, generic = 'Pieza') => {
    blocks.push({ name, cls, x, y, params, generic });
    blockClass.set(name, cls);
    return name;
  };
  const link = (from, fromPort, to, toPort = 'in') => conns.push({ from, fromPort, to, toPort });
  const unitS = (c) => codeUnit(c, 'TimeUnits', 'SECOND');

  // recursos
  const pools = [];
  pools.push(block('operarios', 'ResourcePool', 0, -120, { newUnit: code('nuevoOperario()'), capacity: code(String(m.operators.length)), forceStatisticsCollection: code('true') }, 'Operario'));
  m.machines.forEach((x, i) => pools.push(block(`maquina${i + 1}`, 'ResourcePool', 80 + i * 80, -120, { capacity: code('1'), forceStatisticsCollection: code('true') }, 'Agent')));
  m.stations.forEach((s, i) => pools.push(block(`puestos${i + 1}`, 'ResourcePool', 80 + (m.machines.length + i) * 80, -120, { capacity: code(String(Math.max(1, s.workplaces))), forceStatisticsCollection: code('true') }, 'Agent')));
  const machineBlock = (i) => `maquina${i + 1}`;

  const COL = 70;
  const ROW = 160;
  const startup = [
    'for (int i = 0; i < maqUptime.length; i++) maqUptime[i] = maqAverias[i] ? Math.max(1, mtbf(i)) : Double.POSITIVE_INFINITY;',
  ];

  // llegadas
  const firstSeize = 'est1_entrada';
  if (m.arrivals.mode === 'interarrival') {
    block('llegadas', 'Source', 0, 0, {
      arrivalType: code('self.INTERARRIVAL_TIME'),
      interarrivalTime: unitS('tiempoEntreLlegadas()'),
      multipleEntitiesPerArrival: code(String((m.arrivals.batchSize || 1) > 1)),
      entitiesPerArrival: code(int(Math.max(1, m.arrivals.batchSize || 1))),
      newEntity: code('new Pieza()'),
      onAtExit: code('asignarProducto(agent);'),
    });
    block('pedidos', 'Queue', COL, 0, { maximumCapacity: code('true') });
    link('llegadas', 'out', 'pedidos');
    link('pedidos', 'out', firstSeize);
  } else {
    block('llegadas', 'Source', 0, 0, {
      arrivalType: code('self.MANUAL'),
      newEntity: code('new Pieza()'),
      onAtExit: code('asignarProducto(agent);'),
    });
    link('llegadas', 'out', firstSeize);
    startup.push(`llegadas.inject(${Math.max(1, m.stations[0]?.bufferCapacity ?? 1)});`);
  }

  const codeChecks = []; // expresiones de bloques para comprobar compilación

  m.stations.forEach((s, i) => {
    const y = 80 + i * ROW;
    let x = COL * 2;
    const p = `est${i + 1}_`;
    const nx = () => (x += COL);
    const enterCode = [i === 0 ? 'cambiarWip(1);' : ''].filter(Boolean).join('\n');
    const exitCode = i === 0 && m.arrivals.mode !== 'interarrival' ? 'llegadas.inject(1);' : '';
    block(`${p}entrada`, 'Seize', x, y, {
      seizeFromOnePool: code('true'),
      resourcePool: code(`puestos${i + 1}`),
      capacity: code(String(Math.max(1, s.bufferCapacity))),
      ...(enterCode ? { onEnter: code(enterCode) } : {}),
      ...(exitCode ? { onExit: code(exitCode) } : {}),
    });
    if (s.bufferCapacity === 0) warnings.push(`${s.name || s.id}: AnyLogic necesita cola ≥ 1; se usa 1 en lugar de 0.`);
    let tail = `${p}entrada`;
    let tailPort = 'out';
    const pending = []; // salidas sueltas que deben unirse al siguiente bloque
    const connectTo = (target) => {
      link(tail, tailPort, target);
      for (const [b, port] of pending.splice(0)) link(b, port, target);
    };

    // cadena de una operación; devuelve [primero, último]
    const opChain = (op, tag, yy, extraExit = '') => {
      const names = [];
      const add = (nm) => names.push(nm);
      const req = op.requires;
      const mIdx = s.machineId ? mcIdx.get(s.machineId) : undefined;
      if (req.machine && mIdx === undefined) warnings.push(`${s.name}: «${op.name}» necesita máquina y la estación no tiene.`);
      if (req.machine && mIdx !== undefined) add(block(`${p}${tag}_tomaMaq`, 'Seize', nx(), yy, { seizeFromOnePool: code('true'), resourcePool: code(machineBlock(mIdx)), maximumCapacity: code('true') }));
      if (req.operator) {
        const cond = `puedeHacer(((Operario) unit).idx, ${i}, ${jstr(op.id)})`;
        codeChecks.push({ kind: 'choice', code: cond });
        add(block(`${p}${tag}_tomaOp`, 'Seize', nx(), yy, {
          seizeFromOnePool: code('true'),
          resourcePool: code('operarios'),
          maximumCapacity: code('true'),
          customizeResourceChoice: code('true'),
          resourceChoiceCondition: code(cond),
          onSeizeUnit: code('agent.operario = (Operario) unit;'),
        }));
      }
      const onExit = [!op.isInspection && op.quality.defectProb > 0 ? `trasOperacion(agent, ${jstr(op.id)});` : '', extraExit].filter(Boolean).join('\n');
      const delayCode = `${jid.get(op.id)}(agent, ${i})`;
      codeChecks.push({ kind: 'delay', code: delayCode }, ...(onExit ? [{ kind: 'action', code: onExit }] : []));
      add(block(`${p}${tag}`, 'Delay', nx(), yy, { delayTime: unitS(delayCode), maximumCapacity: code('true'), ...(onExit ? { onExit: code(onExit) } : {}) }));
      if (req.operator) add(block(`${p}${tag}_liberaOp`, 'Release', nx(), yy, { releaseMode: code('self.ALL_FROM_POOLS'), resources: code('{ operarios }'), resourcePool: code('operarios') }));
      if (req.machine && mIdx !== undefined) add(block(`${p}${tag}_liberaMaq`, 'Release', nx(), yy, { releaseMode: code('self.ALL_FROM_POOLS'), resources: code(`{ ${machineBlock(mIdx)} }`), resourcePool: code(machineBlock(mIdx)) }));
      for (let k = 1; k < names.length; k++) link(names[k - 1], 'out', names[k]);
      return [names[0], names[names.length - 1]];
    };

    // setup
    const setupOp = s.setup?.operationId ? opIndex.get(s.setup.operationId) : null;
    if (setupOp && s.setup.trigger !== 'none') {
      const sel = block(`${p}setup_si`, 'SelectOutput', nx(), y, { conditionIsProbabilistic: code('false'), condition: code(`necesitaSetup(agent, ${i})`) });
      codeChecks.push({ kind: 'cond', code: `necesitaSetup(agent, ${i})` });
      connectTo(sel);
      const [a, b] = opChain(setupOp, 'setup', y + 60);
      link(sel, 'outT', a);
      tail = sel;
      tailPort = 'outF';
      pending.push([b, 'out']);
    }

    // operaciones
    s.operationIds.forEach((opId, k) => {
      const op = opIndex.get(opId);
      if (!op) return;
      const tag = `${String(opId).replace(/[^A-Za-z0-9_]/g, '_')}${k}`;
      const [a, b] = opChain(op, tag, y);
      connectTo(a);
      tail = b;
      tailPort = 'out';
      if (op.isInspection) {
        const ok = block(`${p}${tag}_ok`, 'SelectOutput', nx(), y, { conditionIsProbabilistic: code('false'), condition: code(`inspeccionOk(agent, ${jstr(op.id)})`) });
        const rw = block(`${p}${tag}_retrabajo_si`, 'SelectOutput', x, y + 60, { conditionIsProbabilistic: code('false'), condition: code(`puedeRetrabajar(agent, ${jstr(op.id)})`) });
        codeChecks.push({ kind: 'cond', code: `inspeccionOk(agent, ${jstr(op.id)})` }, { kind: 'cond', code: `puedeRetrabajar(agent, ${jstr(op.id)})` });
        link(b, 'out', ok);
        link(ok, 'outF', rw);
        const reworkOp = op.quality.reworkOperationId ? opIndex.get(op.quality.reworkOperationId) : null;
        if (reworkOp) {
          const saveX = x;
          const [ra, rb] = opChain(reworkOp, `${tag}_rt`, y + 60, `reparar(agent, ${jstr(op.id)});`);
          x = saveX;
          link(rw, 'outT', ra);
          link(rb, 'out', a); // vuelve a inspeccionar
        }
        const scrap = block(`${p}${tag}_desecho`, 'Release', x + COL, y + 110, { releaseMode: code('self.ALL_FROM_POOLS'), resources: code(`{ puestos${i + 1} }`), resourcePool: code(`puestos${i + 1}`) });
        link(rw, 'outF', scrap);
        link(scrap, 'out', 'desecho');
        if (!reworkOp) link(rw, 'outT', scrap);
        tail = ok;
        tailPort = 'outT';
      }
    });

    // salida con bloqueo, transporte y liberación del puesto
    const out = block(`${p}salida`, 'Queue', nx(), y, { maximumCapacity: code('true') });
    connectTo(out);
    tail = out;
    tailPort = 'out';
    const tr = s.transportOperationId ? opIndex.get(s.transportOperationId) : null;
    if (tr && i < nS - 1) {
      const [a, b] = opChain(tr, 'transporte', y);
      connectTo(a);
      tail = b;
    }
    const rel = block(`${p}libera`, 'Release', nx(), y, { releaseMode: code('self.ALL_FROM_POOLS'), resources: code(`{ puestos${i + 1} }`), resourcePool: code(`puestos${i + 1}`) });
    connectTo(rel);
    link(rel, 'out', i < nS - 1 ? `est${i + 2}_entrada` : 'fin');
  });

  const lastY = 80 + nS * ROW;
  block('fin', 'Sink', COL * 2, lastY, { onEnter: code('registrarSalida(agent, true);') });
  block('desecho', 'Sink', COL * 4, lastY, { onEnter: code('registrarSalida(agent, false);') });
  codeChecks.push({ kind: 'action', code: 'registrarSalida(agent, true);' }, { kind: 'action', code: 'asignarProducto(agent);' });

  const xml = renderXml({ m, ids, pkg, functions, variables, blocks, blockClass, conns, startup, S });
  return {
    xml,
    fileName: `${pkg}.alp`,
    warnings,
    javaPackage: pkg,
    // para las pruebas: todo el código Java que contiene el modelo
    java: { functions, variables, startup, codeChecks },
  };
}

// ------------------------------------------------------------------ render XML
function renderXml({ m, ids, pkg, functions, variables, blocks, blockClass, conns, startup, S }) {
  const horizon = S.horizonHours * 3600;
  const mainId = ids.next();
  const piezaId = ids.next();
  const operarioId = ids.next();
  const mainLevel = ids.next();
  const genericId = ids.next();
  const t0 = Date.UTC(2026, 0, 1, 6, 0, 0);

  const common = (name, x, y) => `<Id>${ids.next()}</Id>
<Name>${cdata(name)}</Name>
<X>${Math.round(x)}</X><Y>${Math.round(y)}</Y>
<Label><X>10</X><Y>0</Y></Label>
<PublicFlag>false</PublicFlag>
<PresentationFlag>true</PresentationFlag>
<ShowLabel>true</ShowLabel>`;

  const plainVar = ([name, type, init], i) => `<Variable Class="PlainVariable">
${common(name, 900, -300 + i * 20)}
<Properties SaveInSnapshot="true" Constant="false" AccessType="public" StaticVariable="false">
<Type>${cdata(type)}</Type>
${init !== undefined ? `<InitialValue Class="CodeValue"><Code>${cdata(init)}</Code></InitialValue>` : ''}
</Properties>
</Variable>`;

  const parameter = ([name, type, def, , label], i, y0 = -300) => `<Variable Class="Parameter">
${common(name, 700, y0 + i * 20)}
<Properties SaveInSnapshot="true" ModificatorType="STATIC">
<Type>${cdata(type)}</Type>
<UnitType>${cdata('NONE')}</UnitType>
<SdArray>false</SdArray>
<DefaultValue Class="CodeValue"><Code>${cdata(def)}</Code></DefaultValue>
<ParameterEditor>
<Id>${ids.next()}</Id>
<Label>${cdata(label || name)}</Label>
<EditorContolType>TEXT_BOX</EditorContolType>
<MinSliderValue>${cdata('0')}</MinSliderValue>
<MaxSliderValue>${cdata('100')}</MaxSliderValue>
<DelimeterType>NO_DELIMETER</DelimeterType>
</ParameterEditor>
</Properties>
</Variable>`;

  const funcXml = ([name, ret, params, body], i) => `<Function AccessType="public" StaticFunction="false">
<ReturnModificator>${ret === 'void' ? 'VOID' : 'RETURNS_VALUE'}</ReturnModificator>
<ReturnType>${cdata(ret)}</ReturnType>
${common(name, 1100 + Math.floor(i / 40) * 180, -300 + (i % 40) * 20)}
${params.map(([n, t]) => `<Parameter>
<Name>${cdata(n)}</Name>
<Type>${cdata(t)}</Type>
</Parameter>`).join('\n')}
<Body>${cdata(body)}</Body>
</Function>`;

  const tail = `<ReplicationFlag>false</ReplicationFlag>
<Replication Class="CodeValue"><Code>${cdata('100')}</Code></Replication>
<CollectionType>ARRAY_LIST_BASED</CollectionType>
<InitialSpeedCode Class="CodeUnitValue"><Code>${cdata('10')}</Code><Unit Class="SpeedUnits">${cdata('MPS')}</Unit></InitialSpeedCode>
<InitialLocationType>XYZ</InitialLocationType>
<XCode Class="CodeValue"><Code>${cdata('0')}</Code></XCode>
<YCode Class="CodeValue"><Code>${cdata('0')}</Code></YCode>
<ZCode Class="CodeValue"><Code>${cdata('0')}</Code></ZCode>
<ColumnCode Class="CodeValue"><Code>${cdata('0')}</Code></ColumnCode>
<RowCode Class="CodeValue"><Code>${cdata('0')}</Code></RowCode>
<LocationNameCode Class="CodeValue"><Code>${cdata('""')}</Code></LocationNameCode>
<InitializationType>SPECIFIED_NUMBER</InitializationType>
<InitializationDatabaseTableQuery>
<TableReference>
</TableReference>
</InitializationDatabaseTableQuery>
<InitializationDatabaseType>ONE_AGENT_PER_DATABASE_RECORD</InitializationDatabaseType>
<QuantityColumn>
</QuantityColumn>`;

  const blockXml = (b) => {
    const names = BLOCK_PARAMS[b.cls];
    const set = Object.keys(b.params);
    const ordered = [...set, ...names.filter((n) => !set.includes(n))];
    return `<EmbeddedObject>
<Id>${ids.next()}</Id>
<Name>${cdata(b.name)}</Name>
<X>${b.x}</X><Y>${b.y}</Y>
<Label><X>0</X><Y>-12</Y></Label>
<PublicFlag>false</PublicFlag>
<PresentationFlag>true</PresentationFlag>
<ShowLabel>true</ShowLabel>
<ActiveObjectClass>
<PackageName>${cdata(PML)}</PackageName>
<ClassName>${cdata(b.cls)}</ClassName>
</ActiveObjectClass>
<GenericParameterSubstitute>
<GenericParameterSubstituteReference>
<PackageName>${cdata(PML)}</PackageName>
<ClassName>${cdata(b.cls)}</ClassName>
<ItemName>${cdata(GENERIC_ID[b.cls])}</ItemName>
</GenericParameterSubstituteReference>
<GenericParameterSubstituteValue Class="CodeValue">
<Code>${cdata(b.generic)}</Code>
</GenericParameterSubstituteValue>
</GenericParameterSubstitute>
<Parameters>
${ordered.map((n) => `<Parameter>
<Name>${cdata(n)}</Name>
${b.params[n] ? valueXml(b.params[n]) : ''}
</Parameter>`).join('\n')}
</Parameters>
${tail}
</EmbeddedObject>`;
  };

  const pos = new Map(blocks.map((b) => [b.name, b]));
  const port = (name, p) => {
    const cls = blockClass.get(name);
    const o = PORTS[cls]?.[p] || PORTS.default[p] || [0, 0];
    const b = pos.get(name);
    return [b.x + o[0], b.y + o[1]];
  };
  const connXml = (c, i) => {
    const [x1, y1] = port(c.from, c.fromPort);
    const [x2, y2] = port(c.to, c.toPort);
    const dx = x2 - x1;
    const dy = y2 - y1;
    const pts = dy === 0 ? [[0, 0], [dx, 0]] : dx > 10 ? [[0, 0], [Math.round(dx / 2), 0], [Math.round(dx / 2), dy], [dx, dy]] : [[0, 0], [10, 0], [10, dy - 30 * Math.sign(dy || 1)], [dx - 10, dy - 30 * Math.sign(dy || 1)], [dx - 10, dy], [dx, dy]];
    return `<Connector>
<Id>${ids.next()}</Id>
<Name>${cdata(`connector${i}`)}</Name>
<X>${x1}</X><Y>${y1}</Y>
<Label><X>10</X><Y>0</Y></Label>
<PublicFlag>false</PublicFlag>
<PresentationFlag>true</PresentationFlag>
<ShowLabel>false</ShowLabel>
<SourceEmbeddedObjectReference>
<PackageName>${cdata(pkg)}</PackageName>
<ClassName>${cdata('Main')}</ClassName>
<ItemName>${cdata(c.from)}</ItemName>
</SourceEmbeddedObjectReference>
<SourceConnectableItemReference>
<PackageName>${cdata(PML)}</PackageName>
<ClassName>${cdata(blockClass.get(c.from))}</ClassName>
<ItemName>${cdata(c.fromPort)}</ItemName>
</SourceConnectableItemReference>
<TargetEmbeddedObjectReference>
<PackageName>${cdata(pkg)}</PackageName>
<ClassName>${cdata('Main')}</ClassName>
<ItemName>${cdata(c.to)}</ItemName>
</TargetEmbeddedObjectReference>
<TargetConnectableItemReference>
<PackageName>${cdata(PML)}</PackageName>
<ClassName>${cdata(blockClass.get(c.to))}</ClassName>
<ItemName>${cdata(c.toPort)}</ItemName>
</TargetConnectableItemReference>
<Points>
${pts.map(([px, py]) => `<Point><X>${px}</X><Y>${py}</Y></Point>`).join('\n')}
</Points>
</Connector>`;
  };

  const agentProps = `<AgentProperties>
<EnvironmentDefinesInitialLocation>true</EnvironmentDefinesInitialLocation>
<RotateAnimationTowardsMovement>true</RotateAnimationTowardsMovement>
<RotateAnimationVertically>false</RotateAnimationVertically>
<VelocityCode Class="CodeUnitValue"><Code>${cdata('10')}</Code><Unit Class="SpeedUnits">${cdata('MPS')}</Unit></VelocityCode>
<PhysicalLength Class="CodeUnitValue"><Code>${cdata('1')}</Code><Unit Class="LengthUnits">${cdata('METER')}</Unit></PhysicalLength>
<PhysicalWidth Class="CodeUnitValue"><Code>${cdata('1')}</Code><Unit Class="LengthUnits">${cdata('METER')}</Unit></PhysicalWidth>
<PhysicalHeight Class="CodeUnitValue"><Code>${cdata('1')}</Code><Unit Class="LengthUnits">${cdata('METER')}</Unit></PhysicalHeight>
</AgentProperties>
<EnvironmentProperties>
<EnableSteps>false</EnableSteps>
<StepDurationCode Class="CodeUnitValue"><Code>${cdata('1.0')}</Code><Unit Class="TimeUnits">${cdata('SECOND')}</Unit></StepDurationCode>
<SpaceType>CONTINUOUS</SpaceType>
<WidthCode>${cdata('500')}</WidthCode>
<HeightCode>${cdata('500')}</HeightCode>
<ZHeightCode>${cdata('0')}</ZHeightCode>
<ColumnsCountCode>${cdata('100')}</ColumnsCountCode>
<RowsCountCode>${cdata('100')}</RowsCountCode>
<NeigborhoodType>MOORE</NeigborhoodType>
<LayoutType>USER_DEF</LayoutType>
<NetworkType>USER_DEF</NetworkType>
<ConnectionsPerAgentCode>${cdata('2')}</ConnectionsPerAgentCode>
<ConnectionsRangeCode>${cdata('50')}</ConnectionsRangeCode>
<NeighborLinkFractionCode>${cdata('0.95')}</NeighborLinkFractionCode>
<MCode>${cdata('10')}</MCode>
</EnvironmentProperties>
<DatasetsCreationProperties>
<AutoCreate>true</AutoCreate>
<OccurrenceAtTime>true</OccurrenceAtTime>
<OccurrenceDate>${t0}</OccurrenceDate>
<OccurrenceTime Class="CodeUnitValue"><Code>${cdata('0')}</Code><Unit Class="TimeUnits">${cdata('SECOND')}</Unit></OccurrenceTime>
<RecurrenceCode Class="CodeUnitValue"><Code>${cdata('60')}</Code><Unit Class="TimeUnits">${cdata('SECOND')}</Unit></RecurrenceCode>
</DatasetsCreationProperties>`;

  const scale = () => `<ScaleRuler>
<Id>${ids.next()}</Id>
<Name>${cdata('scale')}</Name>
<X>0</X><Y>-150</Y>
<PublicFlag>false</PublicFlag>
<PresentationFlag>false</PresentationFlag>
<ShowLabel>false</ShowLabel>
<DrawMode>SHAPE_DRAW_2D3D</DrawMode>
<Length>100</Length>
<Rotation>0</Rotation>
<ScaleType>BASED_ON_LENGTH</ScaleType>
<ModelLength>10</ModelLength>
<LengthUnits>METER</LengthUnits>
<Scale>10</Scale>
<InheritedFromParentAgentType>true</InheritedFromParentAgentType>
</ScaleRuler>`;

  const linksXml = (connId) => `<AgentLinks>
<AgentLink>
<Id>${connId}</Id>
<Name>${cdata('connections')}</Name>
<X>50</X><Y>-50</Y>
<Label><X>15</X><Y>0</Y></Label>
<PublicFlag>false</PublicFlag>
<PresentationFlag>true</PresentationFlag>
<ShowLabel>true</ShowLabel>
<HandleReceiveInConnections>false</HandleReceiveInConnections>
<AgentLinkType>COLLECTION_OF_LINKS</AgentLinkType>
<AgentLinkBidirectional>true</AgentLinkBidirectional>
<MessageType>${cdata('Object')}</MessageType>
<LineStyle>SOLID</LineStyle>
<LineWidth>1</LineWidth>
<LineColor>-16777216</LineColor>
<LineZOrder>UNDER_AGENTS</LineZOrder>
<LineArrow>NONE</LineArrow>
<LineArrowPosition>END</LineArrowPosition>
</AgentLink>
</AgentLinks>`;

  const level = (id) => `<Presentation>
<Level>
<Id>${id}</Id>
<Name>${cdata('level')}</Name>
<X>0</X><Y>0</Y>
<Label><X>10</X><Y>0</Y></Label>
<PublicFlag>true</PublicFlag>
<PresentationFlag>true</PresentationFlag>
<ShowLabel>false</ShowLabel>
<DrawMode>SHAPE_DRAW_2D3D</DrawMode>
<Z>0</Z>
<LevelVisibility>ALWAYS_SHOW</LevelVisibility>
</Level>
</Presentation>`;

  const agentClass = (id, name, vars, params = []) => {
    const lvl = ids.next();
    const conn = ids.next();
    return `<ActiveObjectClass>
<Id>${id}</Id>
<Name>${cdata(name)}</Name>
<Generic>false</Generic>
<FlowChartsUsage>ENTITY</FlowChartsUsage>
<SamplesToKeep>100</SamplesToKeep>
<LimitNumberOfArrayElements>false</LimitNumberOfArrayElements>
<ElementsLimitValue>100</ElementsLimitValue>
<MakeDefaultViewArea>true</MakeDefaultViewArea>
<SceneGridColor/>
<SceneBackgroundColor/>
<SceneSkybox>null</SceneSkybox>
${agentProps}
${scale()}
<CurrentLevel>${lvl}</CurrentLevel>
<ConnectionsId>${conn}</ConnectionsId>
<Variables>
${params.map((p, i) => parameter(p, i, 50)).join('\n')}
${vars.map(plainVar).join('\n')}
</Variables>
${linksXml(conn)}
${level(lvl)}
</ActiveObjectClass>`;
  };

  const piezaVars = [
    ['producto', 'int', '0'],
    ['creada', 'double', '0'],
    ['defectuosa', 'boolean', 'false'],
    ['primeraPasada', 'boolean', 'true'],
    ['retrabajos', 'int', '0'],
    ['operario', 'Operario', 'null'],
  ];
  const operarioVars = [
    ['fatigaH', 'double', '0'],
    ['ultimoCambio', 'double', '0'],
    ['finTarea', 'double', '0'],
    ['ultimaPausa', 'double', '-1'],
    ['tiempoPausa', 'double', '0'],
    ['ubicacion', 'int', '-1'],
    ['metros', 'double', '0'],
    ['ocupado', 'double', '0'],
    ['tareas', 'int', '0'],
    ['maxFatiga', 'double', '1'],
    ['repeticiones', 'java.util.HashMap<String, Integer>', 'new java.util.HashMap<String, Integer>()'],
  ];

  const mainConn = ids.next();
  const params = variables.filter((v) => v[3] === 'param');
  const plain = variables.filter((v) => v[3] !== 'param');
  const outputs = [
    ['produccionUdsHora', 'imprimirInforme()'],
    ['leadTimeMedioS', 'leadTimeMedio()'],
    ['leadTimeP90S', 'percentil(0.9)'],
    ['wipMedioUds', 'wipMedio()'],
    ['firstPassYield', 'fpy()'],
  ];
  const outputXml = ([name, expr], i) => `<Output>
${common(name, 500, -300 + i * 20)}
<Type>${cdata('double')}</Type>
<UnitType>${cdata('NONE')}</UnitType>
<Value Class="CodeValue"><Code>${cdata(expr)}</Code></Value>
<ComputationMoment>ON_SIMULATION_END</ComputationMoment>
<ComputationTimeCode Class="CodeUnitValue"><Code>${cdata('')}</Code><Unit Class="TimeUnits">${cdata('SECOND')}</Unit></ComputationTimeCode>
<ComputationDate>${t0}</ComputationDate>
</Output>`;

  const description = `${m.name}\n\nGenerado por Universal Manual Process Simulator el ${new Date().toISOString().slice(0, 10)}.\n` +
    'Diagrama de flujo con la Process Modeling Library. La variabilidad de cada operación (distribución, ritmo, consistencia, aprendizaje, fatiga, interrupciones, desplazamientos, averías, calidad y pausas) está en las funciones op_* y en los arrays de parámetros de Main. ' +
    'Al terminar la simulación se escribe un informe en la consola.';

  return `<?xml version="1.0" encoding="UTF-8"?>
<!--
*************************************************
	         AnyLogic Project File
*************************************************
-->
<AnyLogicWorkspace WorkspaceVersion="1.9" AnyLogicVersion="8.9.4.qualifier" AlpVersion="8.9.2">
<Model>
<Id>${ids.next()}</Id>
<Name>${cdata(m.name)}</Name>
<Description>${cdata(description)}</Description>
<EngineVersion>6</EngineVersion>
<JavaPackageName>${cdata(pkg)}</JavaPackageName>
<ModelTimeUnit>${cdata('Second')}</ModelTimeUnit>
<Folders>
</Folders>
<ActiveObjectClasses>
<ActiveObjectClass>
<Id>${mainId}</Id>
<Name>${cdata('Main')}</Name>
<Import>${cdata('import java.util.function.DoubleSupplier;')}</Import>
<StartupCode>${cdata(startup.join('\n'))}</StartupCode>
<Generic>false</Generic>
<GenericParameter>
<Id>${genericId}</Id>
<Name>${cdata(genericId)}</Name>
<GenericParameterValue Class="CodeValue"><Code>${cdata('T extends Agent')}</Code></GenericParameterValue>
<GenericParameterLabel>${cdata('Generic parameter:')}</GenericParameterLabel>
</GenericParameter>
<FlowChartsUsage>ENTITY</FlowChartsUsage>
<SamplesToKeep>100</SamplesToKeep>
<LimitNumberOfArrayElements>false</LimitNumberOfArrayElements>
<ElementsLimitValue>100</ElementsLimitValue>
<MakeDefaultViewArea>false</MakeDefaultViewArea>
<SceneGridColor/>
<SceneBackgroundColor/>
<SceneSkybox>null</SceneSkybox>
${agentProps}
${scale()}
<CurrentLevel>${mainLevel}</CurrentLevel>
<ConnectionsId>${mainConn}</ConnectionsId>
<Outputs>
${outputs.map(outputXml).join('\n')}
</Outputs>
<Variables>
${params.map((p, i) => parameter(p, i)).join('\n')}
${plain.map(plainVar).join('\n')}
</Variables>
<Connectors>
${conns.map(connXml).join('\n')}
</Connectors>
<Functions>
${functions.map(funcXml).join('\n')}
</Functions>
${linksXml(mainConn)}
<EmbeddedObjects>
${blocks.map(blockXml).join('\n')}
</EmbeddedObjects>
${level(mainLevel)}
</ActiveObjectClass>
${agentClass(piezaId, 'Pieza', piezaVars)}
${agentClass(operarioId, 'Operario', operarioVars, [['idx', 'int', '0', 'param', 'Índice']])}
</ActiveObjectClasses>
<DifferentialEquationsMethod>EULER</DifferentialEquationsMethod>
<MixedEquationsMethod>RK45_NEWTON</MixedEquationsMethod>
<AlgebraicEquationsMethod>MODIFIED_NEWTON</AlgebraicEquationsMethod>
<AbsoluteAccuracy>1.0E-5</AbsoluteAccuracy>
<FixedTimeStep>0.001</FixedTimeStep>
<RelativeAccuracy>1.0E-5</RelativeAccuracy>
<TimeAccuracy>1.0E-5</TimeAccuracy>
<Frame>
<Width>1200</Width>
<Height>800</Height>
</Frame>
<Database>
<Logging>false</Logging>
<AutoExport>false</AutoExport>
<ShutdownCompact>false</ShutdownCompact>
<ImportSettings>
</ImportSettings>
<ExportSettings>
</ExportSettings>
</Database>
<RunConfiguration ActiveObjectClassId="${mainId}">
<Id>${ids.next()}</Id>
<Name>${cdata('RunConfiguration')}</Name>
<MaximumMemory>1024</MaximumMemory>
<ModelTimeProperties>
<StopOption>${cdata('Stop at specified time')}</StopOption>
<InitialDate>${cdata(String(t0))}</InitialDate>
<InitialTime>${cdata('0.0')}</InitialTime>
<FinalDate>${cdata(String(t0 + horizon * 1000))}</FinalDate>
<FinalTime>${cdata(num(horizon))}</FinalTime>
</ModelTimeProperties>
<AnimationProperties>
<StopNever>true</StopNever>
<ExecutionMode>realTimeScaled</ExecutionMode>
<RealTimeScale>100.0</RealTimeScale>
<EnableZoomAndPanning>true</EnableZoomAndPanning>
<EnableDeveloperPanel>true</EnableDeveloperPanel>
<ShowDeveloperPanelOnStart>false</ShowDeveloperPanelOnStart>
</AnimationProperties>
<Inputs>
</Inputs>
<Outputs>
</Outputs>
</RunConfiguration>
<Experiments>
<SimulationExperiment ActiveObjectClassId="${mainId}">
<Id>${ids.next()}</Id>
<Name>${cdata('Simulation')}</Name>
<CommandLineArguments>${cdata('')}</CommandLineArguments>
<MaximumMemory>1024</MaximumMemory>
<RandomNumberGenerationType>randomSeed</RandomNumberGenerationType>
<CustomGeneratorCode>new Random()</CustomGeneratorCode>
<SeedValue>${int(S.seed ?? 1)}</SeedValue>
<SelectionModeForSimultaneousEvents>LIFO</SelectionModeForSimultaneousEvents>
<VmArgs>${cdata('')}</VmArgs>
<LoadRootFromSnapshot>false</LoadRootFromSnapshot>
<Parameters>
${params.map(([n]) => `<Parameter>
<ParameterName>${cdata(n)}</ParameterName>
</Parameter>`).join('\n')}
</Parameters>
<PresentationProperties>
<EnableZoomAndPanning>true</EnableZoomAndPanning>
<ExecutionMode>${cdata('realTimeScaled')}</ExecutionMode>
<Title>${cdata(`${m.name} : Simulation`)}</Title>
<EnableDeveloperPanel>true</EnableDeveloperPanel>
<ShowDeveloperPanelOnStart>false</ShowDeveloperPanelOnStart>
<RealTimeScale>100.0</RealTimeScale>
</PresentationProperties>
<ModelTimeProperties>
<StopOption>${cdata('Stop at specified time')}</StopOption>
<InitialDate>${cdata(String(t0))}</InitialDate>
<InitialTime>${cdata('0.0')}</InitialTime>
<FinalDate>${cdata(String(t0 + horizon * 1000))}</FinalDate>
<FinalTime>${cdata(num(horizon))}</FinalTime>
</ModelTimeProperties>
<BypassInitialScreen>false</BypassInitialScreen>
</SimulationExperiment>
</Experiments>
<RequiredLibraryReference>
<LibraryName>${cdata(PML)}</LibraryName>
<VersionMajor>8</VersionMajor>
<VersionMinor>0</VersionMinor>
<VersionBuild>5</VersionBuild>
</RequiredLibraryReference>
</Model>
</AnyLogicWorkspace>
`;
}
