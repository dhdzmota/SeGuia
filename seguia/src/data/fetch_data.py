# -*- coding: utf-8 -*-
import os
import pandas as pd
import requests
import ssl
import time
import yaml
import zipfile


def load_yaml(file_path):
    """
    This function is used only to load a yaml file in a given path.

    Parameters
    ----------
    file_path: str
        String that contains the path of a yaml file.

    Returns
    -------
    dict:
        Dictionary that contains the information of the yaml file.
    """
    with open(file_path, 'r') as file:
        yaml_file = yaml.load(file, Loader=yaml.FullLoader)
    return yaml_file

def create_https_context():
    """
    This function creates a default https context so that requests to websites
    are generated without a context error and thus a 403 error.

    Returns
    -------
        None
    """
    ssl._create_default_https_context = ssl._create_unverified_context

def fetch_core_data(url, path, key):
    """
    This function uses pandas to read the core data from the desired url.
    In this case since the url is actually an Excel file, we can use the method
    pd.read_excel. Then it is transformed into a Hierarchical Data Format (HDF)
    for further use.

    Parameters
    ----------
    url: str
        String that contains the core data as Excel.
    path: str
        String that contains the path and file where de data will be stored.
    key: str
        String that contains the key used for storage in hdf file.

    Returns
    -------
        None
    """
    df = pd.read_excel(url)
    df.to_hdf(path, key=key)

def fetch_geo_data(url, path):
    """
    This function uses requests to read geographic data, and downloads it as a
    zip file; then the files from the zip file are extracted.

    Note: This data is obtained only the first time; when the files do not
    exist locally.

    Parameters
    ----------
    url: str
        String that contains the geographic data as a zip file.
    path: str
        Path where de zip files will be downloaded and extracted.

    Returns
    -------

    """
    doc_name = url.split('/')[-1]
    file_path = path + doc_name
    extract_file_name = doc_name.replace('.zip', '')
    extract_file_path = path + extract_file_name
    try:
        os.mkdir(extract_file_path)
        request = requests.get(url)
        content = request.content
        with open(file_path, 'wb') as out_file:
            out_file.write(content)
        with zipfile.ZipFile(file_path, 'r') as zip_object:
            zip_object.extractall(extract_file_path)
    except OSError as error:
        pass


if __name__ == '__main__':
    base_path = os.path.join(
        os.path.dirname(__file__), '..', '..')
    data_conf_path = os.path.abspath(
        os.path.join(base_path, 'config/data.config')
    )
    general_data_path = os.path.join(
        os.path.join(base_path, 'data/raw/')
    )
    raw_data_path = os.path.join(
        os.path.join(base_path, general_data_path,'raw_data.h5')
    )
    data_conf = load_yaml(data_conf_path)
    url_core = data_conf['url_core']
    key_core = data_conf['key_core']
    url_geo = data_conf['url_geo']
    create_https_context()
    logger_string = f'Getting core data:'
    time_start=time.perf_counter()
    fetch_core_data(url=url_core, path=raw_data_path, key=key_core)
    time_end=time.perf_counter()
    total_time = time_end-time_start
    logger_string = f'Data key: {key_core}'
    print(logger_string)
    logger_string = f'Time to download data: {total_time}'
    print(logger_string)
    logger_string = f'Getting geo data:'
    print(logger_string)
    time_start=time.perf_counter()
    fetch_geo_data(url=url_geo, path=general_data_path)
    time_end=time.perf_counter()
    total_time = time_end-time_start
    logger_string = f'Time to download data: {total_time}'
    print(logger_string)
