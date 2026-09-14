import pandas as pd
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


def read_xy_set(set_name):
    general_path = get_general_path()
    x_filename = f'x_{set_name}.parquet'
    y_filename = f'y_{set_name}.parquet'
    x_path = join_paths(general_path, PROCESSED_DATA, x_filename)
    y_path = join_paths(general_path, PROCESSED_DATA, y_filename)
    x = pd.read_parquet(x_path)
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
