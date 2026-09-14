'use strict';
// Sin librerías: los mapas son SVG construidos a partir de la geometría
// proyectada (LCC México, km) que sirve /api/geo una sola vez.

const STATS = JSON.parse(document.getElementById('stats-data').textContent);
const DATES = STATS.forecast_dates;
const CATEGORIES = STATS.categories;

// ── Color ───────────────────────────────────────────────────────────────────
const RAMP = ['#FBEFC6', '#F1C46B', '#DC8F2A', '#B85C12', '#7F3408'];
const MSM = ['#F3E9DA', '#FCD37F', '#FFAA00', '#E60000', '#730000'];
const NO_DATA = '#D9D2C6';
const PROB_BREAKS = [0.2, CATEGORIES.media, CATEGORIES.alta, 0.75];
const PCT_BREAKS = [0.5, 0.8, 0.9, 0.95];
function classOf(v, breaks) { let i = 0; while (i < breaks.length && v >= breaks[i]) i += 1; return i; }
function probColor(p) { return p == null ? NO_DATA : RAMP[classOf(p, PROB_BREAKS)]; }
function category(p) { return p >= CATEGORIES.alta ? 'alta' : p >= CATEGORIES.media ? 'media' : 'baja'; }
const pct = (p) => `${Math.round(p * 100)} %`;

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
  const focus = el('path', { d: '' }, 'state-focus');
  svg.appendChild(focus);
  container.appendChild(svg);
  return { svg, paths, focus };
}
function paint(map, colorOf) {
  Object.entries(map.paths).forEach(([id, p]) => { p.setAttribute('fill', colorOf(id)); });
}
function focusState(map, entity) {
  Object.entries(map.paths).forEach(([id, p]) => p.classList.toggle('is-dim', MUN_STATE[id] !== entity));
  map.focus.setAttribute('d', entity ? ringsToPath(GEO.states[entity].rings) : '');
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
  hoverCard.innerHTML = `<p class="hover-name">${MUN_NAME[id]}</p><p class="hover-prob">${pct(p)}</p><p class="muted">probabilidad ${category(p)} de sequía D1+</p>`;
}
function forecastTip(id) {
  const p = forecastValues && forecastValues.values[id];
  return `<b>${MUN_NAME[id]}</b>, ${MUN_STATE[id]}${p == null ? '' : ` · ${pct(p)}`}`;
}

async function setDate(i) {
  dateIndex = i;
  renderTimeline();
  const target = DATES[i];
  forecastValues = await getJSON(`/api/forecast/values?date=${target}`);
  document.getElementById('timeline-label').innerHTML =
    `Pronóstico para el <b>${fmtDate(target)}</b> <small>· hecho con datos al ${fmtDate(forecastValues.feature_date)}</small>`;
  document.getElementById('national-caption').textContent = `probabilidad de sequía D1+ el ${fmtDate(target)}`;
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
  document.getElementById('state-summary').textContent = `${n} municipios · media ${pct(sum / n)}`;
  ['alta', 'media', 'baja'].forEach((k) => { document.getElementById(`tally-${k}`).textContent = tally[k]; });
  hoverCard.innerHTML = '<p class="muted">Pasa el cursor sobre un municipio.</p>';
}

function setState(entity) {
  focusState(nationalMap, entity);
  stateMap = buildMap(document.getElementById('state-map'), {
    bbox: GEO.states[entity].bbox, filter: (m) => m.state === entity, withStates: false, aspect: '1 / 1',
  });
  stateMap.focus.setAttribute('d', ringsToPath(GEO.states[entity].rings));
  attachHover(stateMap, forecastTip, setHover);
  if (forecastValues) { paint(stateMap, (id) => probColor(forecastValues.values[id])); updateStateSummary(); }
}

// ── Gráfica de AUC ──────────────────────────────────────────────────────────
function drawAucChart() {
  const data = STATS.oot_auc_by_date;
  const W = 640, H = 220, padL = 34, padR = 8, padT = 10, padB = 34;
  const iw = W - padL - padR, ih = H - padT - padB, bw = iw / data.length;
  const y = (v) => padT + ih - v * ih;
  let svg = `<svg viewBox="0 0 ${W} ${H}" aria-hidden="true">`;
  [0, 0.25, 0.5, 0.75, 1].forEach((t) => {
    svg += `<line class="axis" x1="${padL}" x2="${W - padR}" y1="${y(t)}" y2="${y(t)}"/><text x="${padL - 6}" y="${y(t) + 4}" text-anchor="end">${t.toFixed(2)}</text>`;
  });
  svg += `<line class="ref" x1="${padL}" x2="${W - padR}" y1="${y(0.5)}" y2="${y(0.5)}"/><text class="ref-label" x="${W - padR}" y="${y(0.5) - 5}" text-anchor="end">azar</text>`;
  data.forEach((d, i) => {
    const x = padL + i * bw + 3, w = bw - 6, top = y(d.auc ?? 0);
    svg += `<rect class="bar" data-i="${i}" x="${x}" y="${top}" width="${w}" height="${Math.max(0, y(0) - top)}" rx="3"/>`;
    svg += `<text x="${x + w / 2}" y="${H - padB + 16}" text-anchor="middle">${fmtDate(d.feature_date).replace(/ \d{4}$/, '')}</text>`;
    if (i === 0 || d.feature_date.slice(0, 4) !== data[i - 1].feature_date.slice(0, 4)) svg += `<text x="${x + w / 2}" y="${H - padB + 30}" text-anchor="middle">${d.feature_date.slice(0, 4)}</text>`;
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
      tip.innerHTML = `<b>${fmtDate(d.feature_date)}</b> → ${fmtDate(d.target_date)}<br>AUC <b>${d.auc?.toFixed(3) ?? '—'}</b> · con sequía: ${(d.positive_rate * 100).toFixed(1)} %`;
      const r = host.getBoundingClientRect();
      tip.style.left = `${Math.min(ev.clientX - r.left + 12, r.width - tip.offsetWidth)}px`;
      tip.style.top = `${ev.clientY - r.top - 8}px`;
    });
    hit.addEventListener('mouseleave', () => { tip.hidden = true; bars.forEach((b) => b.classList.remove('is-active')); });
  });
}

// ── Validación ──────────────────────────────────────────────────────────────
const validationSelect = document.getElementById('validation-select');
let validationValues = null, percentileOf = null;

async function updateValidation() {
  const opt = validationSelect.selectedOptions[0];
  validationValues = await getJSON(`/api/validation/values?date=${opt.value}`);
  document.getElementById('val-feature-date').textContent = fmtDate(opt.value);
  document.getElementById('val-target-date').textContent = fmtDate(opt.dataset.target);

  const sorted = Object.values(validationValues.prediction).sort((a, b) => a - b);
  percentileOf = (p) => { let lo = 0, hi = sorted.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < p) lo = mid + 1; else hi = mid; } return lo / sorted.length; };
  const withDrought = Object.entries(validationValues.real_index).filter(([, v]) => v >= 1).map(([id]) => id);
  const caught = withDrought.filter((id) => percentileOf(validationValues.prediction[id]) >= 0.9).length;
  document.getElementById('validation-catch').textContent = withDrought.length
    ? `De los ${withDrought.length} municipios con sequía D1+ el ${fmtDate(opt.dataset.target)}, ${caught} (${Math.round((caught / withDrought.length) * 100)} %) estaban en el 10 % que SeGuía marcó con más riesgo.`
    : 'Esa quincena ningún municipio tuvo sequía D1+ seis meses después.';

  paint(predMap, (id) => { const p = validationValues.prediction[id]; return p == null ? NO_DATA : RAMP[classOf(percentileOf(p), PCT_BREAKS)]; });
  paint(realMap, (id) => { const v = validationValues.real_index[id]; return v == null ? NO_DATA : MSM[v]; });
}
function predTip(id) { const p = validationValues.prediction[id]; return `<b>${MUN_NAME[id]}</b>, ${MUN_STATE[id]}${p == null ? '' : ` · percentil ${Math.round(percentileOf(p) * 100)} · ${pct(p)}`}`; }
function realTip(id) { const v = validationValues.real_index[id]; return `<b>${MUN_NAME[id]}</b>, ${MUN_STATE[id]} · ${v == null ? 'sin dato' : v >= 1 ? `D${v}` : 'sin sequía o D0'}`; }

// ── Arranque ────────────────────────────────────────────────────────────────
(async function init() {
  drawAucChart();
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
  const best = [...validationSelect.options].reduce((a, b) => (Number(b.dataset.auc) > Number(a.dataset.auc) ? b : a));
  validationSelect.value = best.value;
  validationSelect.addEventListener('change', updateValidation);
  await updateValidation();
})();
