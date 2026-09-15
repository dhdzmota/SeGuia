'use strict';
// Sin librerías: los mapas son SVG construidos a partir de la geometría
// proyectada (LCC México, km) que sirve /api/geo una sola vez.

const STATS = JSON.parse(document.getElementById('stats-data').textContent);
const DATES = STATS.forecast_dates;
const CATEGORIES = STATS.categories;

// ── Color ───────────────────────────────────────────────────────────────────
// Verde (sin sequía) → amarillo → naranja → rojo vivo → café (D4).
const RAMP = ['#7DBE6E', '#F2DE5A', '#F39A22', '#DE2A15', '#6B2A0E'];
const MSM = RAMP;             // observado: sin sequía/D0, D1, D2, D3, D4
const NO_DATA = '#D9D2C6';
// Clases del score: baja (<35) verde · media (35–45 amarillo, 45–55 naranja) · alta (55–75 rojo, ≥75 café)
const PROB_BREAKS = [CATEGORIES.media, (CATEGORIES.media + CATEGORIES.alta) / 2, CATEGORIES.alta, 0.75];
let PCT_BREAKS = [0.5, 0.8, 0.9, 0.95];   // editable con las manijas del mapa de validación
function classOf(v, breaks) { let i = 0; while (i < breaks.length && v >= breaks[i]) i += 1; return i; }
function probColor(p) { return p == null ? NO_DATA : RAMP[classOf(p, PROB_BREAKS)]; }
function category(p) { return p >= CATEGORIES.alta ? 'alta' : p >= CATEGORIES.media ? 'media' : 'baja'; }
const score = (p) => `${Math.round(p * 100)}`;

// ── Fechas ──────────────────────────────────────────────────────────────────
const MONTHS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
function fmtDate(iso, short = false) {
  if (!iso) return '—';
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return short ? `${MONTHS[m - 1]} ${y}` : `${d} ${MONTHS[m - 1]} ${y}`;
}
document.querySelectorAll('[data-date]').forEach((el) => { el.textContent = fmtDate(el.dataset.date, el.hasAttribute('data-short')); });

// ── Red ─────────────────────────────────────────────────────────────────────
const cache = {};
function getJSON(url) {
  if (!cache[url]) cache[url] = fetch(url).then((r) => { if (!r.ok) throw new Error(`${r.status} ${url}`); return r.json(); });
  return cache[url];
}

// ── SVG ─────────────────────────────────────────────────────────────────────
const SVG_NS = 'http://www.w3.org/2000/svg';
let GEO = null;               // /api/geo
const PATH_D = {};            // mun_id -> atributo d (calculado una vez)
let FLIP_Y = 0;               // y del SVG = FLIP_Y - y (km), para que el norte quede arriba

function ringsToPath(rings) {
  return rings.map((ring) => 'M' + ring.map(([x, y]) => `${x},${(FLIP_Y - y).toFixed(1)}`).join('L') + 'Z').join('');
}
function viewBoxFor(bbox, pad = 0.03) {
  const [minx, miny, maxx, maxy] = bbox;
  const w = maxx - minx, h = maxy - miny;
  const px = w * pad, py = h * pad;
  return `${minx - px} ${FLIP_Y - maxy - py} ${w + 2 * px} ${h + 2 * py}`;
}
function el(name, attrs = {}, cls = '') {
  const node = document.createElementNS(SVG_NS, name);
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  if (cls) node.setAttribute('class', cls);
  return node;
}

/** Dibuja un mapa de municipios. `filter` limita los municipios (zoom a estado). */
function buildMap(container, { bbox, filter = null, withStates = true, aspect = null }) {
  container.innerHTML = '';
  const svg = el('svg', { viewBox: viewBoxFor(bbox), preserveAspectRatio: 'xMidYMid meet', role: 'img' });
  if (aspect) svg.style.aspectRatio = aspect;
  svg.appendChild(el('path', { d: ringsToPath(GEO.country) }, 'country'));
  const layer = el('g');
  const paths = {};
  GEO.municipalities.forEach((m) => {
    if (filter && !filter(m)) return;
    const p = el('path', { d: PATH_D[m.id], 'data-id': m.id, fill: NO_DATA }, 'mun');
    layer.appendChild(p);
    paths[m.id] = p;
  });
  svg.appendChild(layer);
  if (withStates) {
    const states = el('g');
    Object.values(GEO.states).forEach((s) => states.appendChild(el('path', { d: ringsToPath(s.rings) }, 'state-line')));
    svg.appendChild(states);
  }
  const focusHalo = el('path', { d: '' }, 'state-focus-halo');
  const focus = el('path', { d: '' }, 'state-focus');
  svg.appendChild(focusHalo);
  svg.appendChild(focus);
  container.appendChild(svg);
  return { svg, paths, focus, focusHalo };
}
function paint(map, colorOf) {
  Object.entries(map.paths).forEach(([id, p]) => { p.setAttribute('fill', colorOf(id)); });
}
function focusState(map, entity) {
  const d = entity ? ringsToPath(GEO.states[entity].rings) : '';
  map.focusHalo.setAttribute('d', d);
  map.focus.setAttribute('d', d);
}

// ── Tooltip compartido ──────────────────────────────────────────────────────
const tooltip = document.getElementById('tooltip');
function attachHover(map, textOf, onHover) {
  map.svg.addEventListener('mousemove', (ev) => {
    const id = ev.target.dataset && ev.target.dataset.id;
    if (!id) { tooltip.hidden = true; return; }
    tooltip.hidden = false;
    tooltip.innerHTML = textOf(id);
    tooltip.style.left = `${ev.clientX + 14}px`;
    tooltip.style.top = `${ev.clientY - 30}px`;
    if (onHover) onHover(id);
  });
  map.svg.addEventListener('mouseleave', () => { tooltip.hidden = true; });
}

// ── Estado de la página ─────────────────────────────────────────────────────
const MUN_NAME = {}, MUN_STATE = {};
let dateIndex = 0;
let nationalMap = null, stateMap = null, predMap = null, realMap = null;
let forecastValues = null;

// ── Barra temporal ──────────────────────────────────────────────────────────
const rail = document.getElementById('timeline');
function buildTimeline() {
  DATES.forEach((d, i) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'tick'; b.setAttribute('role', 'radio');
    const [y, m, day] = d.split('-').map(Number);
    const showYear = i === 0 || DATES[i - 1].slice(0, 4) !== d.slice(0, 4);
    b.innerHTML = `<small>${day} ${MONTHS[m - 1]}${showYear ? `<b>${y}</b>` : '<b>&nbsp;</b>'}</small>`;
    b.addEventListener('click', () => setDate(i));
    rail.appendChild(b);
  });
  rail.addEventListener('keydown', (ev) => {
    if (ev.key === 'ArrowRight') setDate(Math.min(DATES.length - 1, dateIndex + 1));
    if (ev.key === 'ArrowLeft') setDate(Math.max(0, dateIndex - 1));
  });
}
function renderTimeline() {
  [...rail.children].forEach((b, i) => {
    b.setAttribute('aria-checked', String(i === dateIndex));
    b.tabIndex = i === dateIndex ? 0 : -1;
    b.classList.toggle('is-past', i < dateIndex);
  });
  rail.style.setProperty('--progress', `${(dateIndex / (DATES.length - 1)) * 100}%`);
}

// ── Pronóstico ──────────────────────────────────────────────────────────────
const stateSelect = document.getElementById('state-select');
const hoverCard = document.getElementById('hover-card');

function setHover(id) {
  const p = forecastValues && forecastValues.values[id];
  if (p == null) return;
  hoverCard.innerHTML = `<p class="hover-name">${MUN_NAME[id]}</p><p class="hover-prob">${score(p)}</p><p class="muted">score ${category(p)} de sequía D1+</p>`;
}
function forecastTip(id) {
  const p = forecastValues && forecastValues.values[id];
  return `<b>${MUN_NAME[id]}</b>, ${MUN_STATE[id]}${p == null ? '' : ` · score ${score(p)}`}`;
}

async function setDate(i) {
  dateIndex = i;
  renderTimeline();
  const target = DATES[i];
  forecastValues = await getJSON(`/api/forecast/values?date=${target}`);
  document.getElementById('timeline-label').innerHTML =
    `Pronóstico para el <b>${fmtDate(target)}</b> <small>· hecho con datos al ${fmtDate(forecastValues.feature_date)}</small>`;
  document.getElementById('national-caption').textContent = `score de sequía D1+ el ${fmtDate(target)}`;
  paint(nationalMap, (id) => probColor(forecastValues.values[id]));
  paint(stateMap, (id) => probColor(forecastValues.values[id]));
  updateStateSummary();
}

function updateStateSummary() {
  const entity = stateSelect.value;
  const ids = Object.keys(stateMap.paths);
  const tally = { alta: 0, media: 0, baja: 0 };
  let sum = 0, n = 0;
  ids.forEach((id) => { const p = forecastValues.values[id]; if (p == null) return; tally[category(p)] += 1; sum += p; n += 1; });
  document.getElementById('state-caption').textContent = entity;
  document.getElementById('state-summary').textContent = `${n} municipios · score medio ${score(sum / n)}`;
  ['alta', 'media', 'baja'].forEach((k) => { document.getElementById(`tally-${k}`).textContent = tally[k]; });
  hoverCard.innerHTML = '<p class="muted">Pasa el cursor sobre un municipio.</p>';
}

function setState(entity) {
  focusState(nationalMap, entity);
  stateMap = buildMap(document.getElementById('state-map'), {
    bbox: GEO.states[entity].bbox, filter: (m) => m.state === entity, withStates: false, aspect: '1 / 1',
  });
  focusState(stateMap, entity);
  attachHover(stateMap, forecastTip, setHover);
  if (forecastValues) { paint(stateMap, (id) => probColor(forecastValues.values[id])); updateStateSummary(); }
}

// ── Gráfica: sequías observadas, anticipadas o no ───────────────────────────
// Eje x = quincena evaluada (cuando se supo la respuesta). Cada barra son los
// municipios con sequía D1+; la parte oscura, los que seis meses antes ya
// estaban en el 10 % de mayor score.
function drawAucChart() {
  const data = STATS.oot_auc_by_date;
  const W = 640, H = 240, padL = 40, padR = 8, padT = 12, padB = 36;
  const iw = W - padL - padR, ih = H - padT - padB, bw = iw / data.length;
  const max = Math.max(...data.map((d) => d.positives), 1);
  const step = max > 200 ? 100 : max > 80 ? 50 : max > 40 ? 20 : 10;
  const top = Math.ceil(max / step) * step;
  const y = (v) => padT + ih - (v / top) * ih;
  let svg = `<svg viewBox="0 0 ${W} ${H}" aria-hidden="true">`;
  for (let t = 0; t <= top; t += step) {
    svg += `<line class="axis" x1="${padL}" x2="${W - padR}" y1="${y(t)}" y2="${y(t)}"/><text x="${padL - 6}" y="${y(t) + 4}" text-anchor="end">${t}</text>`;
  }
  data.forEach((d, i) => {
    const x = padL + i * bw + 3, w = bw - 6;
    const hit = d.captured_top10, miss = d.positives - d.captured_top10;
    svg += `<rect class="bar bar-miss" data-i="${i}" x="${x}" y="${y(d.positives)}" width="${w}" height="${Math.max(0, y(hit) - y(d.positives))}" rx="3"/>`;
    svg += `<rect class="bar bar-hit-part" data-i="${i}" x="${x}" y="${y(hit)}" width="${w}" height="${Math.max(0, y(0) - y(hit))}" rx="2"/>`;
    svg += `<text x="${x + w / 2}" y="${H - padB + 16}" text-anchor="middle">${fmtDate(d.target_date).replace(/ \d{4}$/, '')}</text>`;
    if (i === 0 || d.target_date.slice(0, 4) !== data[i - 1].target_date.slice(0, 4)) svg += `<text x="${x + w / 2}" y="${H - padB + 30}" text-anchor="middle">${d.target_date.slice(0, 4)}</text>`;
    svg += `<rect class="bar-hit" data-i="${i}" x="${padL + i * bw}" y="${padT}" width="${bw}" height="${ih}"/>`;
  });
  const host = document.getElementById('auc-chart');
  host.innerHTML = svg + '</svg>';
  const tip = document.getElementById('auc-tooltip');
  const bars = host.querySelectorAll('.bar');
  host.querySelectorAll('.bar-hit').forEach((hit) => {
    hit.addEventListener('mousemove', (ev) => {
      const d = data[Number(hit.dataset.i)];
      bars.forEach((b) => b.classList.toggle('is-active', b.dataset.i === hit.dataset.i));
      tip.hidden = false;
      tip.innerHTML = `<b>Observado el ${fmtDate(d.target_date)}</b> · pronóstico del ${fmtDate(d.feature_date)}<br>${d.positives} municipios con sequía · ${d.captured_top10} anticipados (${d.positives ? Math.round((d.captured_top10 / d.positives) * 100) : 0} %)<br>${d.persisting} ya estaban en sequía al pronosticar · AUC ${d.auc?.toFixed(2) ?? '—'}`;
      const r = host.getBoundingClientRect();
      tip.style.left = `${Math.min(ev.clientX - r.left + 12, r.width - tip.offsetWidth)}px`;
      tip.style.top = `${ev.clientY - r.top - 8}px`;
    });
    hit.addEventListener('mouseleave', () => { tip.hidden = true; bars.forEach((b) => b.classList.remove('is-active')); });
    hit.addEventListener('click', () => { validationSelect.selectedIndex = Number(hit.dataset.i); updateValidation(); document.getElementById('validation-select').scrollIntoView({ behavior: 'smooth', block: 'center' }); });
  });
}

// ── Validación ──────────────────────────────────────────────────────────────
const validationSelect = document.getElementById('validation-select');
let validationValues = null, percentileOf = null;

function storyFor(d) {
  if (!d.positives) return 'Esa quincena ningún municipio tuvo sequía D1+.';
  const parts = [`${d.persisting} de los ${d.positives} ya estaban en sequía cuando se hizo el pronóstico`];
  if (d.mean_percentile_persisting != null) parts[0] += ` (el modelo los puso en el percentil ${d.mean_percentile_persisting} en promedio)`;
  if (d.new) {
    const where = d.new_top_states.map((s) => `${s.state} ${s.n}`).join(', ');
    parts.push(`${d.new} eran sequías nuevas${where ? ` —sobre todo en ${where}—` : ''} y el modelo las dejó en el percentil ${d.mean_percentile_new}: ${d.mean_percentile_new >= 80 ? 'las vio venir' : d.mean_percentile_new >= 60 ? 'las vio a medias' : 'no las vio venir'}`);
  }
  return parts.join('. ') + '.';
}

async function updateValidation() {
  const opt = validationSelect.selectedOptions[0];
  const d = STATS.oot_auc_by_date[Number(opt.dataset.i)];
  validationValues = await getJSON(`/api/validation/values?date=${opt.value}`);
  document.getElementById('val-feature-date').textContent = fmtDate(d.feature_date);
  document.getElementById('val-target-date').textContent = fmtDate(d.target_date);

  const sorted = Object.values(validationValues.prediction).sort((a, b) => a - b);
  percentileOf = (p) => { let lo = 0, hi = sorted.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < p) lo = mid + 1; else hi = mid; } return lo / sorted.length; };
  document.getElementById('validation-catch').textContent = d.positives
    ? `El ${fmtDate(d.target_date)} hubo ${d.positives} municipios con sequía D1+; ${d.captured_top10} (${Math.round((d.captured_top10 / d.positives) * 100)} %) estaban en el 10 % de mayor score seis meses antes.`
    : `El ${fmtDate(d.target_date)} ningún municipio tuvo sequía D1+.`;
  document.getElementById('validation-story').textContent = storyFor(d);

  paint(predMap, (id) => { const p = validationValues.prediction[id]; return p == null ? NO_DATA : RAMP[classOf(percentileOf(p), PCT_BREAKS)]; });
  paint(realMap, (id) => { const v = validationValues.real_index[id]; return v == null ? NO_DATA : MSM[v]; });
}
// ── Cortes de color del mapa de percentiles (4 manijas) ─────────────────────
const NAMES = ['verde', 'amarillo', 'naranja', 'rojo', 'café'];
function initBreaks() {
  const box = document.getElementById('pct-breaks');
  const inputs = [...box.querySelectorAll('input[type="range"]')];
  const ramp = document.getElementById('pct-ramp');
  const labels = document.getElementById('pct-labels');
  const render = () => {
    const b = PCT_BREAKS.map((v) => Math.round(v * 100));
    const stops = [0, ...b, 100];
    ramp.style.background = `linear-gradient(90deg, ${RAMP.map((c, i) => `${c} ${stops[i]}% ${stops[i + 1]}%`).join(', ')})`;
    labels.innerHTML = RAMP.map((c, i) => {
      const range = i === 0 ? `&lt; ${stops[1]}` : i === RAMP.length - 1 ? `≥ ${stops[i]}` : `${stops[i]}–${stops[i + 1]}`;
      return `<li><i style="background:${c}"></i>${NAMES[i]} ${range}</li>`;
    }).join('');
  };
  inputs.forEach((input) => {
    input.addEventListener('input', () => {
      const i = Number(input.dataset.i);
      let v = Number(input.value);
      // las manijas no se cruzan: cada corte queda entre sus vecinos
      const lo = i === 0 ? 1 : Math.round(PCT_BREAKS[i - 1] * 100) + 1;
      const hi = i === inputs.length - 1 ? 99 : Math.round(PCT_BREAKS[i + 1] * 100) - 1;
      v = Math.min(hi, Math.max(lo, v));
      input.value = v;
      PCT_BREAKS[i] = v / 100;
      render();
      if (predMap && validationValues) paint(predMap, (id) => { const p = validationValues.prediction[id]; return p == null ? NO_DATA : RAMP[classOf(percentileOf(p), PCT_BREAKS)]; });
    });
  });
  render();
}

function predTip(id) { const p = validationValues.prediction[id]; return `<b>${MUN_NAME[id]}</b>, ${MUN_STATE[id]}${p == null ? '' : ` · percentil ${Math.round(percentileOf(p) * 100)} · score ${score(p)}`}`; }
function realTip(id) { const v = validationValues.real_index[id]; return `<b>${MUN_NAME[id]}</b>, ${MUN_STATE[id]} · ${v == null ? 'sin dato' : v >= 1 ? `D${v}` : 'sin sequía o D0'}`; }

// ── Diagrama: ventanas de entrenamiento, evaluación y pronóstico ────────────
function drawTimeline() {
  const m = STATS.model;
  const t = (iso) => new Date(iso).getTime();
  const start = new Date(m.training_from.slice(0, 4) + '-01-01').getTime();
  const end = new Date((Number(DATES[DATES.length - 1].slice(0, 4)) + 1) + '-01-01').getTime();
  const W = 900, padL = 150, padR = 16, rowH = 34, gap = 10, top = 44;
  const rows = [
    { label: 'Entrenamiento', from: m.training_from, to: m.training_to, cls: 'band-train', text: `${fmtDate(m.training_from, true)} → ${fmtDate(m.training_to, true)}` },
    { label: 'Fuera de entrenamiento', from: m.training_to, to: m.oot_to, cls: 'band-oot', text: `${fmtDate(m.oot_to, true)}` },
    { label: 'Datos observados', from: m.training_from, to: STATS.data.conagua_last_date, cls: 'band-data', text: `CONAGUA al ${fmtDate(STATS.data.conagua_last_date)}` },
    { label: 'Pronóstico posible', from: DATES[0], to: DATES[DATES.length - 1], cls: 'band-forecast', text: `${fmtDate(DATES[0])} → ${fmtDate(DATES[DATES.length - 1])}` },
  ];
  const H = top + rows.length * (rowH + gap) + 8;
  const x = (iso) => padL + ((t(iso) - start) / (end - start)) * (W - padL - padR);
  let svg = `<svg viewBox="0 0 ${W} ${H}" aria-hidden="true">`;
  for (let yr = new Date(start).getFullYear(); yr <= new Date(end).getFullYear(); yr += 1) {
    const xx = x(`${yr}-01-01`);
    svg += `<line class="grid" x1="${xx}" x2="${xx}" y1="${top - 6}" y2="${H - 8}"/><text class="yr" x="${xx + 3}" y="${top - 10}">${yr}</text>`;
  }
  rows.forEach((r, i) => {
    const y = top + i * (rowH + gap);
    const x1 = x(r.from), x2 = Math.max(x(r.to), x1 + 2);
    svg += `<text class="lbl" x="${padL - 12}" y="${y + rowH / 2 + 4}" text-anchor="end">${r.label}</text>`;
    svg += `<rect class="${r.cls}" x="${x1}" y="${y}" width="${x2 - x1}" height="${rowH}" rx="4"/>`;
    const wide = x2 - x1 > 150;
    svg += `<text class="${wide ? 'band-lbl' : ''}" x="${wide ? x1 + 10 : x2 + 8}" y="${y + rowH / 2 + 4}">${r.text}</text>`;
  });
  const tx = x(STATS.today);
  svg += `<line class="today" x1="${tx}" x2="${tx}" y1="${top - 6}" y2="${H - 8}"/><text class="today-lbl" x="${tx}" y="${top - 24}" text-anchor="middle">hoy</text>`;
  document.getElementById('timeline-diagram').innerHTML = svg + '</svg>';
}

function drawSplitDots() {
  // 100 puntos = 100 % de las filas de la ventana de entrenamiento, en orden
  // barajado con semilla fija para transmitir que el reparto es aleatorio.
  const cls = [...Array(60).fill('dot-train'), ...Array(20).fill('dot-dev'), ...Array(20).fill('dot-test')];
  let seed = 69;
  const rnd = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
  for (let i = cls.length - 1; i > 0; i -= 1) { const j = Math.floor(rnd() * (i + 1)); [cls[i], cls[j]] = [cls[j], cls[i]]; }
  document.getElementById('split-dots').innerHTML = cls.map((c) => `<i class="${c}"></i>`).join('');
}

// ── Arranque ────────────────────────────────────────────────────────────────
(async function init() {
  drawAucChart();
  drawTimeline();
  drawSplitDots();
  initBreaks();
  buildTimeline();
  GEO = await getJSON('/api/geo');
  FLIP_Y = GEO.bbox[3];
  GEO.municipalities.forEach((m) => { MUN_NAME[m.id] = m.name; MUN_STATE[m.id] = m.state; PATH_D[m.id] = ringsToPath(m.rings); });

  nationalMap = buildMap(document.getElementById('national-map'), { bbox: GEO.bbox });
  attachHover(nationalMap, forecastTip, setHover);
  nationalMap.svg.addEventListener('click', (ev) => {
    const id = ev.target.dataset && ev.target.dataset.id;
    if (id) { stateSelect.value = MUN_STATE[id]; setState(MUN_STATE[id]); }
  });
  stateSelect.addEventListener('change', () => setState(stateSelect.value));
  setState(stateSelect.value);
  await setDate(0);

  predMap = buildMap(document.getElementById('val-pred-map'), { bbox: GEO.bbox });
  realMap = buildMap(document.getElementById('val-real-map'), { bbox: GEO.bbox });
  attachHover(predMap, predTip);
  attachHover(realMap, realTip);
  const best = STATS.oot_auc_by_date.reduce((a, b, i) => ((b.auc ?? 0) > (STATS.oot_auc_by_date[a].auc ?? 0) ? i : a), 0);
  validationSelect.selectedIndex = best;
  validationSelect.addEventListener('change', updateValidation);
  await updateValidation();
})();
