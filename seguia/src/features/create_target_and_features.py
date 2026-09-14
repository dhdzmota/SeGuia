import argparse

from src.features.build_features import (
    create_target,
    create_initial_features,
    create_meteorological_features,
    merge_initial_and_meteorological_features,
    create_neighbour_features,
)


def process(force=False):
    create_target()
    create_initial_features()
    create_meteorological_features(force=force)
    merge_initial_and_meteorological_features()
    create_neighbour_features()


def parse_args():
    parser = argparse.ArgumentParser(
        description='Etapa 2: construye target y features (sequia, '
                    'meteorologia, vecinos).'
    )
    parser.add_argument(
        '--force', action='store_true',
        help='Recalcula las features meteorologicas de todos los '
             'municipios aunque esten al dia.'
    )
    return parser.parse_args()


if __name__ == '__main__':
    process(force=parse_args().force)
