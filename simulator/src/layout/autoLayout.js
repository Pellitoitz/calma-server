// Distribución automática de estaciones en planta (metros, plano XZ).
// Modos: 'line' (línea recta), 'u' (célula en U), 'l' (en L), 'manual' (posiciones del modelo).

export function computeLayout(model) {
  const stations = model.stations || [];
  const mode = model.settings?.layout || 'u';
  const spacing = model.settings?.spacing ?? 3.5;
  const positions = {};
  const n = stations.length;

  if (mode === 'manual') {
    stations.forEach((s, i) => {
      positions[s.id] = s.position && Number.isFinite(s.position.x)
        ? { x: s.position.x, z: s.position.z ?? 0, rot: s.position.rot ?? 0 }
        : { x: i * spacing, z: 0, rot: 0 };
    });
    return positions;
  }

  if (mode === 'line' || n <= 2) {
    stations.forEach((s, i) => (positions[s.id] = { x: (i - (n - 1) / 2) * spacing, z: 0, rot: 0 }));
    return positions;
  }

  if (mode === 'l') {
    const leg = Math.ceil(n / 2);
    stations.forEach((s, i) => {
      positions[s.id] = i < leg
        ? { x: i * spacing, z: 0, rot: 0 }
        : { x: (leg - 1) * spacing, z: (i - leg + 1) * spacing, rot: -Math.PI / 2 };
    });
    return center(positions);
  }

  // Célula en U: ida por un lado, vuelta por el otro, operarios en el interior.
  const half = Math.ceil(n / 2);
  const width = spacing * 1.6;
  stations.forEach((s, i) => {
    if (i < half) positions[s.id] = { x: i * spacing, z: -width / 2, rot: 0 };
    else positions[s.id] = { x: (n - 1 - i) * spacing, z: width / 2, rot: Math.PI };
  });
  return center(positions);
}

function center(positions) {
  const vals = Object.values(positions);
  const cx = (Math.min(...vals.map((p) => p.x)) + Math.max(...vals.map((p) => p.x))) / 2;
  const cz = (Math.min(...vals.map((p) => p.z)) + Math.max(...vals.map((p) => p.z))) / 2;
  for (const p of vals) {
    p.x -= cx;
    p.z -= cz;
  }
  return positions;
}

/** Punto donde se coloca el operario para trabajar (delante del puesto, lado interior). */
export function workSpot(pos, slot = 0) {
  const d = 0.9;
  const lateral = [0, 0.75, -0.75][slot % 3] + Math.floor(slot / 3) * 0.25;
  return {
    x: pos.x + Math.sin(pos.rot) * d + Math.cos(pos.rot) * lateral,
    z: pos.z + Math.cos(pos.rot) * d - Math.sin(pos.rot) * lateral,
  };
}

export function distance(a, b) {
  if (!a || !b) return 0;
  return Math.hypot(a.x - b.x, a.z - b.z);
}

/** Matriz de distancias de recorrido entre puestos de trabajo (metros). */
export function distanceMatrix(model, positions = computeLayout(model)) {
  const ids = model.stations.map((s) => s.id);
  const m = {};
  for (const a of ids) {
    m[a] = {};
    for (const b of ids) m[a][b] = distance(workSpot(positions[a]), workSpot(positions[b]));
  }
  return m;
}
