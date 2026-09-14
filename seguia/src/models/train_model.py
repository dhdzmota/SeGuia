import datetime

import xgboost

from src.data.utils import (
    get_general_path, join_paths, make_desired_folder, save_as_pickle
)
from src.models.model_utils import (
    RANDOM_SEED, MODEL_PATH, read_xy_set
)

MODEL_FILE_TEMPLATE = 'SeGuia_{run_id}.pkl'
RUN_ID_FORMAT = '%Y%m%d'

PARAMS = {
    'n_estimators': 10000,
    'max_depth': 6,
    'gamma': 0.4,
    'learning_rate': 0.001,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'colsample_bylevel': 0.8,
    'colsample_bynode': 0.8,
    'reg_alpha': 10,
    'reg_lambda': 10,
    'base_score': 0.5,
    'random_state': RANDOM_SEED,
    'eval_metric': ['aucpr', 'auc', 'logloss'],
    'early_stopping_rounds': 3,
}


def new_run_id():
    """Identificador de la corrida (fecha), usado para versionar el modelo
    y su reporte de metricas."""
    return datetime.datetime.now().strftime(RUN_ID_FORMAT)


def training(run_id=None):
    """Entrena el modelo y lo guarda como candidato versionado
    (models/SeGuia_<run_id>.pkl). La promocion a models/SeGuia.pkl la
    decide evaluate_model segun el AUC en OOT.

    Devuelve (modelo, ruta_del_candidato, run_id).
    """
    run_id = run_id or new_run_id()
    general_path = get_general_path()
    x_train, y_train = read_xy_set('train')
    x_dev, y_dev = read_xy_set('dev')

    scale_pos_weight = (y_train == 0).sum() / (y_train == 1).sum()
    params = dict(PARAMS, scale_pos_weight=float(scale_pos_weight))

    print(
        f'Training candidate {run_id}: {len(x_train):,} rows, '
        f'{x_train.shape[1]} features, scale_pos_weight={scale_pos_weight:.3f}'
    )
    model = xgboost.XGBClassifier(**params)
    model.fit(
        x_train,
        y_train,
        eval_set=[(x_train, y_train), (x_dev, y_dev)],
        verbose=500,
    )
    print(f'Best iteration: {model.best_iteration}')

    make_desired_folder(MODEL_PATH)
    model_path = join_paths(
        general_path, MODEL_PATH, MODEL_FILE_TEMPLATE.format(run_id=run_id)
    )
    print('Saving candidate model...')
    save_as_pickle(what=model, where=model_path)
    return model, model_path, run_id
