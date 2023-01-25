# copy_if_missing.py
import os
import shutil
from functions import generate_file_lists


def copy_if_missing(file_paths):
    session_list, file_list = generate_file_lists(file_paths=file_paths)
    for file in file_list['origin_path']:
        file_path = file.split(os.sep)
        external_path = os.path.join(file_paths['external_path'], *file_path[len(file_paths['origin_path'].split(os.sep)):])
        if external_path not in file_list['external_path']:
            dest = os.path.dirname(external_path)
            if not os.path.isdir(dest):
                os.mkdir(dest)
            print(f'copying {file} to {file_paths["external_path"]}')
            shutil.copy(file, external_path)



