import json

import pandas as pd

from sklearn.model_selection import train_test_split

from src.data.utils import (
    get_general_path, join_paths, make_desired_folder, save_dataframe
)
from src.models.model_utils import (
    RANDOM_SEED,
    HORIZON_MONTHS,
    TARGET,
    get_training_window,
    read_features,
)

RAW_DATA = 'data/raw/'
INTERIM_DATA = 'data/interim/'
PROCESSED_DATA = 'data/processed/'
MUNICIPAL_DATA = 'municipal_data.pkl'
FUTURE_SCOPE = f'{HORIZON_MONTHS}M'
SPLIT_INFO_FILE = 'split_info.json'
# Fraccion minima de features no nulas para considerar una fila utilizable.
# Las filas sin datos meteorologicos (p. ej. fechas posteriores a la ultima
# descarga de NASA) quedan muy por debajo y se excluyen del split.
MIN_FEATURE_COVERAGE = 0.5
ALL_FEATURES_FILE = 'all_features.parquet'
TARGET_FILE = 'target_datasets.pkl'


def split_data():
    general_path = get_general_path()
    features_path = join_paths(general_path, INTERIM_DATA, ALL_FEATURES_FILE)
    features = read_features(features_path)

    target_file_path = join_paths(general_path, INTERIM_DATA, TARGET_FILE)
    targets = pd.read_pickle(target_file_path)

    target = targets[FUTURE_SCOPE]

    # `features` ocupa varios GB (600K filas x 770 columnas). Para no
    # agotar la memoria no se copia entero: el reparto se hace sobre
    # etiquetas del indice y cada conjunto se materializa y guarda de uno
    # en uno (seleccionar columnas sobre todo el frame ya lo duplicaria).
    feature_cols = [
        col for col in features.columns
        if col not in ('mun_id', 'standard_date')
    ]

    # Solo se usan filas con features completas (ver MIN_FEATURE_COVERAGE).
    coverage = features.notna().mean(axis=1)
    incomplete_dates = features.loc[
        coverage < MIN_FEATURE_COVERAGE, 'standard_date'
    ]
    if len(incomplete_dates):
        print(
            f'Excluyendo {len(incomplete_dates):,} filas sin features '
            f'suficientes ({incomplete_dates.min():%Y-%m-%d} -> '
            f'{incomplete_dates.max():%Y-%m-%d}).'
        )
    dates = features.loc[coverage >= MIN_FEATURE_COVERAGE, 'standard_date']
    del coverage, incomplete_dates

    # La ventana de entrenamiento se deriva de los datos: solo las filas
    # cuyo target ya se conoce (existen en `target`) cuentan como
    # etiquetadas, y las mas recientes se reservan como OOT.
    dates = dates.loc[dates.index.intersection(target.index)]
    window = get_training_window(dates)
    print(
        f"Ventana de entrenamiento: {window['min_training_date']:%Y-%m-%d} "
        f"-> {window['max_training_date']:%Y-%m-%d}; OOT hasta "
        f"{window['last_labelled_date']:%Y-%m-%d}."
    )

    index_train = sorted(dates[
        dates.between(window['min_training_date'], window['max_training_date'])
    ].index)
    index_oot = sorted(dates[dates > window['max_training_date']].index)

    # Split 60/20/20 (train/dev/test): primero se separa el 20% de test,
    # y del 80% restante el 75% es train (60% del total) y 25% dev (20%).
    index_train, index_test = train_test_split(
        index_train, train_size=0.8, random_state=RANDOM_SEED
    )
    index_train, index_dev = train_test_split(
        index_train, train_size=0.75, random_state=RANDOM_SEED
    )

    y_all = (target[[TARGET]] > 0).astype('int')
    make_desired_folder(PROCESSED_DATA)
    sets = {
        'train': index_train,
        'dev': index_dev,
        'test': index_test,
        'oot': index_oot,
    }
    rows, positive_rate = {}, {}
    for name, index in sets.items():
        x_set = features.loc[index, feature_cols]
        y_set = y_all.loc[index]
        x_path = join_paths(general_path, PROCESSED_DATA, f'x_{name}.parquet')
        y_path = join_paths(general_path, PROCESSED_DATA, f'y_{name}.parquet')
        save_dataframe(filepath=x_path, dataframe=x_set, file_format='parquet')
        save_dataframe(filepath=y_path, dataframe=y_set, file_format='parquet')
        rows[name] = len(x_set)
        positive_rate[name] = round(float(y_set[TARGET].mean()), 4)
        del x_set, y_set

    # Resumen del split para auditar cada corrida (fechas y tamanos).
    split_info = {
        'horizon_months': HORIZON_MONTHS,
        'min_training_date': f"{window['min_training_date']:%Y-%m-%d}",
        'max_training_date': f"{window['max_training_date']:%Y-%m-%d}",
        'last_labelled_date': f"{window['last_labelled_date']:%Y-%m-%d}",
        'rows': rows,
        'positive_rate': positive_rate,
    }
    split_info_path = join_paths(general_path, PROCESSED_DATA, SPLIT_INFO_FILE)
    with open(split_info_path, 'w') as file:
        json.dump(split_info, file, indent=2)
    print(f'Split info saved into `{split_info_path}`.')
    return split_info
