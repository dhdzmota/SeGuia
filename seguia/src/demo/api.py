from contextlib import asynccontextmanager
import json
import os
from typing import Optional

import geopandas as gpd
import pandas as pd
from pandas.tseries.offsets import DateOffset
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.data.utils import get_general_path, join_paths
from src.models.model_utils import (
    read_features, read_xy_set, get_model, predict
)

INTERIM_DATA = 'data/interim/'
MUNICIPAL_DATA = 'municipal_data.pkl'
ALL_FEATURES_FILE = 'all_features.parquet'
DROP_COLS = ['mun_id', 'standard_date', 'future_date']
MONTHS = 6
MEXICO_EPSG = "EPSG:6362"
WGS84 = "EPSG:4326"
MAX_DROUGHT_INDEX = 4.0

_here = os.path.dirname(os.path.abspath(__file__))


class _AppState:
    """Runtime state populated once at startup."""
    municipal_wgs84: gpd.GeoDataFrame = None
    forecast_df: pd.DataFrame = None      # columns: mun_id, future_date (str), prediction
    val_df: pd.DataFrame = None           # index: mun_id; columns: prediction, real_value
    states: list = None
    dates: list = None
    validation_date: str = None
    oot_auc: Optional[float] = None


_state = _AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    gp = get_general_path()
    features = read_features(join_paths(gp, INTERIM_DATA, ALL_FEATURES_FILE))
    muni_info = pd.read_pickle(join_paths(gp, INTERIM_DATA, MUNICIPAL_DATA))
    x_oot, y_oot = read_xy_set('oot')
    model = get_model()

    max_oot_date = pd.to_datetime(x_oot.index.max().split('__')[1], format='%Y%m%d')

    # Forecast: all feature rows beyond the OOT window
    future_mask = features['standard_date'] > max_oot_date
    future_features = features[future_mask].copy()
    future_x = future_features.drop(DROP_COLS, axis=1, errors='ignore')
    _state.forecast_df = pd.DataFrame({
        'mun_id': future_features['mun_id'].values,
        'future_date': (
            future_features['standard_date'] + DateOffset(months=MONTHS)
        ).dt.strftime('%Y-%m-%d'),
        'prediction': predict(model, future_x),
    })

    # Validation: last OOT date — model prediction vs. what actually happened
    val_features = features[features['standard_date'] == max_oot_date].copy()
    val_preds = predict(model, val_features.drop(DROP_COLS, axis=1, errors='ignore'))

    real_date = max_oot_date + DateOffset(months=MONTHS)
    real_df = (
        features[features['standard_date'] == real_date][['mun_id', 'num_drought_index']]
        .copy()
        .rename(columns={'num_drought_index': 'real_value'})
    )
    real_df['real_value'] = (real_df['real_value'].fillna(0) / MAX_DROUGHT_INDEX).clip(0, 1)

    val_df = pd.DataFrame({'mun_id': val_features['mun_id'].values, 'prediction': val_preds})
    val_df = val_df.merge(real_df[['mun_id', 'real_value']], on='mun_id', how='left')
    _state.val_df = val_df.set_index('mun_id')

    # OOT AUC
    oot_preds = predict(model, x_oot)
    try:
        from sklearn.metrics import roc_auc_score
        _state.oot_auc = round(float(roc_auc_score(y_oot, oot_preds)), 4)
    except Exception:
        _state.oot_auc = None

    # Municipal geometry converted to WGS84 once at startup
    muni_gdf = gpd.GeoDataFrame(muni_info)
    if muni_gdf.crs is None:
        muni_gdf = muni_gdf.set_crs(MEXICO_EPSG)
    _state.municipal_wgs84 = muni_gdf.to_crs(WGS84)

    _state.states = sorted(muni_info['entidad_federativa'].unique().tolist())
    _state.dates = sorted(_state.forecast_df['future_date'].unique().tolist())
    _state.validation_date = max_oot_date.strftime('%Y-%m-%d')

    yield


app = FastAPI(title="SeGuía API", version="2.0.0", lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(_here, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(_here, "static")), name="static")

_refs = join_paths(get_general_path(), "references")
if os.path.isdir(_refs):
    app.mount("/references", StaticFiles(directory=_refs), name="references")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "states": _state.states,
        "dates": _state.dates,
        "validation_date": _state.validation_date,
        "oot_auc": _state.oot_auc,
    })


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/stats")
def stats():
    return {
        "oot_auc": _state.oot_auc,
        "validation_date": _state.validation_date,
        "municipalities": len(_state.municipal_wgs84) if _state.municipal_wgs84 is not None else None,
        "forecast_horizon_months": MONTHS,
    }


@app.get("/api/forecast/map")
def forecast_map(
    entity: str = Query(..., description="Estado (entidad federativa)"),
    date: str = Query(..., description="Fecha predicha (YYYY-MM-DD)"),
):
    df = _state.forecast_df
    filtered = df[df['future_date'] == date].set_index('mun_id')
    merged = filtered.join(_state.municipal_wgs84, how='inner')
    gdf = gpd.GeoDataFrame(merged[merged['entidad_federativa'] == entity])

    if gdf.empty:
        raise HTTPException(404, f"Sin datos para {entity!r} en {date!r}.")

    geojson = json.loads(gdf[['nombre_municipio', 'prediction', 'geometry']].to_json())
    return JSONResponse(content=geojson)


@app.get("/api/validation/map")
def validation_map(
    layer: str = Query(..., pattern=r"^(prediction|real_value)$"),
    simplify: float = Query(default=0.01, ge=0, le=1, description="Tolerancia de simplificación geométrica en grados"),
):
    merged = _state.val_df.join(_state.municipal_wgs84, how='inner')
    gdf = gpd.GeoDataFrame(merged)[['nombre_municipio', layer, 'geometry']].copy()
    gdf = gdf.rename(columns={layer: 'value'})
    if simplify > 0:
        gdf.geometry = gdf.geometry.simplify(simplify)
    return JSONResponse(content=json.loads(gdf.to_json()))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
