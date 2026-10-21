// Pestaña de resultados: KPIs con intervalos de confianza, cuellos de botella,
// utilización de recursos, OEE, calidad, análisis de variabilidad y comparación.

import { KPI_LABELS } from '/src/analytics/kpis.js';
import { OPERATION_TYPES } from '/src/stochastic/variability.js';
import { h, pct, fmtNum, fmtTime, numField } from './dom.js';
import { lineBand, histogramChart, stackedBars, tornado } from './charts.js';

const STATE_COLORS = {
  working: 'var(--c-blue)',
  setup: 'var(--c-violet)',
  failure: 'var(--c-red)',
  waitingResource: 'var(--c-yellow)',
  blocked: 'var(--c-orange)',
  starved: 'var(--c-gray)',
  walking: 'var(--c-aqua)',
  idle: 'var(--c-gray)',
  break: 'var(--c-light)',
  down: 'var(--c-red)',
  busy: 'var(--c-blue)',
};

const PCT_KPIS = new Set(['fpy', 'scrapRate', 'demandFulfilment', 'littleDeviation', 'operatorUtilizationMean', 'valueAddedRatio', 'oeeMean']);
const TIME_KPIS = new Set(['leadTimeMean', 'leadTimeP50', 'leadTimeP90', 'leadTimeP95', 'leadTimeMax', 'leadTimeSd', 'cycleTime']);

function fmtKpi(key, v) {
  if (PCT_KPIS.has(key)) return pct(v);
  if (TIME_KPIS.has(key)) return fmtTime(v);
  if (key === 'escapedPpm') return `${fmtNum(v, 0)} ppm`;
  return fmtNum(v);
}

function legend(keys) {
  return h('div', { class: 'legend' }, keys.map((k) => h('span', {}, h('i', { style: { background: k.color } }), k.label)));
}

function tile(label, s, key, extra) {
  if (!s) return null;
  return h('div', { class: 'tile' },
    h('div', { class: 'tile-label' }, label),
    h('div', { class: 'tile-value' }, fmtKpi(key, s.mean)),
    h('div', { class: 'tile-ci' }, Number.isFinite(s.halfWidth) ? `IC ${Math.round((s.confidence ?? 0.95) * 100)} %: ${fmtKpi(key, s.ciLow)} – ${fmtKpi(key, s.ciHigh)}` : 'una sola réplica'),
    extra ? h('div', { class: 'tile-extra' }, extra) : null,
  );
}

const ci = (s, f = fmtNum) => (s ? `${f(s.mean)}${Number.isFinite(s.halfWidth) ? ` ± ${f(s.halfWidth)}` : ''}` : '—');
const pctCi = (s) => (s ? `${pct(s.mean)}${Number.isFinite(s.halfWidth) ? ` ± ${(s.halfWidth * 100).toFixed(1)}` : ''}` : '—');

function table(headers, rows) {
  return h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', {}, h('tr', {}, headers.map((x) => h('th', {}, x)))), h('tbody', {}, rows)));
}

export function renderResults(ctx) {
  const { model, result, contribution, ui } = ctx;
  const root = h('div', { class: 'stack' });

  // -------------------------------------------------- panel de ejecución
  ui.runReps ??= model.settings?.replications ?? 10;
  const runCard = h('section', { class: 'card' },
    h('h3', {}, 'Ejecutar'),
    h('div', { class: 'row' },
      numField('Réplicas', { get: () => ui.runReps, set: (v) => (ui.runReps = v), key: 'run.reps', step: 1, min: 1 }),
      h('button', { type: 'button', class: 'primary', disabled: ctx.busy || undefined, onclick: () => ctx.runSimulation(ui.runReps) }, 'Simular'),
      h('button', { type: 'button', disabled: ctx.busy || undefined, onclick: () => ctx.runContribution() }, 'Analizar fuentes de variabilidad'),
    ),
    ctx.busy ? h('div', { class: 'progress' }, h('div', { style: { width: `${Math.round(ctx.progress * 100)}%` } })) : null,
    ctx.validation?.errors?.length ? h('ul', { class: 'errors' }, ctx.validation.errors.map((e) => h('li', {}, e))) : null,
    ctx.validation?.warnings?.length ? h('ul', { class: 'warnings' }, ctx.validation.warnings.map((e) => h('li', {}, e))) : null,
  );
  root.appendChild(runCard);

  if (!result) {
    root.appendChild(h('section', { class: 'card' }, h('p', { class: 'muted' }, 'Aún no hay resultados guardados para este modelo. Pulsa «Simular».')));
    if (contribution) root.appendChild(renderContribution(contribution));
    root.appendChild(renderCompare(ctx));
    return root;
  }

  const meta = result.meta;
  const S = result.scalars;
  const stale = meta.modelRevision && model.revision && meta.modelRevision !== model.revision;
  root.appendChild(
    h('section', { class: 'card' },
      h('p', { class: 'muted' },
        `Resultados del ${new Date(meta.createdAt).toLocaleString()} · ${meta.replications} réplicas de ${meta.horizonHours} h (calentamiento ${meta.warmupHours} h) · confianza ${Math.round(meta.confidence * 100)} % · ${(meta.runtimeMs / 1000).toFixed(1)} s`,
      ),
      stale ? h('p', { class: 'warn-box' }, 'El modelo ha cambiado desde esta simulación. Vuelve a simular para actualizar los resultados.') : null,
      meta.warnings?.length ? h('ul', { class: 'warnings' }, meta.warnings.map((w) => h('li', {}, w))) : null,
    ),
  );

  // -------------------------------------------------- KPIs principales
  for (const s of Object.values(S)) s.confidence = meta.confidence;
  const bott = [...result.stations].sort((a, b) => b.bottleneckProbability - a.bottleneckProbability)[0];
  root.appendChild(
    h('section', { class: 'card' },
      h('h3', {}, 'Indicadores principales'),
      h('div', { class: 'tiles' },
        tile('Producción', S.throughputPerHour, 'throughputPerHour', meta.demandPerHour ? `Demanda ${meta.demandPerHour} uds/h · P(cumplir) = ${pct(result.risk.probabilityMeetDemand, 0)}` : `P10–P90: ${fmtNum(S.throughputPerHour.p10)} – ${fmtNum(S.throughputPerHour.p90)}`),
        tile('Lead time medio', S.leadTimeMean, 'leadTimeMean', `P90 ${fmtTime(S.leadTimeP90.mean)} · P95 ${fmtTime(S.leadTimeP95.mean)}`),
        tile('WIP medio', S.wipMean, 'wipMean', `máximo ${fmtNum(S.wipMax.mean, 1)}`),
        tile('Tiempo de ciclo real', S.cycleTime, 'cycleTime', meta.demandPerHour ? `Takt ${fmtTime(3600 / meta.demandPerHour)}` : null),
        tile('First Pass Yield', S.fpy, 'fpy', `retrabajos/ud ${fmtNum(S.reworkPerUnit.mean, 3)} · desecho ${pct(S.scrapRate.mean, 2)}`),
        tile('Utilización operarios', S.operatorUtilizationMean, 'operatorUtilizationMean', `valor añadido ${pct(S.valueAddedRatio.mean)}`),
        Number.isFinite(S.oeeMean.mean) ? tile('OEE medio', S.oeeMean, 'oeeMean') : null,
        bott ? h('div', { class: 'tile accent' },
          h('div', { class: 'tile-label' }, 'Cuello de botella'),
          h('div', { class: 'tile-value' }, bott.name),
          h('div', { class: 'tile-ci' }, `en el ${pct(bott.bottleneckProbability, 0)} de las réplicas`),
          h('div', { class: 'tile-extra' }, `activa ${pctCi(bott.active)}`),
        ) : null,
      ),
    ),
  );

  // -------------------------------------------------- evolución temporal
  root.appendChild(
    h('section', { class: 'card' },
      h('h3', {}, 'Producción por hora (media e IC entre réplicas)'),
      lineBand(result.hourly.map((p) => ({ x: p.hour + 1, y: p.mean, low: p.low, high: p.high })), {
        ref: meta.demandPerHour,
        refLabel: meta.demandPerHour ? `Demanda ${meta.demandPerHour}` : '',
        xFmt: (v) => `h${v}`,
        yFmt: (v) => fmtNum(v, 1),
        yLabel: 'uds/h',
        name: 'Producción',
      }),
      h('p', { class: 'help' }, 'Las primeras horas incluyen el llenado de la línea; las caídas periódicas corresponden a las pausas del turno.'),
    ),
  );
  root.appendChild(
    h('section', { class: 'card' },
      h('h3', {}, 'WIP en el tiempo (comprobación del calentamiento)'),
      lineBand(result.wipSeries.map((p) => ({ x: p.t / 3600, y: p.mean, low: p.min, high: p.max })), {
        ref: undefined,
        xFmt: (v) => `${v.toFixed(1)} h`,
        yFmt: (v) => fmtNum(v, 1),
        yLabel: 'uds',
        name: 'WIP medio',
      }),
      h('p', { class: 'help' }, `Banda = mínimo y máximo entre réplicas. Si la curva sigue creciendo después de ${meta.warmupHours} h, amplía el calentamiento o el sistema no es estable (demanda > capacidad).`),
    ),
  );
  root.appendChild(
    h('section', { class: 'card' },
      h('h3', {}, 'Distribución del lead time (todas las réplicas)'),
      histogramChart(result.leadTimeHistogram, {
        xFmt: (v) => fmtTime(v),
        markers: [
          { value: S.leadTimeP50.mean, label: 'P50' },
          { value: S.leadTimeP90.mean, label: 'P90' },
        ],
      }),
    ),
  );

  // -------------------------------------------------- estaciones
  const stKeys = [
    { key: 'working', label: 'Trabajando', color: STATE_COLORS.working },
    { key: 'setup', label: 'Setup', color: STATE_COLORS.setup },
    { key: 'failure', label: 'Avería', color: STATE_COLORS.failure },
    { key: 'waitingResource', label: 'Esperando operario/máquina', color: STATE_COLORS.waitingResource },
    { key: 'blocked', label: 'Bloqueada (buffer lleno)', color: STATE_COLORS.blocked },
    { key: 'starved', label: 'Sin material', color: STATE_COLORS.starved },
  ];
  root.appendChild(
    h('section', { class: 'card' },
      h('h3', {}, 'Estaciones'),
      legend(stKeys),
      stackedBars(result.stations.map((s) => ({ label: s.name, parts: Object.fromEntries(stKeys.map((k) => [k.key, s[k.key]?.mean || 0])), marker: s.bottleneckProbability > 0 ? `◆ ${pct(s.bottleneckProbability, 0)}` : '' })), stKeys),
      h('p', { class: 'help' }, '◆ = probabilidad de ser el cuello de botella (método del periodo activo: estación con mayor tiempo trabajando, en setup, averiada o esperando recursos).'),
      table(
        ['Estación', 'Activa', 'Bloqueada', 'Sin material', 'Uds/h', 'Ciclo medio', 'CV salidas', 'Buffer medio / máx / cap.', 'P(cuello)'],
        result.stations.map((s) => h('tr', { class: s.id === bott?.id ? 'hl' : '' },
          h('td', {}, s.name),
          h('td', {}, pctCi(s.active)),
          h('td', {}, pct(s.blocked.mean)),
          h('td', {}, pct(s.starved.mean)),
          h('td', {}, ci(s.throughput)),
          h('td', {}, fmtTime(s.cycleMean.mean)),
          h('td', {}, fmtNum(s.interDepartureCv.mean)),
          h('td', {}, `${fmtNum(s.bufferMean.mean, 1)} / ${fmtNum(s.bufferMax.mean, 1)} / ${s.bufferCapacity.mean}`),
          h('td', {}, pct(s.bottleneckProbability, 0)),
        )),
      ),
    ),
  );

  // -------------------------------------------------- operarios
  const opKeys = [
    { key: 'working', label: 'Trabajando', color: STATE_COLORS.working },
    { key: 'setup', label: 'Setup', color: STATE_COLORS.setup },
    { key: 'walking', label: 'Andando', color: STATE_COLORS.walking },
    { key: 'idle', label: 'Libre', color: STATE_COLORS.idle },
    { key: 'break', label: 'Pausa', color: STATE_COLORS.break },
  ];
  if (result.operators.length) {
    root.appendChild(
      h('section', { class: 'card' },
        h('h3', {}, 'Operarios'),
        legend(opKeys),
        stackedBars(result.operators.map((o) => ({ label: o.name, parts: Object.fromEntries(opKeys.map((k) => [k.key, o[k.key]?.mean || 0])) })), opKeys),
        table(
          ['Operario', 'Utilización (sin pausas)', 'Valor añadido', 'Andado (m/h)', 'Tareas/h', 'Fatiga máx.', 'Reparto de trabajo'],
          result.operators.map((o) => h('tr', {},
            h('td', {}, o.name),
            h('td', { class: o.utilization.mean > 0.9 ? 'warn' : '' }, pctCi(o.utilization)),
            h('td', {}, pct(o.valueAddedRatio.mean)),
            h('td', {}, fmtNum(o.walkedMetersPerHour.mean, 0)),
            h('td', {}, fmtNum(o.tasksPerHour.mean, 1)),
            h('td', {}, `+${((o.maxFatigueFactor.mean - 1) * 100).toFixed(1)} %`),
            h('td', { class: 'small-text' }, Object.entries(o.byType || {}).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([t, v]) => `${OPERATION_TYPES[t]?.label ?? t} ${pct(v, 0)}`).join(' · ')),
          )),
        ),
        h('p', { class: 'help' }, 'Utilización > 90 % deja poco margen frente a la variabilidad: las colas crecen de forma no lineal. Valor añadido = montaje, atornillado, cableado, embalaje, mecanizado (Lean).'),
      ),
    );
  }

  // -------------------------------------------------- máquinas
  if (result.machines.length) {
    root.appendChild(
      h('section', { class: 'card' },
        h('h3', {}, 'Máquinas · OEE'),
        table(
          ['Máquina', 'OEE', 'Disponibilidad (en marcha)', 'Rendimiento', 'Calidad', 'Disp. técnica', 'Averías', 'MTTR observado', 'MTBF observado'],
          result.machines.map((m) => h('tr', {},
            h('td', {}, m.name),
            h('td', {}, pctCi(m.oee)),
            h('td', {}, pct(m.oeeAvailability.mean)),
            h('td', {}, pct(m.oeePerformance.mean)),
            h('td', {}, pct(m.oeeQuality.mean)),
            h('td', {}, pct(m.technicalAvailability.mean)),
            h('td', {}, fmtNum(m.failures.mean, 1)),
            h('td', {}, fmtTime(m.mttrObserved.mean)),
            h('td', {}, m.mtbfObserved?.mean ? fmtTime(m.mtbfObserved.mean) : '—'),
          )),
        ),
        h('p', { class: 'help' }, 'OEE = disponibilidad × rendimiento × calidad. La disponibilidad incluye el tiempo parado por falta de material o bloqueo; la disponibilidad técnica solo descuenta averías.'),
      ),
    );
  }

  // -------------------------------------------------- operaciones
  root.appendChild(
    h('section', { class: 'card' },
      h('h3', {}, 'Operaciones: tiempo especificado frente a observado'),
      table(
        ['Operación', 'Tipo', 'Ejecuciones', 'μ especificada', 'μ observada', 'CV observado', 'P90', 'Interrupciones/ud', 'Factor de pérdida'],
        result.operations.filter((o) => o.count.mean > 0).map((o) => h('tr', {},
          h('td', {}, o.name),
          h('td', {}, OPERATION_TYPES[o.type]?.label ?? o.type),
          h('td', {}, fmtNum(o.count.mean, 0)),
          h('td', {}, o.specified ? fmtTime(o.specified.mean) : '—'),
          h('td', {}, fmtTime(o.mean.mean)),
          h('td', {}, pct(o.cv.mean)),
          h('td', {}, fmtTime(o.p90.mean)),
          h('td', {}, fmtNum(o.interruptionsPerUnit.mean, 3)),
          h('td', { class: o.lossFactor.mean > 1.1 ? 'warn' : '' }, `×${fmtNum(o.lossFactor.mean, 3)}`),
        )),
      ),
      h('p', { class: 'help' }, 'Factor de pérdida = tiempo real / tiempo estándar. Recoge aprendizaje, fatiga, ritmo del operario, interrupciones y averías.'),
    ),
  );

  // -------------------------------------------------- tabla completa
  root.appendChild(
    h('section', { class: 'card' },
      h('h3', {}, 'Todos los indicadores con su incertidumbre'),
      table(
        ['Indicador', 'Media', 'IC inferior', 'IC superior', 'σ entre réplicas', 'Mín.', 'Máx.', 'Precisión', 'Réplicas necesarias'],
        Object.entries(S).map(([k, s]) => h('tr', {},
          h('td', {}, KPI_LABELS[k]?.label ?? k),
          h('td', {}, fmtKpi(k, s.mean)),
          h('td', {}, fmtKpi(k, s.ciLow)),
          h('td', {}, fmtKpi(k, s.ciHigh)),
          h('td', {}, fmtKpi(k, s.sd)),
          h('td', {}, fmtKpi(k, s.min)),
          h('td', {}, fmtKpi(k, s.max)),
          h('td', {}, Number.isFinite(s.relativePrecision) ? `±${(s.relativePrecision * 100).toFixed(1)} %` : '—'),
          h('td', {}, s.replicationsNeeded ?? '—'),
        )),
      ),
    ),
  );

  if (contribution) root.appendChild(renderContribution(contribution));
  root.appendChild(renderCompare(ctx));
  return root;
}

function renderContribution(c) {
  const items = c.sources.map((s) => ({
    label: s.label,
    value: s.effects.throughputPerHour.mean,
    low: s.effects.throughputPerHour.ciLow,
    high: s.effects.throughputPerHour.ciHigh,
    significant: s.effects.throughputPerHour.significant,
  }));
  const all = c.allDeterministic.effects;
  return h('section', { class: 'card' },
    h('h3', {}, '¿Qué variabilidad cuesta más producción?'),
    h('p', { class: 'help' }, `Cada fuente se sustituye por su valor medio manteniendo todo lo demás (números aleatorios comunes, ${c.replications} réplicas). Barra positiva = se ganaría producción eliminando esa variabilidad. Las barras tenues no son estadísticamente significativas.`),
    tornado(items, { unit: ' uds/h', fmt: (v) => v.toFixed(2) }),
    h('p', {}, `Sin ninguna variabilidad la producción cambiaría ${all.throughputPerHour.mean >= 0 ? '+' : ''}${fmtNum(all.throughputPerHour.mean)} uds/h (${pct(all.throughputPerHour.relative)}) y el lead time ${fmtTime(all.leadTimeMean.mean)}.`),
    table(
      ['Fuente', 'Δ producción (uds/h)', 'Δ lead time', 'Δ WIP', 'Significativo'],
      c.sources.map((s) => h('tr', {},
        h('td', {}, s.label),
        h('td', {}, `${fmtNum(s.effects.throughputPerHour.mean)} [${fmtNum(s.effects.throughputPerHour.ciLow)}, ${fmtNum(s.effects.throughputPerHour.ciHigh)}]`),
        h('td', {}, fmtTime(s.effects.leadTimeMean.mean)),
        h('td', {}, fmtNum(s.effects.wipMean.mean)),
        h('td', {}, s.effects.throughputPerHour.significant ? 'Sí' : 'No'),
      )),
    ),
  );
}

function renderCompare(ctx) {
  const others = ctx.models.filter((m) => m.id !== ctx.model.id);
  const sel = h('select', {}, h('option', { value: '' }, others.length ? 'Elige otro escenario…' : 'No hay otros modelos (duplica este para crear un escenario)'), others.map((m) => h('option', { value: m.id }, m.name)));
  sel.value = ctx.ui.compareWith || '';
  sel.addEventListener('change', () => (ctx.ui.compareWith = sel.value));
  const cmp = ctx.comparison;
  const keys = ['throughputPerHour', 'leadTimeMean', 'leadTimeP90', 'wipMean', 'fpy', 'operatorUtilizationMean', 'walkedMetersPerHour', 'oeeMean'];
  return h('section', { class: 'card' },
    h('h3', {}, 'Comparar escenarios'),
    h('p', { class: 'help' }, 'Ambos escenarios se simulan con las mismas semillas y se comparan réplica a réplica (diferencias pareadas): detecta mejoras pequeñas con muchas menos réplicas.'),
    h('div', { class: 'row' }, sel, h('button', { type: 'button', disabled: ctx.busy || undefined, onclick: () => sel.value && ctx.runCompare(sel.value) }, 'Comparar')),
    cmp
      ? table(
          ['Indicador', cmp.a.name, cmp.b.name, 'Diferencia (B − A)', 'IC de la diferencia', '¿Significativa?'],
          keys.filter((k) => cmp.kpis[k] && Number.isFinite(cmp.kpis[k].a.mean)).map((k) => {
            const d = cmp.kpis[k].difference;
            const better = KPI_LABELS[k].better;
            const good = d.significant && ((better === 'higher' && d.mean > 0) || (better === 'lower' && d.mean < 0));
            const bad = d.significant && ((better === 'higher' && d.mean < 0) || (better === 'lower' && d.mean > 0));
            return h('tr', {},
              h('td', {}, KPI_LABELS[k].label),
              h('td', {}, fmtKpi(k, cmp.kpis[k].a.mean)),
              h('td', {}, fmtKpi(k, cmp.kpis[k].b.mean)),
              h('td', { class: good ? 'good' : bad ? 'warn' : '' }, `${d.mean >= 0 ? '+' : ''}${fmtKpi(k, d.mean)}`),
              h('td', {}, `${fmtKpi(k, d.ciLow)} – ${fmtKpi(k, d.ciHigh)}`),
              h('td', {}, d.significant ? (good ? '✔ Mejora' : bad ? '✖ Empeora' : 'Sí') : 'No'),
            );
          }),
        )
      : null,
  );
}
