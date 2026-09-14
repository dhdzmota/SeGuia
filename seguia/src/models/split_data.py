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

TRAIN_X = 'x_train.parquet'
TRAIN_Y = 'y_train.parquet'
TEST_X = 'x_test.parquet'
TEST_Y = 'y_test.parquet'
DEV_X = 'x_dev.parquet'
DEV_Y = 'y_dev.parquet'
OOT_X = 'x_oot.parquet'
OOT_Y = 'y_oot.parquet'


def split_data():
    general_path = get_general_path()
    features_path = join_paths(general_path, INTERIM_DATA, ALL_FEATURES_FILE)
    features = pd.read_parquet(features_path)

    target_file_path = join_paths(general_path, INTERIM_DATA, TARGET_FILE)
    targets = pd.read_pickle(target_file_path)

    target = targets[FUTURE_SCOPE]

    # Solo se usan filas con features completas (ver MIN_FEATURE_COVERAGE).
    feature_cols = features.columns.difference(['mun_id', 'standard_date'])
    coverage = features[feature_cols].notna().mean(axis=1)
    incomplete = features[coverage < MIN_FEATURE_COVERAGE]
    if len(incomplete):
        print(
            f'Excluyendo {len(incomplete):,} filas sin features suficientes '
            f'({incomplete.standard_date.min():%Y-%m-%d} -> '
            f'{incomplete.standard_date.max():%Y-%m-%d}).'
        )
    features = features[coverage >= MIN_FEATURE_COVERAGE]

    # La ventana de entrenamiento se deriva de los datos: solo las filas
    # cuyo target ya se conoce (existen en `target`) cuentan como
    # etiquetadas, y las mas recientes se reservan como OOT.
    labelled_dates = features.loc[
        features.index.intersection(target.index), 'standard_date'
    ]
    window = get_training_window(labelled_dates)
    print(
        f"Ventana de entrenamiento: {window['min_training_date']:%Y-%m-%d} "
        f"-> {window['max_training_date']:%Y-%m-%d}; OOT hasta "
        f"{window['last_labelled_date']:%Y-%m-%d}."
    )

    features = features[
        features.standard_date >= window['min_training_date']
    ]

    f = features[['mun_id', 'standard_date', ]]
    X = features.drop(['mun_id', 'standard_date'], axis=1)
    Y = (target[[TARGET]] > 0).astype('int')

    training_window = (
        window['min_training_date'], window['max_training_date']
    )

    f_index_train = f[
        f.standard_date.between(training_window[0], training_window[1])
    ].index
    general_index_train = sorted(
        list(
            set(X.index).intersection(set(f_index_train)).intersection(Y.index)
        )
    )
    x_train = X.loc[general_index_train]
    y_train = Y.loc[general_index_train]

    future_window = training_window[1]

    f_index_oot = f[f.standard_date > future_window].index
    general_index_oot = sorted(
        list(
            set(X.index).intersection(set(f_index_oot)).intersection(Y.index)
        )
    )

    x_oot = X.loc[general_index_oot]
    y_oot = Y.loc[general_index_oot]

    # Split 60/20/20 (train/dev/test): primero se separa el 20% de test,
    # y del 80% restante el 75% es train (60% del total) y 25% dev (20%).
    x_train, x_test, y_train, y_test = train_test_split(
        x_train,
        y_train,
        train_size=0.8,
        random_state=RANDOM_SEED
    )
    x_train, x_dev, y_train, y_dev = train_test_split(
        x_train,
        y_train,
        train_size=0.75,
        random_state=RANDOM_SEED
    )

    make_desired_folder(PROCESSED_DATA)
    train_x_path = join_paths(general_path, PROCESSED_DATA, TRAIN_X)
    train_y_path = join_paths(general_path, PROCESSED_DATA, TRAIN_Y)
    test_x_path = join_paths(general_path, PROCESSED_DATA, TEST_X)
    test_y_path = join_paths(general_path, PROCESSED_DATA, TEST_Y)
    dev_x_path = join_paths(general_path, PROCESSED_DATA, DEV_X)
    dev_y_path = join_paths(general_path, PROCESSED_DATA, DEV_Y)
    oot_x_path = join_paths(general_path, PROCESSED_DATA, OOT_X)
    oot_y_path = join_paths(general_path, PROCESSED_DATA, OOT_Y)

    save_dataframe(
        filepath=train_x_path,
        dataframe=x_train,
        file_format='parquet'
    )
    save_dataframe(
        filepath=train_y_path,
        dataframe=y_train,
        file_format='parquet'
    )
    save_dataframe(
        filepath=test_x_path,
        dataframe=x_test,
        file_format='parquet'
    )
    save_dataframe(
        filepath=test_y_path,
        dataframe=y_test,
        file_format='parquet'
    )
    save_dataframe(
        filepath=dev_x_path,
        dataframe=x_dev,
        file_format='parquet'
    )
    save_dataframe(
        filepath=dev_y_path,
        dataframe=y_dev,
        file_format='parquet'
    )
    save_dataframe(
        filepath=oot_x_path,
        dataframe=x_oot,
        file_format='parquet'
    )
    save_dataframe(
        filepath=oot_y_path,
        dataframe=y_oot,
        file_format='parquet'
    )

    # Resumen del split para auditar cada corrida (fechas y tamanos).
    split_info = {
        'horizon_months': HORIZON_MONTHS,
        'min_training_date': f"{window['min_training_date']:%Y-%m-%d}",
        'max_training_date': f"{window['max_training_date']:%Y-%m-%d}",
        'last_labelled_date': f"{window['last_labelled_date']:%Y-%m-%d}",
        'rows': {
            'train': len(x_train),
            'dev': len(x_dev),
            'test': len(x_test),
            'oot': len(x_oot),
        },
        'positive_rate': {
            'train': round(float(y_train[TARGET].mean()), 4),
            'dev': round(float(y_dev[TARGET].mean()), 4),
            'test': round(float(y_test[TARGET].mean()), 4),
            'oot': round(float(y_oot[TARGET].mean()), 4),
        },
    }
    split_info_path = join_paths(general_path, PROCESSED_DATA, SPLIT_INFO_FILE)
    with open(split_info_path, 'w') as file:
        json.dump(split_info, file, indent=2)
    print(f'Split info saved into `{split_info_path}`.')
    return split_info
