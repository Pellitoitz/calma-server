// Aplicación principal: navegación, estado, guardado automático, historial y 3D.

import { validateModel } from '/src/model/schema.js';
import { api, waitJob, AutoSaver, local } from './api.js';
import { h } from './dom.js';
import { installTooltip } from './charts.js';
import { renderGeneral, renderResources, renderOperations, renderStations } from './editors.js';
import { renderResults } from './results.js';

const TABS = [
  ['general', 'General'],
  ['resources', 'Recursos'],
  ['operations', 'Operaciones'],
  ['stations', 'Estaciones'],
  ['results', 'Simulación y KPIs'],
  ['view3d', 'Vista 3D'],
];

const state = {
  models: [],
  model: null,
  library: { operations: [], operators: [], machines: [] },
  tab: local.get('umps:tab', 'general'),
  ui: {},
  open: new Set(),
  result: null,
  contribution: null,
  comparison: null,
  busy: false,
  progress: 0,
  saveStatus: 'saved',
  validation: null,
};

const $ = (sel) => document.querySelector(sel);
let viewer = null;

// ------------------------------------------------------------------ guardado
const saver = new AutoSaver({
  onStatus: (s) => {
    state.saveStatus = s;
    renderSaveStatus();
  },
  onSaved: (saved) => {
    if (state.model && saved.id === state.model.id) {
      state.model.revision = saved.revision;
      state.model.updatedAt = saved.updatedAt;
      const entry = state.models.find((m) => m.id === saved.id);
      if (entry) Object.assign(entry, { name: saved.name, updatedAt: saved.updatedAt });
    }
  },
  onConflict: async (mine, theirs) => {
    const keepMine = confirm('Este modelo se ha modificado en otra ventana o dispositivo.\n\nAceptar = conservar TUS cambios (sobrescribe la otra versión, que queda en el historial).\nCancelar = cargar la otra versión.');
    if (keepMine) {
      mine.revision = theirs?.revision;
      saver.schedule(mine);
    } else {
      AutoSaver.discardPending(mine.id);
      await openModel(mine.id);
    }
  },
});

function renderSaveStatus() {
  const el = $('#save-status');
  if (!el) return;
  const map = {
    saved: ['ok', 'Guardado'],
    pending: ['pending', 'Cambios pendientes…'],
    saving: ['pending', 'Guardando…'],
    offline: ['warn', 'Sin conexión · guardado en este navegador, se reintentará'],
    conflict: ['warn', 'Conflicto de versiones'],
  };
  const [cls, text] = map[state.saveStatus] || map.saved;
  el.className = `save-status ${cls}`;
  el.textContent = text;
}

let validateTimer = null;
function revalidate() {
  clearTimeout(validateTimer);
  validateTimer = setTimeout(() => {
    try {
      const { errors, warnings } = validateModel(state.model);
      state.validation = { errors, warnings };
    } catch (e) {
      state.validation = { errors: [e.message], warnings: [] };
    }
    renderTabs();
  }, 300);
}

// ------------------------------------------------------------------ contexto para editores
const ctx = {
  get model() {
    return state.model;
  },
  get library() {
    return state.library;
  },
  get ui() {
    return state.ui;
  },
  get result() {
    return state.result;
  },
  get contribution() {
    return state.contribution;
  },
  get comparison() {
    return state.comparison;
  },
  get busy() {
    return state.busy;
  },
  get progress() {
    return state.progress;
  },
  get validation() {
    return state.validation;
  },
  get models() {
    return state.models;
  },
  change({ rerender = false } = {}) {
    saver.schedule(state.model);
    revalidate();
    if (rerender) render();
  },
  rerender: () => render(),
  refreshList: () => renderSidebar(),
  isOpen: (k) => state.open.has(k),
  setOpen(k, v) {
    if (v) state.open.add(k);
    else state.open.delete(k);
    local.set(`umps:open:${state.model?.id}`, [...state.open]);
  },
  saveLibrary: async () => {
    try {
      state.library = await api('PUT', '/api/library', state.library);
    } catch (e) {
      toast(`No se pudo guardar la biblioteca: ${e.message}`, true);
    }
  },
  toast: (m) => toast(m),
  runSimulation,
  runContribution,
  runCompare,
};

// ------------------------------------------------------------------ acciones
async function runJob(startUrl, body) {
  await saver.flush();
  state.busy = true;
  state.progress = 0;
  render();
  try {
    const { jobId } = await api('POST', startUrl, body);
    return await waitJob(jobId, (p) => {
      state.progress = p;
      const bar = document.querySelector('.progress > div');
      if (bar) bar.style.width = `${Math.round(p * 100)}%`;
    });
  } catch (e) {
    toast(e.details?.length ? `${e.message}: ${e.details.slice(0, 3).join(' · ')}` : e.message, true);
    return null;
  } finally {
    state.busy = false;
  }
}

async function runSimulation(replications) {
  const r = await runJob(`/api/models/${state.model.id}/simulate`, { replications, model: state.model });
  if (r) {
    state.result = r;
    toast('Simulación terminada y guardada');
  }
  render();
}

async function runContribution() {
  const r = await runJob(`/api/models/${state.model.id}/contribution`, { model: state.model });
  if (r) {
    state.contribution = r;
    toast('Análisis de variabilidad terminado');
  }
  render();
}

async function runCompare(otherId) {
  const r = await runJob('/api/compare', { a: state.model, b: otherId });
  if (r) state.comparison = r;
  render();
}

function toast(msg, error = false) {
  const t = h('div', { class: `toast${error ? ' error' : ''}` }, msg);
  document.body.appendChild(t);
  setTimeout(() => t.classList.add('show'), 10);
  setTimeout(() => {
    t.classList.remove('show');
    setTimeout(() => t.remove(), 300);
  }, error ? 6000 : 2800);
}

async function refreshModels() {
  state.models = await api('GET', '/api/models');
}

async function openModel(id) {
  await saver.flush();
  let model = await api('GET', `/api/models/${id}`);
  const pending = AutoSaver.recoverPending(id);
  if (pending && pending.model && pending.at > Date.parse(model.updatedAt || 0)) {
    model = { ...pending.model, revision: model.revision };
    saver.schedule(model);
    toast('Se han recuperado cambios que no llegaron a guardarse en el servidor');
  } else if (pending) {
    AutoSaver.discardPending(id);
  }
  state.model = model;
  state.open = new Set(local.get(`umps:open:${id}`, []));
  state.ui = local.get(`umps:ui:${id}`, {}) || {};
  state.comparison = null;
  local.set('umps:last', id);
  const [result, contribution] = await Promise.all([
    api('GET', `/api/models/${id}/results`).catch(() => null),
    api('GET', `/api/models/${id}/contribution`).catch(() => null),
  ]);
  state.result = result;
  state.contribution = contribution;
  state.validation = null;
  revalidate();
  render();
}

async function createModel(template) {
  const name = prompt('Nombre del nuevo modelo', template === 'example' ? 'Célula de montaje ECU (ejemplo)' : 'Nuevo modelo');
  if (name === null) return;
  const m = await api('POST', '/api/models', { template, name });
  await refreshModels();
  await openModel(m.id);
}

async function duplicateModel() {
  await saver.flush();
  const m = await api('POST', `/api/models/${state.model.id}/duplicate`);
  await refreshModels();
  await openModel(m.id);
  toast('Escenario duplicado: modifícalo y compáralo con el original');
}

async function deleteModel() {
  if (!confirm(`¿Eliminar «${state.model.name}»? Se guardará una copia en el historial.`)) return;
  const id = state.model.id;
  await api('DELETE', `/api/models/${id}`);
  AutoSaver.discardPending(id);
  state.model = null;
  await refreshModels();
  if (state.models.length) await openModel(state.models[0].id);
  else render();
}

function exportModel() {
  const { revision, ...m } = state.model;
  const blob = new Blob([JSON.stringify(m, null, 2)], { type: 'application/json' });
  const a = h('a', { href: URL.createObjectURL(blob), download: `${state.model.id}.json` });
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function importModel() {
  const inp = h('input', { type: 'file', accept: '.json,application/json' });
  inp.addEventListener('change', async () => {
    const file = inp.files[0];
    if (!file) return;
    try {
      const model = JSON.parse(await file.text());
      const saved = await api('POST', '/api/models', { model });
      await refreshModels();
      await openModel(saved.id);
      toast('Modelo importado');
    } catch (e) {
      toast(`No se pudo importar: ${e.message}`, true);
    }
  });
  inp.click();
}

async function showHistory() {
  const list = await api('GET', `/api/models/${state.model.id}/history`);
  const dlg = h('dialog', { class: 'dialog' },
    h('h3', {}, 'Historial de versiones'),
    h('p', { class: 'help' }, 'Cada guardado conserva la versión anterior. Restaurar crea una versión nueva, así que no pierdes nada.'),
    list.length
      ? h('table', { class: 'data' },
          h('tr', {}, h('th', {}, 'Revisión'), h('th', {}, 'Fecha'), h('th', {}, 'Estaciones'), h('th', {}, 'Operaciones'), h('th', {}, '')),
          list.map((v) => h('tr', {},
            h('td', {}, v.revision),
            h('td', {}, new Date(v.updatedAt).toLocaleString()),
            h('td', {}, v.stations),
            h('td', {}, v.operations),
            h('td', {}, h('button', { type: 'button', class: 'small', onclick: async () => {
              await saver.flush();
              await api('POST', `/api/models/${state.model.id}/restore/${v.revision}`);
              dlg.close();
              await openModel(state.model.id);
              toast(`Restaurada la revisión ${v.revision}`);
            } }, 'Restaurar')),
          )),
        )
      : h('p', {}, 'Todavía no hay versiones anteriores.'),
    h('div', { class: 'row end' }, h('button', { type: 'button', onclick: () => dlg.close() }, 'Cerrar')),
  );
  dlg.addEventListener('close', () => dlg.remove());
  document.body.appendChild(dlg);
  dlg.showModal();
}

// ------------------------------------------------------------------ render
function renderSidebar() {
  const side = $('#sidebar');
  side.replaceChildren(
    h('div', { class: 'brand' }, h('strong', {}, 'Process Simulator'), h('small', {}, 'Simulación estocástica de procesos manuales')),
    h('div', { class: 'side-actions' },
      h('button', { type: 'button', onclick: () => createModel('blank') }, 'Nuevo'),
      h('button', { type: 'button', onclick: () => createModel('example') }, 'Ejemplo'),
      h('button', { type: 'button', onclick: importModel }, 'Importar'),
    ),
    h('nav', { class: 'model-list' },
      state.models.map((m) => h('button', {
        type: 'button',
        class: `model-item${state.model?.id === m.id ? ' active' : ''}`,
        onclick: () => openModel(m.id),
      }, h('span', {}, state.model?.id === m.id ? state.model.name : m.name), h('small', {}, `${m.stations} est. · ${m.operations} op. · ${new Date(m.updatedAt).toLocaleDateString()}`))),
    ),
  );
}

function renderTabs() {
  const tabs = $('#tabs');
  if (!tabs) return;
  const errs = state.validation?.errors?.length || 0;
  tabs.replaceChildren(
    ...TABS.map(([id, label]) => h('button', {
      type: 'button',
      class: `tab${state.tab === id ? ' active' : ''}`,
      onclick: () => {
        state.tab = id;
        local.set('umps:tab', id);
        render();
      },
    }, label, id === 'results' && errs ? h('span', { class: 'badge error' }, errs) : null)),
  );
}

function render() {
  renderSidebar();
  const main = $('#main');
  if (!state.model) {
    main.replaceChildren(h('div', { class: 'empty' }, h('p', {}, 'Crea un modelo nuevo o carga el ejemplo para empezar.')));
    return;
  }
  local.set(`umps:ui:${state.model.id}`, state.ui);

  // conserva el foco y la posición del cursor al repintar
  const active = document.activeElement;
  const focusKey = active?.dataset?.key;
  const sel = active && 'selectionStart' in active ? [active.selectionStart, active.selectionEnd] : null;
  const scroll = $('#content')?.scrollTop ?? 0;

  if (viewer) {
    viewer.dispose();
    viewer = null;
  }

  const content = h('div', { id: 'content', class: 'content' });
  main.replaceChildren(
    h('header', { class: 'topbar' },
      h('div', { class: 'title' }, h('h2', {}, state.model.name), h('span', { id: 'save-status', class: 'save-status' })),
      h('div', { class: 'top-actions' },
        h('button', { type: 'button', onclick: duplicateModel, title: 'Crea una copia para probar cambios' }, 'Duplicar escenario'),
        h('button', { type: 'button', onclick: showHistory }, 'Historial'),
        h('button', { type: 'button', onclick: exportModel }, 'Exportar'),
        h('button', { type: 'button', class: 'danger', onclick: deleteModel }, 'Eliminar'),
      ),
    ),
    h('div', { id: 'tabs', class: 'tabs' }),
    content,
  );
  renderTabs();
  renderSaveStatus();

  const views = {
    general: renderGeneral,
    resources: renderResources,
    operations: renderOperations,
    stations: renderStations,
    results: renderResults,
    view3d: render3D,
  };
  try {
    content.appendChild(views[state.tab](ctx));
  } catch (e) {
    console.error(e);
    content.appendChild(h('p', { class: 'error' }, `Error al mostrar esta vista: ${e.message}`));
  }
  content.scrollTop = scroll;

  if (focusKey) {
    const el = content.querySelector(`[data-key="${CSS.escape(focusKey)}"]`);
    if (el) {
      el.focus({ preventScroll: true });
      if (sel && 'setSelectionRange' in el) {
        try {
          el.setSelectionRange(sel[0], sel[1]);
        } catch {
          /* tipo de campo sin selección */
        }
      }
    }
  }
}

// ------------------------------------------------------------------ 3D
function render3D() {
  const wrap = h('div', { class: 'view3d' });
  const stage = h('div', { class: 'stage' }, h('p', { class: 'muted pad' }, 'Cargando motor 3D…'));
  const clock = h('span', { class: 'clock' }, '0:00:00');
  const counters = h('span', { class: 'muted' }, '');
  const slider = h('input', { type: 'range', min: 0, max: 1, step: 1, value: 0 });
  const playBtn = h('button', { type: 'button', class: 'primary' }, '▶ Reproducir');
  const speedSel = h('select', {}, [1, 5, 20, 60, 200, 600].map((s) => h('option', { value: s }, `×${s}`)));
  speedSel.value = state.ui.speed3d || 20;
  const info = h('p', { class: 'help' });
  wrap.append(
    h('div', { class: 'row controls' }, playBtn, speedSel, slider, clock, counters),
    stage,
    info,
    h('div', { class: 'legend' },
      h('span', {}, h('i', { style: { background: '#1baf7a' } }), 'Máquina en marcha'),
      h('span', {}, h('i', { style: { background: '#eda100' } }), 'Parada / esperando'),
      h('span', {}, h('i', { style: { background: '#e34948' } }), 'Avería'),
      h('span', {}, 'Operario semitransparente = en pausa'),
    ),
  );

  (async () => {
    let mod;
    try {
      mod = await import('./view3d.js');
    } catch (e) {
      stage.replaceChildren(h('p', { class: 'error pad' }, `No se pudo cargar three.js (¿sin conexión a internet?): ${e.message}`));
      return;
    }
    const traceData = await api('GET', `/api/models/${state.model.id}/trace`).catch(() => null);
    stage.replaceChildren();
    viewer = new mod.CellViewer(stage, {
      onTime: (t, v) => {
        const hh = Math.floor(t / 3600);
        const mm = Math.floor((t % 3600) / 60);
        const ss = Math.floor(t % 60);
        clock.textContent = `${hh}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`;
        if (document.activeElement !== slider) slider.value = Math.floor(t);
        counters.textContent = `terminadas ${v.completed}${v.scrapped ? ` · desechadas ${v.scrapped}` : ''}`;
        playBtn.textContent = v.playing ? '❚❚ Pausa' : '▶ Reproducir';
      },
    });
    const useTrace = traceData?.trace?.length ? traceData : null;
    viewer.build(state.model, { layout: useTrace?.layout, trace: useTrace?.trace });
    viewer.speed = Number(speedSel.value);
    slider.max = Math.ceil(viewer.duration || 1);
    const stale = state.result?.meta?.modelRevision && state.result.meta.modelRevision !== state.model.revision;
    info.textContent = useTrace
      ? `Reproduciendo la réplica 1 (primeras ${(viewer.duration / 3600).toFixed(1)} h). Arrastra para girar, rueda para zoom.${stale ? ' El modelo ha cambiado desde la última simulación: vuelve a simular para sincronizar.' : ''}`
      : 'Celda generada a partir del modelo. Ejecuta una simulación para ver a operarios y piezas en movimiento.';
    playBtn.onclick = () => (viewer.playing ? viewer.pause() : viewer.play());
    speedSel.onchange = () => {
      viewer.speed = Number(speedSel.value);
      state.ui.speed3d = viewer.speed;
      local.set(`umps:ui:${state.model.id}`, state.ui);
    };
    slider.oninput = () => viewer.seek(Number(slider.value));
  })();
  return wrap;
}

// ------------------------------------------------------------------ arranque
async function init() {
  installTooltip();
  try {
    [state.library] = await Promise.all([api('GET', '/api/library'), refreshModels()]);
  } catch (e) {
    $('#main').replaceChildren(h('p', { class: 'error pad' }, `No se puede conectar con el servidor: ${e.message}`));
    return;
  }
  const last = local.get('umps:last');
  const id = state.models.find((m) => m.id === last)?.id || state.models[0]?.id;
  if (id) await openModel(id);
  else render();
}

init();
