"""
API y pagina de la demo de SeGuia.

Al arrancar calcula una sola vez:
  * el pronostico (probabilidad de sequia D1+ a 6 meses) para cada
    municipio y cada quincena posterior al ultimo dato etiquetado;
  * la validacion: para cada quincena del OOT, lo que el modelo predijo y
    lo que CONAGUA reporto seis meses despues, con AUC por fecha;
  * la procedencia (fechas de datos, version del modelo, ventana de
    entrenamiento) leida de download_manifest.json, split_info.json y
    models/SeGuia.json;
  * la geometria municipal, estatal y nacional proyectada (LCC) en km.
La pagina solo pide GeoJSON por estado/fecha.
"""

from contextlib import asynccontextmanager
import json
import os

import geopandas as gpd
import numpy as np
import pandas as pd
from pandas.tseries.offsets import DateOffset
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sklearn.metrics import roc_auc_score

from src.data.utils import (
    check_if_filepath_exists, get_general_path, join_paths
)
from src.models.model_utils import (
    HORIZON_MONTHS, OOT_MONTHS, PROCESSED_DATA, MODEL_PATH,
    read_features, read_xy_set, get_model, predict,
)

INTERIM_DATA = 'data/interim/'
MUNICIPAL_DATA = 'municipal_data.pkl'
ALL_FEATURES_FILE = 'all_features.parquet'
DOWNLOAD_MANIFEST = 'data/raw/download_manifest.json'
SPLIT_INFO = 'split_info.json'
PRODUCTION_INFO = 'SeGuia.json'
NON_FEATURE_COLS = ['mun_id', 'standard_date']
MEXICO_EPSG = "EPSG:6362"
# Tolerancias de simplificacion (metros) para servir geometria ligera.
MUNICIPAL_SIMPLIFY_M = 900
STATE_SIMPLIFY_M = 2500
# Categorias de probabilidad mostradas en la UI (limites inferiores).
CATEGORY_THRESHOLDS = {'baja': 0.0, 'media': 0.35, 'alta': 0.55}

_here = os.path.dirname(os.path.abspath(__file__))


class _AppState:
    """Estado calculado una vez al arrancar."""
    geo: dict = None                 # geometria proyectada en km
    muni_names: pd.DataFrame = None  # index mun_id; nombre, entidad
    forecast_df: pd.DataFrame = None  # mun_id, feature/target_date, prediction
    validation_df: pd.DataFrame = None  # + real_index, real_binary
    validation_dates: list = None  # [{feature_date, target_date, auc, ...}]
    stats: dict = None


_state = _AppState()


def _read_json(path):
    if not check_if_filepath_exists(path):
        return None
    with open(path) as file:
        return json.load(file)


def _date_from_index(index):
    return pd.to_datetime(
        pd.Series(index).str.split('__').str[1], format='%Y%m%d'
    ).values


def _fmt(date):
    return pd.Timestamp(date).strftime('%Y-%m-%d')


def _summarize_fortnight(feature_date, group):
    """Resumen de una quincena del OOT: AUC, cuantos municipios tuvieron
    sequia, cuantos de ellos ya la tenian al pronosticar (persistentes) y
    cuantos estaban en el 10 % de mayor score (anticipados)."""
    y, p = group['real_binary'], group['prediction']
    rank = p.rank(pct=True)
    positives = group[y == 1]
    persisting = positives[positives['drought_now'] == 1]
    new = positives[positives['drought_now'] == 0]
    new_states = new['state'].value_counts().head(3)
    return {
        'feature_date': _fmt(feature_date),
        'target_date': _fmt(group['target_date'].iloc[0]),
        'auc': (
            round(float(roc_auc_score(y, p)), 3) if y.nunique() > 1 else None
        ),
        'positive_rate': round(float(y.mean()), 4),
        'n': int(len(group)),
        'positives': int(len(positives)),
        'captured_top10': int((rank[positives.index] >= 0.9).sum()),
        'persisting': int(len(persisting)),
        'new': int(len(new)),
        'new_top_states': [
            {'state': s, 'n': int(n)} for s, n in new_states.items()
        ],
        'mean_percentile_new': (
            round(float(rank[new.index].mean() * 100)) if len(new) else None
        ),
        'mean_percentile_persisting': (
            round(float(rank[persisting.index].mean() * 100))
            if len(persisting) else None
        ),
    }


def _bbox_km(bounds):
    return [round(float(v) / 1000, 1) for v in bounds]


def _rings_km(geom):
    """Anillos exteriores de un (Multi)Polygon como listas [x, y] en km,
    redondeados a 100 m: suficiente para dibujar y ligero de transmitir."""
    polygons = geom.geoms if geom.geom_type == 'MultiPolygon' else [geom]
    return [
        [[round(x / 1000, 1), round(y / 1000, 1)]
         for x, y in polygon.exterior.coords]
        for polygon in polygons if not polygon.is_empty
    ]


def _build_provenance(split_info, manifest, production, report):
    nasa = (manifest or {}).get('nasa') or {}
    drought = (manifest or {}).get('drought') or {}
    metrics = (production or {}).get('metrics') or {}
    nasa_last = nasa.get('last_date_max')
    params = (report or {}).get('params') or {}
    return {
        'horizon_months': HORIZON_MONTHS,
        'oot_months': OOT_MONTHS,
        'today': pd.Timestamp.today().strftime('%Y-%m-%d'),
        'municipalities': int(len(_state.muni_names)),
        'data': {
            'conagua_last_date': drought.get('last_date'),
            'nasa_last_date': (
                f'{nasa_last[:4]}-{nasa_last[4:6]}-{nasa_last[6:]}'
                if nasa_last else None
            ),
            'downloaded_at': (manifest or {}).get('run_at'),
        },
        'model': {
            'run_id': (production or {}).get('run_id'),
            'promoted_at': (production or {}).get('promoted_at'),
            'training_from': (split_info or {}).get('min_training_date'),
            'training_to': (split_info or {}).get('max_training_date'),
            'oot_to': (split_info or {}).get('last_labelled_date'),
            'rows': (split_info or {}).get('rows'),
            'metrics': {
                name: {
                    k: values.get(k)
                    for k in ('auc', 'aucpr', 'positive_rate', 'rows')
                }
                for name, values in metrics.items()
            },
            'n_features': (report or {}).get('n_features'),
            'best_iteration': (report or {}).get('best_iteration'),
            'xgboost_version': (report or {}).get('xgboost_version'),
            'params': {
                k: params.get(k) for k in (
                    'n_estimators', 'max_depth', 'learning_rate', 'subsample',
                    'colsample_bytree', 'reg_alpha', 'reg_lambda', 'gamma',
                    'scale_pos_weight', 'early_stopping_rounds',
                ) if k in params
            },
        },
        'categories': CATEGORY_THRESHOLDS,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    gp = get_general_path()
    muni_info = pd.read_pickle(join_paths(gp, INTERIM_DATA, MUNICIPAL_DATA))
    model = get_model()
    split_info = _read_json(join_paths(gp, PROCESSED_DATA, SPLIT_INFO))
    manifest = _read_json(join_paths(gp, DOWNLOAD_MANIFEST))
    production = _read_json(join_paths(gp, MODEL_PATH, PRODUCTION_INFO))
    report = _read_json(
        join_paths(gp, (production or {}).get('metrics_file', ''))
    ) if production else None

    features = read_features(
        join_paths(gp, INTERIM_DATA, ALL_FEATURES_FILE)
    )
    feature_cols = [
        c for c in features.columns if c not in NON_FEATURE_COLS
    ]
    index_by_key = pd.Series(np.arange(len(features)), index=features.index)

    # ── Pronostico: filas posteriores al ultimo dato etiquetado ─────────────
    x_oot, y_oot = read_xy_set('oot')
    last_labelled = pd.Timestamp(
        split_info['last_labelled_date'] if split_info
        else _date_from_index(x_oot.index).max()
    )
    future_mask = features['standard_date'] > last_labelled
    future = features.loc[future_mask]
    _state.forecast_df = pd.DataFrame({
        'mun_id': future['mun_id'].values,
        'feature_date': future['standard_date'].values,
        'target_date': (
            future['standard_date'] + DateOffset(months=HORIZON_MONTHS)
        ).values,
        'prediction': predict(model, future[feature_cols]),
    })
    del future

    # ── Validacion: cada quincena del OOT vs. lo observado 6 meses despues ──
    oot_dates = _date_from_index(x_oot.index)
    target_dates = (
        pd.to_datetime(oot_dates) + DateOffset(months=HORIZON_MONTHS)
    )
    mun_ids = pd.Series(x_oot.index).str.split('__').str[0].values
    target_keys = (
        mun_ids + '__' + pd.Series(target_dates).dt.strftime('%Y%m%d').values
    )
    positions = index_by_key.reindex(target_keys)
    real_index = np.full(len(target_keys), np.nan)
    found = positions.notna().values
    real_index[found] = features['num_drought_index'].values[
        positions[found].astype(int)
    ]
    _state.validation_df = pd.DataFrame({
        'mun_id': mun_ids,
        'feature_date': oot_dates,
        'target_date': target_dates.values,
        'prediction': predict(model, x_oot),
        'real_index': real_index,
        'real_binary': y_oot.values,
        # Si el municipio ya estaba en sequia (D1+) al hacer el pronostico:
        # separa "persistencia" de "inicio", que es donde falla el modelo.
        'drought_now': (x_oot['num_drought_index'] >= 1).values.astype(int),
    })
    del features, x_oot, y_oot
    _state.validation_df['state'] = _state.validation_df['mun_id'].map(
        muni_info['entidad_federativa']
    )
    _state.validation_dates = [
        _summarize_fortnight(feature_date, group)
        for feature_date, group in _state.validation_df.groupby('feature_date')
    ]

    # ── Geometria en la proyeccion oficial (LCC Mexico, EPSG:6362), en km ─
    # La pagina dibuja SVG directamente: sin librerias de mapas ni teselas.
    muni_gdf = gpd.GeoDataFrame(muni_info, geometry='geometry')
    if muni_gdf.crs is None:
        muni_gdf = muni_gdf.set_crs(MEXICO_EPSG)
    muni_gdf = muni_gdf.to_crs(MEXICO_EPSG)
    states = muni_gdf[['entidad_federativa', 'geometry']].dissolve(
        by='entidad_federativa'
    )
    country = gpd.GeoSeries([states.geometry.union_all()], crs=MEXICO_EPSG)
    _state.geo = {
        'crs': MEXICO_EPSG,
        'units': 'km',
        'bbox': _bbox_km(country.total_bounds),
        'country': _rings_km(country.iloc[0].simplify(STATE_SIMPLIFY_M)),
        'states': {
            name: {
                'bbox': _bbox_km(geom.bounds),
                'rings': _rings_km(geom.simplify(STATE_SIMPLIFY_M)),
            }
            for name, geom in states.geometry.items()
        },
        'municipalities': [
            {
                'id': mun_id,
                'name': row['nombre_municipio'],
                'state': row['entidad_federativa'],
                'rings': _rings_km(
                    row.geometry.simplify(MUNICIPAL_SIMPLIFY_M)
                ),
            }
            for mun_id, row in muni_gdf.iterrows()
        ],
    }
    _state.muni_names = muni_info[['nombre_municipio', 'entidad_federativa']]

    _state.stats = _build_provenance(
        split_info, manifest, production, report
    )
    _state.stats['oot_auc_by_date'] = _state.validation_dates
    _state.stats['forecast_dates'] = sorted(
        _fmt(d) for d in _state.forecast_df['target_date'].unique()
    )
    _state.stats['states'] = sorted(
        muni_info['entidad_federativa'].unique().tolist()
    )
    yield


app = FastAPI(title="SeGuía API", version="3.0.0", lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(_here, "templates"))
app.mount(
    "/static", StaticFiles(directory=os.path.join(_here, "static")),
    name="static",
)

_refs = join_paths(get_general_path(), "references")
if os.path.isdir(_refs):
    app.mount("/references", StaticFiles(directory=_refs), name="references")


# ── Rutas ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"stats": _state.stats}
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/stats")
def stats():
    return _state.stats


@app.get("/api/geo")
def geo():
    """Toda la geometria de una vez; la pagina la cachea y solo pide
    valores por municipio en las demas rutas."""
    return JSONResponse(content=_state.geo)


@app.get("/api/forecast/values")
def forecast_values(
    date: str = Query(..., description="Fecha objetivo (YYYY-MM-DD)"),
):
    df = _state.forecast_df
    rows = df[df['target_date'] == pd.Timestamp(date)]
    if rows.empty:
        raise HTTPException(404, f"Sin pronostico para {date!r}.")
    return {
        'target_date': date,
        'feature_date': _fmt(rows['feature_date'].iloc[0]),
        'values': {
            m: round(float(p), 4)
            for m, p in zip(rows['mun_id'], rows['prediction'])
        },
    }


@app.get("/api/validation/values")
def validation_values(
    date: str = Query(..., description="Quincena OOT (YYYY-MM-DD)"),
):
    df = _state.validation_df
    rows = df[df['feature_date'] == pd.Timestamp(date)]
    if rows.empty:
        raise HTTPException(404, f"Sin validacion para {date!r}.")
    info = next(
        d for d in _state.validation_dates if d['feature_date'] == date
    )
    return {
        'meta': info,
        'prediction': {
            m: round(float(p), 4)
            for m, p in zip(rows['mun_id'], rows['prediction'])
        },
        'real_index': {
            m: (None if pd.isna(v) else int(v))
            for m, v in zip(rows['mun_id'], rows['real_index'])
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
