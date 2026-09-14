import json

import pandas as pd
import pyarrow.parquet as pq
from pandas.tseries.offsets import DateOffset

from src.data.utils import (
    get_general_path, join_paths
)

RANDOM_SEED = 69
MIN_TRAINING_DATE = '2017-01-01'
# Meses hacia el futuro que predice el modelo (define el target usado).
HORIZON_MONTHS = 6
# Ventana out-of-time: los ultimos meses con target conocido se reservan
# para evaluar el modelo fuera del periodo de entrenamiento.
OOT_MONTHS = 6
TARGET = 'num_drought_index_future'
PROCESSED_DATA = 'data/processed/'
MODEL_PATH = 'models/'
# Columnas por bloque al leer parquets de features (ver read_features).
READ_BLOCK_COLUMNS = 64


def read_features(path, columns=None):
    """Lee un parquet de features por bloques de columnas y en float32.

    all_features.parquet tiene ~770 columnas float64 (~4 GB en memoria) y
    leerlo de golpe con pandas llega a ~10 GB de pico por la conversion
    Arrow -> pandas. Leer por bloques y castear a float32 (XGBoost trabaja
    en float32 internamente, asi que el modelo no cambia) deja el pico en
    ~2x el tamano final. El indice se restaura igual que con read_parquet.
    """
    parquet_file = pq.ParquetFile(path)
    metadata = json.loads(parquet_file.schema_arrow.metadata[b'pandas'])
    index_cols = [c for c in metadata['index_columns'] if isinstance(c, str)]
    data_cols = [
        c for c in parquet_file.schema_arrow.names
        if c not in index_cols and (columns is None or c in columns)
    ]
    pieces = []
    for start in range(0, len(data_cols), READ_BLOCK_COLUMNS):
        block = data_cols[start:start + READ_BLOCK_COLUMNS]
        table = parquet_file.read(
            columns=block + (index_cols if not pieces else [])
        )
        piece = table.to_pandas(self_destruct=True)
        del table
        float_cols = piece.select_dtypes('float64').columns
        piece[float_cols] = piece[float_cols].astype('float32')
        if pieces:
            piece.index = pieces[0].index
        pieces.append(piece)
    return pd.concat(pieces, axis=1, copy=False)


def read_xy_set(set_name):
    general_path = get_general_path()
    x_filename = f'x_{set_name}.parquet'
    y_filename = f'y_{set_name}.parquet'
    x_path = join_paths(general_path, PROCESSED_DATA, x_filename)
    y_path = join_paths(general_path, PROCESSED_DATA, y_filename)
    x = read_features(x_path)
    y = pd.read_parquet(y_path)
    y = y[TARGET]
    return x, y


def get_model(model_name='SeGuia.pkl'):
    general_path = get_general_path()
    model_filepath = join_paths(general_path, MODEL_PATH, model_name)
    model = pd.read_pickle(model_filepath)
    return model


def predict(model, x_set):
    prediction = model.predict_proba(x_set)[:, 1]
    return prediction


def get_training_window(labelled_dates):
    """Deriva la ventana de entrenamiento a partir de los datos.

    `labelled_dates` son las fechas (standard_date) de las filas que ya
    tienen target conocido. La ultima de ellas menos OOT_MONTHS marca el
    fin del entrenamiento; lo que queda despues es el conjunto OOT. Asi la
    ventana avanza sola cada vez que se descargan datos nuevos, en lugar de
    depender de una fecha fija.
    """
    last_labelled_date = pd.to_datetime(pd.Series(labelled_dates)).max()
    max_training_date = last_labelled_date - DateOffset(months=OOT_MONTHS)
    return {
        'min_training_date': pd.to_datetime(MIN_TRAINING_DATE),
        'max_training_date': max_training_date,
        'last_labelled_date': last_labelled_date,
    }
