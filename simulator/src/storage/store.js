// Persistencia en disco (JSON). Todo lo que el usuario introduce queda guardado:
// modelos, historial de versiones, biblioteca de plantillas y últimos resultados.
// Las escrituras son atómicas (fichero temporal + rename) para no corromper datos.

import { promises as fs } from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const SAFE_ID = /^[A-Za-z0-9_-]{1,80}$/;
const MAX_HISTORY = 30;

export class Store {
  constructor(dir) {
    this.dir = dir;
    this.paths = {
      models: path.join(dir, 'models'),
      history: path.join(dir, 'history'),
      results: path.join(dir, 'results'),
      library: path.join(dir, 'library.json'),
    };
    this.locks = new Map();
  }

  async init() {
    for (const p of [this.paths.models, this.paths.history, this.paths.results]) await fs.mkdir(p, { recursive: true });
  }

  static checkId(id) {
    if (!SAFE_ID.test(String(id))) throw Object.assign(new Error('Identificador no válido'), { status: 400 });
    return id;
  }

  static newId(name = 'modelo') {
    const slug = String(name)
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '')
      .slice(0, 40) || 'modelo';
    return `${slug}-${crypto.randomBytes(3).toString('hex')}`;
  }

  async _writeJson(file, data) {
    // serializa escrituras sobre el mismo fichero
    const prev = this.locks.get(file) || Promise.resolve();
    const next = prev.then(async () => {
      const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
      await fs.writeFile(tmp, JSON.stringify(data, null, 2));
      await fs.rename(tmp, file);
    });
    this.locks.set(file, next.catch(() => {}));
    return next;
  }

  async _readJson(file, fallback) {
    try {
      return JSON.parse(await fs.readFile(file, 'utf8'));
    } catch (e) {
      if (e.code === 'ENOENT') return fallback;
      throw e;
    }
  }

  // ------------------------------------------------------------ modelos
  async listModels() {
    const files = (await fs.readdir(this.paths.models)).filter((f) => f.endsWith('.json'));
    const out = [];
    for (const f of files) {
      const m = await this._readJson(path.join(this.paths.models, f), null);
      if (!m) continue;
      out.push({
        id: m.id,
        name: m.name,
        description: m.description || '',
        updatedAt: m.updatedAt,
        createdAt: m.createdAt,
        stations: m.stations?.length || 0,
        operations: m.operations?.length || 0,
        revision: m.revision || 1,
      });
    }
    return out.sort((a, b) => String(b.updatedAt).localeCompare(String(a.updatedAt)));
  }

  async getModel(id) {
    Store.checkId(id);
    return this._readJson(path.join(this.paths.models, `${id}.json`), null);
  }

  /**
   * Guarda un modelo. Si `expectedRevision` no coincide con la guardada se
   * rechaza (evita que dos pestañas se pisen los cambios).
   */
  async saveModel(model, { expectedRevision } = {}) {
    if (!model || typeof model !== 'object') throw Object.assign(new Error('Modelo vacío'), { status: 400 });
    if (!model.id) model.id = Store.newId(model.name);
    Store.checkId(model.id);
    const file = path.join(this.paths.models, `${model.id}.json`);
    const current = await this._readJson(file, null);
    if (current && expectedRevision !== undefined && expectedRevision !== null && current.revision !== expectedRevision) {
      throw Object.assign(new Error('El modelo ha cambiado en otra ventana'), { status: 409, current });
    }
    const now = new Date().toISOString();
    const saved = {
      ...model,
      createdAt: current?.createdAt || model.createdAt || now,
      updatedAt: now,
      revision: (current?.revision || 0) + 1,
    };
    if (current) await this._snapshot(current);
    await this._writeJson(file, saved);
    return saved;
  }

  async deleteModel(id) {
    Store.checkId(id);
    const current = await this.getModel(id);
    if (current) await this._snapshot(current);
    await fs.rm(path.join(this.paths.models, `${id}.json`), { force: true });
    await fs.rm(path.join(this.paths.results, `${id}.json`), { force: true });
    await fs.rm(path.join(this.paths.results, `${id}.trace.json`), { force: true });
  }

  // ------------------------------------------------------------ historial
  async _snapshot(model) {
    const dir = path.join(this.paths.history, model.id);
    await fs.mkdir(dir, { recursive: true });
    const name = `${String(model.revision || 0).padStart(6, '0')}.json`;
    await this._writeJson(path.join(dir, name), model);
    const files = (await fs.readdir(dir)).filter((f) => f.endsWith('.json')).sort();
    // conserva las versiones más recientes, y una de cada 10 de las antiguas
    const excess = files.slice(0, Math.max(0, files.length - MAX_HISTORY));
    for (const f of excess) if (parseInt(f, 10) % 10 !== 0) await fs.rm(path.join(dir, f), { force: true });
  }

  async listHistory(id) {
    Store.checkId(id);
    const dir = path.join(this.paths.history, id);
    let files = [];
    try {
      files = (await fs.readdir(dir)).filter((f) => f.endsWith('.json')).sort().reverse();
    } catch {
      return [];
    }
    const out = [];
    for (const f of files) {
      const m = await this._readJson(path.join(dir, f), null);
      if (m) out.push({ revision: m.revision, updatedAt: m.updatedAt, name: m.name, operations: m.operations?.length || 0, stations: m.stations?.length || 0 });
    }
    return out;
  }

  async getHistoryVersion(id, revision) {
    Store.checkId(id);
    const r = parseInt(revision, 10);
    if (!Number.isFinite(r)) throw Object.assign(new Error('Revisión no válida'), { status: 400 });
    return this._readJson(path.join(this.paths.history, id, `${String(r).padStart(6, '0')}.json`), null);
  }

  // ------------------------------------------------------------ resultados
  async saveResult(id, result) {
    Store.checkId(id);
    const { trace, layout, ...rest } = result;
    await this._writeJson(path.join(this.paths.results, `${id}.json`), rest);
    if (trace) await this._writeJson(path.join(this.paths.results, `${id}.trace.json`), { trace, layout, createdAt: rest.meta?.createdAt });
  }

  async getResult(id) {
    Store.checkId(id);
    return this._readJson(path.join(this.paths.results, `${id}.json`), null);
  }

  async getTrace(id) {
    Store.checkId(id);
    return this._readJson(path.join(this.paths.results, `${id}.trace.json`), null);
  }

  async saveAnalysis(id, kind, data) {
    Store.checkId(id);
    Store.checkId(kind);
    await this._writeJson(path.join(this.paths.results, `${id}.${kind}.json`), data);
  }

  async getAnalysis(id, kind) {
    Store.checkId(id);
    Store.checkId(kind);
    return this._readJson(path.join(this.paths.results, `${id}.${kind}.json`), null);
  }

  // ------------------------------------------------------------ biblioteca
  async getLibrary() {
    return this._readJson(this.paths.library, { operations: [], operators: [], machines: [] });
  }

  async saveLibrary(lib) {
    const clean = {
      operations: Array.isArray(lib.operations) ? lib.operations : [],
      operators: Array.isArray(lib.operators) ? lib.operators : [],
      machines: Array.isArray(lib.machines) ? lib.machines : [],
      updatedAt: new Date().toISOString(),
    };
    await this._writeJson(this.paths.library, clean);
    return clean;
  }
}
