// Servidor del Universal Manual Process Simulator.
// Sin dependencias externas: node:http + hilos de trabajo para las simulaciones.
//
//   PORT       puerto (por defecto 3100)
//   DATA_DIR   carpeta de datos persistentes (por defecto ./data)

import http from 'node:http';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Worker } from 'node:worker_threads';
import crypto from 'node:crypto';

import { Store } from './src/storage/store.js';
import { exampleModel } from './src/model/examples.js';
import { validateModel } from './src/model/schema.js';
import { fitDistributions } from './src/stochastic/fitting.js';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT) || 3100;
const store = new Store(process.env.DATA_DIR || path.join(ROOT, 'data'));
const MAX_BODY = 20 * 1024 * 1024;
const JOB_TTL_MS = 30 * 60 * 1000;

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
};

// ------------------------------------------------------------------ trabajos
const jobs = new Map();

function startJob(task, args, onDone) {
  const id = crypto.randomUUID();
  const job = { id, task, progress: 0, status: 'running', startedAt: Date.now() };
  jobs.set(id, job);
  const worker = new Worker(path.join(ROOT, 'src/worker.js'));
  worker.on('message', async (msg) => {
    if (msg.progress !== undefined) {
      job.progress = msg.progress;
      return;
    }
    if (msg.error) {
      Object.assign(job, { status: 'error', error: msg.error, details: msg.details });
    } else {
      try {
        if (onDone) await onDone(msg.result);
        Object.assign(job, { status: 'done', progress: 1, result: msg.result });
      } catch (e) {
        Object.assign(job, { status: 'error', error: e.message });
      }
    }
    job.finishedAt = Date.now();
    worker.terminate();
  });
  worker.on('error', (e) => Object.assign(job, { status: 'error', error: e.message, finishedAt: Date.now() }));
  worker.postMessage({ task, args });
  return job;
}

setInterval(() => {
  const now = Date.now();
  for (const [id, j] of jobs) if (j.finishedAt && now - j.finishedAt > JOB_TTL_MS) jobs.delete(id);
}, 60_000).unref();

// ------------------------------------------------------------------ utilidades
function send(res, status, body) {
  const data = JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': MIME['.json'], 'Cache-Control': 'no-store' });
  res.end(data);
}

async function readBody(req) {
  const chunks = [];
  let size = 0;
  for await (const c of req) {
    size += c.length;
    if (size > MAX_BODY) throw Object.assign(new Error('Petición demasiado grande'), { status: 413 });
    chunks.push(c);
  }
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    throw Object.assign(new Error('JSON no válido'), { status: 400 });
  }
}

const THREE_VERSION = '0.160.0';

async function serveStatic(res, urlPath) {
  // three.js se sirve desde node_modules (funciona sin internet); si no está
  // instalado se redirige al CDN.
  if (urlPath.startsWith('/vendor/three/')) {
    const base = path.join(ROOT, 'node_modules', 'three');
    const file = path.normalize(path.join(base, urlPath.slice('/vendor/three/'.length)));
    if (!file.startsWith(base)) return res.writeHead(403).end();
    try {
      const data = await fs.readFile(file);
      res.writeHead(200, { 'Content-Type': MIME['.js'], 'Cache-Control': 'public, max-age=86400' });
      return res.end(data);
    } catch {
      res.writeHead(302, { Location: `https://cdn.jsdelivr.net/npm/three@${THREE_VERSION}/${urlPath.slice('/vendor/three/'.length)}` });
      return res.end();
    }
  }
  let rel = urlPath === '/' ? '/public/index.html' : urlPath;
  if (!rel.startsWith('/public/') && !rel.startsWith('/src/')) rel = `/public${rel}`;
  const file = path.normalize(path.join(ROOT, rel));
  if (!file.startsWith(path.join(ROOT, 'public')) && !file.startsWith(path.join(ROOT, 'src'))) {
    res.writeHead(403).end();
    return;
  }
  try {
    const data = await fs.readFile(file);
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-cache' });
    res.end(data);
  } catch {
    res.writeHead(404, { 'Content-Type': 'text/plain' }).end('No encontrado');
  }
}

// ------------------------------------------------------------------ rutas
const routes = [];
const route = (method, pattern, handler) => {
  const keys = [];
  const re = new RegExp(`^${pattern.replace(/:(\w+)/g, (_, k) => (keys.push(k), '([^/]+)'))}$`);
  routes.push({ method, re, keys, handler });
};

route('GET', '/api/health', () => ({ ok: true }));

route('GET', '/api/models', () => store.listModels());

route('POST', '/api/models', async (_p, body) => {
  let model;
  if (body.template === 'example') model = { ...exampleModel(), id: undefined, name: body.name || exampleModel().name };
  else if (body.model) model = { ...body.model, id: undefined };
  else model = { name: body.name || 'Nuevo modelo', settings: {}, products: [], operators: [], machines: [], operations: [], stations: [] };
  delete model.revision;
  model.id = Store.newId(model.name);
  return store.saveModel(model);
});

route('GET', '/api/models/:id', async ({ id }) => {
  const m = await store.getModel(id);
  if (!m) throw Object.assign(new Error('Modelo no encontrado'), { status: 404 });
  return m;
});

route('PUT', '/api/models/:id', async ({ id }, body) => {
  const { model, expectedRevision } = body.model ? body : { model: body };
  return store.saveModel({ ...model, id }, { expectedRevision });
});

route('DELETE', '/api/models/:id', async ({ id }) => {
  await store.deleteModel(id);
  return { ok: true };
});

route('POST', '/api/models/:id/duplicate', async ({ id }) => {
  const m = await store.getModel(id);
  if (!m) throw Object.assign(new Error('Modelo no encontrado'), { status: 404 });
  const copy = { ...m, name: `${m.name} (copia)`, revision: undefined, createdAt: undefined };
  copy.id = Store.newId(copy.name);
  return store.saveModel(copy);
});

route('GET', '/api/models/:id/history', ({ id }) => store.listHistory(id));

route('POST', '/api/models/:id/restore/:rev', async ({ id, rev }) => {
  const old = await store.getHistoryVersion(id, rev);
  if (!old) throw Object.assign(new Error('Versión no encontrada'), { status: 404 });
  return store.saveModel({ ...old, id });
});

route('POST', '/api/validate', async (_p, body) => {
  const { errors, warnings } = validateModel(body.model || body);
  return { errors, warnings };
});

route('POST', '/api/models/:id/simulate', async ({ id }, body) => {
  const model = body.model || (await store.getModel(id));
  if (!model) throw Object.assign(new Error('Modelo no encontrado'), { status: 404 });
  const { errors } = validateModel(model);
  if (errors.length) throw Object.assign(new Error('El modelo tiene errores'), { status: 422, details: errors });
  const options = { replications: body.replications, trace: body.trace !== false, traceHours: body.traceHours ?? Math.min(2, model.settings?.horizonHours ?? 8) };
  const job = startJob('simulate', { model, options }, async (result) => {
    result.meta.modelRevision = model.revision;
    await store.saveResult(id, result);
    delete result.trace;
    delete result.layout;
  });
  return { jobId: job.id };
});

route('GET', '/api/models/:id/results', async ({ id }) => (await store.getResult(id)) || null);
route('GET', '/api/models/:id/trace', async ({ id }) => (await store.getTrace(id)) || null);

route('POST', '/api/models/:id/contribution', async ({ id }, body) => {
  const model = body.model || (await store.getModel(id));
  if (!model) throw Object.assign(new Error('Modelo no encontrado'), { status: 404 });
  const { errors } = validateModel(model);
  if (errors.length) throw Object.assign(new Error('El modelo tiene errores'), { status: 422, details: errors });
  const job = startJob('contribution', { model, options: { replications: body.replications } }, (r) =>
    store.saveAnalysis(id, 'contribution', { ...r, createdAt: new Date().toISOString(), modelRevision: model.revision }),
  );
  return { jobId: job.id };
});

route('GET', '/api/models/:id/contribution', async ({ id }) => (await store.getAnalysis(id, 'contribution')) || null);

route('POST', '/api/compare', async (_p, body) => {
  const a = body.a?.stations ? body.a : await store.getModel(body.a);
  const b = body.b?.stations ? body.b : await store.getModel(body.b);
  if (!a || !b) throw Object.assign(new Error('Escenario no encontrado'), { status: 404 });
  for (const m of [a, b]) {
    const { errors } = validateModel(m);
    if (errors.length) throw Object.assign(new Error(`«${m.name}» tiene errores`), { status: 422, details: errors });
  }
  const job = startJob('compare', { a, b, options: { replications: body.replications } });
  return { jobId: job.id };
});

route('GET', '/api/jobs/:id', ({ id }) => {
  const j = jobs.get(id);
  if (!j) throw Object.assign(new Error('Trabajo no encontrado'), { status: 404 });
  const { result, ...rest } = j;
  return j.status === 'done' ? { ...rest, result } : rest;
});

route('POST', '/api/fit', (_p, body) => fitDistributions(body.samples));

route('GET', '/api/library', () => store.getLibrary());
route('PUT', '/api/library', (_p, body) => store.saveLibrary(body));

// ------------------------------------------------------------------ servidor
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  try {
    if (!url.pathname.startsWith('/api/')) {
      if (req.method !== 'GET') return send(res, 405, { error: 'Método no permitido' });
      return await serveStatic(res, decodeURIComponent(url.pathname));
    }
    for (const r of routes) {
      if (r.method !== req.method) continue;
      const m = url.pathname.match(r.re);
      if (!m) continue;
      const params = Object.fromEntries(r.keys.map((k, i) => [k, decodeURIComponent(m[i + 1])]));
      const body = ['POST', 'PUT'].includes(req.method) ? await readBody(req) : {};
      const out = await r.handler(params, body, url.searchParams);
      return send(res, 200, out);
    }
    send(res, 404, { error: 'Ruta no encontrada' });
  } catch (e) {
    const status = e.status || 500;
    if (status >= 500) console.error(e);
    send(res, status, { error: e.message, details: e.details, current: e.current });
  }
});

await store.init();
if (!(await store.listModels()).length) {
  await store.saveModel(exampleModel());
  console.log('Creado el modelo de ejemplo');
}

server.listen(PORT, () => console.log(`Simulador escuchando en http://localhost:${PORT}`));
