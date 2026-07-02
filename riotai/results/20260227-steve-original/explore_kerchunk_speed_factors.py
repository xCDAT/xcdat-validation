# %%  Imports
import glob
import xcdat as xc
import numpy as np
import time
import os
import json
import pandas as pd
import logging
import gc
import random
import warnings
from joblib import Parallel, delayed
import tqdm
import matplotlib.pyplot as plt

# %%  Attempts to suppress output
logging.getLogger("fsspec").setLevel(logging.WARNING)
logging.getLogger("kerchunk").setLevel(logging.WARNING)
logging.getLogger("xarray").setLevel(logging.WARNING)
logging.getLogger("xcdat").setLevel(logging.WARNING)

# %% Custom Convenience Functions
def get_path_from_json(fn) -> set[str]:
    """Extract dataset path from kerchunk json file.

    Parameters
    ----------
    fn : str
        JSON file to use.

    Returns
    -------
    str | None
        Dataset path from refs (or None if no valid path exists)
    """
    # get path from json file
    with open(fn, 'r') as file:
        refs = json.load(file)
    # iterate through json until you hit a directory reference
    for key in refs['refs'].keys():
        # if there is a valid entry return the path
        if isinstance(refs['refs'][key], list):
            return os.path.dirname(refs['refs'][key][0]) + '/'
    # if no valid entries, return None
    return


def get_dataset_attributes(fn, vid):
    ds = xc.open_dataset(fn, engine='kerchunk')
    ntime = len(ds['time'])
    size_gb = ds[vid].nbytes / 1e9
    ds.close()
    del ds
    return ntime, size_gb


def open_dataset(fn, tool='xcdat'):
    # get dataset path for xcdat (if needed)
    # do not include this in timing test
    if tool == 'xcdat':
        p = get_path_from_json(fn)
    # start timer
    s1 = time.time()
    # open dataset (based on tool)
    if tool == 'kerchunk':
        ds = xc.open_dataset(fn, engine='kerchunk')
    elif tool == 'xcdat':
        ds = xc.open_mfdataset(p)
    # stop timer
    e1 = time.time()
    # return dataset and elapsed time
    return ds, e1-s1

def load_data(ds, vid, tool='xcdat', max_size_gb=0.5):
    # get total dataarray size (don't include in timing)
    size_gb = ds[vid].nbytes / 1e9
    # get number of timesteps needed for target dataset load
    tsteps = int(np.floor(max_size_gb/size_gb*len(ds.time)))
    # start time
    s1 = time.time()
    # load dataset (of some max size)
    if size_gb <= max_size_gb:
        ds.load()
    else:
        ds = ds.isel(time=slice(0, tsteps+1))
        ds.load()
    # end time
    e1 = time.time()
    # return dataset and timing results
    return ds, e1-s1


def chunk_data(ds, vid, chunk_size_mb):
    # get total dataarray size (don't include in timing)
    size_mb = ds[vid].nbytes / 1e6
    # get number of chunks needed
    n_chunks = int(np.ceil(size_mb / chunk_size_mb))
    # Get the time dimension size and compute chunk size along time
    # (assuming time is the primary dimension to chunk along)
    time_size = ds[vid].sizes['time']
    time_chunk = max(1, time_size // n_chunks)
    # rechunk data (and time it)
    s1 = time.time()
    ds = ds.chunk({'time': time_chunk, 'lat': -1, 'lon': -1}).load()
    e1 = time.time()
    return ds, e1-s1


def compute_annual_mean(ds, vid):
    # time annual averaging
    s1 = time.time()
    dsa = ds.temporal.group_average(vid, freq='year')
    dsa.load()
    e1 = time.time()
    # return dataset and timing
    return dsa, e1-s1


def compute_spatial_average(ds, vid):
    # time annual averaging
    s1 = time.time()
    dsa = ds.spatial.average(vid)
    dsa.load()
    e1 = time.time()
    # return dataset and timing
    return dsa, e1-s1


def run_timing_test(fn, vid, tool, ntests, chunk_size_mb, max_size_gb):
    all_tests = {}
    for i in range(ntests):
        timing = {}
        if 'open' in tests:
            ds, t = open_dataset(fn, tool=tool)
            timing['open'] = t
        if 'load' in tests:
            ds, t = load_data(ds, vid, tool=tool, max_size_gb=max_size_gb)
            timing['load'] = t
        if 'chunk' in tests:
            ds, t = chunk_data(ds, vid, chunk_size_mb)
            timing['chunk'] = t
        if 'temporal' in tests:
            dst, t = compute_annual_mean(ds, vid)
            timing['temporal'] = t
        if 'spatial' in tests:
            dsa, t = compute_spatial_average(ds, vid)
            timing['spatial'] = t
        timing['total'] = sum([timing[key] for key in timing.keys()])
        all_tests[i] = timing
        # cleanup
        ds.close()
        dst.close()
        dsa.close()
        del ds, dst, dsa
        gc.collect()
    # get total speed for all tests
    tspeed = [all_tests[i]['total'] for i in all_tests.keys()]
    # find fastest results
    I = np.where(tspeed == np.min(tspeed))[0][0]
    # return fastest result
    return all_tests[I]


def head_to_head(fn, ntests, chunk_size_mb, max_size_gb):
    # Attempts to suppress output for joblib (unsuccessful)
    logging.getLogger("fsspec").setLevel(logging.ERROR)
    logging.getLogger("kerchunk").setLevel(logging.ERROR)
    logging.getLogger("xarray").setLevel(logging.ERROR)
    logging.getLogger("xcdat").setLevel(logging.ERROR)
    vid = fn.split('/')[-1].split('.')[7]
    freq = fn.split('/')[-2]
    try:
        ntime, size_gb = get_dataset_attributes(fn, vid)
        timing_kerchunk = run_timing_test(fn, vid, 'kerchunk', ntests=ntests, chunk_size_mb=chunk_size_mb, max_size_gb=max_size_gb)
        timing_xcdat = run_timing_test(fn, vid, 'xcdat', ntests=ntests, chunk_size_mb=chunk_size_mb, max_size_gb=max_size_gb)
        results = {'kfile': fn, 'freq': freq, 'variable': vid, 'ntimesteps': ntime, 'size_gb': size_gb}
        for key in timing_kerchunk.keys():
            results[key + '_kerchunk'] = timing_kerchunk[key]
            results[key + '_xcdat'] = timing_xcdat[key]
        return results
    except:
        return None

# %% parameters
kerchunk_directory =  '/global/cfs/projectdirs/m4931/kerchunk/'
max_size_gb = 0.5
chunk_size_mb = 100
ntests = 2
nfiles = 100 # or None to run all files
tests = ['open', 'load', 'chunk', 'temporal', 'spatial'] # open must be in test list

# %% get files to process (ta + tas for all frequencies)
files = glob.glob(kerchunk_directory + 'ta*/historical/*/*')
if nfiles is not None:
    files = random.sample(files, k=nfiles)
# do timing in parallel
results = Parallel(n_jobs=5)(delayed(head_to_head)(fn, ntests, chunk_size_mb, max_size_gb) for fn in tqdm.tqdm(files))

# %% process results
header = [key for key in results[0]]
df = pd.DataFrame(columns=header)
for row in results:
    if row is not None:
        df.loc[len(df)] = row
df.to_csv('head-to-head.csv')
print(df)

# %% plot some results
size_gb = df['size_gb'].values
metrics = {'open': 'Open', 'load': 'Load', 'chunk': 'Re-chunk', 'sa': 'Spatial Average', 'tot': 'Total'}
plt.figure(figsize=(8, 8))
for i, key in enumerate(tests):
    plt.subplot(3, 2, i+1)
    x = df[key + '_kerchunk'].values
    y = df[key + '_xcdat'].values
    myv = np.max(y)
    mxv = np.max(x)
    mv = np.max([mxv, myv])
    plt.scatter(x, y, s=size_gb)
    plt.plot([0, mv], [0, mv], 'k:')
    plt.xlabel('Kerchunk Time [s]')
    plt.ylabel('mf-dataset Time [s]')
    plt.title(key.capitalize())
    plt.xlim(0, mv)
    plt.ylim(0, mv)
plt.tight_layout()
# plt.savefig('rechunk.png', dpi=250)
plt.show()
