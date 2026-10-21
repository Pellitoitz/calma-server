// Generador automático de celdas industriales 3D y reproductor sincronizado.
//
// A partir del modelo (estaciones, operaciones, máquinas, operarios y
// distribución en planta) se genera la geometría: bancos de trabajo, máquinas,
// bancos de prueba, hornos, mesas de embalaje, racks de buffer, cintas y
// operarios articulados. La traza de eventos de la simulación (réplica 1) mueve
// operarios (andar / trabajar / pausa), piezas (buffers, puestos, transporte) y
// estados de máquina (marcha / avería) en el mismo reloj simulado.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { computeLayout, workSpot } from '/src/layout/autoLayout.js';
import { typeDef } from '/src/stochastic/variability.js';

const OPERATOR_COLORS = [0x2a78d6, 0xeb6834, 0x1baf7a, 0xeda100, 0xe87ba4, 0x008300, 0x6250d6, 0xe34948];

function cssColor(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function label(text, { size = 28, color = '#ffffff', bg = 'rgba(20,20,20,0.72)' } = {}) {
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ depthTest: false }));
  sp.renderOrder = 10;
  const draw = (t) => {
    const c = document.createElement('canvas');
    const ctx = c.getContext('2d');
    ctx.font = `600 ${size}px system-ui, sans-serif`;
    c.width = Math.ceil(ctx.measureText(t).width) + 24;
    c.height = size + 16;
    ctx.font = `600 ${size}px system-ui, sans-serif`;
    ctx.fillStyle = bg;
    ctx.beginPath();
    ctx.roundRect(0, 0, c.width, c.height, 10);
    ctx.fill();
    ctx.fillStyle = color;
    ctx.textBaseline = 'middle';
    ctx.fillText(t, 12, c.height / 2 + 1);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    sp.material.map?.dispose();
    sp.material.map = tex;
    sp.material.needsUpdate = true;
    sp.scale.set((c.width / c.height) * 0.3, 0.3, 1);
  };
  draw(text);
  sp.userData.setText = draw;
  return sp;
}

const mat = (color, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.7, metalness: 0.1, ...extra });

function box(w, hgt, d, material, x = 0, y = 0, z = 0) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, hgt, d), material);
  m.position.set(x, y, z);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

// ------------------------------------------------------------------ geometría
function stationKind(model, st) {
  const ops = (st.operationIds || []).map((id) => model.operations.find((o) => o.id === id)).filter(Boolean);
  const types = ops.map((o) => o.type);
  if (types.includes('drying')) return 'oven';
  if (types.includes('auto_test')) return 'tester';
  if (types.includes('machining')) return 'machine';
  if (types.includes('packing')) return 'packing';
  if (types.includes('inspection')) return 'inspection';
  return 'bench';
}

function benchGeometry(group, accent, n) {
  const top = mat(0xb9b5a8);
  const leg = mat(0x55524d, { metalness: 0.5 });
  const width = Math.max(1.6, n * 0.8 + 0.4);
  group.add(box(width, 0.05, 0.8, top, 0, 0.9, 0));
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) group.add(box(0.05, 0.9, 0.05, leg, sx * (width / 2 - 0.08), 0.45, sz * 0.32));
  group.add(box(width, 0.6, 0.04, mat(0x7a776f), 0, 1.25, -0.38)); // panel trasero
  group.add(box(width, 0.04, 0.04, mat(accent, { emissive: accent, emissiveIntensity: 0.25 }), 0, 1.57, -0.38));
  group.add(box(0.5, 0.25, 0.3, mat(0x8c8a84), -width / 2 + 0.35, 1.05, -0.2)); // cajas de componentes
}

function buildStation(model, st, pos, scene, refs) {
  const g = new THREE.Group();
  g.position.set(pos.x, 0, pos.z);
  g.rotation.y = pos.rot;
  const kind = stationKind(model, st);
  const firstOp = model.operations.find((o) => o.id === st.operationIds?.[0]);
  const accent = new THREE.Color(typeDef(firstOp?.type).color).getHex();
  const n = Math.max(1, st.workplaces || 1);
  const slots = [];
  let light = null;

  if (kind === 'oven') {
    const len = Math.max(2, n * 0.45 + 0.6);
    g.add(box(len, 1.1, 1.0, mat(0x9a9890, { metalness: 0.4 }), 0, 0.85, -0.1));
    g.add(box(len - 0.2, 0.35, 0.02, mat(0x332e2a, { emissive: 0xff6a00, emissiveIntensity: 0.35 }), 0, 0.95, 0.41));
    g.add(box(0.3, 0.3, 0.3, mat(0x55524d), len / 2 - 0.2, 1.55, -0.2));
    for (let i = 0; i < n; i++) slots.push(new THREE.Vector3((i - (n - 1) / 2) * 0.42, 0.85, 0.48));
    light = box(0.12, 0.12, 0.12, mat(0x1baf7a, { emissive: 0x1baf7a, emissiveIntensity: 1 }), -len / 2 + 0.15, 1.5, 0.3);
  } else if (kind === 'machine' || kind === 'tester') {
    benchGeometry(g, accent, 1);
    const body = kind === 'machine' ? mat(0x3d6fa8, { metalness: 0.35 }) : mat(0x2f5d3a, { metalness: 0.35 });
    g.add(box(1.0, 1.0, 0.7, body, 0.55, 1.42, -0.05));
    g.add(box(0.6, 0.45, 0.02, mat(0x111111, { emissive: kind === 'tester' ? 0x1baf7a : 0x2a78d6, emissiveIntensity: 0.4 }), 0.55, 1.5, 0.31));
    light = box(0.1, 0.25, 0.1, mat(0x1baf7a, { emissive: 0x1baf7a, emissiveIntensity: 1 }), 0.55, 2.05, 0);
    for (let i = 0; i < n; i++) slots.push(new THREE.Vector3(-0.3 + [0, 0.75, -0.75][i % 3] * 0.6, 0.98, 0.1));
  } else {
    benchGeometry(g, accent, n);
    if (kind === 'packing') for (let i = 0; i < 3; i++) g.add(box(0.4, 0.3, 0.4, mat(0xc49a6c), 0.9 + i * 0.05, 0.15 + i * 0.3, -0.2));
    if (kind === 'inspection') g.add(box(0.5, 0.02, 0.4, mat(0xffffff, { emissive: 0xffffff, emissiveIntensity: 0.6 }), 0, 1.5, -0.1));
    for (let i = 0; i < n; i++) slots.push(new THREE.Vector3([0, 0.75, -0.75][i % 3] + Math.floor(i / 3) * 0.25, 0.98, 0.1));
  }

  // rack de buffer de entrada (lado aguas arriba)
  const cap = Math.max(0, st.bufferCapacity ?? 2);
  const bufferSlots = [];
  if (cap > 0) {
    const levels = Math.min(4, Math.ceil(cap / 3));
    const perLevel = Math.ceil(cap / levels);
    const rx = -(kind === 'oven' ? Math.max(2, n * 0.45 + 0.6) / 2 + 0.6 : 1.55);
    const rack = mat(0xe0a526, { metalness: 0.4 });
    for (const sz of [-0.25, 0.25]) for (const sx of [-0.22, 0.22]) g.add(box(0.04, 0.5 + levels * 0.35, 0.04, rack, rx + sx, (0.5 + levels * 0.35) / 2, sz));
    for (let l = 0; l < levels; l++) {
      g.add(box(0.5, 0.03, 0.55, mat(0x8a8780), rx, 0.5 + l * 0.35, 0));
      for (let k = 0; k < perLevel && bufferSlots.length < cap; k++) bufferSlots.push(new THREE.Vector3(rx, 0.6 + l * 0.35, -0.18 + (k % 3) * 0.18));
    }
  }

  const lbl = label(st.name || st.id);
  lbl.position.set(0, 2.45, 0);
  g.add(lbl);
  const status = label('—', { size: 22, bg: 'rgba(40,40,40,0.6)' });
  status.position.set(0, 2.15, 0);
  g.add(status);

  if (light) g.add(light);
  scene.add(g);
  refs.stations.set(st.id, { group: g, slots, bufferSlots, light, kind, status, pos, buffer: [], workplaces: new Map() });
}

function buildConveyor(scene, a, b) {
  const pa = new THREE.Vector3(a.x, 0, a.z);
  const pb = new THREE.Vector3(b.x, 0, b.z);
  const len = pa.distanceTo(pb);
  if (len < 0.1) return;
  const belt = box(len, 0.06, 0.45, mat(0x2b2b2b), 0, 0.75, 0);
  const g = new THREE.Group();
  g.add(belt);
  for (const s of [-1, 1]) g.add(box(len, 0.08, 0.04, mat(0x9a9890, { metalness: 0.5 }), 0, 0.8, s * 0.24));
  for (let x = -len / 2 + 0.3; x < len / 2; x += 1) for (const s of [-1, 1]) g.add(box(0.04, 0.75, 0.04, mat(0x55524d), x, 0.375, s * 0.2));
  g.position.copy(pa.clone().add(pb).multiplyScalar(0.5));
  g.rotation.y = -Math.atan2(pb.z - pa.z, pb.x - pa.x);
  scene.add(g);
}

function buildOperator(color, name) {
  const g = new THREE.Group();
  const shirt = mat(color);
  const pants = mat(0x2d3440);
  const skin = mat(0xe0b48f);
  const limb = (r, l, m) => {
    const geo = new THREE.CylinderGeometry(r, r * 0.9, l, 10);
    geo.translate(0, -l / 2, 0);
    const mesh = new THREE.Mesh(geo, m);
    mesh.castShadow = true;
    return mesh;
  };
  const hipL = new THREE.Group();
  hipL.position.set(-0.1, 0.9, 0);
  hipL.add(limb(0.065, 0.88, pants));
  const hipR = hipL.clone();
  hipR.position.x = 0.1;
  const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.18, 0.42, 6, 12), shirt);
  torso.position.y = 1.22;
  torso.castShadow = true;
  const vest = new THREE.Mesh(new THREE.CapsuleGeometry(0.185, 0.2, 6, 12), mat(0xd7ff3a, { emissive: 0x334400, emissiveIntensity: 0.3 }));
  vest.position.y = 1.3;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.12, 16, 12), skin);
  head.position.y = 1.62;
  head.castShadow = true;
  const cap = new THREE.Mesh(new THREE.SphereGeometry(0.13, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2), mat(color));
  cap.position.y = 1.64;
  const shL = new THREE.Group();
  shL.position.set(-0.25, 1.45, 0);
  shL.add(limb(0.05, 0.62, shirt));
  const shR = shL.clone();
  shR.position.x = 0.25;
  g.add(hipL, hipR, torso, vest, head, cap, shL, shR);
  const tag = label(name, { size: 24 });
  tag.position.y = 2.0;
  g.add(tag);
  g.userData = { hipL, hipR, shL, shR, head, tag, materials: [shirt, pants, skin] };
  return g;
}

// ------------------------------------------------------------------ visor
export class CellViewer {
  constructor(container, { onTime } = {}) {
    this.container = container;
    this.onTime = onTime;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    container.appendChild(this.renderer.domElement);
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 300);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = Math.PI * 0.49;
    this.clock = new THREE.Clock();
    this.playing = false;
    this.speed = 20;
    this.t = 0;
    this._resize = () => this.resize();
    window.addEventListener('resize', this._resize);
    this.resize();
    this._loop = () => {
      if (this.disposed) return;
      requestAnimationFrame(this._loop);
      this.frame();
    };
    requestAnimationFrame(this._loop);
  }

  resize() {
    const w = this.container.clientWidth || 600;
    const hgt = this.container.clientHeight || 420;
    this.renderer.setSize(w, hgt);
    this.camera.aspect = w / hgt;
    this.camera.updateProjectionMatrix();
  }

  dispose() {
    this.disposed = true;
    window.removeEventListener('resize', this._resize);
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }

  /** Genera la celda a partir del modelo y la posición de las estaciones. */
  build(model, { layout, trace } = {}) {
    this.model = model;
    this.positions = layout || computeLayout(model);
    const scene = (this.scene = new THREE.Scene());
    const bg = cssColor('--surface-2', '#eceae4');
    scene.background = new THREE.Color(bg);
    scene.fog = new THREE.Fog(bg, 30, 90);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8a80, 1.1));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(8, 14, 6);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -20, right: 20, top: 20, bottom: -20 });
    scene.add(sun);

    const vals = Object.values(this.positions);
    const span = vals.length ? Math.max(6, ...vals.map((p) => Math.hypot(p.x, p.z))) : 6;
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(span * 4 + 10, span * 4 + 10), mat(0xc9c6bd, { roughness: 0.95 }));
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    scene.add(floor);
    const grid = new THREE.GridHelper(span * 4 + 10, Math.round(span * 4 + 10), 0x9a978e, 0xb3b0a7);
    grid.position.y = 0.002;
    scene.add(grid);
    // marcas de pasillo de seguridad
    const lane = new THREE.Mesh(new THREE.RingGeometry(span + 2.2, span + 2.35, 64), new THREE.MeshBasicMaterial({ color: 0xe0b000 }));
    lane.rotation.x = -Math.PI / 2;
    lane.position.y = 0.004;
    scene.add(lane);

    this.refs = { stations: new Map(), operators: new Map(), entities: new Map() };
    model.stations.forEach((st) => buildStation(model, st, this.positions[st.id], scene, this.refs));
    model.stations.forEach((st, i) => {
      const next = model.stations[i + 1];
      if (st.transportOperationId && next) {
        const a = this.positions[st.id];
        const b = this.positions[next.id];
        buildConveyor(scene, { x: a.x, z: a.z }, { x: b.x, z: b.z });
      }
    });
    (model.operators || []).forEach((o, i) => {
      const fig = buildOperator(OPERATOR_COLORS[i % OPERATOR_COLORS.length], o.name || o.id);
      const home = o.homeStationId || model.stations.find((s) => (s.operatorIds || []).includes(o.id))?.id || model.stations[0]?.id;
      const spot = workSpot(this.positions[home] || { x: 0, z: 0, rot: 0 });
      fig.position.set(spot.x, 0, spot.z);
      scene.add(fig);
      this.refs.operators.set(o.id, { fig, home, name: o.name || o.id, state: 'idle', anim: null });
    });
    this.productColors = new Map((model.products || []).map((p) => [p.id, new THREE.Color(p.color || '#2a78d6')]));

    this.camera.position.set(span * 0.6, span * 0.8 + 3, span * 1.1 + 3);
    this.controls.target.set(0, 0.8, 0);
    this.controls.update();

    this.setTrace(trace);
  }

  setTrace(trace) {
    this.trace = trace && trace.length ? trace : null;
    this.duration = this.trace ? this.trace[this.trace.length - 1].t : 0;
    this.reset();
  }

  reset() {
    this.cursor = 0;
    this.t = 0;
    this.completed = 0;
    this.scrapped = 0;
    for (const e of this.refs.entities.values()) this.scene.remove(e.mesh);
    this.refs.entities.clear();
    for (const s of this.refs.stations.values()) {
      s.buffer = [];
      s.workplaces.clear();
      s.down = false;
      s.active = 0;
      this._setLight(s, 'idle');
    }
    for (const o of this.refs.operators.values()) {
      o.anim = null;
      o.state = 'idle';
      o.station = o.home;
      o.slot = 0;
      const spot = workSpot(this.positions[o.home] || { x: 0, z: 0, rot: 0 });
      o.fig.position.set(spot.x, 0, spot.z);
      o.fig.userData.materials.forEach((m) => ((m.transparent = false), (m.opacity = 1)));
    }
  }

  _setLight(s, state) {
    if (!s.light) return;
    const c = state === 'down' ? 0xe34948 : state === 'busy' ? 0x1baf7a : 0xeda100;
    s.light.material.color.setHex(c);
    s.light.material.emissive.setHex(c);
  }

  _entity(id, productId) {
    let e = this.refs.entities.get(id);
    if (!e) {
      const color = this.productColors.get(productId) || new THREE.Color('#2a78d6');
      const mesh = box(0.28, 0.14, 0.2, mat(color, { metalness: 0.3 }));
      mesh.add(box(0.2, 0.02, 0.12, mat(0x1d5f2a), 0, 0.08, 0));
      this.scene.add(mesh);
      e = { mesh, where: null };
      this.refs.entities.set(id, e);
    }
    return e;
  }

  _local(s, v) {
    return s.group.localToWorld(v.clone());
  }

  _layoutBuffer(s) {
    s.buffer.forEach((id, i) => {
      const e = this.refs.entities.get(id);
      if (!e) return;
      const slot = s.bufferSlots[Math.min(i, s.bufferSlots.length - 1)] || new THREE.Vector3(-1.5, 0.3, 0);
      e.mesh.position.copy(this._local(s, slot));
      e.mesh.position.y += Math.max(0, i - s.bufferSlots.length + 1) * 0.15;
      e.anim = null;
    });
  }

  /** Aplica un evento de la traza al estado de la escena. */
  _apply(ev) {
    const R = this.refs;
    switch (ev.k) {
      case 'arr': {
        const s = R.stations.get(ev.st);
        const e = this._entity(ev.e, ev.p);
        e.anim = null;
        if (s && !s.buffer.includes(ev.e)) s.buffer.push(ev.e);
        if (s) this._layoutBuffer(s);
        break;
      }
      case 'start': {
        const s = R.stations.get(ev.st);
        if (!s) break;
        s.buffer = s.buffer.filter((x) => x !== ev.e);
        this._layoutBuffer(s);
        s.workplaces.set(ev.wp, ev.e);
        const e = R.entities.get(ev.e);
        if (e) {
          e.anim = null;
          e.mesh.position.copy(this._local(s, s.slots[ev.wp] || s.slots[0] || new THREE.Vector3(0, 1, 0)));
        }
        break;
      }
      case 'leave': {
        const s = R.stations.get(ev.st);
        if (s) s.workplaces.delete(ev.wp);
        break;
      }
      case 'op': {
        const s = R.stations.get(ev.st);
        if (ev.ty === 'transport' && ev.e) {
          const idx = this.model.stations.findIndex((x) => x.id === ev.st);
          const next = this.model.stations[idx + 1];
          const ns = next && R.stations.get(next.id);
          const e = R.entities.get(ev.e);
          if (e && s && ns) {
            const from = this._local(s, s.slots[0] || new THREE.Vector3()).setY(0.85);
            const to = this._local(ns, ns.bufferSlots[0] || ns.slots[0] || new THREE.Vector3()).setY(0.85);
            e.anim = { from, to, t0: ev.t, d: Math.max(0.01, ev.d) };
          }
        }
        if (ev.o) {
          const o = R.operators.get(ev.o);
          if (o) {
            o.state = ev.s ? 'setup' : 'work';
            o.opType = ev.ty;
            o.station = ev.st;
            o.slot = Math.max(0, ev.wp);
            o.until = ev.t + ev.d;
            o.anim = null;
            const spot = workSpot(this.positions[ev.st], o.slot);
            o.fig.position.set(spot.x, 0, spot.z);
            o.fig.rotation.y = this.positions[ev.st].rot + Math.PI;
          }
        }
        if (ev.m && s) {
          s.busyUntil = ev.t + ev.d;
          if (!s.down) this._setLight(s, 'busy');
        }
        if (s) s.lastOp = { ty: ev.ty, until: ev.t + ev.d };
        break;
      }
      case 'walk': {
        const o = R.operators.get(ev.o);
        if (!o) break;
        const a = workSpot(this.positions[ev.from] || { x: 0, z: 0, rot: 0 }, o.station === ev.from ? o.slot : 0);
        const b = workSpot(this.positions[ev.to] || { x: 0, z: 0, rot: 0 });
        o.state = 'walk';
        o.anim = { from: new THREE.Vector3(a.x, 0, a.z), to: new THREE.Vector3(b.x, 0, b.z), t0: ev.t, d: Math.max(0.01, ev.d) };
        o.station = ev.to;
        o.slot = 0;
        break;
      }
      case 'brk': {
        const o = R.operators.get(ev.o);
        if (o) {
          o.state = 'break';
          o.anim = null;
          o.fig.userData.materials.forEach((m) => ((m.transparent = true), (m.opacity = 0.35)));
        }
        break;
      }
      case 'brkEnd': {
        const o = R.operators.get(ev.o);
        if (o) {
          o.state = 'idle';
          o.fig.userData.materials.forEach((m) => ((m.transparent = false), (m.opacity = 1)));
        }
        break;
      }
      case 'down': {
        const s = R.stations.get(ev.st);
        if (s) {
          s.down = true;
          this._setLight(s, 'down');
        }
        break;
      }
      case 'up': {
        const s = R.stations.get(ev.st);
        if (s) {
          s.down = false;
          this._setLight(s, 'busy');
        }
        break;
      }
      case 'exit': {
        const e = R.entities.get(ev.e);
        if (e) {
          this.scene.remove(e.mesh);
          R.entities.delete(ev.e);
        }
        if (ev.s === 'completed') this.completed++;
        else this.scrapped++;
        break;
      }
      default:
    }
  }

  seek(t) {
    if (!this.trace) return;
    if (t < this.t) this.reset();
    while (this.cursor < this.trace.length && this.trace[this.cursor].t <= t) this._apply(this.trace[this.cursor++]);
    this.t = t;
  }

  play() {
    this.playing = true;
  }

  pause() {
    this.playing = false;
  }

  frame() {
    const dt = Math.min(0.1, this.clock.getDelta());
    if (this.playing && this.trace) {
      const next = Math.min(this.duration, this.t + dt * this.speed);
      this.seek(next);
      if (next >= this.duration) this.playing = false;
    }
    this._animate();
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.onTime?.(this.t, this);
  }

  _animate() {
    const t = this.t;
    const wall = performance.now() / 1000;
    for (const o of this.refs.operators.values()) {
      const u = o.fig.userData;
      if (o.state === 'walk' && o.anim) {
        const k = Math.min(1, (t - o.anim.t0) / o.anim.d);
        o.fig.position.lerpVectors(o.anim.from, o.anim.to, k);
        const dir = o.anim.to.clone().sub(o.anim.from);
        if (dir.lengthSq() > 1e-6) o.fig.rotation.y = Math.atan2(dir.x, dir.z);
        const sw = Math.sin(t * 6) * 0.6;
        u.hipL.rotation.x = sw;
        u.hipR.rotation.x = -sw;
        u.shL.rotation.x = -sw * 0.7;
        u.shR.rotation.x = sw * 0.7;
        if (k >= 1) o.state = 'idle';
      } else if ((o.state === 'work' || o.state === 'setup') && t < o.until) {
        u.hipL.rotation.x = u.hipR.rotation.x = 0;
        const fast = ['screwing', 'wiring'].includes(o.opType) ? 9 : o.opType === 'inspection' ? 2 : 5;
        const amp = o.state === 'setup' ? 0.9 : o.opType === 'inspection' ? 0.15 : 0.35;
        u.shL.rotation.x = -0.9 + Math.sin(wall * fast) * amp;
        u.shR.rotation.x = -0.9 - Math.sin(wall * fast + 1) * amp;
        u.head.rotation.x = o.opType === 'inspection' ? 0.35 + Math.sin(wall * 1.5) * 0.15 : 0.25;
      } else {
        u.hipL.rotation.x = u.hipR.rotation.x = 0;
        u.shL.rotation.x = u.shR.rotation.x = 0;
        u.head.rotation.x = 0;
        if (o.state === 'work' || o.state === 'setup') o.state = 'idle';
      }
      const stLbl = o.state === 'break' ? 'pausa' : o.state === 'walk' ? 'andando' : o.state === 'idle' ? 'libre' : typeDef(o.opType).label.toLowerCase();
      if (u.tag.userData.last !== stLbl) {
        u.tag.userData.last = stLbl;
        u.tag.userData.setText(`${o.name} · ${stLbl}`);
      }
    }
    for (const e of this.refs.entities.values()) {
      if (!e.anim) continue;
      const k = Math.min(1, (t - e.anim.t0) / e.anim.d);
      e.mesh.position.lerpVectors(e.anim.from, e.anim.to, k);
    }
    for (const s of this.refs.stations.values()) {
      let text;
      if (s.down) text = 'AVERÍA';
      else if (s.lastOp && t < s.lastOp.until) text = typeDef(s.lastOp.ty).label;
      else if (s.workplaces.size) text = 'esperando';
      else text = 'sin material';
      text += ` · buffer ${s.buffer.length}`;
      if (s.light && !s.down && !(s.busyUntil > t)) this._setLight(s, 'idle');
      if (s._last !== text) {
        s._last = text;
        s.status.userData.setText(text);
      }
    }
  }
}
