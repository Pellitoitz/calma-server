// Gráficos SVG ligeros con tooltip. Los colores salen de variables CSS (modo claro/oscuro).

const NS = 'http://www.w3.org/2000/svg';

function el(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}

let tipEl = null;
export function installTooltip() {
  if (tipEl) return;
  tipEl = document.createElement('div');
  tipEl.className = 'chart-tip';
  document.body.appendChild(tipEl);
  document.addEventListener('pointermove', (ev) => {
    const t = ev.target.closest?.('[data-tip]');
    if (!t) {
      tipEl.style.opacity = 0;
      return;
    }
    tipEl.innerHTML = t.getAttribute('data-tip');
    tipEl.style.opacity = 1;
    const x = Math.min(window.innerWidth - tipEl.offsetWidth - 8, ev.clientX + 14);
    const y = Math.max(8, ev.clientY - tipEl.offsetHeight - 10);
    tipEl.style.transform = `translate(${x}px, ${y}px)`;
  });
}

function niceTicks(min, max, count = 5) {
  if (!(max > min)) {
    max = min + 1;
  }
  const span = max - min;
  const step0 = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) || 10 * mag;
  const start = Math.floor(min / step) * step;
  const ticks = [];
  for (let v = start; v <= max + step * 0.001; v += step) ticks.push(Number(v.toPrecision(12)));
  return ticks;
}

function frame(width, height, m) {
  const svg = el('svg', { viewBox: `0 0 ${width} ${height}`, class: 'chart', role: 'img' });
  return { svg, iw: width - m.l - m.r, ih: height - m.t - m.b, g: el('g', { transform: `translate(${m.l},${m.t})` }, svg) };
}

function yAxis(g, ticks, y, iw, fmt) {
  for (const t of ticks) {
    el('line', { x1: 0, x2: iw, y1: y(t), y2: y(t), class: 'grid' }, g);
    el('text', { x: -6, y: y(t) + 4, class: 'tick', 'text-anchor': 'end' }, g).textContent = fmt(t);
  }
}

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

/** Serie temporal con banda de confianza y línea de referencia opcional. */
export function lineBand(points, { width = 640, height = 220, ref, refLabel, xFmt = (v) => v, yFmt = (v) => v, yLabel = '', name = 'Media' } = {}) {
  const m = { l: 48, r: 16, t: 14, b: 30 };
  const { svg, g, iw, ih } = frame(width, height, m);
  if (!points.length) return svg;
  const xs = points.map((p) => p.x);
  const ymax = Math.max(...points.map((p) => p.high ?? p.y), ref ?? 0) * 1.1 || 1;
  const ymin = Math.min(0, ...points.map((p) => p.low ?? p.y));
  const x = (v) => ((v - xs[0]) / (xs[xs.length - 1] - xs[0] || 1)) * iw;
  const y = (v) => ih - ((v - ymin) / (ymax - ymin)) * ih;
  yAxis(g, niceTicks(ymin, ymax, 4), y, iw, yFmt);
  if (points[0].low !== undefined) {
    const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(p.x)},${y(p.high)}`).join('') + [...points].reverse().map((p) => `L${x(p.x)},${y(p.low)}`).join('') + 'Z';
    el('path', { d, class: 'band' }, g);
  }
  el('path', { d: points.map((p, i) => `${i ? 'L' : 'M'}${x(p.x)},${y(p.y)}`).join(''), class: 'line' }, g);
  if (ref) {
    el('line', { x1: 0, x2: iw, y1: y(ref), y2: y(ref), class: 'ref' }, g);
    el('text', { x: iw - 4, y: y(ref) - 5, class: 'tick', 'text-anchor': 'end' }, g).textContent = refLabel || `${ref}`;
  }
  const step = Math.max(1, Math.ceil(points.length / 8));
  points.forEach((p, i) => {
    if (i % step === 0) el('text', { x: x(p.x), y: ih + 18, class: 'tick', 'text-anchor': 'middle' }, g).textContent = xFmt(p.x);
    const w = iw / Math.max(1, points.length - 1);
    const tip = `<b>${esc(xFmt(p.x))}</b><br>${esc(name)}: ${esc(yFmt(p.y))}${p.low !== undefined ? `<br>IC: ${esc(yFmt(p.low))} – ${esc(yFmt(p.high))}` : ''}`;
    el('rect', { x: x(p.x) - w / 2, y: 0, width: w, height: ih, class: 'hit', 'data-tip': tip }, g);
  });
  if (yLabel) el('text', { x: -m.l + 4, y: -4, class: 'axis-label' }, g).textContent = yLabel;
  return svg;
}

/** Histograma (barras con hueco de 2px y extremo redondeado). */
export function histogramChart(hist, { width = 640, height = 200, xFmt = (v) => v.toFixed(0), yLabel = 'Frecuencia', markers = [] } = {}) {
  const m = { l: 44, r: 12, t: 14, b: 30 };
  const { svg, g, iw, ih } = frame(width, height, m);
  if (!hist?.counts?.length) return svg;
  const maxC = Math.max(...hist.counts) || 1;
  const n = hist.counts.length;
  const bw = iw / n;
  const y = (v) => ih - (v / maxC) * ih;
  yAxis(g, niceTicks(0, maxC, 4), y, iw, (v) => v);
  const lo = hist.edges[0];
  const hi = hist.edges[n];
  const xv = (v) => ((v - lo) / (hi - lo)) * iw;
  hist.counts.forEach((c, i) => {
    const h = ih - y(c);
    const tip = `${esc(xFmt(hist.edges[i]))} – ${esc(xFmt(hist.edges[i + 1]))}<br>${c} obs. (${((c / hist.n) * 100).toFixed(1)} %)`;
    if (h > 0) el('path', { d: roundedTop(i * bw + 1, ih - h, Math.max(1, bw - 2), h, Math.min(4, bw / 2 - 1)), class: 'bar' }, g);
    el('rect', { x: i * bw, y: 0, width: bw, height: ih, class: 'hit', 'data-tip': tip }, g);
  });
  for (const mk of markers) {
    if (!(mk.value >= lo && mk.value <= hi)) continue;
    el('line', { x1: xv(mk.value), x2: xv(mk.value), y1: 0, y2: ih, class: 'ref' }, g);
    el('text', { x: xv(mk.value) + 4, y: 10, class: 'tick' }, g).textContent = mk.label;
  }
  for (const t of niceTicks(lo, hi, 6)) if (t >= lo && t <= hi) el('text', { x: xv(t), y: ih + 18, class: 'tick', 'text-anchor': 'middle' }, g).textContent = xFmt(t);
  if (yLabel) el('text', { x: -m.l + 4, y: -4, class: 'axis-label' }, g).textContent = yLabel;
  return svg;
}

function roundedTop(x, y, w, h, r) {
  r = Math.max(0, Math.min(r, h, w / 2));
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

/** Barras horizontales apiladas al 100 % (estados de estaciones, operarios...). */
export function stackedBars(rows, keys, { width = 640, rowH = 26, fmt = (v) => `${(v * 100).toFixed(1)} %` } = {}) {
  const m = { l: 150, r: 12, t: 4, b: 4 };
  const height = m.t + m.b + rows.length * rowH;
  const { svg, g, iw } = frame(width, height, m);
  rows.forEach((row, i) => {
    const yy = i * rowH + 4;
    const label = el('text', { x: -8, y: yy + rowH / 2 + 1, class: 'row-label', 'text-anchor': 'end' }, g);
    label.textContent = row.label.length > 22 ? `${row.label.slice(0, 21)}…` : row.label;
    const total = keys.reduce((a, k) => a + (row.parts[k.key] || 0), 0) || 1;
    let acc = 0;
    for (const k of keys) {
      const v = row.parts[k.key] || 0;
      if (v <= 0) continue;
      const w = (v / total) * iw;
      el('rect', {
        x: (acc / total) * iw,
        y: yy,
        width: Math.max(0, w - 2),
        height: rowH - 8,
        rx: 3,
        style: `fill:${k.color}`,
        'data-tip': `<b>${esc(row.label)}</b><br>${esc(k.label)}: ${esc(fmt(v))}`,
      }, g);
      acc += v;
    }
    if (row.marker) el('text', { x: iw + 2, y: yy + rowH / 2 + 1, class: 'tick' }, g).textContent = row.marker;
  });
  return svg;
}

/** Barras horizontales divergentes con intervalo de confianza (tornado). */
export function tornado(items, { width = 640, rowH = 26, fmt = (v) => v.toFixed(2), unit = '' } = {}) {
  const m = { l: 230, r: 60, t: 6, b: 24 };
  const height = m.t + m.b + items.length * rowH;
  const { svg, g, iw, ih } = frame(width, height, m);
  const ext = Math.max(1e-9, ...items.flatMap((i) => [Math.abs(i.low), Math.abs(i.high), Math.abs(i.value)]));
  const x = (v) => iw / 2 + (v / ext) * (iw / 2);
  el('line', { x1: x(0), x2: x(0), y1: 0, y2: ih, class: 'axis' }, g);
  items.forEach((it, i) => {
    const yy = i * rowH + 4;
    const label = el('text', { x: -8, y: yy + rowH / 2 + 1, class: 'row-label', 'text-anchor': 'end' }, g);
    label.textContent = it.label.length > 34 ? `${it.label.slice(0, 33)}…` : it.label;
    const x0 = Math.min(x(0), x(it.value));
    const w = Math.abs(x(it.value) - x(0));
    el('rect', {
      x: x0,
      y: yy + 3,
      width: Math.max(1, w),
      height: rowH - 14,
      rx: 3,
      class: it.value >= 0 ? (it.good === false ? 'bar-neg' : 'bar') : it.good === true ? 'bar' : 'bar-neg',
      opacity: it.significant ? 1 : 0.45,
    }, g);
    el('line', { x1: x(it.low), x2: x(it.high), y1: yy + rowH / 2 - 2, y2: yy + rowH / 2 - 2, class: 'whisker' }, g);
    el('text', { x: iw + 4, y: yy + rowH / 2 + 1, class: 'tick' }, g).textContent = `${it.value >= 0 ? '+' : ''}${fmt(it.value)}${unit}`;
    el('rect', {
      x: -m.l,
      y: yy,
      width: iw + m.l + m.r,
      height: rowH,
      class: 'hit',
      'data-tip': `<b>${esc(it.label)}</b><br>Efecto: ${esc(fmt(it.value))}${esc(unit)}<br>IC: ${esc(fmt(it.low))} – ${esc(fmt(it.high))}<br>${it.significant ? 'Significativo' : 'No significativo'}`,
    }, g);
  });
  return svg;
}

/** Mini histograma de una distribución (vista previa en el editor). */
export function sparkHistogram(values, { width = 220, height = 48 } = {}) {
  const svg = el('svg', { viewBox: `0 0 ${width} ${height}`, class: 'spark' });
  if (!values.length) return svg;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const n = 24;
  const counts = new Array(n).fill(0);
  const span = hi - lo || 1;
  for (const v of values) counts[Math.min(n - 1, Math.floor(((v - lo) / span) * n))]++;
  const max = Math.max(...counts);
  const bw = width / n;
  counts.forEach((c, i) => {
    const h = (c / max) * (height - 12);
    if (h > 0) el('path', { d: roundedTop(i * bw + 1, height - 12 - h, bw - 2, h, 2), class: 'bar' }, svg);
  });
  const f = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1));
  el('text', { x: 0, y: height - 1, class: 'tick' }, svg).textContent = f(lo);
  el('text', { x: width, y: height - 1, class: 'tick', 'text-anchor': 'end' }, svg).textContent = f(hi);
  return svg;
}
