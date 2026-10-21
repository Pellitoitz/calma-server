// Utilidades mínimas de DOM y campos de formulario enlazados al modelo.

export function h(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'html') e.innerHTML = v;
    else if (v === true) e.setAttribute(k, '');
    else e.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    e.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

let keySeq = 0;
/** Clave estable para recuperar el foco tras volver a pintar. */
export function fieldKey(...parts) {
  return parts.join('|') || `k${keySeq++}`;
}

function wrap(label, input, help) {
  return h('label', { class: 'field' }, h('span', { class: 'field-label' }, label), input, help ? h('small', { class: 'help' }, help) : null);
}

/**
 * Campo numérico. `get`/`set` trabajan en unidades internas; `scale` convierte a
 * las unidades mostradas (p. ej. segundos → minutos).
 */
export function numField(label, { get, set, key, step = 'any', min, max, scale = 1, placeholder, help, unit, onCommit }) {
  const v = get();
  const input = h('input', {
    type: 'number',
    step,
    min,
    max,
    value: Number.isFinite(v) ? Number((v / scale).toPrecision(10)) : '',
    placeholder: placeholder !== undefined ? String(placeholder) : '',
    'data-key': key,
    inputmode: 'decimal',
  });
  input.addEventListener('input', () => {
    if (input.value === '') set(undefined);
    else {
      const n = Number(input.value);
      if (Number.isFinite(n)) set(n * scale);
    }
  });
  if (onCommit) input.addEventListener('change', onCommit);
  return wrap(unit ? `${label} (${unit})` : label, input, help);
}

export function textField(label, { get, set, key, placeholder, multiline, help, onCommit }) {
  const input = multiline
    ? h('textarea', { rows: 2, placeholder, 'data-key': key })
    : h('input', { type: 'text', placeholder, 'data-key': key });
  input.value = get() ?? '';
  input.addEventListener('input', () => set(input.value));
  if (onCommit) input.addEventListener('change', onCommit);
  return wrap(label, input, help);
}

export function selectField(label, { get, set, key, options, help, onCommit }) {
  const sel = h('select', { 'data-key': key }, options.map(([v, l]) => h('option', { value: v ?? '' }, l)));
  sel.value = get() ?? '';
  sel.addEventListener('change', () => {
    set(sel.value === '' ? null : sel.value);
    onCommit?.();
  });
  return wrap(label, sel, help);
}

export function checkField(label, { get, set, key, help, onCommit }) {
  const input = h('input', { type: 'checkbox', 'data-key': key });
  input.checked = Boolean(get());
  input.addEventListener('change', () => {
    set(input.checked);
    onCommit?.();
  });
  return h('label', { class: 'check' }, input, h('span', {}, label), help ? h('small', { class: 'help' }, help) : null);
}

export function uniqueId(prefix, existing) {
  const set = new Set(existing);
  let i = 1;
  while (set.has(`${prefix}${i}`)) i++;
  return `${prefix}${i}`;
}

export const pct = (v, d = 1) => (Number.isFinite(v) ? `${(v * 100).toFixed(d)} %` : '—');
export const fmtNum = (v, d = 2) => (Number.isFinite(v) ? (Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(d)) : '—');
export function fmtTime(s) {
  if (!Number.isFinite(s)) return '—';
  const a = Math.abs(s);
  if (a < 120) return `${s.toFixed(1)} s`;
  if (a < 7200) return `${(s / 60).toFixed(1)} min`;
  return `${(s / 3600).toFixed(2)} h`;
}
