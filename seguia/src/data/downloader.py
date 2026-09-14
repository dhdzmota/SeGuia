"""
Descarga todos los datos crudos que necesita el pipeline de SeGuía:
  1. Índice de sequía (Excel de CONAGUA → data/raw/drought_data.parquet)
  2. Límites municipales (shapefile de CONABIO → data/raw/muni.pkl)
  3. Datos municipales simplificados (data/interim/municipal_data.pkl)
  4. Meteorología NASA POWER (data/raw/meteorological_info/<mun_id>.pkl)

Dos modos de ejecución:
  * resume (por defecto): salta todo lo que ya existe. Sirve para reanudar
    una descarga interrumpida.
  * --refresh: re-descarga el índice de sequía y trae de NASA solo los días
    posteriores a la última fecha guardada de cada municipio (incremental).
    Es el modo para la corrida mensual.

Al terminar escribe data/raw/download_manifest.json con el resumen de lo
que se actualizó, para auditoría y para que las etapas siguientes sepan
qué caché invalidar.
"""

import argparse
import concurrent.futures
import datetime
import io
import json
import os
import pickle
import tempfile
import time
import zipfile

import geopandas as gpd
import pandas as pd
import requests

from src.data.utils import (
    check_if_filepath_exists,
    get_general_path,
    get_reference_url,
    join_paths,
    make_desired_folder,
    save_as_pickle,
    zeroes_to_cve,
)

RAW_DATA = 'data/raw'
INTERIM_DATA = 'data/interim'
METEO_DIR = 'data/raw/meteorological_info'

DROUGHT_FILE = 'drought_data.parquet'
MUNI_RAW_FILE = 'muni.pkl'
MUNI_INTERIM_FILE = 'municipal_data.pkl'
MANIFEST_FILE = 'download_manifest.json'

MEXICO_EPSG = "EPSG:6362"
WGS84 = "EPSG:4326"

# Columnas que el resto del pipeline espera en el Excel de CONAGUA. Si una
# descarga nueva no las trae, se conserva el archivo anterior.
DROUGHT_REQUIRED_COLUMNS = [
    'CVE_ENT', 'CVE_MUN', 'NOMBRE_MUN', 'ENTIDAD', 'CLV_OC', 'CVE_CONC',
]
# Mismo criterio que process_utils.TIME_IDENTIFIER para reconocer columnas
# de fecha en el Excel de sequía.
DROUGHT_DATE_IDENTIFIER = '00:00'

NASA_START = '20000101'
# Hasta hoy: la ventana de descarga avanza sola en cada corrida mensual.
NASA_END = datetime.date.today().strftime('%Y%m%d')
NASA_DATE_FORMAT = '%Y%m%d'
NASA_PARAMETERS = [
    'PS', 'RH2M', 'RHOA', 'T10M', 'T10M_MAX', 'T10M_MIN',
    'T2M', 'T2M_MAX', 'T2M_MIN', 'PRECTOTCORR', 'TQV',
    'T2MWET', 'T2MDEW', 'TROPQ', 'QV2M', 'TO3', 'TROPT',
    'TROPPB', 'TS',
]
NASA_MAX_WORKERS = 8
# Reintentos ante errores transitorios (429 / 5xx / red), con espera
# creciente entre intentos.
NASA_RETRIES = 3
NASA_BACKOFF_SECONDS = (5, 20, 60)


# ── Utilidades ───────────────────────────────────────────────────────────────

def _atomic_write(write_fn, out_path):
    """Escribe en un archivo temporal del mismo directorio y lo renombra al
    final, para que una descarga fallida nunca deje un archivo a medias."""
    directory = os.path.dirname(out_path)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix='.tmp')
    os.close(fd)
    try:
        write_fn(tmp_path)
        os.replace(tmp_path, out_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _get_with_retry(url, timeout):
    last_exc = None
    for attempt in range(NASA_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(
                    f'HTTP {resp.status_code}', response=resp
                )
            resp.raise_for_status()
            return resp
        except (requests.RequestException, ConnectionError) as exc:
            last_exc = exc
            if attempt < NASA_RETRIES:
                time.sleep(NASA_BACKOFF_SECONDS[attempt])
    raise last_exc


def _drought_date_columns(df):
    return [c for c in df.columns if DROUGHT_DATE_IDENTIFIER in str(c)]


# ── 1. Datos de sequía (CONAGUA) ─────────────────────────────────────────────

def download_drought_data(refresh=False):
    gp = get_general_path()
    out_path = join_paths(gp, RAW_DATA, DROUGHT_FILE)
    exists = check_if_filepath_exists(out_path)
    if exists and not refresh:
        print('[drought] Already exists, skipping.')
        return {'updated': False}

    urls = get_reference_url()
    url = urls['sequia']
    print('[drought] Downloading from CONAGUA ...')
    resp = requests.get(url, timeout=120, verify=False)
    resp.raise_for_status()
    df = pd.read_excel(io.BytesIO(resp.content))

    # Validacion: la descarga nueva debe traer las columnas esperadas y no
    # menos fechas que la que ya tenemos; si no, se conserva la anterior.
    missing = [c for c in DROUGHT_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f'[drought] El Excel descargado no trae las columnas {missing}; '
            f'se conserva el archivo anterior.'
        )
    new_dates = _drought_date_columns(df)
    if not new_dates:
        raise ValueError(
            '[drought] El Excel descargado no trae columnas de fecha; '
            'se conserva el archivo anterior.'
        )
    previous_last_date = None
    if exists:
        previous = pd.read_parquet(out_path)
        previous_dates = _drought_date_columns(previous)
        previous_last_date = max(previous_dates)
        if len(new_dates) < len(previous_dates):
            raise ValueError(
                f'[drought] La descarga trae {len(new_dates)} fechas y el '
                f'archivo actual {len(previous_dates)}; se conserva el '
                f'archivo anterior.'
            )

    make_desired_folder(RAW_DATA)
    _atomic_write(lambda p: df.to_parquet(p), out_path)
    last_date = pd.to_datetime(max(new_dates))
    print(
        f'[drought] Saved {len(df):,} rows, {len(new_dates)} dates '
        f'(last: {last_date:%Y-%m-%d}) → {out_path}'
    )
    return {
        'updated': True,
        'n_dates': len(new_dates),
        'last_date': f'{last_date:%Y-%m-%d}',
        'previous_last_date': (
            f'{pd.to_datetime(previous_last_date):%Y-%m-%d}'
            if previous_last_date is not None else None
        ),
    }


# ── 2. Límites municipales (CONABIO) ─────────────────────────────────────────

def download_municipal_data():
    gp = get_general_path()
    out_path = join_paths(gp, RAW_DATA, MUNI_RAW_FILE)
    if check_if_filepath_exists(out_path):
        print('[muni] Already exists, skipping.')
        return

    urls = get_reference_url()
    url = urls['muni']
    print('[muni] Downloading shapefile from CONABIO ...')
    resp = requests.get(url, timeout=180, verify=False)
    resp.raise_for_status()

    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            zf.extractall(tmpdir)

        shp_files = [
            os.path.join(root, f)
            for root, _, files in os.walk(tmpdir)
            for f in files if f.endswith('.shp')
        ]
        if not shp_files:
            raise FileNotFoundError(
                'No .shp file found inside downloaded zip.'
            )

        gdf = gpd.read_file(shp_files[0])

    make_desired_folder(RAW_DATA)
    save_as_pickle(what=gdf, where=out_path)
    print(f'[muni] Saved {len(gdf):,} municipalities → {out_path}')


# ── 3. Datos municipales simplificados (interim) ─────────────────────────────

def create_simplified_municipal_data():
    gp = get_general_path()
    out_path = join_paths(gp, INTERIM_DATA, MUNI_INTERIM_FILE)
    if check_if_filepath_exists(out_path):
        print('[muni-interim] Already exists, skipping.')
        return

    drought_df = pd.read_parquet(join_paths(gp, RAW_DATA, DROUGHT_FILE))
    muni_df = pd.read_pickle(join_paths(gp, RAW_DATA, MUNI_RAW_FILE))

    for df in [drought_df, muni_df]:
        df['mun_id'] = (
            df['CVE_ENT'].apply(zeroes_to_cve, zeroes=2) + '_' +
            df['CVE_MUN'].apply(zeroes_to_cve, zeroes=3)
        )

    lacking = set(muni_df.mun_id) - set(drought_df.mun_id)
    drought_df.set_index('mun_id', inplace=True)
    muni_df.set_index('mun_id', inplace=True)
    muni_df.drop(index=lacking, inplace=True)

    muni_gdf = gpd.GeoDataFrame(muni_df, geometry='geometry')
    if muni_gdf.crs is None:
        muni_gdf = muni_gdf.set_crs(MEXICO_EPSG)
    muni_df['representative_coordinate'] = (
        muni_gdf.geometry.representative_point().to_crs(WGS84)
    )

    drop_cols = ['CVEGEO', 'CVE_ENT', 'CVE_MUN', 'NOMGEO', 'NOM_ENT',
                 'COV_', 'COV_ID', 'AREA', 'PERIMETER']
    simplified = muni_df.drop(
        columns=[c for c in drop_cols if c in muni_df.columns]
    )
    simplified['nombre_municipio'] = drought_df['NOMBRE_MUN']
    simplified['entidad_federativa'] = drought_df['ENTIDAD']
    simplified['org_cuenca'] = drought_df.get(
        'ORG_CUENCA*', pd.Series(dtype=str)
    )
    simplified['clv_oc'] = drought_df.get('CLV_OC', pd.Series(dtype=str))
    simplified['con_cuenca'] = drought_df.get(
        'CON_CUENCA', pd.Series(dtype=str)
    )
    simplified['cve_conc'] = drought_df.get(
        'CVE_CONC', pd.Series(dtype=str)
    )

    make_desired_folder(INTERIM_DATA)
    save_as_pickle(what=simplified, where=out_path)
    print(
        f'[muni-interim] Saved {len(simplified):,} municipalities '
        f'→ {out_path}'
    )


# ── 4. Meteorología NASA POWER ───────────────────────────────────────────────

def _nasa_url(lon, lat, start=NASA_START, end=NASA_END):
    params = ','.join(NASA_PARAMETERS)
    return (
        f"https://power.larc.nasa.gov/api/temporal/daily/point?"
        f"parameters={params}&community=RE"
        f"&longitude={lon}&latitude={lat}"
        f"&start={start}&end={end}&format=JSON"
    )


def _last_stored_date(payload):
    """Ultima fecha (YYYYMMDD) guardada en un pkl de NASA, o None."""
    params = payload.get('properties', {}).get('parameter', {})
    for series in params.values():
        if series:
            return max(series)
    return None


def _clean_nasa_parameters(params, fill_value):
    """Prepara los parametros recien descargados para guardarlos.

    NASA rellena con `fill_value` (-999) los dias que aun no ha procesado
    (tipicamente los ultimos 2-3). Esos dias finales se recortan para que
    la siguiente corrida los vuelva a pedir. Cualquier fill_value que
    quede en medio de la serie se convierte a NaN para que no contamine
    los promedios moviles.

    Devuelve (parametros_limpios, ultima_fecha_real) o ({}, None) si no
    hay ningun dia con datos reales.
    """
    df = pd.DataFrame(params)
    if df.empty:
        return {}, None
    df = df.sort_index()
    is_fill = df == fill_value
    real_rows = df[~is_fill.all(axis=1)]
    if real_rows.empty:
        return {}, None
    last_real_date = real_rows.index[-1]
    df = df.loc[:last_real_date].mask(is_fill.loc[:last_real_date])
    return {col: df[col].to_dict() for col in df.columns}, last_real_date


def _merge_nasa_payload(existing, new_payload, new_params, last_real_date):
    """Anexa los parametros nuevos al pkl existente y actualiza el header."""
    merged = dict(existing)
    params = {
        name: dict(series)
        for name, series in existing['properties']['parameter'].items()
    }
    for name, series in new_params.items():
        params.setdefault(name, {}).update(series)
    merged['properties'] = dict(existing['properties'], parameter=params)
    merged['header'] = dict(existing.get('header', {}), end=last_real_date)
    return merged


def _download_one(task):
    """Descarga (o completa) la meteorologia de un municipio.

    Devuelve (mun_id, estado, ultima_fecha) donde estado es uno de:
    'skipped' (ya existe y no es refresh), 'up-to-date' (no hay dias
    nuevos), 'downloaded' (descarga completa), 'updated' (incremental) o
    'ERROR: ...'.
    """
    mun_id, lon, lat, out_path, refresh = task
    exists = check_if_filepath_exists(out_path)
    if exists and not refresh:
        return mun_id, 'skipped', None

    existing = None
    start = NASA_START
    if exists:
        with open(out_path, 'rb') as file:
            existing = pickle.load(file)
        last_stored = _last_stored_date(existing)
        if last_stored:
            next_day = datetime.datetime.strptime(
                last_stored, NASA_DATE_FORMAT
            ) + datetime.timedelta(days=1)
            start = next_day.strftime(NASA_DATE_FORMAT)
            if start > NASA_END:
                return mun_id, 'up-to-date', last_stored

    try:
        resp = _get_with_retry(_nasa_url(lon, lat, start, NASA_END), 120)
        payload = json.loads(resp.text)
        fill_value = payload.get('header', {}).get('fill_value', -999.0)
        new_params, last_real_date = _clean_nasa_parameters(
            payload['properties']['parameter'], fill_value
        )
        if not new_params:
            return mun_id, 'up-to-date', _last_stored_date(existing or {})

        if existing is not None:
            to_save = _merge_nasa_payload(
                existing, payload, new_params, last_real_date
            )
            status = 'updated'
        else:
            payload['properties']['parameter'] = new_params
            payload['header']['end'] = last_real_date
            to_save = payload
            status = 'downloaded'

        _atomic_write(
            lambda p: pickle.dump(to_save, open(p, 'wb')), out_path
        )
        return mun_id, status, last_real_date
    except Exception as exc:
        return mun_id, f'ERROR: {exc}', None


def download_nasa_data(refresh=False):
    gp = get_general_path()
    muni = pd.read_pickle(join_paths(gp, INTERIM_DATA, MUNI_INTERIM_FILE))
    make_desired_folder(METEO_DIR)
    meteo_dir = join_paths(gp, METEO_DIR)

    tasks = [
        (mun_id, row['representative_coordinate'].x,
         row['representative_coordinate'].y,
         join_paths(meteo_dir, f'{mun_id}.pkl'), refresh)
        for mun_id, row in muni.iterrows()
    ]
    total = len(tasks)
    already = sum(1 for *_, p, _ in tasks if check_if_filepath_exists(p))
    mode = 'incremental refresh' if refresh else 'resume'
    print(
        f'[nasa] Mode: {mode}. {already}/{total} files present. '
        f'Requesting data up to {NASA_END} ...'
    )

    counts = {'downloaded': 0, 'updated': 0, 'up-to-date': 0, 'skipped': 0}
    errors = []
    last_dates = []
    done = 0
    workers = concurrent.futures.ThreadPoolExecutor(
        max_workers=NASA_MAX_WORKERS
    )
    with workers as pool:
        for mun_id, status, last_date in pool.map(_download_one, tasks):
            done += 1
            if status.startswith('ERROR'):
                errors.append({'mun_id': mun_id, 'error': status})
                print(f'[nasa] {mun_id}: {status}')
            else:
                counts[status] += 1
                if last_date:
                    last_dates.append(last_date)
            if done % 100 == 0:
                print(f'[nasa] {done}/{total} processed ...')

    summary = {
        'requested_end': NASA_END,
        'municipalities': total,
        **counts,
        'errors': errors,
        'last_date_min': min(last_dates) if last_dates else None,
        'last_date_max': max(last_dates) if last_dates else None,
    }
    if errors:
        print(f'[nasa] Finished with {len(errors)} errors.')
    print(
        f"[nasa] downloaded={counts['downloaded']} "
        f"updated={counts['updated']} up-to-date={counts['up-to-date']} "
        f"skipped={counts['skipped']} errors={len(errors)}; "
        f"data up to {summary['last_date_max']}."
    )
    return summary


# ── Punto de entrada ─────────────────────────────────────────────────────────

def write_manifest(manifest):
    gp = get_general_path()
    path = join_paths(gp, RAW_DATA, MANIFEST_FILE)
    with open(path, 'w') as file:
        json.dump(manifest, file, indent=2)
    print(f'Manifest written to {path}')


def download(refresh=False):
    started = datetime.datetime.now()
    print('=== 1/4  Drought data (CONAGUA) ===')
    drought = download_drought_data(refresh=refresh)

    print('\n=== 2/4  Municipal boundaries (CONABIO) ===')
    download_municipal_data()

    print('\n=== 3/4  Simplified municipal data ===')
    create_simplified_municipal_data()

    print('\n=== 4/4  Meteorological data (NASA POWER) ===')
    nasa = download_nasa_data(refresh=refresh)

    manifest = {
        'run_at': started.isoformat(timespec='seconds'),
        'refresh': refresh,
        'drought': drought,
        'nasa': nasa,
    }
    write_manifest(manifest)
    print('\nAll downloads complete.')
    if nasa['errors']:
        raise RuntimeError(
            f"{len(nasa['errors'])} municipalities failed to download "
            f"from NASA; re-run to retry them."
        )
    return manifest


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.strip())
    parser.add_argument(
        '--refresh', action='store_true',
        help='Re-descarga el indice de sequia y actualiza NASA de forma '
             'incremental (modo para la corrida mensual).'
    )
    return parser.parse_args()


if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    download(refresh=parse_args().refresh)
