import networkx as nx
import pandas as pd


def get_intersections_as_list(geom, df):
    """Assumes that df has a geometry column that may or not intersect"""
    mun_id_list = df[geom.intersects(df.geometry)].index.to_list()
    return mun_id_list


def process_neighbour_features(neighbour_grade, mun_id, features_df, graph):
    relevant_index = features_df[features_df.mun_id == mun_id].index
    if mun_id not in graph:
        return pd.DataFrame(index=relevant_index)
    neighbours = nx.descendants_at_distance(graph, mun_id, neighbour_grade)
    neighbour_features = features_df[
        features_df.mun_id.isin(neighbours)
    ].drop('mun_id', axis=1).groupby('standard_date').mean()
    renamed_cols = {
        col: f'{col}__neighbour{neighbour_grade}_mean'
        for col in neighbour_features.columns
    }
    neighbour_features.rename(columns=renamed_cols, inplace=True)
    return neighbour_features.set_index(relevant_index)
