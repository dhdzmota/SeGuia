import argparse

from src.features.process_utils import (
    joining_meteorological_data,
    identify_neighbours,
    process_drought_data,
)


def process(force=False):
    joining_meteorological_data(force=force)
    identify_neighbours(force=force)
    process_drought_data()


def parse_args():
    parser = argparse.ArgumentParser(
        description='Etapa 1: procesa los datos crudos (NASA, vecinos, '
                    'indice de sequia).'
    )
    parser.add_argument(
        '--force', action='store_true',
        help='Recalcula todo aunque las salidas esten al dia.'
    )
    return parser.parse_args()


if __name__ == '__main__':
    process(force=parse_args().force)
