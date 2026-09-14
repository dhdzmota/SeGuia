"""
Evalua un modelo candidato y decide si se promueve a produccion.

Para cada corrida se escribe reports/metrics/metrics_<run_id>.json con las
metricas en train/dev/test/oot, la ventana de datos usada, el manifiesto
de descarga y los hiperparametros: es el registro auditable de cada
reentrenamiento mensual.

Regla de promocion: el candidato reemplaza a models/SeGuia.pkl solo si su
AUC en el conjunto OOT actual no es menor que el del modelo vigente,
evaluado sobre ese mismo OOT. Ningun modelo previo entreno con esos
meses (la ventana de entrenamiento siempre termina OOT_MONTHS antes),
asi que la comparacion es justa.
"""

import argparse
import datetime
import json
import os
import shutil

import xgboost
from sklearn.metrics import (
    average_precision_score, log_loss, roc_auc_score
)

from src.data.utils import (
    check_if_filepath_exists,
    get_general_path,
    join_paths,
    make_desired_folder,
)
from src.models.model_utils import (
    MODEL_PATH,
    PROCESSED_DATA,
    get_model,
    predict,
    read_xy_set,
)

METRICS_DIR = 'reports/metrics'
METRICS_FILE_TEMPLATE = 'metrics_{run_id}.json'
PRODUCTION_MODEL = 'SeGuia.pkl'
# Registro de que version esta promovida (junto al pkl de produccion).
PRODUCTION_INFO = 'SeGuia.json'
SPLIT_INFO_FILE = 'split_info.json'
DOWNLOAD_MANIFEST = 'data/raw/download_manifest.json'
EVALUATION_SETS = ('train', 'dev', 'test', 'oot')
# Conjunto que decide la promocion y metrica usada.
PROMOTION_SET = 'oot'
PROMOTION_METRIC = 'auc'


def _read_json(path):
    if not check_if_filepath_exists(path):
        return None
    with open(path) as file:
        return json.load(file)


def compute_metrics(y_true, y_score):
    return {
        'rows': int(len(y_true)),
        'positive_rate': round(float(y_true.mean()), 4),
        'auc': round(float(roc_auc_score(y_true, y_score)), 4),
        'aucpr': round(float(average_precision_score(y_true, y_score)), 4),
        'logloss': round(float(log_loss(y_true, y_score)), 4),
    }


def evaluate_on_sets(model, set_names=EVALUATION_SETS):
    """Metricas del modelo en cada conjunto. Devuelve (metricas, x_oot,
    y_oot) para reutilizar el OOT en la comparacion con el modelo vigente
    sin volver a leerlo."""
    metrics = {}
    oot = None
    for name in set_names:
        x_set, y_set = read_xy_set(name)
        metrics[name] = compute_metrics(y_set, predict(model, x_set))
        print(f'[{name}] {metrics[name]}')
        if name == PROMOTION_SET:
            oot = (x_set, y_set)
        else:
            del x_set
    return metrics, oot


def production_metric(x_oot, y_oot):
    """AUC en el OOT actual del modelo en produccion, o None si no hay
    modelo o no puede evaluar estas features (p. ej. cambio de columnas).
    """
    general_path = get_general_path()
    production_path = join_paths(general_path, MODEL_PATH, PRODUCTION_MODEL)
    if not check_if_filepath_exists(production_path):
        print('[promotion] No production model yet.')
        return None
    try:
        current = get_model(PRODUCTION_MODEL)
        value = round(float(roc_auc_score(y_oot, predict(current, x_oot))), 4)
    except Exception as exc:  # noqa: BLE001 - cualquier fallo => no comparable
        print(f'[promotion] Production model cannot be scored on the '
              f'current OOT set ({exc}); treating as no baseline.')
        return None
    print(f'[promotion] Production model {PROMOTION_METRIC} on current '
          f'{PROMOTION_SET}: {value}')
    return value


def decide_promotion(candidate_value, production_value, force=False):
    if force:
        return True, 'forced'
    if production_value is None:
        return True, 'no comparable production model'
    if candidate_value >= production_value:
        return True, (
            f'candidate {PROMOTION_METRIC} {candidate_value} >= '
            f'production {production_value}'
        )
    return False, (
        f'candidate {PROMOTION_METRIC} {candidate_value} < '
        f'production {production_value}'
    )


def promote(candidate_path, run_id, report_path, candidate_metrics):
    general_path = get_general_path()
    production_path = join_paths(general_path, MODEL_PATH, PRODUCTION_MODEL)
    shutil.copyfile(candidate_path, production_path)
    info = {
        'run_id': run_id,
        'promoted_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'model_file': os.path.basename(candidate_path),
        'metrics_file': os.path.relpath(report_path, general_path),
        'metrics': candidate_metrics,
    }
    info_path = join_paths(general_path, MODEL_PATH, PRODUCTION_INFO)
    with open(info_path, 'w') as file:
        json.dump(info, file, indent=2)
    print(f'[promotion] Promoted {os.path.basename(candidate_path)} -> '
          f'{PRODUCTION_MODEL}')


def build_report(model, run_id, candidate_path, metrics):
    general_path = get_general_path()
    booster = model.get_booster()
    return {
        'run_id': run_id,
        'evaluated_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'model_file': os.path.basename(candidate_path),
        'xgboost_version': xgboost.__version__,
        'n_features': booster.num_features(),
        'best_iteration': int(model.best_iteration),
        'params': {
            k: v for k, v in model.get_params().items()
            if v is not None and k not in ('missing',)
        },
        'split': _read_json(
            join_paths(general_path, PROCESSED_DATA, SPLIT_INFO_FILE)
        ),
        'download_manifest': _read_json(
            join_paths(general_path, DOWNLOAD_MANIFEST)
        ),
        'metrics': metrics,
    }


def evaluate(model, candidate_path, run_id, promote_mode='auto'):
    """Evalua el candidato, guarda el reporte y aplica la regla de
    promocion. promote_mode: 'auto' (regla de AUC), 'never' o 'force'."""
    metrics, (x_oot, y_oot) = evaluate_on_sets(model)
    report = build_report(model, run_id, candidate_path, metrics)

    candidate_value = metrics[PROMOTION_SET][PROMOTION_METRIC]
    production_value = production_metric(x_oot, y_oot)
    del x_oot, y_oot
    if promote_mode == 'never':
        promoted, reason = False, 'promotion disabled'
    else:
        promoted, reason = decide_promotion(
            candidate_value, production_value, force=promote_mode == 'force'
        )
    report['promotion'] = {
        'set': PROMOTION_SET,
        'metric': PROMOTION_METRIC,
        'candidate': candidate_value,
        'production_before': production_value,
        'promoted': promoted,
        'reason': reason,
    }

    general_path = get_general_path()
    make_desired_folder(METRICS_DIR)
    report_path = join_paths(
        general_path, METRICS_DIR, METRICS_FILE_TEMPLATE.format(run_id=run_id)
    )
    with open(report_path, 'w') as file:
        json.dump(report, file, indent=2, default=str)
    print(f'Metrics report saved to {report_path}')
    print(f'[promotion] promoted={promoted}: {reason}')

    if promoted:
        promote(candidate_path, run_id, report_path, metrics)
    return report


def parse_args():
    parser = argparse.ArgumentParser(
        description='Evalua un modelo candidato ya entrenado y decide su '
                    'promocion.'
    )
    parser.add_argument(
        'run_id',
        help='Identificador del candidato (models/SeGuia_<run_id>.pkl).'
    )
    parser.add_argument(
        '--promote', choices=['auto', 'never', 'force'], default='auto',
        help='auto: promueve si el AUC OOT no cae (default); never: solo '
             'evalua; force: promueve sin comparar.'
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    candidate_file = f'SeGuia_{args.run_id}.pkl'
    candidate = get_model(candidate_file)
    evaluate(
        candidate,
        join_paths(get_general_path(), MODEL_PATH, candidate_file),
        args.run_id,
        promote_mode=args.promote,
    )
