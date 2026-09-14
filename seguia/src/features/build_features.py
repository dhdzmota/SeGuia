import pandas as pd

from pandas.tseries.offsets import DateOffset

from src.data.utils import (
    get_general_path,
    join_paths,
    save_as_pickle,
    save_dataframe
)
from src.features.meteorological_utils import (
    get_rolling_data_partition,
    get_meteorological_features_partition,
)
from src.features.neighbour_utils import (
    process_neighbour_features,
)


INTERIM_DATA = 'data/interim'
TARGET_DATA_FILE = 'target_datasets.pkl'
MUNICIPAL_DATA = 'municipal_data.pkl'
NEIGHBOUR_GRAPH = 'municipal_neighbour_graph.pkl'
METEOROLOGICAL_FEATURES = 'meteorological_features'
PROCESSED_DROUGTH_DATA_FILE = 'processed_drought_data.parquet'
INITIAL_FEATURES = 'initial_features.parquet'
METEOROLOGICAL_AND_INITIAL_FEAT = 'meteorological_and_initial_features.parquet'
ALL_FEATURES_FILE = 'all_features.parquet'
DATE_NAME = 'date'
NEW_DATE = 'standard_date'
THRESHOLD_DATE = '2016-01-01'
TARGET_NAME = 'num_drought_index_future'
MONTHS_INTO_FUTURE = {1: '1M', 2: '2M', 3: '3M', 4: '4M', 6: '6M'}
USELESS_COLUMNS = [
    'CVE_CONCATENADA',
    'CVE_ENT',
    'CVE_MUN',
    'NOMBRE_MUN',
    'ENTIDAD',
    'ORG_CUENCA*',
    'CON_CUENCA',
]
DROP_COLS = ['CLV_OC', 'CVE_CONC', 'date']


def calculate_rolling_window_features(
    data, days, date_col='DATE', column_value='DROUGHT_INDEX'
):
    df = data.copy()
    rolling_df = df.rolling(
        f'{days}D', on=date_col, min_periods=days//30-2, closed='left'
    )
    rolling_df_target = rolling_df[column_value]

    df[f'{column_value}__mean__last{days}_days'] = rolling_df_target.mean()
    df[f'{column_value}__std__last{days}_days'] = rolling_df_target.std()
    df[f'{column_value}__max__last{days}_days'] = rolling_df_target.max()
    df[f'{column_value}__min__last{days}_days'] = rolling_df_target.min()
    df[f'{column_value}__median__last{days}_days'] = rolling_df_target.median()
    df[f'{column_value}__kurtosis__last{days}_days'] = rolling_df_target.kurt()
    df[f'{column_value}__skewness__last{days}_days'] = rolling_df_target.skew()
    df[f'{column_value}__range__last{days}_days'] = (
            df[f'{column_value}__max__last{days}_days'] -
            df[f'{column_value}__min__last{days}_days']
    )
    df[f'{column_value}__mean_vs_median__last{days}_days'] = (
            df[f'{column_value}__mean__last{days}_days'] -
            df[f'{column_value}__median__last{days}_days']
    )
    features_cols = [col for col in df.columns if '__' in col]
    return df[features_cols]


def calculate_stable_drought(df):
    stable_df = df.copy()
    stable_df['is_stable'] = (
            stable_df.num_drought_index.diff() == 0
    ).astype('float')
    stable_df['val_groups'] = (
            stable_df.is_stable != stable_df.is_stable.shift()
    ).cumsum()
    stable_df['date_differences'] = stable_df[NEW_DATE].diff().dt.days
    stable_df['months_stable'] = stable_df.groupby(
        'val_groups'
    ).date_differences.cumsum()/30
    return stable_df[['is_stable', 'months_stable']]


def create_target():
    print('Creating target...')

    general_path = get_general_path()
    processed_drought_data_path = join_paths(
        general_path, INTERIM_DATA, PROCESSED_DROUGTH_DATA_FILE
    )
    print('Getting processed drought data files...')
    processed_drought_data = pd.read_parquet(processed_drought_data_path)
    df_to_manipulate = processed_drought_data.copy()
    df_to_manipulate = df_to_manipulate[
        ['mun_id', 'num_drought_index', NEW_DATE]
    ]
    individual_datasets = {}
    print('Generating individual datasets:')
    for months, month in MONTHS_INTO_FUTURE.items():
        print(f'Dataset for {month} into the future.')
        df = df_to_manipulate.copy()
        test_date = f'{NEW_DATE}{month}'
        index_date = f"mun_id__date{month}"
        df[test_date] = df[NEW_DATE] - DateOffset(months=months)
        date_as_string = df[test_date].dt.strftime('%Y%m%d')
        df[index_date] = df["mun_id"] + "__" + date_as_string

        # Since not all values are valid to compute since there is a problem
        # with the information, we need this filter:
        df = df[df[NEW_DATE] > pd.to_datetime(THRESHOLD_DATE)]

        individual_dataset_for_prediction = df[
            ['mun_id', test_date, index_date, 'num_drought_index']
        ]
        columns_renames = {
            index_date: 'mun_id__date',
            'num_drought_index': TARGET_NAME
        }
        individual_dataset_for_prediction.rename(
            columns=columns_renames,
            inplace=True
        )
        individual_dataset_for_prediction.set_index(
            'mun_id__date', inplace=True
        )
        individual_datasets[month] = individual_dataset_for_prediction
    print('Saving  individual targets.')
    target_files = join_paths(
        general_path, INTERIM_DATA, TARGET_DATA_FILE
    )
    save_as_pickle(what=individual_datasets, where=target_files)


def create_initial_features():
    print('Creating initial features')
    general_path = get_general_path()
    processed_drought_data_path = join_paths(
        general_path, INTERIM_DATA, PROCESSED_DROUGTH_DATA_FILE
    )
    print('Reading  processed_drought_data_path')
    processed_drought_data = pd.read_parquet(processed_drought_data_path)
    data = processed_drought_data.drop(USELESS_COLUMNS, axis=1)
    # Compute features
    print('Computing initial features for clv_oc.')
    data_num_drought_index__clv_oc = data.groupby(
        ['CLV_OC', 'standard_date']
    ).agg(
        num_drought_index__clv_oc__mean=('num_drought_index', 'mean'),
        num_drought_index__clv_oc__std=('num_drought_index', 'std'),
        num_drought_index__clv_oc__max=('num_drought_index', 'max'),
        num_drought_index__clv_oc__min=('num_drought_index', 'min'),
        num_drought_index__clv_oc__median=('num_drought_index', 'median'),
    )
    print('Computing initial features for cve_conc.')
    data_num_drought_index__cve_conc = data.groupby(
        ['CVE_CONC', 'standard_date']
    ).agg(
        num_drought_index__cve_conc__mean=('num_drought_index', 'mean'),
        num_drought_index__cve_conc__std=('num_drought_index', 'std'),
        num_drought_index__cve_conc__max=('num_drought_index', 'max'),
        num_drought_index__cve_conc__min=('num_drought_index', 'min'),
        num_drought_index__cve_conc__median=('num_drought_index', 'median'),
    )
    print('Merging information...')
    data_with_features = data.merge(
        data_num_drought_index__clv_oc.reset_index(),
        on=['CLV_OC', 'standard_date'],
        how='left',
    ).merge(
        data_num_drought_index__cve_conc.reset_index(),
        on=['CVE_CONC', 'standard_date'],
        how='left'
    ).set_index(data.index)

    print('Calculating rolling window (100 days) features '
          'for num_drought_index')
    data_drougt_index_3m = data.groupby('mun_id').apply(
        calculate_rolling_window_features,
        days=100,
        date_col='standard_date',
        column_value='num_drought_index'
    ).reset_index().set_index('mun_id__date').drop('mun_id', axis=1)

    print('Calculating rolling window (190 days) features for '
          'num_drought_index')
    data_drougt_index_6m = data.groupby('mun_id').apply(
        calculate_rolling_window_features,
        days=190,
        date_col='standard_date',
        column_value='num_drought_index'
    ).reset_index().set_index('mun_id__date').drop('mun_id', axis=1)
    print('Getting stability drought index')
    data_stability_drought_index = data.groupby('mun_id').apply(
        calculate_stable_drought
    ).reset_index().set_index('mun_id__date').drop('mun_id', axis=1)
    features_list = [
        data_with_features,
        data_drougt_index_3m,
        data_drougt_index_6m,
        data_stability_drought_index
    ]
    print('Merging all features...')
    features = pd.concat(features_list, axis=1)
    final_features = features[
        features['date'] > pd.to_datetime(THRESHOLD_DATE)
    ]
    final_features.drop(DROP_COLS, axis=1, inplace=True)
    print('Saving initial features.')
    feature_files = join_paths(general_path, INTERIM_DATA, INITIAL_FEATURES)
    save_dataframe(feature_files, final_features, 'parquet')


def create_meteorological_features():
    print('Creating meteorological features...')
    general_path = get_general_path()
    municipal_data_path = join_paths(
        general_path, INTERIM_DATA, MUNICIPAL_DATA
    )
    print('Reading municipal data...')
    municipal_data = pd.read_pickle(municipal_data_path)
    indexes = municipal_data.index
    l_indexes = len(indexes)
    import os
    for i, mun_id in enumerate(indexes):
        cached = join_paths(
            general_path, INTERIM_DATA, METEOROLOGICAL_FEATURES,
            f'mun_id={mun_id}'
        )
        if os.path.isdir(cached):
            continue
        get_rolling_data_partition(mun_id)
        print(
            f"Getting meteorological features "
            f"for: {mun_id},  progress{i}/{l_indexes}"
        )


def merge_initial_and_meteorological_features():
    print('Merging initial and meteorological features')
    general_path = get_general_path()
    initial_features_path = join_paths(
        general_path, INTERIM_DATA, INITIAL_FEATURES)
    print(f'Reading initial features at {initial_features_path}')
    initial_features = pd.read_parquet(initial_features_path)

    municipal_data_path = join_paths(
        general_path, INTERIM_DATA, MUNICIPAL_DATA
    )
    print(f'Reading municipal data at {municipal_data_path}')
    municipal_data = pd.read_pickle(municipal_data_path)
    meteorological_features_list = []
    for i, mun_id in enumerate(municipal_data.index):
        mf = get_meteorological_features_partition(
            mun_id=mun_id,
            relevant_index=initial_features.index
        )
        meteorological_features_list.append(mf)
        print(f'Getting meteorological features '
              f'partition with indexes for {mun_id}.')
    print('Joining all  meteorological_features.')
    meteorological_features = pd.concat(meteorological_features_list)

    print('Merging initial_features and meteorological_features.')
    meteorological_and_initial_features = pd.concat(
        [initial_features, meteorological_features], axis=1
    )
    meteorological_and_initial_features_path = join_paths(
        general_path,
        INTERIM_DATA,
        METEOROLOGICAL_AND_INITIAL_FEAT
    )
    save_dataframe(
        filepath=meteorological_and_initial_features_path,
        dataframe=meteorological_and_initial_features,
        file_format='parquet'
    )


def create_neighbour_features():
    print('Creating neighbour features.')
    general_path = get_general_path()
    features_path = join_paths(
        general_path, INTERIM_DATA, METEOROLOGICAL_AND_INITIAL_FEAT
    )
    print(f'Reading features at {features_path}.')
    features = pd.read_parquet(features_path)
    graph_path = join_paths(
        general_path, INTERIM_DATA, NEIGHBOUR_GRAPH
    )
    print(f'Getting neighbour graph: {graph_path}.')
    neighbour_graph = pd.read_pickle(graph_path)

    neighbour1_feature_list = []
    neighbour2_feature_list = []

    for i, mun_id in enumerate(features.mun_id.unique()):
        n1 = process_neighbour_features(
            neighbour_grade=1,
            mun_id=mun_id,
            features_df=features,
            graph=neighbour_graph
        )
        n2 = process_neighbour_features(
            neighbour_grade=2,
            mun_id=mun_id,
            features_df=features,
            graph=neighbour_graph
        )
        neighbour1_feature_list.append(n1)
        neighbour2_feature_list.append(n2)
        print(f'Getting neighbour features for {mun_id}, number: {i}')

    print('Merging neighbour features...')
    neighbour1_features = pd.concat(neighbour1_feature_list, axis=0)
    neighbour2_features = pd.concat(neighbour2_feature_list, axis=0)
    print('Joining all features...')
    all_features = pd.concat(
        [features, neighbour1_features, neighbour2_features], axis=1
    )
    all_features_path = join_paths(
        general_path, INTERIM_DATA, ALL_FEATURES_FILE
    )
    print(f'Saving all features at: {all_features_path}')

    save_dataframe(
        filepath=all_features_path,
        dataframe=all_features,
        file_format='parquet'
    )
