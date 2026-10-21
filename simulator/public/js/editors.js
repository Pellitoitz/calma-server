// Formularios del modelo: general, productos, recursos, operaciones y estaciones.
// Cada cambio llama a ctx.change() (guardado automático) y, si cambia la
// estructura, a ctx.rerender().

import { OPERATION_TYPES, typeDef } from '/src/stochastic/variability.js';
import { describe } from '/src/stochastic/distributions.js';
import { DEFAULT_OPERATOR, DEFAULT_MACHINE, DEFAULT_SETTINGS, DEFAULT_QUALITY } from '/src/model/schema.js';
import { h, numField, textField, selectField, checkField, uniqueId } from './dom.js';
import { distEditor } from './distEditor.js';

const clone = (v) => JSON.parse(JSON.stringify(v));
const typeOptions = () => Object.entries(OPERATION_TYPES).map(([k, d]) => [k, d.label]);

function section(title, ...children) {
  return h('section', { class: 'card' }, h('h3', {}, title), ...children);
}

function grid(...children) {
  return h('div', { class: 'grid' }, ...children);
}

function itemCard({ title, subtitle, open, onToggle, actions = [], body, badge, color }) {
  const d = h('details', { class: 'item', open: open || undefined });
  d.addEventListener('toggle', () => onToggle?.(d.open));
  d.append(
    h('summary', {},
      color ? h('span', { class: 'swatch', style: { background: color } }) : null,
      h('span', { class: 'item-title' }, title),
      badge ? h('span', { class: 'badge' }, badge) : null,
      subtitle ? h('span', { class: 'item-sub' }, subtitle) : null,
      h('span', { class: 'item-actions', onclick: (e) => e.preventDefault() }, actions),
    ),
    h('div', { class: 'item-body' }, body()),
  );
  return d;
}

const btn = (label, onclick, cls = 'small') => h('button', { type: 'button', class: cls, onclick }, label);

function moveItem(list, i, delta) {
  const j = i + delta;
  if (j < 0 || j >= list.length) return;
  [list[i], list[j]] = [list[j], list[i]];
}

// ======================================================================== GENERAL
export function renderGeneral(ctx) {
  const m = ctx.model;
  m.settings ||= {};
  m.arrivals ||= { mode: 'push', batchSize: 1 };
  const s = m.settings;
  const d = DEFAULT_SETTINGS;
  const c = () => ctx.change();
  const cr = () => ctx.change({ rerender: true });

  const shift = (s.shift ||= clone(d.shift));
  shift.breaks ||= [];

  return h('div', { class: 'stack' },
    section('Modelo',
      grid(
        textField('Nombre', { get: () => m.name, set: (v) => ((m.name = v), c()), key: 'm.name', onCommit: () => ctx.refreshList() }),
        textField('Descripción', { get: () => m.description, set: (v) => ((m.description = v), c()), key: 'm.desc', multiline: true }),
      ),
    ),
    section('Experimento',
      grid(
        numField('Horizonte', { get: () => s.horizonHours, set: (v) => ((s.horizonHours = v), c()), key: 's.h', unit: 'h', placeholder: d.horizonHours, min: 0.1 }),
        numField('Calentamiento', { get: () => s.warmupHours, set: (v) => ((s.warmupHours = v), c()), key: 's.w', unit: 'h', placeholder: d.warmupHours, help: 'Periodo inicial que no se mide (línea vacía al arrancar)' }),
        numField('Réplicas', { get: () => s.replications, set: (v) => ((s.replications = v), c()), key: 's.r', step: 1, min: 1, placeholder: d.replications }),
        numField('Semilla', { get: () => s.seed, set: (v) => ((s.seed = v), c()), key: 's.seed', step: 1, placeholder: d.seed, help: 'Misma semilla ⇒ mismos resultados (reproducible)' }),
        numField('Nivel de confianza', { get: () => s.confidence, set: (v) => ((s.confidence = v), c()), key: 's.conf', scale: 0.01, unit: '%', placeholder: 95 }),
        numField('Precisión objetivo', { get: () => s.targetRelativePrecision, set: (v) => ((s.targetRelativePrecision = v), c()), key: 's.prec', scale: 0.01, unit: '± %', placeholder: 5, help: 'Para calcular cuántas réplicas hacen falta' }),
        numField('Demanda', { get: () => s.demandPerHour ?? undefined, set: (v) => ((s.demandPerHour = v ?? null), c()), key: 's.dem', unit: 'uds/h', help: 'Takt = 3600 / demanda' }),
      ),
    ),
    section('Turno y pausas',
      grid(numField('Duración del turno', { get: () => shift.lengthHours, set: (v) => ((shift.lengthHours = v), c()), key: 'sh.len', unit: 'h', placeholder: 8 })),
      h('table', { class: 'mini' },
        h('tr', {}, h('th', {}, 'Inicio (h desde inicio de turno)'), h('th', {}, 'Duración (min)'), h('th', {}, '')),
        shift.breaks.map((b, i) =>
          h('tr', {},
            h('td', {}, numField('', { get: () => b.atHours, set: (v) => ((b.atHours = v), c()), key: `br.${i}.at` })),
            h('td', {}, numField('', { get: () => b.durationMin, set: (v) => ((b.durationMin = v), c()), key: `br.${i}.d` })),
            h('td', {}, btn('Quitar', () => (shift.breaks.splice(i, 1), cr()))),
          ),
        ),
      ),
      btn('Añadir pausa', () => (shift.breaks.push({ atHours: 4, durationMin: 15 }), cr())),
      h('p', { class: 'help' }, 'Los operarios ocupados terminan su tarea y luego hacen la pausa completa. La pausa reduce la fatiga.'),
    ),
    section('Llegadas de material',
      grid(
        selectField('Modo', {
          get: () => m.arrivals.mode,
          set: (v) => (m.arrivals.mode = v),
          key: 'a.mode',
          options: [['push', 'Material siempre disponible (capacidad)'], ['interarrival', 'Llegadas aleatorias (pedidos)']],
          onCommit: cr,
        }),
        numField('Tamaño de lote', { get: () => m.arrivals.batchSize, set: (v) => ((m.arrivals.batchSize = v), c()), key: 'a.batch', step: 1, min: 1, placeholder: 1, help: 'Unidades seguidas de la misma referencia (afecta a los setups)' }),
      ),
      m.arrivals.mode === 'interarrival'
        ? distEditor({ label: 'Tiempo entre llegadas de lote', key: 'a.ia', get: () => m.arrivals.interarrival || { type: 'exponential', mean: 60 }, set: (v) => ((m.arrivals.interarrival = v), c()) })
        : null,
    ),
    renderProducts(ctx),
    section('Distribución en planta (3D y distancias)',
      grid(
        selectField('Disposición', {
          get: () => s.layout || 'u',
          set: (v) => (s.layout = v),
          key: 's.layout',
          options: [['u', 'Célula en U'], ['line', 'Línea recta'], ['l', 'En L'], ['manual', 'Manual (coordenadas por estación)']],
          onCommit: cr,
        }),
        numField('Separación entre estaciones', { get: () => s.spacing, set: (v) => ((s.spacing = v), c()), key: 's.sp', unit: 'm', placeholder: 3.5 }),
      ),
      h('p', { class: 'help' }, 'Las distancias entre puestos determinan los tiempos de desplazamiento de los operarios y de los transportes.'),
    ),
  );
}

function renderProducts(ctx) {
  const m = ctx.model;
  m.products ||= [];
  const c = () => ctx.change();
  const cr = () => ctx.change({ rerender: true });
  return section('Productos / referencias',
    h('p', { class: 'help' }, 'La mezcla indica la proporción de cada referencia. Los factores de tiempo multiplican la duración de las operaciones (1,3 = 30 % más lenta).'),
    m.products.map((p, i) =>
      itemCard({
        title: p.name || p.id,
        color: p.color,
        badge: `mezcla ${p.mix ?? 1}`,
        open: ctx.isOpen(`prod:${p.id}`),
        onToggle: (o) => ctx.setOpen(`prod:${p.id}`, o),
        actions: [btn('Quitar', () => (m.products.splice(i, 1), cr()))],
        body: () => [
          grid(
            textField('Nombre', { get: () => p.name, set: (v) => ((p.name = v), c()), key: `p.${p.id}.n` }),
            numField('Mezcla (peso)', { get: () => p.mix, set: (v) => ((p.mix = v), c()), key: `p.${p.id}.mix`, placeholder: 1 }),
            numField('Factor de tiempo global', { get: () => p.timeFactor, set: (v) => ((p.timeFactor = v), c()), key: `p.${p.id}.tf`, placeholder: 1 }),
            h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'Color'), (() => {
              const inp = h('input', { type: 'color', value: p.color || '#2a78d6' });
              inp.addEventListener('input', () => ((p.color = inp.value), c()));
              return inp;
            })()),
          ),
          h('details', { class: 'sub' }, h('summary', {}, 'Factores de tiempo por tipo de operación'),
            grid(Object.entries(OPERATION_TYPES).map(([t, def]) =>
              numField(def.label, { get: () => p.timeFactorsByType?.[t], set: (v) => { p.timeFactorsByType ||= {}; if (v === undefined) delete p.timeFactorsByType[t]; else p.timeFactorsByType[t] = v; c(); }, key: `p.${p.id}.t.${t}`, placeholder: 1 }),
            )),
          ),
        ],
      }),
    ),
    btn('Añadir producto', () => {
      const id = uniqueId('P', m.products.map((x) => x.id));
      m.products.push({ id, name: `Producto ${id}`, mix: 1, color: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100'][m.products.length % 4] });
      ctx.setOpen(`prod:${id}`, true);
      cr();
    }),
  );
}

// ======================================================================== RECURSOS
export function renderResources(ctx) {
  return h('div', { class: 'stack' }, renderOperators(ctx), renderMachines(ctx));
}

function libraryActions(ctx, kind, list, makeCopy) {
  const lib = ctx.library[kind] || [];
  const sel = h('select', {}, h('option', { value: '' }, lib.length ? `Añadir desde biblioteca (${lib.length})…` : 'Biblioteca vacía'), lib.map((e, i) => h('option', { value: i }, e.name)));
  sel.addEventListener('change', () => {
    if (sel.value === '') return;
    makeCopy(clone(lib[Number(sel.value)].item));
    ctx.change({ rerender: true });
  });
  return sel;
}

function saveToLibrary(ctx, kind, item, name) {
  const lib = (ctx.library[kind] ||= []);
  const existing = lib.findIndex((e) => e.name === name);
  const entry = { name, savedAt: new Date().toISOString(), item: clone(item) };
  if (existing >= 0) lib[existing] = entry;
  else lib.push(entry);
  ctx.saveLibrary();
  ctx.toast(`«${name}» guardado en la biblioteca`);
}

function renderOperators(ctx) {
  const m = ctx.model;
  m.operators ||= [];
  const c = () => ctx.change();
  const cr = () => ctx.change({ rerender: true });
  const D = DEFAULT_OPERATOR;

  return section('Operarios',
    h('p', { class: 'help' }, 'Cada operario tiene su propia variabilidad: ritmo (actividad, 100 % = estándar), consistencia (dispersión de sus tiempos), velocidad de marcha, curva de aprendizaje y fatiga.'),
    m.operators.map((o, i) =>
      itemCard({
        title: o.name || o.id,
        badge: `${o.performance?.default ?? 100} %`,
        subtitle: o.id,
        open: ctx.isOpen(`opr:${o.id}`),
        onToggle: (v) => ctx.setOpen(`opr:${o.id}`, v),
        actions: [
          btn('A biblioteca', () => saveToLibrary(ctx, 'operators', o, o.name || o.id)),
          btn('Quitar', () => {
            m.operators.splice(i, 1);
            for (const s of m.stations || []) s.operatorIds = (s.operatorIds || []).filter((x) => x !== o.id);
            cr();
          }),
        ],
        body: () => {
          o.performance ||= {};
          o.learning ||= {};
          o.fatigue ||= {};
          return [
            grid(
              textField('Nombre', { get: () => o.name, set: (v) => ((o.name = v), c()), key: `o.${o.id}.n` }),
              numField('Actividad / ritmo', { get: () => o.performance.default, set: (v) => ((o.performance.default = v), c()), key: `o.${o.id}.perf`, unit: '%', placeholder: 100, help: '120 % ⇒ trabaja un 20 % más rápido que el estándar' }),
              numField('Consistencia', { get: () => o.consistency, set: (v) => ((o.consistency = v), c()), key: `o.${o.id}.cons`, placeholder: 1, help: '<1 tiempos más regulares, >1 más dispersos' }),
              selectField('Puesto inicial', { get: () => o.homeStationId, set: (v) => ((o.homeStationId = v), c()), key: `o.${o.id}.home`, options: [['', '(primera estación asignada)'], ...(m.stations || []).map((s) => [s.id, s.name || s.id])] }),
              selectField('Regla de asignación', { get: () => o.dispatch, set: (v) => ((o.dispatch = v), c()), key: `o.${o.id}.disp`, options: [['', 'El más cercano'], ['fastest', 'El más rápido'], ['longestIdle', 'El que más tiempo lleva libre']] }),
              numField('Sensibilidad calidad-fatiga', { get: () => o.qualityFatigueSensitivity, set: (v) => ((o.qualityFatigueSensitivity = v), c()), key: `o.${o.id}.qfs`, placeholder: 0, help: 'Cuánto aumenta la probabilidad de defecto con la fatiga (0 = nada)' }),
            ),
            h('details', { class: 'sub' }, h('summary', {}, 'Ritmo por tipo de operación'),
              grid(Object.entries(OPERATION_TYPES).filter(([, d]) => d.requires.operator).map(([t, def]) =>
                numField(def.label, { get: () => o.performance.byType?.[t], set: (v) => { o.performance.byType ||= {}; if (v === undefined) delete o.performance.byType[t]; else o.performance.byType[t] = v; c(); }, key: `o.${o.id}.pt.${t}`, unit: '%', placeholder: o.performance.default ?? 100 }),
              )),
            ),
            h('div', { class: 'two' },
              h('div', {},
                h('h4', {}, 'Curva de aprendizaje (Wright)'),
                grid(
                  numField('Tasa de aprendizaje', { get: () => o.learning.rate, set: (v) => ((o.learning.rate = v), c()), key: `o.${o.id}.lr`, scale: 0.01, unit: '%', placeholder: D.learning.rate * 100, help: '90 % ⇒ cada vez que se duplica la experiencia el tiempo baja un 10 %' }),
                  numField('Experiencia previa', { get: () => o.learning.experienceUnits, set: (v) => ((o.learning.experienceUnits = v), c()), key: `o.${o.id}.le`, unit: 'uds', placeholder: D.learning.experienceUnits }),
                  numField('Unidades para tiempo estándar', { get: () => o.learning.standardUnits, set: (v) => ((o.learning.standardUnits = v), c()), key: `o.${o.id}.ls`, unit: 'uds', placeholder: D.learning.standardUnits }),
                ),
              ),
              h('div', {},
                h('h4', {}, 'Fatiga y recuperación'),
                grid(
                  numField('Incremento máximo de tiempo', { get: () => o.fatigue.maxIncrease, set: (v) => ((o.fatigue.maxIncrease = v), c()), key: `o.${o.id}.fm`, scale: 0.01, unit: '%', placeholder: D.fatigue.maxIncrease * 100 }),
                  numField('Constante de fatiga', { get: () => o.fatigue.timeConstantH, set: (v) => ((o.fatigue.timeConstantH = v), c()), key: `o.${o.id}.ft`, unit: 'h', placeholder: D.fatigue.timeConstantH }),
                  numField('Constante de recuperación', { get: () => o.fatigue.recoveryH, set: (v) => ((o.fatigue.recoveryH = v), c()), key: `o.${o.id}.fr`, unit: 'h', placeholder: D.fatigue.recoveryH }),
                ),
              ),
            ),
            distEditor({ label: 'Velocidad de marcha', unit: 'm/s', key: `o.${o.id}.ws`, get: () => o.walkSpeed || D.walkSpeed, set: (v) => ((o.walkSpeed = v), c()), compact: true }),
          ];
        },
      }),
    ),
    h('div', { class: 'row' },
      btn('Añadir operario', () => {
        const id = uniqueId('OP', m.operators.map((x) => x.id));
        m.operators.push({ id, name: `Operario ${id.slice(2)}`, performance: { default: 100 } });
        ctx.setOpen(`opr:${id}`, true);
        cr();
      }),
      libraryActions(ctx, 'operators', m.operators, (item) => {
        item.id = uniqueId('OP', m.operators.map((x) => x.id));
        m.operators.push(item);
      }),
    ),
  );
}

function renderMachines(ctx) {
  const m = ctx.model;
  m.machines ||= [];
  const c = () => ctx.change();
  const cr = () => ctx.change({ rerender: true });
  return section('Máquinas y equipos',
    h('p', { class: 'help' }, 'Las averías se generan según el tiempo de funcionamiento (MTBF en horas de marcha) y su reparación según el MTTR. Una máquina parada no se avería.'),
    m.machines.map((mc, i) =>
      itemCard({
        title: mc.name || mc.id,
        subtitle: mc.id,
        badge: mc.failures?.enabled === false ? 'sin averías' : 'con averías',
        open: ctx.isOpen(`mc:${mc.id}`),
        onToggle: (v) => ctx.setOpen(`mc:${mc.id}`, v),
        actions: [
          btn('A biblioteca', () => saveToLibrary(ctx, 'machines', mc, mc.name || mc.id)),
          btn('Quitar', () => {
            m.machines.splice(i, 1);
            for (const s of m.stations || []) if (s.machineId === mc.id) s.machineId = null;
            cr();
          }),
        ],
        body: () => {
          mc.failures ||= clone(DEFAULT_MACHINE.failures);
          return [
            grid(
              textField('Nombre', { get: () => mc.name, set: (v) => ((mc.name = v), c()), key: `mc.${mc.id}.n` }),
              numField('Factor de velocidad', { get: () => mc.speedFactor, set: (v) => ((mc.speedFactor = v), c()), key: `mc.${mc.id}.sf`, placeholder: 1, help: '1,1 ⇒ 10 % más rápida que el tiempo nominal' }),
              numField('Consistencia', { get: () => mc.consistency, set: (v) => ((mc.consistency = v), c()), key: `mc.${mc.id}.co`, placeholder: 1 }),
              checkField('Averías activadas', { get: () => mc.failures.enabled !== false, set: (v) => (mc.failures.enabled = v), key: `mc.${mc.id}.fe`, onCommit: cr }),
            ),
            mc.failures.enabled !== false
              ? h('div', { class: 'two' },
                  distEditor({ label: 'Tiempo entre averías (MTBF)', unit: 'h', key: `mc.${mc.id}.mtbf`, get: () => mc.failures.mtbf || DEFAULT_MACHINE.failures.mtbf, set: (v) => ((mc.failures.mtbf = v), c()) }),
                  distEditor({ label: 'Tiempo de reparación (MTTR)', unit: 'min', key: `mc.${mc.id}.mttr`, get: () => mc.failures.mttr || DEFAULT_MACHINE.failures.mttr, set: (v) => ((mc.failures.mttr = v), c()) }),
                )
              : null,
          ];
        },
      }),
    ),
    h('div', { class: 'row' },
      btn('Añadir máquina', () => {
        const id = uniqueId('M', m.machines.map((x) => x.id));
        m.machines.push({ id, name: `Máquina ${id.slice(1)}`, failures: clone(DEFAULT_MACHINE.failures) });
        ctx.setOpen(`mc:${id}`, true);
        cr();
      }),
      libraryActions(ctx, 'machines', m.machines, (item) => {
        item.id = uniqueId('M', m.machines.map((x) => x.id));
        m.machines.push(item);
      }),
    ),
  );
}

// ======================================================================== OPERACIONES
export function renderOperations(ctx) {
  const m = ctx.model;
  m.operations ||= [];
  const c = () => ctx.change();
  const cr = () => ctx.change({ rerender: true });
  const filter = ctx.ui.opFilter || '';

  const filterSel = h('select', {}, h('option', { value: '' }, 'Todos los tipos'), typeOptions().map(([v, l]) => h('option', { value: v }, l)));
  filterSel.value = filter;
  filterSel.addEventListener('change', () => ((ctx.ui.opFilter = filterSel.value), ctx.rerender()));

  const used = new Map();
  for (const s of m.stations || []) {
    for (const id of s.operationIds || []) used.set(id, [...(used.get(id) || []), s.name || s.id]);
    if (s.setup?.operationId) used.set(s.setup.operationId, [...(used.get(s.setup.operationId) || []), `${s.name || s.id} (setup)`]);
    if (s.transportOperationId) used.set(s.transportOperationId, [...(used.get(s.transportOperationId) || []), `${s.name || s.id} (salida)`]);
  }

  const ops = m.operations.filter((o) => !filter || o.type === filter);
  return h('div', { class: 'stack' },
    section('Operaciones',
      h('p', { class: 'help' }, 'Cada operación tiene su propia distribución de tiempo y sus fuentes de variabilidad. Los valores en gris son los predeterminados del tipo: escribe encima solo lo que quieras cambiar.'),
      h('div', { class: 'row' }, filterSel,
        btn('Nueva operación', () => {
          const id = uniqueId('op', m.operations.map((x) => x.id));
          const type = filter || 'manual_assembly';
          m.operations.push({ id, name: `${typeDef(type).label} ${id.slice(2)}`, type, duration: clone(typeDef(type).duration) });
          ctx.setOpen(`op:${id}`, true);
          cr();
        }, ''),
        libraryActions(ctx, 'operations', m.operations, (item) => {
          item.id = uniqueId('op', m.operations.map((x) => x.id));
          m.operations.push(item);
          ctx.setOpen(`op:${item.id}`, true);
        }),
      ),
    ),
    ops.map((op) => operationCard(ctx, op, used.get(op.id), c, cr)),
  );
}

function operationCard(ctx, op, usedIn, c, cr) {
  const m = ctx.model;
  const def = typeDef(op.type);
  op.duration ||= clone(def.duration);
  let desc = '';
  try {
    desc = describe(op.duration);
  } catch {
    desc = 'distribución no válida';
  }
  return itemCard({
    title: op.name || op.id,
    color: def.color,
    badge: def.label,
    subtitle: `${desc}${usedIn ? ` · en ${usedIn.join(', ')}` : ' · sin usar'}`,
    open: ctx.isOpen(`op:${op.id}`),
    onToggle: (v) => ctx.setOpen(`op:${op.id}`, v),
    actions: [
      btn('Duplicar', () => {
        const copy = clone(op);
        copy.id = uniqueId('op', m.operations.map((x) => x.id));
        copy.name = `${op.name} (copia)`;
        m.operations.splice(m.operations.indexOf(op) + 1, 0, copy);
        ctx.setOpen(`op:${copy.id}`, true);
        cr();
      }),
      btn('A biblioteca', () => saveToLibrary(ctx, 'operations', op, op.name || op.id)),
      btn('Quitar', () => {
        if (usedIn && !confirm(`«${op.name}» se usa en ${usedIn.join(', ')}. ¿Quitarla?`)) return;
        m.operations.splice(m.operations.indexOf(op), 1);
        for (const s of m.stations || []) {
          s.operationIds = (s.operationIds || []).filter((x) => x !== op.id);
          if (s.setup?.operationId === op.id) s.setup.operationId = null;
          if (s.transportOperationId === op.id) s.transportOperationId = null;
        }
        cr();
      }),
    ],
    body: () => operationBody(ctx, op, def, c, cr),
  });
}

function operationBody(ctx, op, def, c, cr) {
  const m = ctx.model;
  op.modifiers ||= {};
  op.requires ||= {};
  op.quality ||= {};
  const eff = (group, k) => op[group]?.[k] ?? def[group][k];
  const isInspection = op.isInspection ?? Boolean(def.inspection);
  const q = op.quality;
  const Q = DEFAULT_QUALITY;

  const modifierLabels = {
    skill: 'Ritmo / habilidad del operario',
    learning: 'Curva de aprendizaje',
    fatigue: 'Fatiga',
    interruptions: 'Interrupciones aleatorias',
  };

  return [
    grid(
      textField('Nombre', { get: () => op.name, set: (v) => ((op.name = v), c()), key: `op.${op.id}.n` }),
      selectField('Tipo', {
        get: () => op.type,
        set: (v) => {
          op.type = v;
          op.modifiers = {};
          op.requires = {};
          delete op.interruptions;
          delete op.distanceBased;
          delete op.isInspection;
        },
        key: `op.${op.id}.t`,
        options: typeOptions(),
        onCommit: () => {
          if (confirm('¿Cargar también la distribución de tiempo por defecto de este tipo?')) op.duration = clone(typeDef(op.type).duration);
          cr();
        },
      }),
      textField('Notas / método', { get: () => op.notes, set: (v) => ((op.notes = v), c()), key: `op.${op.id}.notes`, multiline: true }),
    ),
    h('div', { class: 'two' },
      distEditor({ label: op.distanceBased || def.distanceBased ? 'Tiempo fijo (recoger / dejar)' : 'Tiempo de operación', key: `op.${op.id}.dur`, get: () => op.duration, set: (v) => ((op.duration = v), c()), onChange: () => ctx.refreshSummary?.() }),
      h('div', {},
        h('h4', {}, 'Fuentes de variabilidad aplicadas'),
        Object.entries(modifierLabels).map(([k, label]) =>
          checkField(label, { get: () => eff('modifiers', k), set: (v) => ((op.modifiers[k] = v), c()), key: `op.${op.id}.mod.${k}`, onCommit: cr }),
        ),
        h('h4', {}, 'Recursos necesarios'),
        checkField('Operario', { get: () => eff('requires', 'operator'), set: (v) => ((op.requires.operator = v), c()), key: `op.${op.id}.req.o`, onCommit: cr }),
        checkField('Máquina de la estación', { get: () => eff('requires', 'machine'), set: (v) => ((op.requires.machine = v), c()), key: `op.${op.id}.req.m`, onCommit: cr }),
        eff('requires', 'operator') && (m.operators || []).length
          ? h('details', { class: 'sub' }, h('summary', {}, `Restringir a operarios concretos${op.operatorIds?.length ? ` (${op.operatorIds.length})` : ''}`),
              (m.operators || []).map((o) => checkField(o.name || o.id, {
                get: () => op.operatorIds?.includes(o.id),
                set: (v) => {
                  op.operatorIds = (op.operatorIds || []).filter((x) => x !== o.id);
                  if (v) op.operatorIds.push(o.id);
                  if (!op.operatorIds.length) delete op.operatorIds;
                  c();
                },
                key: `op.${op.id}.ol.${o.id}`,
              })),
              h('p', { class: 'help' }, 'Si no marcas ninguno, puede hacerla cualquier operario asignado a la estación.'),
            )
          : null,
      ),
    ),
    def.distanceBased || op.distanceBased
      ? h('div', { class: 'card inner' },
          h('h4', {}, 'Componente por distancia'),
          h('p', { class: 'help' }, op.type === 'walking' ? 'La distancia sale de la distribución en planta. Para desplazamientos se usa la velocidad de marcha de cada operario si está definida.' : 'Tiempo = tiempo fijo + distancia entre estaciones / velocidad.'),
          distEditor({ label: 'Velocidad', unit: 'm/s', key: `op.${op.id}.speed`, get: () => op.distanceBased?.speed || def.distanceBased.speed, set: (v) => ((op.distanceBased = { ...(op.distanceBased || {}), speed: v }), c()), compact: true }),
        )
      : null,
    eff('modifiers', 'interruptions')
      ? h('div', { class: 'card inner' },
          h('h4', {}, 'Interrupciones y microparadas'),
          grid(numField('Frecuencia', { get: () => op.interruptions?.ratePerHour, set: (v) => { op.interruptions = { ...(op.interruptions || {}) }; if (v === undefined) delete op.interruptions.ratePerHour; else op.interruptions.ratePerHour = v; c(); }, key: `op.${op.id}.ir`, unit: 'por hora de trabajo', placeholder: def.interruptions.ratePerHour })),
          distEditor({ label: 'Duración de cada interrupción', key: `op.${op.id}.id`, get: () => op.interruptions?.duration || def.interruptions.duration, set: (v) => ((op.interruptions = { ...(op.interruptions || {}), duration: v }), c()), compact: true }),
        )
      : null,
    eff('modifiers', 'learning')
      ? h('details', { class: 'sub' }, h('summary', {}, 'Curva de aprendizaje propia de esta operación (opcional)'),
          grid(
            numField('Tasa', { get: () => op.learning?.rate, set: (v) => { op.learning = { ...(op.learning || {}), rate: v }; if (v === undefined) delete op.learning.rate; if (!Object.keys(op.learning).length) delete op.learning; c(); }, key: `op.${op.id}.lr`, scale: 0.01, unit: '%', placeholder: 'la del operario' }),
            numField('Unidades para estándar', { get: () => op.learning?.standardUnits, set: (v) => { op.learning = { ...(op.learning || {}), standardUnits: v }; if (v === undefined) delete op.learning.standardUnits; if (!Object.keys(op.learning).length) delete op.learning; c(); }, key: `op.${op.id}.ls`, placeholder: 500 }),
          ),
          h('p', { class: 'help' }, 'Las tareas complejas (cableado, setups) suelen aprender más despacio (85 %) que las sencillas (95 %).'),
        )
      : null,
    h('div', { class: 'card inner' },
      h('h4', {}, 'Calidad'),
      checkField('Es una inspección / prueba', { get: () => isInspection, set: (v) => (op.isInspection = v), key: `op.${op.id}.insp`, onCommit: cr }),
      isInspection
        ? grid(
            numField('Probabilidad de detección', { get: () => q.detectionProb, set: (v) => ((q.detectionProb = v), c()), key: `op.${op.id}.qd`, scale: 0.01, unit: '%', placeholder: 95 }),
            numField('Falsos rechazos', { get: () => q.falseRejectProb, set: (v) => ((q.falseRejectProb = v), c()), key: `op.${op.id}.qf`, scale: 0.01, unit: '%', placeholder: Q.falseRejectProb * 100 }),
            selectField('Si se rechaza', { get: () => q.onReject || 'rework', set: (v) => (q.onReject = v), key: `op.${op.id}.qr`, options: [['rework', 'Retrabajar y volver a inspeccionar'], ['scrap', 'Desechar']], onCommit: cr }),
            (q.onReject || 'rework') === 'rework'
              ? selectField('Operación de retrabajo', { get: () => q.reworkOperationId, set: (v) => (q.reworkOperationId = v), key: `op.${op.id}.qro`, options: [['', '(ninguna: desechar)'], ...m.operations.filter((x) => x.id !== op.id).map((x) => [x.id, x.name || x.id])], onCommit: c })
              : null,
            numField('Máx. retrabajos por pieza', { get: () => q.maxReworks, set: (v) => ((q.maxReworks = v), c()), key: `op.${op.id}.qm`, step: 1, placeholder: Q.maxReworks }),
            numField('Eficacia del retrabajo', { get: () => q.repairProb, set: (v) => ((q.repairProb = v), c()), key: `op.${op.id}.qp`, scale: 0.01, unit: '%', placeholder: Q.repairProb * 100 }),
          )
        : grid(numField('Probabilidad de generar defecto', { get: () => q.defectProb, set: (v) => ((q.defectProb = v), c()), key: `op.${op.id}.qdef`, scale: 0.01, unit: '%', placeholder: 0, help: 'El defecto se descubre (o no) en una inspección posterior' })),
    ),
  ];
}

// ======================================================================== ESTACIONES
export function renderStations(ctx) {
  const m = ctx.model;
  m.stations ||= [];
  const c = () => ctx.change();
  const cr = () => ctx.change({ rerender: true });
  const opOptions = () => [['', '(ninguna)'], ...m.operations.map((o) => [o.id, `${o.name || o.id} · ${typeDef(o.type).label}`])];

  return h('div', { class: 'stack' },
    section('Estaciones (en orden de flujo)',
      h('p', { class: 'help' }, 'Las piezas recorren las estaciones de arriba abajo. Cada estación tiene puestos en paralelo, un buffer de entrada limitado (si se llena, la anterior se bloquea), operarios que pueden compartirse con otras estaciones y, opcionalmente, una máquina.'),
    ),
    m.stations.map((s, i) => {
      s.operationIds ||= [];
      s.operatorIds ||= [];
      s.setup ||= { operationId: null, trigger: 'none', everyN: 0 };
      return itemCard({
        title: `${i + 1}. ${s.name || s.id}`,
        subtitle: `${s.operationIds.length} operaciones · ${s.operatorIds.length} operarios${s.machineId ? ' · máquina' : ''} · buffer ${s.bufferCapacity ?? 2}`,
        open: ctx.isOpen(`st:${s.id}`),
        onToggle: (v) => ctx.setOpen(`st:${s.id}`, v),
        actions: [
          btn('↑', () => (moveItem(m.stations, i, -1), cr())),
          btn('↓', () => (moveItem(m.stations, i, 1), cr())),
          btn('Quitar', () => (m.stations.splice(i, 1), cr())),
        ],
        body: () => [
          grid(
            textField('Nombre', { get: () => s.name, set: (v) => ((s.name = v), c()), key: `s.${s.id}.n` }),
            numField('Puestos en paralelo', { get: () => s.workplaces, set: (v) => ((s.workplaces = v), c()), key: `s.${s.id}.wp`, step: 1, min: 1, placeholder: 1, help: 'p.ej. huecos del horno' }),
            numField('Capacidad del buffer de entrada', { get: () => s.bufferCapacity, set: (v) => ((s.bufferCapacity = v), c()), key: `s.${s.id}.buf`, step: 1, min: 0, placeholder: 2 }),
            selectField('Máquina', { get: () => s.machineId, set: (v) => (s.machineId = v), key: `s.${s.id}.mc`, options: [['', '(ninguna)'], ...(m.machines || []).map((x) => [x.id, x.name || x.id])], onCommit: cr }),
          ),
          h('h4', {}, 'Secuencia de operaciones'),
          h('ol', { class: 'seq' },
            s.operationIds.map((id, j) => {
              const op = m.operations.find((o) => o.id === id);
              return h('li', {},
                op ? h('span', { class: 'swatch', style: { background: typeDef(op.type).color } }) : null,
                h('span', { class: op ? '' : 'error' }, op ? op.name : `${id} (no existe)`),
                h('span', { class: 'item-actions' },
                  btn('↑', () => (moveItem(s.operationIds, j, -1), cr())),
                  btn('↓', () => (moveItem(s.operationIds, j, 1), cr())),
                  btn('Quitar', () => (s.operationIds.splice(j, 1), cr())),
                ),
              );
            }),
          ),
          (() => {
            const sel = h('select', {}, h('option', { value: '' }, 'Añadir operación…'), m.operations.map((o) => h('option', { value: o.id }, `${o.name || o.id} · ${typeDef(o.type).label}`)));
            sel.addEventListener('change', () => {
              if (sel.value) {
                s.operationIds.push(sel.value);
                cr();
              }
            });
            return sel;
          })(),
          h('h4', {}, 'Operarios que pueden trabajar aquí'),
          (m.operators || []).length
            ? h('div', { class: 'chips' }, (m.operators || []).map((o) => checkField(o.name || o.id, {
                get: () => s.operatorIds.includes(o.id),
                set: (v) => {
                  s.operatorIds = s.operatorIds.filter((x) => x !== o.id);
                  if (v) s.operatorIds.push(o.id);
                },
                key: `s.${s.id}.o.${o.id}`,
                onCommit: cr,
              })))
            : h('p', { class: 'help' }, 'Crea operarios en la pestaña Recursos.'),
          h('div', { class: 'two' },
            h('div', {},
              h('h4', {}, 'Setup / cambio'),
              grid(
                selectField('Operación de setup', { get: () => s.setup.operationId, set: (v) => (s.setup.operationId = v), key: `s.${s.id}.su`, options: opOptions(), onCommit: cr }),
                selectField('Cuándo', { get: () => s.setup.trigger || 'none', set: (v) => (s.setup.trigger = v), key: `s.${s.id}.sut`, options: [['none', 'Nunca'], ['changeover', 'Al cambiar de referencia'], ['everyN', 'Cada N unidades']], onCommit: cr }),
                s.setup.trigger === 'everyN' ? numField('N', { get: () => s.setup.everyN, set: (v) => ((s.setup.everyN = v), c()), key: `s.${s.id}.sun`, step: 1 }) : null,
              ),
            ),
            h('div', {},
              h('h4', {}, 'Transporte de salida'),
              selectField('Operación de transporte a la siguiente estación', { get: () => s.transportOperationId, set: (v) => (s.transportOperationId = v), key: `s.${s.id}.tr`, options: opOptions(), onCommit: c, help: 'Sin transporte la pieza pasa directamente' }),
            ),
          ),
          m.settings?.layout === 'manual'
            ? grid(
                numField('Posición X', { get: () => s.position?.x, set: (v) => ((s.position = { ...(s.position || {}), x: v }), c()), key: `s.${s.id}.x`, unit: 'm' }),
                numField('Posición Z', { get: () => s.position?.z, set: (v) => ((s.position = { ...(s.position || {}), z: v }), c()), key: `s.${s.id}.z`, unit: 'm' }),
                numField('Giro', { get: () => s.position?.rot, set: (v) => ((s.position = { ...(s.position || {}), rot: v }), c()), key: `s.${s.id}.r`, unit: 'grados', scale: Math.PI / 180 }),
              )
            : null,
        ],
      });
    }),
    btn('Añadir estación', () => {
      const id = uniqueId('S', m.stations.map((x) => x.id));
      m.stations.push({ id, name: `Estación ${id.slice(1)}`, operationIds: [], operatorIds: [], bufferCapacity: 2, workplaces: 1 });
      ctx.setOpen(`st:${id}`, true);
      cr();
    }, ''),
  );
}
