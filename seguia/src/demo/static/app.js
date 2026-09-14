'use strict';

// ── Datos inyectados por la plantilla ───────────────────────────────────────
const STATS = JSON.parse(document.getElementById('stats-data').textContent);
const FORECAST_DATES = STATS.forecast_dates;
const CATEGORIES = STATS.categories;          // {baja: 0, media: .35, alta: .55}

// ── Escalas de color ────────────────────────────────────────────────────────
// Probabilidad: un solo matiz cálido, claro → oscuro (5 clases).
const PROB_RAMP = ['#FBEFC6', '#F1C46B', '#DC8F2A', '#B85C12', '#7F3408'];
// Observado: paleta oficial del Monitor de Sequía (D1–D4); sin sequía/D0 en papel.
const MSM = { 0: '#F3E9DA', 1: '#FCD37F', 2: '#FFAA00', 3: '#E60000', 4: '#730000' };
const NO_DATA = '#D9D2C6';

// Clases de color alineadas con las categorías: baja (<20, 20–35), media (35–55),
// alta (55–75, ≥75).
const PROB_BREAKS = [0.2, CATEGORIES.media, CATEGORIES.alta, 0.75];
function probColor(p) {
  if (p == null || Number.isNaN(p)) return NO_DATA;
  let i = 0;
  while (i < PROB_BREAKS.length && p >= PROB_BREAKS[i]) i += 1;
  return PROB_RAMP[i];
}
function category(p) {
  if (p >= CATEGORIES.alta) return 'alta';
  if (p >= CATEGORIES.media) return 'media';
  return 'baja';
}
function pct(p) { return `${Math.round(p * 100)} %`; }

// ── Fechas en español ───────────────────────────────────────────────────────
const MONTHS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
function fmtDate(iso, short = false) {
  if (!iso) return '—';
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return short ? `${MONTHS[m - 1]} ${y}` : `${d} ${MONTHS[m - 1]} ${y}`;
}
document.querySelectorAll('[data-date]').forEach((el) => {
  el.textContent = fmtDate(el.dataset.date, el.hasAttribute('data-short'));
});

// ── Mapa: solo México ───────────────────────────────────────────────────────
// Sin teselas del mundo: el país es una silueta de papel sobre arena y la vista
// no puede salirse de sus límites.
const MEXICO_BOUNDS = L.latLngBounds([14.2, -118.6], [33.0, -86.4]);
const geoCache = {};
async function getJSON(url) {
  if (!geoCache[url]) {
    geoCache[url] = fetch(url).then((r) => {
      if (!r.ok) throw new Error(`${r.status} ${url}`);
      return r.json();
    });
  }
  return geoCache[url];
}

async function createMexicoMap(id, { interactive = true } = {}) {
  const map = L.map(id, {
    zoomControl: interactive,
    attributionControl: false,
    scrollWheelZoom: interactive,
    dragging: interactive,
    doubleClickZoom: interactive,
    touchZoom: interactive,
    boxZoom: false,
    keyboard: interactive,
    maxBounds: MEXICO_BOUNDS.pad(0.05),
    maxBoundsViscosity: 1,
    minZoom: 4,
    maxZoom: 9,
  });
  const [country, states] = await Promise.all([
    getJSON('/api/geo/country'), getJSON('/api/geo/states'),
  ]);
  L.geoJSON(country, {
    style: { color: '#0B2A38', weight: 1, fillColor: '#EDE4D4', fillOpacity: 1 },
    interactive: false,
  }).addTo(map);
  L.geoJSON(states, {
    style: { color: 'rgba(11,42,56,.35)', weight: .7, fill: false },
    interactive: false,
  }).addTo(map);
  map.fitBounds(MEXICO_BOUNDS, { padding: [8, 8] });
  map._statesGeo = states;
  return map;
}

// Contorno del estado elegido, encima de los municipios.
let stateOutline = null;
function outlineState(map, entity) {
  if (stateOutline) map.removeLayer(stateOutline);
  const feature = map._statesGeo.features.find((f) => f.properties.entidad_federativa === entity);
  if (!feature) return;
  stateOutline = L.geoJSON(feature, {
    style: { color: '#0B2A38', weight: 1.6, fill: false }, interactive: false,
  }).addTo(map);
}

// ── Pronóstico ──────────────────────────────────────────────────────────────
const stateSelect = document.getElementById('state-select');
const dateRange = document.getElementById('date-range');
const dateLabel = document.getElementById('date-label');
const forecastStatus = document.getElementById('forecast-status');
const hoverCard = document.getElementById('hover-card');
let forecastMap = null;
let forecastLayer = null;

function setHover(feature) {
  if (!feature) {
    hoverCard.innerHTML = '<p class="hover-hint">Pasa el cursor sobre un municipio.</p>';
    return;
  }
  const p = feature.properties.prediction;
  hoverCard.innerHTML = `
    <p class="hover-name">${feature.properties.nombre_municipio}</p>
    <p class="hover-prob">${pct(p)}</p>
    <p class="hover-cat">probabilidad ${category(p)} de sequía D1+</p>`;
}

function updateDateLabel() {
  const target = FORECAST_DATES[Number(dateRange.value)];
  const t = new Date(target);
  const made = new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth() - STATS.horizon_months, t.getUTCDate()));
  dateLabel.innerHTML = `<b>${fmtDate(target)}</b> <small>· pronóstico hecho con datos al ${fmtDate(made.toISOString())}</small>`;
  dateRange.setAttribute('aria-valuetext', fmtDate(target));
}

async function updateForecast() {
  const entity = stateSelect.value;
  const date = FORECAST_DATES[Number(dateRange.value)];
  updateDateLabel();
  forecastStatus.hidden = false;
  forecastStatus.textContent = 'Cargando…';
  try {
    const geojson = await getJSON(`/api/forecast/map?entity=${encodeURIComponent(entity)}&date=${date}`);
    if (forecastLayer) forecastMap.removeLayer(forecastLayer);
    forecastLayer = L.geoJSON(geojson, {
      style: (f) => ({
        fillColor: probColor(f.properties.prediction), fillOpacity: 1,
        color: '#FFFFFF', weight: .8,
      }),
      onEachFeature(feature, layer) {
        layer.bindTooltip(
          `<b>${feature.properties.nombre_municipio}</b> · ${pct(feature.properties.prediction)}`,
          { sticky: true, className: 'mun-tip', direction: 'top', offset: [0, -6] },
        );
        layer.on('mouseover', () => { layer.setStyle({ weight: 2, color: '#0B2A38' }); layer.bringToFront(); setHover(feature); });
        layer.on('mouseout', () => { forecastLayer.resetStyle(layer); });
      },
    }).addTo(forecastMap);
    outlineState(forecastMap, entity);
    forecastMap.fitBounds(forecastLayer.getBounds(), { padding: [24, 24] });

    const tally = { alta: 0, media: 0, baja: 0 };
    geojson.features.forEach((f) => { tally[category(f.properties.prediction)] += 1; });
    document.getElementById('panel-state').textContent = entity;
    document.getElementById('panel-date').textContent =
      `${geojson.meta.n} municipios · probabilidad media ${pct(geojson.meta.mean)}`;
    ['alta', 'media', 'baja'].forEach((k) => { document.getElementById(`tally-${k}`).textContent = tally[k]; });
    setHover(null);
    forecastStatus.hidden = true;
  } catch (err) {
    forecastStatus.textContent = 'No se pudo cargar este pronóstico. Prueba otro estado o quincena.';
    console.error(err);
  }
}

// ── Gráfica: AUC por quincena (SVG inline) ──────────────────────────────────
function drawAucChart() {
  const data = STATS.oot_auc_by_date;
  const W = 640, H = 220, padL = 34, padR = 8, padT = 10, padB = 34;
  const iw = W - padL - padR, ih = H - padT - padB;
  const bw = iw / data.length;
  const y = (v) => padT + ih - v * ih;
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  let svg = `<svg viewBox="0 0 ${W} ${H}" aria-hidden="true">`;
  ticks.forEach((t) => {
    svg += `<line class="axis" x1="${padL}" x2="${W - padR}" y1="${y(t)}" y2="${y(t)}"/>`;
    svg += `<text x="${padL - 6}" y="${y(t) + 4}" text-anchor="end">${t.toFixed(2)}</text>`;
  });
  svg += `<line class="ref" x1="${padL}" x2="${W - padR}" y1="${y(0.5)}" y2="${y(0.5)}"/>`;
  svg += `<text class="ref-label" x="${W - padR}" y="${y(0.5) - 5}" text-anchor="end">azar</text>`;
  data.forEach((d, i) => {
    const x = padL + i * bw + 3;
    const w = bw - 6;
    const v = d.auc ?? 0;
    const top = y(v);
    svg += `<rect class="bar" data-i="${i}" x="${x}" y="${top}" width="${w}" height="${Math.max(0, y(0) - top)}" rx="3"/>`;
    svg += `<text x="${x + w / 2}" y="${H - padB + 16}" text-anchor="middle">${fmtDate(d.feature_date).replace(/ \d{4}$/, '')}</text>`;
    if (i === 0 || d.feature_date.slice(0, 4) !== data[i - 1].feature_date.slice(0, 4)) {
      svg += `<text x="${x + w / 2}" y="${H - padB + 30}" text-anchor="middle">${d.feature_date.slice(0, 4)}</text>`;
    }
    svg += `<rect class="bar-hit" data-i="${i}" x="${padL + i * bw}" y="${padT}" width="${bw}" height="${ih}"/>`;
  });
  svg += '</svg>';
  const host = document.getElementById('auc-chart');
  host.innerHTML = svg;

  const tip = document.getElementById('auc-tooltip');
  const bars = host.querySelectorAll('.bar');
  host.querySelectorAll('.bar-hit').forEach((hit) => {
    hit.addEventListener('mousemove', (ev) => {
      const d = data[Number(hit.dataset.i)];
      bars.forEach((b) => b.classList.toggle('is-active', b.dataset.i === hit.dataset.i));
      tip.hidden = false;
      tip.innerHTML = `<b>pronóstico del ${fmtDate(d.feature_date)}</b><br>observado el ${fmtDate(d.target_date)}<br>AUC <b>${d.auc?.toFixed(3) ?? '—'}</b> · con sequía: ${(d.positive_rate * 100).toFixed(1)} %`;
      const r = host.getBoundingClientRect();
      tip.style.left = `${Math.min(ev.clientX - r.left + 12, r.width - tip.offsetWidth)}px`;
      tip.style.top = `${ev.clientY - r.top - 8}px`;
    });
    hit.addEventListener('mouseleave', () => { tip.hidden = true; bars.forEach((b) => b.classList.remove('is-active')); });
  });
}

// ── Validación: predicho vs. observado ──────────────────────────────────────
const validationSelect = document.getElementById('validation-select');
let predMap = null, realMap = null, predLayer = null, realLayer = null;

async function updateValidation() {
  const opt = validationSelect.selectedOptions[0];
  const date = opt.value;
  document.getElementById('val-feature-date').textContent = fmtDate(date);
  document.getElementById('val-target-date').textContent = fmtDate(opt.dataset.target);
  const auc = Number(opt.dataset.auc);
  const pos = Number(opt.dataset.pos) * 100;
  document.getElementById('validation-summary').textContent =
    `Esa quincena, ${pos.toFixed(1)} % de los municipios tuvo sequía D1+ seis meses después · AUC ${Number.isFinite(auc) ? auc.toFixed(2) : '—'}`;

  const geojson = await getJSON(`/api/validation/map?date=${date}`);
  // Percentil de riesgo dentro de la quincena: el AUC mide orden, no nivel.
  // Las clases enfatizan la cola alta (< 50, 50–80, 80–90, 90–95, ≥ 95).
  const sorted = geojson.features.map((f) => f.properties.prediction).sort((a, b) => a - b);
  const percentile = (p) => {
    let lo = 0, hi = sorted.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < p) lo = mid + 1; else hi = mid; }
    return lo / sorted.length;
  };
  const PCT_BREAKS = [0.5, 0.8, 0.9, 0.95];
  const pctClass = (p) => { const q = percentile(p); let i = 0; while (i < PCT_BREAKS.length && q >= PCT_BREAKS[i]) i += 1; return i; };

  // Traducción tangible del AUC: ¿cuántos de los municipios que sí tuvieron
  // sequía estaban en el 10 % que el modelo marcó con más riesgo?
  const withDrought = geojson.features.filter((f) => f.properties.real_index >= 1);
  const caught = withDrought.filter((f) => percentile(f.properties.prediction) >= 0.9).length;
  document.getElementById('validation-catch').textContent = withDrought.length
    ? `De los ${withDrought.length} municipios que tuvieron sequía D1+ el ${fmtDate(opt.dataset.target)}, ${caught} (${Math.round((caught / withDrought.length) * 100)} %) estaban en el 10 % que SeGuía había marcado con más riesgo.`
    : 'Esa quincena ningún municipio tuvo sequía D1+ seis meses después.';

  if (predLayer) predMap.removeLayer(predLayer);
  if (realLayer) realMap.removeLayer(realLayer);
  predLayer = L.geoJSON(geojson, {
    style: (f) => ({ fillColor: PROB_RAMP[pctClass(f.properties.prediction)], fillOpacity: 1, color: '#FFFFFF', weight: .3 }),
    onEachFeature: (f, l) => l.bindTooltip(`<b>${f.properties.nombre_municipio}</b>, ${f.properties.entidad_federativa} · percentil ${Math.round(percentile(f.properties.prediction) * 100)} · ${pct(f.properties.prediction)}`, { sticky: true, className: 'mun-tip' }),
  }).addTo(predMap);
  realLayer = L.geoJSON(geojson, {
    style: (f) => {
      const v = f.properties.real_index;
      return { fillColor: v == null ? NO_DATA : MSM[Math.round(v)], fillOpacity: 1, color: '#FFFFFF', weight: .3 };
    },
    onEachFeature: (f, l) => {
      const v = f.properties.real_index;
      const label = v == null ? 'sin dato' : v >= 1 ? `D${Math.round(v)}` : 'sin sequía o D0';
      l.bindTooltip(`<b>${f.properties.nombre_municipio}</b>, ${f.properties.entidad_federativa} · ${label}`, { sticky: true, className: 'mun-tip' });
    },
  }).addTo(realMap);
}

// ── Arranque ────────────────────────────────────────────────────────────────
(async function init() {
  drawAucChart();
  forecastMap = await createMexicoMap('forecast-map');
  stateSelect.addEventListener('change', updateForecast);
  dateRange.addEventListener('input', updateForecast);
  document.getElementById('date-prev').addEventListener('click', () => { dateRange.stepDown(); updateForecast(); });
  document.getElementById('date-next').addEventListener('click', () => { dateRange.stepUp(); updateForecast(); });
  await updateForecast();

  [predMap, realMap] = await Promise.all([
    createMexicoMap('validation-pred-map', { interactive: false }),
    createMexicoMap('validation-real-map', { interactive: false }),
  ]);
  // La quincena mejor evaluada primero, para que la comparación sea legible;
  // el selector permite ver también las que fallan.
  const best = [...validationSelect.options].reduce((a, b) => (Number(b.dataset.auc) > Number(a.dataset.auc) ? b : a));
  validationSelect.value = best.value;
  validationSelect.addEventListener('change', updateValidation);
  await updateValidation();
})();
