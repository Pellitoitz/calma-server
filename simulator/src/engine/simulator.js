// Motor de simulación de eventos discretos orientado a procesos.
//
// Cada pieza que trabaja en un puesto es un "proceso" (generador de JavaScript)
// que cede comandos al motor: esperar un tiempo, solicitar un operario, solicitar
// una máquina o esperar hueco en la estación siguiente. El motor resuelve los
// comandos y reanuda el proceso. Así se modelan con naturalidad:
//   · operarios compartidos entre estaciones (con desplazamientos reales),
//   · bloqueo por buffer lleno y hambre por falta de material,
//   · setups por cambio de referencia o cada N unidades,
//   · averías de máquina dependientes del tiempo de uso (MTBF/MTTR),
//   · inspecciones con detección imperfecta, retrabajos y desechos,
//   · pausas programadas, fatiga y recuperación, curva de aprendizaje.

import { EventQueue } from './eventQueue.js';
import { StateTracker, TimeWeighted, Tally } from './trackers.js';
import { StreamFactory } from '../stochastic/rng.js';
import { sample, mean as distMean } from '../stochastic/distributions.js';
import { computeDuration, idealDuration, fatigueFactor } from '../stochastic/variability.js';
import { normalizeModel, normalizeOperation } from '../model/schema.js';
import { computeLayout, distanceMatrix, workSpot } from '../layout/autoLayout.js';

const delay = (d) => ({ kind: 'delay', d: Math.max(0, d) });

export class Simulation {
  /**
   * @param {object} model modelo (se normaliza internamente)
   * @param {object} [opts]
   * @param {number} [opts.replication=0]
   * @param {boolean} [opts.trace=false] registrar eventos para la animación 3D
   * @param {number} [opts.traceHours] límite de horas a registrar
   * @param {number} [opts.maxTraceEvents=200000]
   * @param {Set<string>} [opts.deterministic] fuentes de variabilidad anuladas (análisis)
   */
  constructor(model, opts = {}) {
    this.model = normalizeModel(model);
    const m = this.model;
    this.opts = opts;
    this.clock = { now: 0 };
    this.queue = new EventQueue();
    this.horizon = m.settings.horizonHours * 3600;
    this.window = { start: m.settings.warmupHours * 3600, end: this.horizon };
    this.streams = new StreamFactory(m.settings.seed, opts.replication ?? 0);
    this.overrides = { deterministic: opts.deterministic || null };
    this.positions = computeLayout(m);
    this.dist = distanceMatrix(m, this.positions);
    this.trace = opts.trace ? [] : null;
    this.traceEnd = opts.traceHours ? opts.traceHours * 3600 : this.horizon;
    this.maxTrace = opts.maxTraceEvents ?? 200000;
    this.entitySeq = 0;

    this.ops = new Map(m.operations.map((o) => [o.id, o]));
    this.walkOp = m.operations.find((o) => o.type === 'walking') || normalizeOperation({ id: '__walk', type: 'walking', name: 'Desplazamiento' });
    this.products = m.products;

    this._buildResources();
    this._buildStations();

    this.stats = {
      created: 0,
      completed: 0,
      scrapped: 0,
      reworkOps: 0,
      rejects: 0,
      falseRejects: 0,
      escapedDefects: 0,
      firstPass: 0,
      defectsCreated: 0,
      leadTime: new Tally(),
      byProduct: Object.fromEntries(this.products.map((p) => [p.id, { completed: 0, scrapped: 0, leadTime: new Tally(2000) }])),
      wip: new TimeWeighted(this.clock, this.window),
      backlog: new TimeWeighted(this.clock, this.window),
      opStats: Object.fromEntries(m.operations.map((o) => [o.id, { duration: new Tally(3000), interruptions: 0, interruptionTime: 0, ideal: 0, count: 0 }])),
      hourly: new Array(Math.ceil(m.settings.horizonHours)).fill(0),
      wipSeries: [],
      setups: 0,
    };
  }

  // ---------------------------------------------------------------- recursos
  _buildResources() {
    const m = this.model;
    this.operators = new Map();
    for (const def of m.operators) {
      const home = def.homeStationId || m.stations.find((s) => s.operatorIds.includes(def.id))?.id || m.stations[0]?.id;
      this.operators.set(def.id, {
        def,
        id: def.id,
        state: 'idle',
        location: home,
        tracker: new StateTracker(this.clock, this.window, 'idle'),
        repetitions: new Map(),
        fatigueH: 0,
        lastChange: 0,
        pendingBreak: 0,
        onBreak: false,
        walked: 0,
        tasks: 0,
        maxFatigueFactor: 1,
        idleSince: 0,
      });
    }
    this.machines = new Map();
    for (const def of m.machines) {
      const mc = {
        def,
        id: def.id,
        busy: false,
        waiting: [],
        tracker: new StateTracker(this.clock, this.window, 'idle'),
        failures: 0,
        repairTime: new Tally(500),
        idealTime: 0,
        runTime: 0,
        units: 0,
        uptimeLeft: Infinity,
      };
      if (def.failures?.enabled) mc.uptimeLeft = this._sampleMachine(mc, 'mtbf');
      this.machines.set(def.id, mc);
    }
    this.operatorRequests = [];
  }

  _sampleMachine(mc, which) {
    const det = this.overrides.deterministic;
    const spec = mc.def.failures[which];
    if (det && (det.has('*') || det.has('failures') || det.has(`machine:${mc.id}`))) {
      return which === 'mtbf' ? Infinity : distMean(spec);
    }
    return Math.max(1, sample(spec, this.streams.get(`machine:${mc.id}:${which}`)));
  }

  _buildStations() {
    this.stations = this.model.stations.map((def, idx) => ({
      def,
      id: def.id,
      idx,
      ops: def.operationIds.map((id) => this.ops.get(id)).filter(Boolean),
      setupOp: def.setup?.operationId ? this.ops.get(def.setup.operationId) : null,
      transportOp: def.transportOperationId ? this.ops.get(def.transportOperationId) : null,
      buffer: [],
      external: [],
      reserved: 0,
      waiters: [],
      bufferTw: new TimeWeighted(this.clock, this.window),
      processed: 0,
      cycle: new Tally(2000),
      interDeparture: new Tally(2000),
      lastDeparture: null,
      workplaces: Array.from({ length: Math.max(1, def.workplaces) }, (_, i) => ({
        id: `${def.id}#${i + 1}`,
        slot: i,
        entity: null,
        lastProduct: null,
        sinceSetup: 0,
        tracker: new StateTracker(this.clock, this.window, 'idle'),
      })),
    }));
  }

  // ---------------------------------------------------------------- utilidades
  schedule(d, fn) {
    this.queue.push(this.clock.now + Math.max(0, d), fn);
  }

  log(ev) {
    if (!this.trace || this.clock.now > this.traceEnd || this.trace.length >= this.maxTrace) return;
    ev.t = Math.round(this.clock.now * 100) / 100;
    this.trace.push(ev);
  }

  inWindow() {
    return this.clock.now >= this.window.start;
  }

  spawn(gen) {
    this._step(gen, undefined);
  }

  _step(gen, value) {
    const r = gen.next(value);
    if (r.done) return;
    const cmd = r.value;
    switch (cmd.kind) {
      case 'delay':
        this.schedule(cmd.d, () => this._step(gen));
        break;
      case 'seizeOperator':
        this.operatorRequests.push({ ...cmd, resume: (o) => this._step(gen, o), t: this.clock.now });
        this._dispatchOperators();
        break;
      case 'seizeMachine': {
        const mc = cmd.machine;
        if (!mc.busy) {
          mc.busy = true;
          this._step(gen, mc);
        } else mc.waiting.push(() => this._step(gen, mc));
        break;
      }
      case 'waitSpace':
        cmd.station.waiters.push(() => this._step(gen));
        break;
      default:
        throw new Error(`Comando desconocido ${cmd.kind}`);
    }
  }

  // ---------------------------------------------------------------- operarios
  _dispatchOperators() {
    let progress = true;
    while (progress && this.operatorRequests.length) {
      progress = false;
      for (let i = 0; i < this.operatorRequests.length; i++) {
        const req = this.operatorRequests[i];
        const free = req.candidates.map((id) => this.operators.get(id)).filter((o) => o && o.state === 'idle');
        if (!free.length) continue;
        const chosen = this._chooseOperator(free, req.station);
        this.operatorRequests.splice(i, 1);
        chosen.state = 'assigned';
        req.resume(chosen);
        progress = true;
        break;
      }
    }
  }

  _chooseOperator(free, station) {
    const rule = free[0].def.dispatch || 'nearest';
    const d = (o) => this.dist[o.location]?.[station.id] ?? 0;
    const perf = (o) => o.def.performance?.default ?? 100;
    const sorted = [...free].sort((a, b) => {
      if (rule === 'fastest') return perf(b) - perf(a) || d(a) - d(b);
      if (rule === 'longestIdle') return a.idleSince - b.idleSince || d(a) - d(b);
      return d(a) - d(b) || perf(b) - perf(a);
    });
    return sorted[0];
  }

  _recover(o) {
    const idleH = (this.clock.now - o.lastChange) / 3600;
    const rec = o.def.fatigue?.recoveryH > 0 ? o.def.fatigue.recoveryH : 0.25;
    if (idleH > 0) o.fatigueH *= Math.exp(-idleH / rec);
    o.lastChange = this.clock.now;
  }

  _work(o, seconds) {
    o.fatigueH += seconds / 3600;
    o.lastChange = this.clock.now;
  }

  _releaseOperator(o) {
    o.state = 'idle';
    o.idleSince = this.clock.now;
    o.tracker.set('idle');
    if (o.pendingBreak > 0) {
      const dur = o.pendingBreak;
      o.pendingBreak = 0;
      this._startBreak(o, dur);
      return;
    }
    this._dispatchOperators();
  }

  _startBreak(o, dur) {
    o.state = 'break';
    o.tracker.set('break');
    this._recover(o);
    this.log({ k: 'brk', o: o.id, d: dur });
    this.schedule(dur, () => {
      this._recover(o);
      o.state = 'idle';
      o.idleSince = this.clock.now;
      o.tracker.set('idle');
      this.log({ k: 'brkEnd', o: o.id });
      this._dispatchOperators();
    });
  }

  _scheduleBreaks() {
    const sh = this.model.settings.shift;
    if (!sh?.breaks?.length || !(sh.lengthHours > 0)) return;
    for (let start = 0; start < this.horizon; start += sh.lengthHours * 3600) {
      for (const b of sh.breaks) {
        const at = start + b.atHours * 3600;
        const dur = b.durationMin * 60;
        if (at >= this.horizon || dur <= 0) continue;
        this.queue.push(at, () => {
          for (const o of this.operators.values()) {
            if (o.state === 'idle') this._startBreak(o, dur);
            else o.pendingBreak = Math.max(o.pendingBreak, dur);
          }
        });
      }
    }
  }

  *_walk(o, station) {
    const from = o.location;
    const dist = this.dist[from]?.[station.id] ?? 0;
    if (dist < 0.05) {
      o.location = station.id;
      return;
    }
    this._recover(o);
    const dur = computeDuration({
      op: this.walkOp,
      operator: o.def,
      operatorState: o,
      distance: dist,
      streams: this.streams,
      overrides: this.overrides,
    });
    o.state = 'walking';
    o.tracker.set('walking');
    this.log({ k: 'walk', o: o.id, from, to: station.id, d: round(dur.total) });
    yield delay(dur.total);
    this._work(o, dur.total);
    o.walked += dist;
    o.location = station.id;
  }

  // ---------------------------------------------------------------- operaciones
  /**
   * Ejecuta una operación sobre una pieza: reserva máquina y operario, calcula la
   * duración con el motor de variabilidad, simula averías y genera defectos.
   */
  *_execOp(op, st, wp, ent, { isSetup = false, distance = 0 } = {}) {
    if (wp) wp.tracker.set('waiting');
    let mc = null;
    if (op.requires.machine && st.def.machineId) {
      mc = this.machines.get(st.def.machineId);
      yield { kind: 'seizeMachine', machine: mc };
    }
    let o = null;
    if (op.requires.operator) {
      const candidates = op.operatorIds?.length ? op.operatorIds : st.def.operatorIds;
      o = yield { kind: 'seizeOperator', candidates, station: st };
      yield* this._walk(o, st);
      this._recover(o);
      o.state = 'busy';
      o.tracker.set(isSetup ? 'setup' : `work:${op.type}`);
    }
    if (wp) wp.tracker.set(isSetup ? 'setup' : 'working');
    if (mc) mc.tracker.set(isSetup ? 'setup' : 'busy');

    const product = ent?.product;
    const dur = computeDuration({
      op,
      operator: o?.def,
      operatorState: o,
      machine: mc?.def,
      product,
      distance,
      streams: this.streams,
      overrides: this.overrides,
    });
    if (o) o.maxFatigueFactor = Math.max(o.maxFatigueFactor, dur.parts.factors.fatigue);

    this.log({
      k: 'op',
      op: op.id,
      ty: op.type,
      st: st.id,
      wp: wp?.slot ?? -1,
      e: ent?.id ?? null,
      o: o?.id ?? null,
      m: mc?.id ?? null,
      d: round(dur.total),
      s: isSetup ? 1 : 0,
    });

    const t0 = this.clock.now;
    if (mc && op.requires.machine && Number.isFinite(mc.uptimeLeft)) {
      yield* this._machineRun(mc, dur.total, st, wp, o);
    } else {
      yield delay(dur.total);
    }
    const elapsed = this.clock.now - t0;

    if (o) {
      this._work(o, elapsed);
      o.repetitions.set(op.id, (o.repetitions.get(op.id) ?? 0) + 1);
      o.tasks++;
    }
    if (mc) {
      mc.runTime += dur.total;
      if (!isSetup && this.inWindow()) {
        mc.idealTime += idealDuration(op, product);
        mc.units++;
      }
    }
    if (this.inWindow()) {
      const os = this.stats.opStats[op.id];
      if (os) {
        os.duration.add(elapsed);
        os.count++;
        os.interruptions += dur.parts.interruptionCount;
        os.interruptionTime += dur.parts.interruptions;
        os.ideal += idealDuration(op, product);
      }
    }

    // Generación de defectos (producción, no inspección)
    if (ent && !op.isInspection && !isSetup && op.quality.defectProb > 0) {
      let p = op.quality.defectProb;
      if (o && o.def.qualityFatigueSensitivity > 0) p *= 1 + o.def.qualityFatigueSensitivity * (fatigueFactor(o.def.fatigue, o.fatigueH) - 1);
      if (this.streams.get(`defect:${op.id}`).random() < Math.min(1, p)) {
        ent.defective = true;
        if (this.inWindow()) this.stats.defectsCreated++;
      }
    }

    if (mc) {
      mc.tracker.set('idle');
      if (mc.waiting.length) mc.waiting.shift()();
      else mc.busy = false;
    }
    if (o) this._releaseOperator(o);
  }

  /** Funcionamiento de máquina con averías según tiempo de uso (MTBF en horas de marcha). */
  *_machineRun(mc, work, st, wp, o) {
    let remaining = work;
    while (remaining > 1e-9) {
      if (remaining <= mc.uptimeLeft) {
        mc.uptimeLeft -= remaining;
        yield delay(remaining);
        remaining = 0;
      } else {
        const run = mc.uptimeLeft;
        yield delay(run);
        remaining -= run;
        const repair = this._sampleMachine(mc, 'mttr');
        mc.tracker.set('down');
        if (wp) wp.tracker.set('failure');
        if (this.inWindow()) {
          mc.failures++;
          mc.repairTime.add(repair);
        }
        this.log({ k: 'down', m: mc.id, st: st.id, d: round(repair) });
        yield delay(repair);
        mc.uptimeLeft = this._sampleMachine(mc, 'mtbf');
        mc.tracker.set('busy');
        if (wp) wp.tracker.set('working');
        this.log({ k: 'up', m: mc.id, st: st.id });
      }
    }
  }

  _inspect(op, ent) {
    const q = op.quality;
    const r = this.streams.get(`inspect:${op.id}`).random();
    if (ent.defective) return r < q.detectionProb ? 'reject' : 'pass';
    if (r < q.falseRejectProb) {
      if (this.inWindow()) this.stats.falseRejects++;
      return 'reject';
    }
    return 'pass';
  }

  // ---------------------------------------------------------------- flujo
  canAccept(st) {
    const idle = st.workplaces.filter((w) => !w.entity).length;
    return st.buffer.length + st.reserved < st.def.bufferCapacity + idle;
  }

  _arrive(ent, st) {
    st.buffer.push(ent);
    st.bufferTw.set(st.buffer.length);
    this.log({ k: 'arr', e: ent.id, st: st.id, p: ent.product.id, n: st.buffer.length });
    this._tryStart(st);
  }

  _tryStart(st) {
    for (const wp of st.workplaces) {
      if (wp.entity || !st.buffer.length) continue;
      const ent = st.buffer.shift();
      st.bufferTw.set(st.buffer.length);
      wp.entity = ent;
      this.log({ k: 'start', e: ent.id, st: st.id, wp: wp.slot, n: st.buffer.length });
      this.spawn(this._job(st, wp, ent));
    }
  }

  _notifySpace(st) {
    if (st.idx === 0) this._feedFirst();
    while (st.waiters.length && this.canAccept(st)) st.waiters.shift()();
  }

  _needsSetup(st, wp, ent) {
    if (!st.setupOp) return false;
    const trig = st.def.setup?.trigger;
    if (trig === 'changeover') return wp.lastProduct !== null && wp.lastProduct !== ent.product.id;
    if (trig === 'everyN') return st.def.setup.everyN > 0 && wp.sinceSetup >= st.def.setup.everyN;
    return false;
  }

  *_job(st, wp, ent) {
    const startedAt = this.clock.now;
    if (this._needsSetup(st, wp, ent)) {
      if (this.inWindow()) this.stats.setups++;
      yield* this._execOp(st.setupOp, st, wp, ent, { isSetup: true });
      wp.sinceSetup = 0;
    }
    wp.lastProduct = ent.product.id;
    wp.sinceSetup++;

    for (const op of st.ops) {
      yield* this._execOp(op, st, wp, ent);
      if (!op.isInspection) continue;
      let verdict = this._inspect(op, ent);
      while (verdict === 'reject') {
        ent.firstPass = false;
        if (this.inWindow()) this.stats.rejects++;
        const q = op.quality;
        const reworkOp = q.reworkOperationId ? this.ops.get(q.reworkOperationId) : null;
        if (q.onReject === 'rework' && reworkOp && ent.reworks < q.maxReworks) {
          ent.reworks++;
          if (this.inWindow()) this.stats.reworkOps++;
          this.log({ k: 'rej', e: ent.id, st: st.id, a: 'rework' });
          yield* this._execOp(reworkOp, st, wp, ent);
          if (ent.defective && this.streams.get(`repair:${reworkOp.id}`).random() < q.repairProb) ent.defective = false;
          yield* this._execOp(op, st, wp, ent);
          verdict = this._inspect(op, ent);
        } else {
          this.log({ k: 'rej', e: ent.id, st: st.id, a: 'scrap' });
          this._leaveWorkplace(st, wp, startedAt);
          this._finish(ent, 'scrapped');
          return;
        }
      }
    }

    const next = this.stations[st.idx + 1];
    if (next) {
      wp.tracker.set('blocked');
      while (!this.canAccept(next)) yield { kind: 'waitSpace', station: next };
      next.reserved++;
    }
    this._leaveWorkplace(st, wp, startedAt);
    if (next) this.spawn(this._transit(ent, st, next));
    else this._finish(ent, 'completed');
  }

  _leaveWorkplace(st, wp, startedAt) {
    if (this.inWindow()) {
      st.processed++;
      st.cycle.add(this.clock.now - startedAt);
      if (st.lastDeparture !== null) st.interDeparture.add(this.clock.now - st.lastDeparture);
    }
    st.lastDeparture = this.clock.now;
    this.log({ k: 'leave', e: wp.entity?.id, st: st.id, wp: wp.slot });
    wp.entity = null;
    wp.tracker.set('idle');
    this._tryStart(st);
    this._notifySpace(st);
  }

  *_transit(ent, from, to) {
    const top = from.transportOp;
    if (top) {
      const d = this.dist[from.id]?.[to.id] ?? 0;
      this.log({ k: 'move', e: ent.id, from: from.id, to: to.id });
      yield* this._execOp(top, from, null, ent, { distance: d });
    }
    to.reserved--;
    this._arrive(ent, to);
  }

  _finish(ent, status) {
    this.stats.wip.add(-1);
    this.log({ k: 'exit', e: ent.id, s: status });
    // la serie horaria incluye el calentamiento para poder ver el arranque
    const hour = Math.floor(this.clock.now / 3600);
    if (status === 'completed' && hour < this.stats.hourly.length) this.stats.hourly[hour]++;
    if (!this.inWindow()) return;
    const bp = this.stats.byProduct[ent.product.id];
    if (status === 'completed') {
      const lt = this.clock.now - ent.createdAt;
      this.stats.completed++;
      this.stats.leadTime.add(lt);
      bp.completed++;
      bp.leadTime.add(lt);
      if (ent.firstPass) this.stats.firstPass++;
      if (ent.defective) this.stats.escapedDefects++;
    } else {
      this.stats.scrapped++;
      bp.scrapped++;
    }
  }

  // ---------------------------------------------------------------- llegadas
  _newEntity() {
    const a = this.model.arrivals;
    const lot = Math.max(1, a.batchSize || 1);
    if (!this._lot || this._lot.left <= 0) {
      const idx = this.streams.get('product-mix').weightedIndex(this.products.map((p) => p.mix ?? 1));
      this._lot = { product: this.products[idx], left: lot };
    }
    this._lot.left--;
    const ent = {
      id: ++this.entitySeq,
      product: this._lot.product,
      createdAt: this.clock.now,
      defective: false,
      firstPass: true,
      reworks: 0,
    };
    if (this.inWindow()) this.stats.created++;
    return ent;
  }

  _feedFirst() {
    const first = this.stations[0];
    if (!first || this._feeding) return;
    this._feeding = true;
    if (this.model.arrivals.mode === 'push') {
      while (this.canAccept(first)) {
        this.stats.wip.add(1);
        this._arrive(this._newEntity(), first);
      }
    } else {
      while (first.external.length && this.canAccept(first)) {
        const ent = first.external.shift();
        this.stats.backlog.set(first.external.length);
        this.stats.wip.add(1);
        this._arrive(ent, first);
      }
    }
    this._feeding = false;
  }

  *_arrivalProcess() {
    const a = this.model.arrivals;
    const rng = this.streams.get('arrivals');
    const det = this.overrides.deterministic;
    const first = this.stations[0];
    for (;;) {
      const gap = det && (det.has('*') || det.has('arrivals')) ? distMean(a.interarrival) : sample(a.interarrival, rng);
      yield delay(gap);
      const n = Math.max(1, a.batchSize || 1);
      for (let i = 0; i < n; i++) first.external.push(this._newEntity());
      this.stats.backlog.set(first.external.length);
      this._feedFirst();
    }
  }

  // ---------------------------------------------------------------- ejecución
  run() {
    if (!this.stations.length) throw new Error('Modelo sin estaciones');
    this._scheduleBreaks();
    // reinicio de estadísticas al terminar el calentamiento
    this.queue.push(this.window.start, () => {
      this.stats.wip.max = this.stats.wip.value;
    });
    const sampleEvery = Math.max(60, this.horizon / 240);
    for (let t = 0; t <= this.horizon; t += sampleEvery) {
      this.queue.push(t, () => this.stats.wipSeries.push([Math.round(this.clock.now), this.stats.wip.value]));
    }
    if (this.model.arrivals.mode === 'interarrival') this.spawn(this._arrivalProcess());
    else this.queue.push(0, () => this._feedFirst());

    let events = 0;
    const maxEvents = this.opts.maxEvents ?? 5e7;
    while (this.queue.size) {
      const ev = this.queue.peek();
      if (ev.time > this.horizon) break;
      this.queue.pop();
      this.clock.now = ev.time;
      ev.fn();
      if (++events > maxEvents) throw new Error('Demasiados eventos: revisa el modelo (¿tiempos nulos?)');
    }
    this.clock.now = this.horizon;
    this.eventCount = events;
    return this._collect();
  }

  _collect() {
    const s = this.stats;
    return {
      replication: this.opts.replication ?? 0,
      observedSeconds: this.window.end - this.window.start,
      events: this.eventCount,
      totals: {
        created: s.created,
        completed: s.completed,
        scrapped: s.scrapped,
        rejects: s.rejects,
        falseRejects: s.falseRejects,
        reworkOps: s.reworkOps,
        escapedDefects: s.escapedDefects,
        firstPass: s.firstPass,
        defectsCreated: s.defectsCreated,
        setups: s.setups,
      },
      leadTime: { ...s.leadTime.summary(), values: s.leadTime.values },
      wip: s.wip.finalize(),
      backlog: s.backlog.finalize(),
      hourly: s.hourly,
      wipSeries: s.wipSeries,
      byProduct: Object.fromEntries(
        Object.entries(s.byProduct).map(([id, b]) => [id, { completed: b.completed, scrapped: b.scrapped, leadTime: b.leadTime.summary() }]),
      ),
      operations: Object.fromEntries(
        Object.entries(s.opStats).map(([id, o]) => [
          id,
          { ...o.duration.summary(), values: o.duration.values.slice(0, 1500), interruptions: o.interruptions, interruptionTime: o.interruptionTime, ideal: o.ideal },
        ]),
      ),
      stations: this.stations.map((st) => {
        const totals = {};
        for (const wp of st.workplaces) for (const [k, v] of Object.entries(wp.tracker.finalize())) totals[k] = (totals[k] || 0) + v;
        const n = st.workplaces.length;
        for (const k of Object.keys(totals)) totals[k] /= n;
        return {
          id: st.id,
          name: st.def.name || st.id,
          states: totals,
          processed: st.processed,
          cycle: st.cycle.summary(),
          interDeparture: st.interDeparture.summary(),
          buffer: st.bufferTw.finalize(),
          bufferCapacity: st.def.bufferCapacity,
          workplaces: n,
        };
      }),
      operators: [...this.operators.values()].map((o) => ({
        id: o.id,
        name: o.def.name,
        states: o.tracker.finalize(),
        walked: o.walked,
        tasks: o.tasks,
        maxFatigueFactor: o.maxFatigueFactor,
      })),
      machines: [...this.machines.values()].map((mc) => ({
        id: mc.id,
        name: mc.def.name,
        states: mc.tracker.finalize(),
        failures: mc.failures,
        repair: mc.repairTime.summary(),
        idealTime: mc.idealTime,
        units: mc.units,
      })),
      trace: this.trace,
      layout: this.trace ? this.positions : undefined,
    };
  }
}

function round(x) {
  return Math.round(x * 100) / 100;
}

export function simulate(model, opts) {
  return new Simulation(model, opts).run();
}

export { workSpot };
