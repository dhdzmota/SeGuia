import argparse

from src.models.split_data import split_data
from src.models.train_model import training
from src.models.evaluate_model import evaluate


def process(promote_mode='auto'):
    split_data()
    model, candidate_path, run_id = training()
    return evaluate(model, candidate_path, run_id, promote_mode=promote_mode)


def parse_args():
    parser = argparse.ArgumentParser(
        description='Etapa 3: split, entrenamiento, evaluacion y promocion '
                    'del modelo.'
    )
    parser.add_argument(
        '--promote', choices=['auto', 'never', 'force'], default='auto',
        help='auto: promueve si el AUC OOT no cae (default); never: solo '
             'entrena y evalua; force: promueve sin comparar.'
    )
    return parser.parse_args()


if __name__ == '__main__':
    process(promote_mode=parse_args().promote)
