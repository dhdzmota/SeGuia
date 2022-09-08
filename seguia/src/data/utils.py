# -*- coding: utf-8 -*-

def get_filename(file):
    file_name_path = file
    file_name = file_name_path.split('/')[-1].split('.')[0]
    return file_name
