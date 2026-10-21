import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import { promises as fs } from 'node:fs';
import { Store } from '../src/storage/store.js';

async function tmpStore() {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'umps-'));
  const s = new Store(dir);
  await s.init();
  return { s, dir };
}

test('guarda, versiona y restaura modelos', async () => {
  const { s, dir } = await tmpStore();
  const m1 = await s.saveModel({ name: 'Línea A', stations: [] });
  assert.equal(m1.revision, 1);
  const m2 = await s.saveModel({ ...m1, name: 'Línea A v2' }, { expectedRevision: 1 });
  assert.equal(m2.revision, 2);
  // reabrir desde disco (simula reiniciar el servidor)
  const again = new Store(dir);
  assert.equal((await again.getModel(m1.id)).name, 'Línea A v2');
  const hist = await again.listHistory(m1.id);
  assert.equal(hist[0].revision, 1);
  assert.equal((await again.getHistoryVersion(m1.id, 1)).name, 'Línea A');
});

test('rechaza escrituras con revisión desactualizada', async () => {
  const { s } = await tmpStore();
  const m = await s.saveModel({ name: 'X' });
  await s.saveModel({ ...m }, { expectedRevision: 1 });
  await assert.rejects(s.saveModel({ ...m }, { expectedRevision: 1 }), (e) => e.status === 409);
});

test('impide identificadores peligrosos', async () => {
  const { s } = await tmpStore();
  await assert.rejects(s.getModel('../etc/passwd'), (e) => e.status === 400);
});

test('biblioteca persistente', async () => {
  const { s, dir } = await tmpStore();
  await s.saveLibrary({ operations: [{ name: 'Atornillado M4', item: { type: 'screwing' } }] });
  const lib = await new Store(dir).getLibrary();
  assert.equal(lib.operations[0].name, 'Atornillado M4');
});

test('resultados y traza se guardan por separado', async () => {
  const { s } = await tmpStore();
  await s.saveResult('m1', { meta: { createdAt: 'x' }, scalars: {}, trace: [{ t: 0 }], layout: {} });
  assert.equal((await s.getResult('m1')).trace, undefined);
  assert.equal((await s.getTrace('m1')).trace.length, 1);
});
