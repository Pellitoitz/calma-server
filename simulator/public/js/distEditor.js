// Editor de distribuciones de probabilidad: tipo, parámetros, truncado, entrada
// rápida por media + CV, vista previa por muestreo y ajuste a datos medidos.

import { DISTRIBUTIONS, sample, moments, validate, fromMeanCv } from '/src/stochastic/distributions.js';
import { RandomStream } from '/src/stochastic/rng.js';
import { fitDistributions, parseSamples } from '/src/stochastic/fitting.js';
import { h, fmtNum } from './dom.js';
import { sparkHistogram } from './charts.js';

const UNITS = { s: 1, min: 60, h: 3600, 'm/s': 1, '': 1 };
const SHAPE_KEYS = new Set(['k', 'shape', 'lambda', 'alpha', 'beta']);

function toDisplay(spec, scale) {
  const out = { ...spec };
  for (const [k, v] of Object.entries(spec)) {
    if (SHAPE_KEYS.has(k) || k === 'type') continue;
    if (typeof v === 'number') out[k] = v / scale;
    if (Array.isArray(v)) out[k] = v.map((x) => x / scale);
  }
  if (spec.truncate) out.truncate = { min: spec.truncate.min / scale, max: spec.truncate.max / scale };
  return out;
}

function fromDisplayValue(k, v, scale) {
  return SHAPE_KEYS.has(k) ? v : v * scale;
}

/**
 * @param {object} o
 * @param {string} o.label
 * @param {() => object} o.get
 * @param {(spec:object) => void} o.set
 * @param {string} [o.unit='s']
 * @param {string} o.key  clave única para foco
 * @param {() => void} o.onChange
 */
export function distEditor({ label, get, set, unit = 's', key, onChange, compact = false }) {
  const scale = UNITS[unit] ?? 1;
  const root = h('div', { class: 'dist-editor' });

  const render = () => {
    root.replaceChildren();
    const spec = get() || { type: 'constant', value: 0 };
    const disp = toDisplay(spec, scale);
    const def = DISTRIBUTIONS[spec.type] || DISTRIBUTIONS.constant;

    const typeSel = h(
      'select',
      { 'data-key': `${key}|type` },
      Object.entries(DISTRIBUTIONS).map(([k, d]) => h('option', { value: k }, d.label)),
    );
    typeSel.value = spec.type;
    typeSel.addEventListener('change', () => {
      const { mean, sd } = safeMoments(spec);
      let next;
      try {
        next = typeSel.value === 'empirical'
          ? { type: 'empirical', values: [mean] }
          : typeSel.value === 'beta'
            ? { type: 'beta', alpha: 2, beta: 2, min: Math.max(0, mean - 2 * sd), max: mean + 2 * sd }
            : fromMeanCv(typeSel.value, mean || 1, mean ? sd / mean || 0.1 : 0.1);
      } catch {
        next = { type: typeSel.value };
      }
      set(next);
      onChange?.();
      render();
    });

    const params = h('div', { class: 'dist-params' });
    for (const p of def.params) {
      if (p.kind === 'list') {
        const ta = h('textarea', { rows: 2, 'data-key': `${key}|${p.key}`, placeholder: 'valores separados por espacios o comas' });
        ta.value = (disp[p.key] || []).map((v) => Number(v.toPrecision(6))).join(' ');
        ta.addEventListener('input', () => {
          const vals = parseSamples(ta.value).map((v) => v * scale);
          set({ ...get(), [p.key]: vals });
          refresh();
        });
        ta.addEventListener('change', () => onChange?.());
        params.appendChild(h('label', { class: 'field wide' }, h('span', { class: 'field-label' }, p.label), ta));
        continue;
      }
      const inp = h('input', { type: 'number', step: 'any', 'data-key': `${key}|${p.key}`, inputmode: 'decimal' });
      const v = disp[p.key] ?? p.default;
      inp.value = Number.isFinite(v) ? Number(v.toPrecision(8)) : '';
      inp.addEventListener('input', () => {
        const n = Number(inp.value);
        const cur = { ...get() };
        if (inp.value === '' && p.default !== undefined) delete cur[p.key];
        else if (Number.isFinite(n)) cur[p.key] = fromDisplayValue(p.key, n, scale);
        set(cur);
        refresh();
      });
      inp.addEventListener('change', () => onChange?.());
      params.appendChild(h('label', { class: 'field' }, h('span', { class: 'field-label' }, p.label), inp));
    }

    // truncado opcional
    if (!compact && spec.type !== 'constant' && spec.type !== 'empirical') {
      for (const bound of ['min', 'max']) {
        const inp = h('input', { type: 'number', step: 'any', 'data-key': `${key}|t${bound}`, placeholder: '—' });
        const tv = spec.truncate?.[bound];
        inp.value = Number.isFinite(tv) ? Number((tv / scale).toPrecision(8)) : '';
        inp.addEventListener('input', () => {
          const cur = { ...get(), truncate: { ...(get().truncate || {}) } };
          const n = Number(inp.value);
          if (inp.value === '' || !Number.isFinite(n)) delete cur.truncate[bound];
          else cur.truncate[bound] = n * scale;
          if (!Number.isFinite(cur.truncate.min) && !Number.isFinite(cur.truncate.max)) delete cur.truncate;
          set(cur);
          refresh();
        });
        inp.addEventListener('change', () => onChange?.());
        params.appendChild(h('label', { class: 'field' }, h('span', { class: 'field-label' }, `Truncar ${bound === 'min' ? 'mín.' : 'máx.'}`), inp));
      }
    }

    const info = h('div', { class: 'dist-info' });
    const spark = h('div', { class: 'dist-spark' });

    const refresh = () => {
      const s = get();
      const errs = validate(s);
      info.replaceChildren();
      spark.replaceChildren();
      if (errs.length) {
        info.appendChild(h('span', { class: 'error' }, errs.join(' · ')));
        return;
      }
      const { mean, sd } = moments(s);
      const u = unit ? ` ${unit}` : '';
      info.append(
        h('span', {}, `μ = ${fmtNum(mean / scale)}${u}`),
        h('span', {}, `σ = ${fmtNum(sd / scale)}${u}`),
        h('span', {}, `CV = ${mean ? ((sd / mean) * 100).toFixed(1) : '0'} %`),
      );
      if (s.type !== 'constant') {
        const rng = new RandomStream(7);
        const vals = Array.from({ length: 1500 }, () => sample(s, rng) / scale);
        spark.appendChild(sparkHistogram(vals));
      }
    };
    refresh();

    const head = h('div', { class: 'dist-head' }, h('span', { class: 'field-label' }, label + (unit ? ` (${unit})` : '')), typeSel);
    root.append(head, params, h('div', { class: 'dist-preview' }, info, spark));
    if (!compact) root.append(quickEntry(), fitPanel());
  };

  const quickEntry = () => {
    const meanIn = h('input', { type: 'number', step: 'any', placeholder: 'media', 'data-key': `${key}|qm` });
    const cvIn = h('input', { type: 'number', step: 'any', placeholder: 'CV %', 'data-key': `${key}|qc` });
    const btn = h('button', {
      type: 'button',
      class: 'small',
      onclick: () => {
        const m = Number(meanIn.value);
        const cv = Number(cvIn.value) / 100;
        if (!(m > 0) || !(cv >= 0)) return;
        const type = get()?.type === 'constant' && cv > 0 ? 'lognormal' : get()?.type || 'lognormal';
        try {
          set(fromMeanCv(cv === 0 ? 'constant' : type === 'empirical' || type === 'beta' ? 'lognormal' : type, m * scale, cv));
        } catch {
          set(fromMeanCv('lognormal', m * scale, cv));
        }
        onChange?.();
        render();
      },
    }, 'Aplicar');
    return h('details', { class: 'sub' }, h('summary', {}, 'Entrada rápida: media + coeficiente de variación'), h('div', { class: 'row' }, meanIn, cvIn, btn));
  };

  const fitPanel = () => {
    const ta = h('textarea', { rows: 3, placeholder: `Pega aquí tiempos medidos (${unit || 'valores'}), separados por espacios, comas o saltos de línea`, 'data-key': `${key}|fit` });
    const out = h('div', { class: 'fit-out' });
    const btn = h('button', {
      type: 'button',
      class: 'small',
      onclick: () => {
        out.replaceChildren();
        try {
          const samples = parseSamples(ta.value).map((v) => v * scale);
          const fit = fitDistributions(samples);
          const s = fit.summary;
          out.appendChild(h('p', { class: 'muted' }, `n = ${s.n} · media ${fmtNum(s.mean / scale)} · σ ${fmtNum(s.sd / scale)} · CV ${(s.cv * 100).toFixed(1)} % · rango ${fmtNum(s.min / scale)}–${fmtNum(s.max / scale)}`));
          const table = h('table', { class: 'mini' }, h('tr', {}, h('th', {}, 'Distribución'), h('th', {}, 'KS'), h('th', {}, 'p-valor'), h('th', {}, '')));
          fit.results.slice(0, 6).forEach((r, i) => {
            table.appendChild(
              h('tr', { class: i === 0 ? 'best' : '' },
                h('td', {}, DISTRIBUTIONS[r.spec.type].label),
                h('td', {}, r.ks.toFixed(3)),
                h('td', { class: r.pValue < 0.05 ? 'error' : '' }, r.pValue.toFixed(3)),
                h('td', {}, h('button', { type: 'button', class: 'small', onclick: () => { set({ ...r.spec, ...(r.spec.type === 'normal' ? { truncate: { min: 0 } } : {}) }); onChange?.(); render(); } }, 'Usar')),
              ),
            );
          });
          out.appendChild(table);
          out.appendChild(h('p', { class: 'help' }, 'KS menor = mejor ajuste. p-valor < 0,05 indica que la distribución se rechaza. También puedes usar la empírica con los datos tal cual.'));
          out.appendChild(h('button', { type: 'button', class: 'small', onclick: () => { set({ type: 'empirical', values: samples }); onChange?.(); render(); } }, 'Usar distribución empírica'));
        } catch (e) {
          out.appendChild(h('p', { class: 'error' }, e.message));
        }
      },
    }, 'Ajustar');
    return h('details', { class: 'sub' }, h('summary', {}, 'Ajustar a partir de datos medidos (cronometraje)'), ta, btn, out);
  };

  render();
  return root;
}

function safeMoments(spec) {
  try {
    if (validate(spec).length) return { mean: 1, sd: 0.1 };
    return moments(spec);
  } catch {
    return { mean: 1, sd: 0.1 };
  }
}
