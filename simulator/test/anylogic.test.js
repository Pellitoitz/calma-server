import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import { promises as fs } from 'node:fs';
import { toAnyLogic, distExpr } from '../src/export/anylogic.js';
import { exampleModel } from '../src/model/examples.js';
import { buildHarness } from './javaHarness.js';

const OUT_PORTS = { Source: ['out'], Queue: ['out'], Seize: ['out'], Delay: ['out'], Release: ['out'], SelectOutput: ['outT', 'outF'], Sink: [], ResourcePool: [] };

function parseBlocks(xml) {
  const blocks = [...xml.matchAll(/<EmbeddedObject>\s*<Id>\d+<\/Id>\s*<Name><!\[CDATA\[([^\]]+)\]\]><\/Name>[\s\S]*?<ClassName><!\[CDATA\[([A-Za-z]+)\]\]><\/ClassName>/g)].map((m) => ({ name: m[1], cls: m[2] }));
  const conns = [...xml.matchAll(/<Connector>[\s\S]*?<SourceEmbeddedObjectReference>[\s\S]*?<ItemName><!\[CDATA\[([^\]]+)\]\]><\/ItemName>[\s\S]*?<SourceConnectableItemReference>[\s\S]*?<ItemName><!\[CDATA\[([^\]]+)\]\]><\/ItemName>[\s\S]*?<TargetEmbeddedObjectReference>[\s\S]*?<ItemName><!\[CDATA\[([^\]]+)\]\]><\/ItemName>[\s\S]*?<TargetConnectableItemReference>[\s\S]*?<ItemName><!\[CDATA\[([^\]]+)\]\]><\/ItemName>/g)].map((m) => ({ from: m[1], fromPort: m[2], to: m[3], toPort: m[4] }));
  return { blocks, conns };
}

function interarrivalModel() {
  const m = exampleModel();
  m.arrivals = { mode: 'interarrival', interarrival: { type: 'exponential', mean: 150 }, batchSize: 5 };
  return m;
}

for (const [label, make] of [['ejemplo (material siempre disponible)', exampleModel], ['llegadas aleatorias por lotes', interarrivalModel]]) {
  test(`AnyLogic: diagrama bien conectado · ${label}`, () => {
    const { xml } = toAnyLogic(make());
    const { blocks, conns } = parseBlocks(xml);
    const names = new Set();
    for (const b of blocks) {
      assert.match(b.name, /^[A-Za-z_][A-Za-z0-9_]*$/, `nombre Java no válido: ${b.name}`);
      assert.ok(!names.has(b.name), `bloque duplicado ${b.name}`);
      names.add(b.name);
    }
    const byName = new Map(blocks.map((b) => [b.name, b]));
    for (const c of conns) {
      assert.ok(byName.has(c.from) && byName.has(c.to), `conector a bloque inexistente ${c.from}→${c.to}`);
    }
    // cada puerto de salida conectado exactamente una vez
    for (const b of blocks) {
      for (const p of OUT_PORTS[b.cls]) {
        const n = conns.filter((c) => c.from === b.name && c.fromPort === p).length;
        assert.equal(n, 1, `${b.name}.${p} tiene ${n} conectores`);
      }
    }
    // todo bloque de flujo (salvo la fuente) recibe al menos un conector
    for (const b of blocks) {
      if (['Source', 'ResourcePool'].includes(b.cls)) continue;
      assert.ok(conns.some((c) => c.to === b.name), `${b.name} no recibe entradas`);
    }
  });
}

test('AnyLogic: todas las distribuciones se traducen a Java', () => {
  const specs = [
    { type: 'constant', value: 3 },
    { type: 'uniform', min: 1, max: 2 },
    { type: 'triangular', min: 1, mode: 2, max: 4 },
    { type: 'pert', min: 1, mode: 2, max: 4 },
    { type: 'normal', mean: 5, sd: 1, truncate: { min: 0 } },
    { type: 'lognormal', mean: 5, sd: 1 },
    { type: 'exponential', mean: 5 },
    { type: 'gamma', mean: 5, sd: 2 },
    { type: 'erlang', mean: 5, k: 3 },
    { type: 'weibull', shape: 2, scale: 5 },
    { type: 'beta', alpha: 2, beta: 3, min: 0, max: 10 },
    { type: 'empirical', values: [1, 2, 3] },
  ];
  for (const s of specs) assert.doesNotMatch(distExpr(s), /^0\.0$/);
});

const hasJavac = spawnSync('javac', ['-version']).status === 0;

test('AnyLogic: el código Java incrustado compila y se ejecuta', { skip: !hasJavac && 'javac no disponible' }, async () => {
  for (const make of [exampleModel, interarrivalModel]) {
    const { java } = toAnyLogic(make());
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'alp-'));
    await fs.writeFile(path.join(dir, 'Main.java'), buildHarness(java, { steps: 300 }));
    execFileSync('javac', ['-nowarn', 'Main.java'], { cwd: dir, stdio: 'pipe' });
    const out = execFileSync('java', ['Main'], { cwd: dir, stdio: 'pipe' }).toString();
    assert.match(out, /TOTAL=/);
    assert.match(out, /RESULTADOS/);
  }
});
