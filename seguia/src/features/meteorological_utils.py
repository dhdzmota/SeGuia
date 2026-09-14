import datetime
import pandas as pd
from src.data.utils import (
    get_general_path,
    join_paths,
    get_time_from_string
)

METEO_RAW_DATA = 'data/raw/meteorological_info/'
INTERIM_DATA = 'data/interim/'
METEOROLOGICAL_FEATURES = 'meteorological_features'
METEOROLOGICAL_INFORMATION = 'meteorological_information'
MUN_PLACEHOLDER = 'mun_id={}'
DAYS = 90  # 3 Months
LAG = 5  # 5 days


def obtain_df_from_meteorological_data(mun_id):
    general_path = get_general_path()
    filename = f"{mun_id}.pkl"
    meteorological_path = join_paths(general_path, METEO_RAW_DATA, filename)
    print(f'Reading meteorological data for {filename}')
    meteorological_data = pd.read_pickle(meteorological_path)
    print('Extracting properties.')
    meteorological_properties = meteorological_data.get('properties')
    print('Extracting Parameters.')
    meteorological_parameters = meteorological_properties.get('parameter')
    meteorological_info = pd.DataFrame(
        meteorological_parameters
    ).reset_index()
    meteorological_info["date"] = meteorological_info['index'].apply(
        get_time_from_string
    )
    meteorological_info['mun_id'] = mun_id
    meteorological_index_str = meteorological_info['index'].astype('string')
    print('Generating index.')
    meteorological_info['mun_id__time'] = (
            mun_id + '__' + meteorological_index_str
    )
    meteorological_info.set_index('mun_id__time', inplace=True)
    meteorological_info.drop(['index'], axis=1, inplace=True)
    print(f'Done with file {filename}.')
    return meteorological_info


def get_rolling_data_partition(mun_id):
    general_path = get_general_path()
    meteorological_information_path = join_paths(
        general_path,
        INTERIM_DATA,
        METEOROLOGICAL_INFORMATION,
        MUN_PLACEHOLDER.format(mun_id)
    )
    meteorological_features_path = join_paths(
        general_path, INTERIM_DATA, METEOROLOGICAL_FEATURES
    )

    mun_data = pd.read_parquet(meteorological_information_path)

    # Create additional features
    mun_data['TS_T2M_change'] = (mun_data['TS'] - mun_data['T2M']) / 2
    mun_data['T2M_T10M_change'] = (mun_data['T2M'] - mun_data['T10M']) / 8
    mun_data['change_difference'] = mun_data['TS_T2M_change'] - mun_data[
        'T2M_T10M_change']
    mun_data['T10M_range'] = mun_data['T10M_MAX'] - mun_data['T10M_MIN']
    mun_data['TS_TROPT_range'] = mun_data['TS'] - mun_data['TROPT']
    mun_data['PS_TROPPB_range'] = mun_data['PS'] - mun_data['TROPPB']
    mun_data['new_date'] = mun_data['date'] + datetime.timedelta(days=LAG)

    # Create rolling features
    non_rolling_columns = ['date']
    rolling_date = 'new_date'
    daily_information_rolling = mun_data.sort_values(rolling_date).drop(
        non_rolling_columns, axis=1
    ).rolling(
        f'{DAYS}D', on=rolling_date, min_periods=DAYS, closed='left'
    )
    daily_information_rolling_info = {}
    daily_information_rolling_info['mean'] = daily_information_rolling.mean()
    daily_information_rolling_info['std'] = daily_information_rolling.std()
    daily_information_rolling_info['max'] = daily_information_rolling.max()
    daily_information_rolling_info['min'] = daily_information_rolling.min()
    daily_information_rolling_info[
        'median'] = daily_information_rolling.median()
    daily_information_rolling_info['skew'] = daily_information_rolling.skew()
    daily_information_rolling_info['kurt'] = daily_information_rolling.kurt()
    daily_information_rolling_info['mean_vs_median'] = (
            daily_information_rolling_info['mean'] -
            daily_information_rolling_info['median']
    )
    daily_information_rolling_info['range'] = (
            daily_information_rolling_info['max'] -
            daily_information_rolling_info['min']
    )
    daily_information_rolling_dfs = []
    for operation, data in daily_information_rolling_info.items():
        rename_col_dict = {
            col: f'{col}__last{DAYS}_days_{operation}'
            for col in data.drop(rolling_date, axis=1).columns
        }
        data.rename(columns=rename_col_dict, inplace=True)
        daily_information_rolling_dfs.append(data)
    concatenated_daily_information_rolling_df = pd.concat(
        daily_information_rolling_dfs, axis=1
    )
    concatenated_daily_information_rolling_df['mun_id'] = mun_id
    concatenated_daily_information_rolling_df.drop(
        rolling_date, axis=1, inplace=True)
    # delete_matching reemplaza la particion del municipio en vez de
    # anexar un archivo mas (evita filas duplicadas entre corridas).
    concatenated_daily_information_rolling_df.to_parquet(
        meteorological_features_path,
        partition_cols=['mun_id'],
        existing_data_behavior='delete_matching',
    )
    return None


def get_meteorological_features_partition(mun_id, relevant_index=None):
    general_path = get_general_path()
    meteorological_features_path = join_paths(
        general_path,
        INTERIM_DATA,
        METEOROLOGICAL_FEATURES,
        MUN_PLACEHOLDER.format(mun_id)
    )
    meteorological_features = pd.read_parquet(meteorological_features_path)
    met_index = meteorological_features.index
    if relevant_index is not None:
        final_index_list = sorted(
            list(
                set(met_index).intersection(set(relevant_index))
            )
        )
        meteorological_features_reduced = meteorological_features.loc[
            final_index_list
        ]
        return meteorological_features_reduced
    else:
        return meteorological_features
