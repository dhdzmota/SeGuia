# -*- coding: utf-8 -*-
import geopandas as gpd
import logging
import os
import shapely
import time

from matplotlib.backends.backend_pdf import PdfPages

from utils import get_filename


def obtain_cve_concat_ent_mun(df):
    """
    This function takes a dataframe, and returns a concatenation of the
    distinct components from the columns CVE_ENT and CVE_MUN as strings.

    Parameters
    ----------
    df: DataFrame
        dataframe that must have the following columns: CVE_ENT, CVE_MUN

    Returns
    -------
    cve_concat_ent_mun: pd.Series
        Pandas series with the information of the concatenated strings from
    the columns CVE_ENT, CVE_MUN
    """

    ent = df['CVE_ENT'].apply(lambda x: str(x).zfill(2))
    mun = df['CVE_MUN'].apply(lambda x: str(x).zfill(3))
    cve_concat_ent_mun = ent + mun
    return cve_concat_ent_mun

def obtain_cve_concat_ent_mun_loc(df, add=''):
    """
    This function takes a dataframe, and returns a concatenation of the
    distinct components from the columns CVE_ENT and CVE_MUN as strings.

    Parameters
    ----------
    df: DataFrame
        dataframe that must have the following columns: CVE_ENT, CVE_MUN
    add: str
        Additinal information to incorpore into the columns if there is
        something else; if needed.

    Returns
    -------
    cve_concat_ent_mun: pd.Series
        Pandas series with the information of the concatenated strings from
    the columns CVE_ENT, CVE_MUN, CVE_LOC
    -------

    """
    ent = df[f'CVE_ENT{add}'].apply(lambda x: str(x).zfill(2))
    mun = df[f'CVE_MUN{add}'].apply(lambda x: str(x).zfill(3))
    loc = df[f'CVE_LOC{add}'].apply(lambda x: str(x).zfill(4))
    cve_concat_ent_mun_loc = ent + mun + loc
    return cve_concat_ent_mun_loc

def check_if_multipolygon(geometry):
    """
    This function evaluates if a shapely.geometry class is a multipolygon
    instance.

    Parameters
    ----------
    geometry: shapely.geometry class
        Shapely geometry class that could be a polygon, point, or multipolygon.

    Returns
    -------
    is_multipolygon: bool
        True or false depending if the instance is a multipoylgon.

    """
    class_type = shapely.geometry.multipolygon.MultiPolygon
    is_multipolygon = isinstance(geometry, class_type)
    return is_multipolygon

def keep_largest_area_polygon(geometry):
    """
    This function takes a multipolygon shapely geometry and keeps only the
    polygone that has the largest area, among the multipolygons.

    Parameters
    ----------
    geometry: shapely.geometry class
        Shapely geometry class that could be a polygon, point, or multipolygon.

    Returns
    -------
    largest_area_polygon: shapely.geometry.polygon.Polygon
        Shapley polygon with the largest area.

    geometry: shapely.geometry class
        The same geometry that was introduced.

    """
    if check_if_multipolygon(geometry):
        geometry_list = list(geometry)
        poly_list = [poly.area for poly in geometry_list]
        max_index = poly_list.index(max(poly_list))
        largest_area_polygon = geometry_list[max_index]
        return largest_area_polygon
    return geometry

def isin_geometry(subgeometry, geometry):
    """
    This function checks if the sub_geometry intersects with a desired
    geometry.

    Parameters
    ----------
    subgeometry: shapley polygon
        Small shapley geometry.
    geometry: shapley polygon
        Larger shapley geometry to see if there is an intersection with the
        sugbeometry.

    Returns
    -------
    is_geometry_intersected_by_subgeometry: bool
        A boolean value depending if there is interesction or not.

    """
    is_geometry_intersected_by_subgeometry = geometry.intersects(subgeometry)
    return is_geometry_intersected_by_subgeometry

def get_mexico_land_geometry(df):
    """
    Function that gets mexico's land shapley geometry disregarding the islands
    based on the largest area of a multipolygon State.

    Parameters
    ----------
    df: GeoDataFrame
        Dataframe that must have a geometry column. This will discard small
        polygons and then will keep the large polygons in one same area;
        creating a huge poligon.

    Returns
    -------
    desired_geometry: shapley polygon.
        A single huge polygon composed of the union of many other poylgons.

    """
    df['geometry'] = df.geometry.apply(
        keep_largest_area_polygon
    )
    desired_geometry_df = df.dissolve()
    desired_geometry_df['NOMGEO'] = 'Mexico'
    desired_geometry_df['CVEGEO'] = '00'
    desired_geometry_df['CVE_ENT'] = '00'
    desired_geometry = desired_geometry_df.geometry.iloc[0]
    return desired_geometry

def plot_results(df, pdf_file_path):
    """
    Helper function to plot shapley geometries into a pdf.

    Parameters
    ----------
    df: GeoDataFrame
        GeoDataFrame that must have the column 'isin_mexico'.
    pdf_file_path: str
        String indicating where is the file going to be saved at.

    Returns
    -------
    None

    """
    ax = df[df['isin_mexico']].plot(
        figsize=(130, 80),
        color='blue',
        alpha=0.4,
    )
    df[~df['isin_mexico']].plot(
        ax=ax,
        color='red',
    )
    ax.set_yticks([])
    ax.set_xticks([])
    with PdfPages(pdf_file_path) as pdf:
        pdf.savefig()


if __name__ == '__main__':
    file_name = get_filename(__file__)
    logging.basicConfig(
        filename=f'{file_name}.log',
        level=logging.DEBUG,
        filemode='w'
    )
    base_path = os.path.join(
        os.path.dirname(__file__), '..', '..')
    general_data_path = os.path.join(base_path, 'data/')
    raw_data_path = os.path.join(
        os.path.join(general_data_path, 'raw/')
    )
    interim_data_path = os.path.join(
        os.path.join(general_data_path,'interim/')
    )
    interim_data_file_path = os.path.join(
        interim_data_path,
        '00a_modified.shp'
    )
    geographic_data_path = os.path.join(
        raw_data_path, 'mg_2020_integrado/conjunto_de_datos/'
    )
    geographic_data_path_a = os.path.join(geographic_data_path, '00a.shp')
    geographic_data_path_ent = os.path.join(geographic_data_path, '00ent.shp')
    pdf_file_path = os.path.join(base_path, 'reports/figures/mexico_land.pdf')

    geographic_data_ent = gpd.read_file(geographic_data_path_ent)
    geographic_data_a = gpd.read_file(geographic_data_path_a)

    time_start=time.perf_counter()
    mexico_land_geometry = get_mexico_land_geometry(geographic_data_ent)
    time_end=time.perf_counter()
    total_time = time_end-time_start
    logging.info(f'Time to get Mexico land geometry: {total_time}')

    time_start=time.perf_counter()
    geographic_data_a['CVE_CONCAT'] = obtain_cve_concat_ent_mun(
        geographic_data_a
    )
    geographic_data_a['CVE_CONCAT_LOC'] = obtain_cve_concat_ent_mun_loc(
        geographic_data_a
    )
    geographic_data_a['isin_mexico'] = geographic_data_a.geometry.apply(
        isin_geometry, geometry=mexico_land_geometry
    )
    time_end=time.perf_counter()
    total_time = time_end-time_start
    logging.info(f'Time to process "a" data for land geometry: {total_time}')

    time_start=time.perf_counter()
    plot_results(geographic_data_a, pdf_file_path=pdf_file_path)
    time_end=time.perf_counter()
    total_time = time_end-time_start
    logging.info(f'Time plotting info: {total_time}')

    new_geographic_data_a = geographic_data_a[geographic_data_a.isin_mexico]
    new_geographic_data_a.to_csv(interim_data_file_path)
    logging.info(f'Saving new information into: {interim_data_file_path}')
