"""
Downloads all raw data required by the SeGuía pipeline:
  1. Drought index (CONAGUA Excel → data/raw/drought_data.parquet)
  2. Municipal boundaries (CONABIO shapefile zip → data/raw/muni.pkl)
  3. Simplified municipal data (data/interim/municipal_data.pkl)
  4. NASA POWER meteorological data (data/raw/meteorological_info/<mun_id>.pkl)
"""

import concurrent.futures
import io
import json
import os
import tempfile
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

MEXICO_EPSG = "EPSG:6362"
WGS84 = "EPSG:4326"

NASA_START = '20000101'
NASA_END = '20240615'
NASA_PARAMETERS = [
    'PS', 'RH2M', 'RHOA', 'T10M', 'T10M_MAX', 'T10M_MIN',
    'T2M', 'T2M_MAX', 'T2M_MIN', 'PRECTOTCORR', 'TQV',
    'T2MWET', 'T2MDEW', 'TROPQ', 'QV2M', 'TO3', 'TROPT',
    'TROPPB', 'TS',
]
NASA_MAX_WORKERS = 8


# ── 1. Drought data (CONAGUA) ─────────────────────────────────────────────────

def download_drought_data():
    gp = get_general_path()
    out_path = join_paths(gp, RAW_DATA, DROUGHT_FILE)
    if check_if_filepath_exists(out_path):
        print('[drought] Already exists, skipping.')
        return

    urls = get_reference_url()
    url = urls['sequia']
    print('[drought] Downloading from CONAGUA ...')
    resp = requests.get(url, timeout=120, verify=False)
    resp.raise_for_status()

    df = pd.read_excel(io.BytesIO(resp.content))
    make_desired_folder(RAW_DATA)
    df.to_parquet(out_path)
    print(f'[drought] Saved {len(df):,} rows → {out_path}')


# ── 2. Municipal boundaries (CONABIO) ─────────────────────────────────────────

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
            raise FileNotFoundError('No .shp file found inside downloaded zip.')

        gdf = gpd.read_file(shp_files[0])

    make_desired_folder(RAW_DATA)
    save_as_pickle(what=gdf, where=out_path)
    print(f'[muni] Saved {len(gdf):,} municipalities → {out_path}')


# ── 3. Simplified municipal data (interim) ────────────────────────────────────

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
    simplified = muni_df.drop(columns=[c for c in drop_cols if c in muni_df.columns])
    simplified['nombre_municipio'] = drought_df['NOMBRE_MUN']
    simplified['entidad_federativa'] = drought_df['ENTIDAD']
    simplified['org_cuenca'] = drought_df.get('ORG_CUENCA*', pd.Series(dtype=str))
    simplified['clv_oc'] = drought_df.get('CLV_OC', pd.Series(dtype=str))
    simplified['con_cuenca'] = drought_df.get('CON_CUENCA', pd.Series(dtype=str))
    simplified['cve_conc'] = drought_df.get('CVE_CONC', pd.Series(dtype=str))

    make_desired_folder(INTERIM_DATA)
    save_as_pickle(what=simplified, where=out_path)
    print(f'[muni-interim] Saved {len(simplified):,} municipalities → {out_path}')


# ── 4. NASA POWER meteorological data ─────────────────────────────────────────

def _nasa_url(lon, lat):
    params = ','.join(NASA_PARAMETERS)
    return (
        f"https://power.larc.nasa.gov/api/temporal/daily/point?"
        f"parameters={params}&community=RE"
        f"&longitude={lon}&latitude={lat}"
        f"&start={NASA_START}&end={NASA_END}&format=JSON"
    )


def _download_one(task):
    mun_id, lon, lat, out_path = task
    if check_if_filepath_exists(out_path):
        return mun_id, 'skipped'
    try:
        resp = requests.get(_nasa_url(lon, lat), timeout=120)
        resp.raise_for_status()
        save_as_pickle(what=json.loads(resp.text), where=out_path)
        return mun_id, 'ok'
    except Exception as exc:
        return mun_id, f'ERROR: {exc}'


def download_nasa_data():
    gp = get_general_path()
    muni = pd.read_pickle(join_paths(gp, INTERIM_DATA, MUNI_INTERIM_FILE))
    make_desired_folder(METEO_DIR)
    meteo_dir = join_paths(gp, METEO_DIR)

    tasks = [
        (mun_id, row['representative_coordinate'].x,
         row['representative_coordinate'].y,
         join_paths(meteo_dir, f'{mun_id}.pkl'))
        for mun_id, row in muni.iterrows()
    ]
    total = len(tasks)
    already = sum(1 for *_, p in tasks if check_if_filepath_exists(p))
    print(f'[nasa] {already}/{total} already downloaded. '
          f'Fetching remaining {total - already} ...')

    done = 0
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=NASA_MAX_WORKERS) as pool:
        for mun_id, status in pool.map(_download_one, tasks):
            done += 1
            if status == 'ok' and done % 50 == 0:
                print(f'[nasa] {done}/{total} done ...')
            elif status.startswith('ERROR'):
                errors.append((mun_id, status))
                print(f'[nasa] {mun_id}: {status}')

    if errors:
        print(f'[nasa] Finished with {len(errors)} errors: {errors}')
    else:
        print(f'[nasa] All {total} municipalities complete.')


# ── Entry point ───────────────────────────────────────────────────────────────

def download():
    print('=== 1/4  Drought data (CONAGUA) ===')
    download_drought_data()

    print('\n=== 2/4  Municipal boundaries (CONABIO) ===')
    download_municipal_data()

    print('\n=== 3/4  Simplified municipal data ===')
    create_simplified_municipal_data()

    print('\n=== 4/4  Meteorological data (NASA POWER) ===')
    download_nasa_data()

    print('\nAll downloads complete.')


if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    download()
