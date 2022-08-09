# -*- coding: utf-8 -*-
import os
import pandas as pd
import ssl
import time
import yaml

def load_yaml(file_path):
    with open(file_path, 'r') as file:
        yaml_file = yaml.load(file, Loader=yaml.FullLoader)
    return yaml_file

def create_https_context():
    ssl._create_default_https_context = ssl._create_unverified_context

def fetch_core_data(url, path, key):
    df = pd.read_excel(url)
    df.to_hdf(path, key=key)


if __name__ == '__main__':
    base_path = os.path.join(
        os.path.dirname(__file__), '..', '..')
    core_data_conf_path = os.path.abspath(
        os.path.join(base_path, 'config/core_data.config')
    )
    raw_data_path = os.path.join(
        os.path.join(base_path, 'data/raw/raw_data.h5')
    )
    core_data_conf = load_yaml(core_data_conf_path)
    url = core_data_conf['url']
    key = core_data_conf['key']
    create_https_context()
    time_start=time.perf_counter()
    fetch_core_data(url=url, path=raw_data_path, key=key)
    time_end=time.perf_counter()
    total_time = time_end-time_start
    logger_string = f'Data key: {key}'
    logger_string = f'Time to download data: {total_time}'
