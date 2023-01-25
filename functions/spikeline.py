# spikeline.py


import os
import json
import glob
import psutil
import traceback
import subprocess
import numpy as np
import logging as log
from time import sleep
from sys import platform
from shutil import rmtree
from functions.reset_folder import reset_folder
from sklearn.preprocessing import normalize

import spikeinterface.full as si
import spikeinterface.sorters as ss
import spikeinterface.extractors as se
import spikeinterface.comparison as sc
from spikeinterface.exporters import export_to_phy

os.environ['KILOSORT3_PATH'] = os.path.join('C:\\', 'github', 'Kilosort')
os.environ['KILOSORT2_5_PATH'] = os.path.join('C:\\', 'github', 'Kilosort2_5')


def remove_empty_or_one(sorter):
    units_to_keep = []
    for segment_index in range(sorter.get_num_segments()):
        for unit in sorter.get_unit_ids():
            spikes = sorter.get_unit_spike_train(unit, segment_index=segment_index)
            if spikes.size > 1:
                units_to_keep.append(unit)
    units_to_keep = np.unique(units_to_keep)
    return sorter.select_units(units_to_keep)


def spikeline(data_path, phy_folder, working_folder=os.path.join('C:\\', 'phy_temp')):
    n_jobs = -1

    if not os.path.isdir(working_folder):
        os.mkdir(working_folder)

    hdd = psutil.disk_usage('/')
    print(f'remaining disk: {hdd.free / (2 ** 30)} GiB')

    folder_name = data_path.split(os.sep)[-1]
    phy_folder = os.path.join(phy_folder, folder_name)
    recording_name = folder_name + '_imec0'
    recording_path = os.path.join(data_path, recording_name)
    print(f'specified recording save path: {recording_path}')

    # recording = si.load_extractor(os.path.join(working_folder, 'recording_save0'))

    recording = se.read_spikeglx(recording_path, stream_id='imec0.ap')
    print(f'read spikeGLX')

    recording_cmr = recording
    recording_f = si.bandpass_filter(recording, freq_min=300, freq_max=6000)
    recording_cmr = si.common_reference(recording_f, reference='local', operator='median',
                                        local_radius=(30, 200))
    kwargs = {'n_jobs': n_jobs, 'total_memory': '8G'}
    print('attempting to apply filters')
    applied = False
    attempt = 1
    while not applied:
        try:
            sleep(5)
            recording_save = reset_folder(os.path.join(working_folder, 'recording_save'), local=False)
            print(f'attempt {attempt}')
            recording = recording_cmr.save(format='binary', folder=recording_save, **kwargs)
            applied = True
            print(f'succeeded on attempt {attempt}')
        except Exception as e:
            attempt += 1
            if attempt > 4:
                print(f'failed to apply filters after {attempt} attempts')
                raise e
            else:
                print(e)

    hdd = psutil.disk_usage('/')
    print(f'remaining disk: {hdd.free / (2 ** 30)} GiB')

    sorter_params = {"keep_good_only": True}
    ss.Kilosort3Sorter.set_kilosort3_path(os.path.join('C:\\', 'github', 'Kilosort'))
    ss.Kilosort2_5Sorter.set_kilosort2_5_path(os.path.join('C:\\', 'github', 'Kilosort2_5'))
    print(f'starting kilosort3...')

    kilosort3_folder = reset_folder(os.path.join(working_folder, 'kilosort3'), local=False)
    ks3_sorter = ss.run_sorter(sorter_name='kilosort3', recording=recording, output_folder=kilosort3_folder,
                               verbose=False, **sorter_params)
    ks3_sorter = remove_empty_or_one(ks3_sorter)
    # kilosort3_folder = os.path.join(working_folder, 'kilosort30')
    # ks3_sorter = si.read_sorter_folder(kilosort3_folder)
    hdd = psutil.disk_usage('/')
    print(f'remaining disk: {hdd.free / (2 ** 30)} GiB')
    sorter_params = {"keep_good_only": False}
    print(f'starting kilosort2_5...')
    kilosort2_5_folder = reset_folder(os.path.join(working_folder, 'kilosort2_5'), local=False)
    ks2_5_sorter = ss.run_sorter(sorter_name='kilosort2_5', recording=recording,
                                 output_folder=kilosort2_5_folder,
                                 verbose=False, **sorter_params)
    ks2_5_sorter = remove_empty_or_one(ks2_5_sorter)
    # kilosort2_5_folder = os.path.join(working_folder, 'kilosort2_50')
    # ks2_5_sorter = si.read_sorter_folder(kilosort2_5_folder)

    hdd = psutil.disk_usage('/')
    print(f'remaining disk: {hdd.free / (2 ** 30)} GiB')

    print(f'starting consensus...')
    consensus = sc.compare_multiple_sorters(sorting_list=[ks3_sorter, ks2_5_sorter],
                                            name_list=['kilosort3', 'kilosort2_5'], verbose=False,
                                            delta_time=.2,
                                            match_score=.3,
                                            spiketrain_mode='union')
    agreement = consensus.get_agreement_sorting(minimum_agreement_count=2)
    kilosort3_templates = np.load(os.path.join(kilosort3_folder, 'templates.npy'))
    kilosort2_5_templates = np.load(os.path.join(kilosort2_5_folder, 'templates.npy'))

    template_similarty = np.array([np.sum(
        (normalize(np.max(abs(kilosort3_templates[int(unit['kilosort3']), :, :]), axis=0, keepdims=True)) -
         normalize(np.max(abs(kilosort2_5_templates[int(unit['kilosort2_5']), :, :]), axis=0,
                          keepdims=True))) ** 2) for unit in agreement._properties['unit_ids']]) / 2
    print(
        f'template filtering would remove {len(np.where(template_similarty >= .9)[0])} from {len(agreement.unit_ids)}')
    agreement = agreement.select_units(agreement.unit_ids[np.where(template_similarty < .9)[0]])
    consensus_folder = reset_folder(os.path.join(working_folder, 'consensus'), local=False)
    agreement = agreement.save(folder=consensus_folder)

    waveforms_folder = reset_folder(os.path.join(working_folder, 'waveforms'), local=False)
    waveforms = si.WaveformExtractor.create(recording, agreement, waveforms_folder)
    waveforms.set_params(ms_before=3., ms_after=4., max_spikes_per_unit=500)
    waveforms.run_extract_waveforms(n_jobs=n_jobs, chunk_size=30000)
    hdd = psutil.disk_usage('/')
    print(f'remaining disk: {hdd.free / (2 ** 30)} GiB')

    sparsity_dict = dict(method="radius", radius_um=50, peak_sign='both')
    print(f'got waveforms')
    print(f'starting phy export')
    job_kwargs = {'n_jobs': n_jobs, 'total_memory': '8G'}
    export_to_phy(waveforms, phy_folder, compute_pc_features=False, compute_amplitudes=True, copy_binary=True,
                  remove_if_exists=True, sparsity_dict=sparsity_dict, max_channels_per_template=None,
                  **job_kwargs)

    print(f'finished phy export')

    hdd = psutil.disk_usage('/')
    print(f'remaining disk: {hdd.free / (2 ** 30)} GiB')

    print(f'removing intermediate data folders')

    rmtree(working_folder, ignore_errors=True)

    hdd = psutil.disk_usage('/')
    print(f'remaining disk: {hdd.free / (2 ** 30)} GiB')
