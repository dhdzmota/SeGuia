'use strict';

// ── Color scale (green → yellow → orange → red) ───────────────────────────────
const SCALE = [
  [0.00, '#4dac26'],
  [0.15, '#b8e186'],
  [0.35, '#f7e353'],
  [0.50, '#f4a93a'],
  [0.65, '#f46d43'],
  [0.80, '#d73027'],
  [1.00, '#a50026'],
];

function getColor(v) {
  if (v == null || isNaN(v)) return '#d1d5db';
  for (let i = SCALE.length - 1; i >= 0; i--) {
    if (v >= SCALE[i][0]) return SCALE[i][1];
  }
  return SCALE[0][1];
}

function featureStyle(feature) {
  const v = feature.properties.value ?? feature.properties.prediction;
  return {
    fillColor: getColor(v),
    weight: 0.8,
    opacity: 1,
    color: '#fff',
    fillOpacity: 0.85,
  };
}

function popup(feature, label) {
  const v = feature.properties.value ?? feature.properties.prediction;
  const fmt = v != null && !isNaN(v) ? (v * 100).toFixed(1) + '%' : 'Sin datos';
  return `<b style="font-size:13px">${feature.properties.nombre_municipio}</b>
          <br><span style="color:#6b7280">${label}:</span> <b>${fmt}</b>`;
}

// ── Leaflet helpers ───────────────────────────────────────────────────────────
function createMap(id, center = [23.6, -102.5], zoom = 4) {
  const map = L.map(id, { zoomControl: true }).setView(center, zoom);
  L.tileLayer(
    'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
    {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; ' +
        '<a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
    }
  ).addTo(map);
  return map;
}

function renderGeoJSON(map, geojson, label, existingLayer) {
  if (existingLayer) map.removeLayer(existingLayer);
  const layer = L.geoJSON(geojson, {
    style: featureStyle,
    onEachFeature(feature, l) {
      l.bindTooltip(popup(feature, label), { sticky: true });
      l.on('mouseover', () => l.setStyle({ weight: 2, color: '#334155' }));
      l.on('mouseout', () => layer.resetStyle(l));
    },
  }).addTo(map);
  if (layer.getBounds().isValid()) {
    map.fitBounds(layer.getBounds(), { padding: [16, 16] });
  }
  return layer;
}

// ── Forecast map ──────────────────────────────────────────────────────────────
const forecastMap = createMap('forecast-map', [23.6, -102.5], 5);
let forecastLayer = null;

async function updateForecastMap() {
  const entity = encodeURIComponent(document.getElementById('state-select').value);
  const date   = encodeURIComponent(document.getElementById('date-select').value);
  const spinner = document.getElementById('forecast-spinner');
  const errBox  = document.getElementById('forecast-error');

  spinner.classList.remove('hidden');
  errBox.classList.add('hidden');

  try {
    const res = await fetch(`/api/forecast/map?entity=${entity}&date=${date}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const geojson = await res.json();
    forecastLayer = renderGeoJSON(forecastMap, geojson, 'Probabilidad sequía', forecastLayer);
  } catch (err) {
    errBox.classList.remove('hidden');
    console.error('Forecast map error:', err);
  } finally {
    spinner.classList.add('hidden');
  }
}

document.getElementById('state-select').addEventListener('change', updateForecastMap);
document.getElementById('date-select').addEventListener('change', updateForecastMap);
updateForecastMap();

// ── Validation maps ───────────────────────────────────────────────────────────
async function loadValidationMap(mapId, layer, label) {
  const map = createMap(mapId);
  const spinner = document.getElementById(`${mapId}-spinner`);
  if (spinner) spinner.classList.remove('hidden');

  try {
    const res = await fetch(`/api/validation/map?layer=${layer}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const geojson = await res.json();
    renderGeoJSON(map, geojson, label, null);
  } catch (err) {
    console.error(`Validation map (${layer}) error:`, err);
  } finally {
    if (spinner) spinner.classList.add('hidden');
  }
}

loadValidationMap('val-pred-map', 'prediction',  'Probabilidad sequía');
loadValidationMap('val-real-map', 'real_value',   'Índice sequía real');
