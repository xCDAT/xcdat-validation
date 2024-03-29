"""
A performance benchmarking script that captures and compares the API runtimes of
xCDAT against CDAT.

Overview:
--------
It uses using multi-file
time series datasets with varying sizes. The default number of samples taken
for each API runtime is 3 and the minimum value is recorded. Runtimes only
include computation and exclude I/O.  xCDAT can operate in serial or parallel,
while CDAT can only operate in serial.

How to use it
--------------
   1. Must have direct access to LLNL Climate Program filesystem with CMIP data.
   2. Create the conda/mamba environment:
      - `mamba env create -f conda-env/test_stable.yml`
      - `mamba activate xcdat_test_stable`
   3. Run the script
      - `python xcdat-cdat-runtime-comparison.py`

Specifications for original machine used to run this script
-----------------------------------------------------------
  - OS: RHEL 7
  - Memory: 1,000 GiB
  - CPU: Intel(R) Xeon(r) CPU E7-8890v4 @ 2.20GHz

How xCDAT is configured for parallelism
---------------------------------------
  - Uses Dask Distributed local sechduler with multiprocessing
    - Docs: https://docs.dask.org/en/stable/scheduling.html#dask-distributed-local
    - Number of workers based on logical cores (num_workers=None), no memory limit
  - Datasets are chunked on the "time" axis using Dask's auto chunking option.
  - Datasets are opened in parallel using the `parallel=True` which uses
    `dask.delayed`.
  - For temporal averaging APIs, the underlying Xarray `groupby()` call uses the
    `flox` package is used for map-reduce grouping, instead of Xarray's native
    grouping logic. Xarray's native grouping logic is much slower because it
    runs serially. More info can be found here: https://xarray.dev/blog/flox.
"""
from __future__ import annotations

import os
import time
import timeit
import warnings
from typing import Dict, List

import cdms2
import cdutil
import numpy as np
import pandas as pd
import xarray as xr
import xcdat as xc
from dask.distributed import Client
from numpy.core._exceptions import _ArrayMemoryError

# Make sure cdms2 generates bounds if they don't exist.
cdms2.setAutoBounds("on")

# Logger configs
# --------------------------
warnings.filterwarnings(
    action="ignore", category=xr.SerializationWarning, module=".*conventions"
)

# Output file configurations
# --------------------------
TIME_STR = time.strftime("%Y%m%d-%H%M%S")
ROOT_DIR = "scripts/performance-benchmarks/"
XC_FILENAME = os.path.join(ROOT_DIR, f"{TIME_STR}-xcdat-runtimes")
CD_FILENAME = os.path.join(ROOT_DIR, f"{TIME_STR}-cdat-runtimes")

# Plot configs
# -------------------
# The base plot configuration passed to Panda's DataFrame plotting API.
PLOT_CONFIG: pd.DataFrame.plot.__init__ = {
    "kind": "bar",
    "legend": True,
    "rot": 0,
    "x": "gb",
    "xlabel": "File Size (GB)",
    "ylabel": "Runtime (secs)",
    "figsize": (6, 4),
}
# The base bar label configuration passed to axis containers to add
# the floating point labels above the bars.
BAR_LABEL_CONFIG = {"fmt": "{:10.2f}", "label_type": "edge", "padding": 3}

# Input data configs
# ------------------
FILES_DICT: Dict[str, Dict[str, str]] = {
    "7_gb": {
        "var_key": "tas",
        "dir_path": "/p/css03/esgf_publish/CMIP6/CMIP/NCAR/CESM2/historical/r1i1p1f1/day/tas/gn/v20190308/",
        "xml_path": "/p/user_pub/e3sm/vo13/xclim/CMIP6/CMIP/historical/atmos/day/tas/CMIP6.CMIP.historical.NCAR.CESM2.r1i1p1f1.day.tas.atmos.glb-p8-gn.v20190308.0000000.0.xml",
    },
    "12_gb": {
        "var_key": "tas",
        "dir_path": "/p/css03/esgf_publish/CMIP6/CMIP/MRI/MRI-ESM2-0/amip/r1i1p1f1/3hr/tas/gn/v20190829/",
        "xml_path": "/p/user_pub/e3sm/vo13/xclim/CMIP6/CMIP/historical/atmos/3hr/tas/CMIP6.CMIP.historical.MRI.MRI-ESM2-0.r1i1p1f1.3hr.tas.gn.v20190829.0000000.0.xml",
    },
    "22_gb": {
        "var_key": "ta",
        "dir_path": "/p/css03/esgf_publish/CMIP6/CMIP/MOHC/UKESM1-0-LL/historical/r5i1p1f3/day/ta/gn/v20191115/",
        "xml_path": "/p/user_pub/xclim/CMIP6/CMIP/historical/atmos/day/ta/CMIP6.CMIP.historical.MOHC.UKESM1-0-LL.r5i1p1f3.day.ta.atmos.glb-p8-gn.v20191115.0000000.0.xml",
    },
    "50_gb": {
        "var_key": "ta",
        "dir_path": "/p/css03/esgf_publish/CMIP6/CMIP/NCAR/CESM2/historical/r1i1p1f1/day/ta/gn/v20190308/",
        "xml_path": "/p/user_pub/xclim/CMIP6/CMIP/historical/atmos/day/ta/CMIP6.CMIP.historical.NCAR.CESM2.r1i1p1f1.day.ta.atmos.glb-p8-gn.v20190308.0000000.0.xml",
    },
    "105_gb": {
        "var_key": "ta",
        "dir_path": "/p/css03/esgf_publish/CMIP6/CMIP/MOHC/HadGEM3-GC31-MM/historical/r2i1p1f3/day/ta/gn/v20191218",
        "xml_path": "/p/user_pub/xclim/CMIP6/CMIP/historical/atmos/day/ta/CMIP6.CMIP.historical.MOHC.HadGEM3-GC31-MM.r2i1p1f3.day.ta.atmos.glb-p8-gn.v20191218.0000000.0.xml",
    },
}

APIS_TO_BENCHMARK = [
    "spatial_avg",
    # "temporal_avg",
    # "group_avg",
    # "climatology",
    # "departures",
]


def get_xcdat_runtimes(
    repeat: int,
    parallel: bool,
) -> pd.DataFrame:
    """Get xCDAT API runtimes.

    Parameters
    ----------
    parallel : bool
        Whether to run the APIs in parallel (True) or serial (False). If
        parallel, datasets are chunked on the time axis using Dask's auto
        chunking, and `flox` is used for temporal averaging.
    repeat : int
        Number of samples to take for each API call. The minimum runtime is
        taken as the final runtime.

    Returns
    -------
    pd.DataFrame
        A DataFrame of API runtimes.
    """
    process_type = "serial" if parallel is False else "parallel"
    print(f"Benchmarking xCDAT {process_type} API runtimes")
    print("---------------------------------------------------------------------")

    # Settings based on parallel or serial.
    _set_xr_config(parallel)
    chunks = _get_chunks_arg(parallel)

    # A list of dictionary entries storing information about each runtime.
    all_runtimes: List[Dict[str, str | float | None]] = []

    # For each file and api, get the runtime N number of times.
    for idx, (fsize, finfo) in enumerate(FILES_DICT.items()):
        dir_path = finfo["dir_path"]
        var_key = finfo["var_key"]

        print(f"Case ({idx+1}) - ")
        print(f" * file size: {fsize}, variable: '{var_key}', path: {dir_path!r}")

        ds = xc.open_mfdataset(
            dir_path, chunks=chunks, add_bounds=["X", "Y", "T"], parallel=parallel
        )
        # For serial API calls, load the dataset into memory beforehand.
        if not parallel:
            print("    * Loading dataset into memory for serial computation.")
            ds.load()

        for api in APIS_TO_BENCHMARK:
            print(f"  * API: {api}")
            api_runtimes = []

            for idx in range(0, repeat):
                runtime = _get_xcdat_runtime(ds.copy(), parallel, var_key, api)
                api_runtimes.append(runtime)

                print(f"    * Runtime ({(idx+1)} of {repeat}): {runtime}")

            min_runtime = min(api_runtimes)
            print(f"  * Min Runtime (out of {repeat} runs): {min_runtime}")

            entry = {
                "pkg": "xcdat",
                "gb": fsize.split("_")[0],
                "api": api,
                f"runtime_{process_type}": min_runtime,
            }
            all_runtimes.append(entry)

    df_runtimes = pd.DataFrame(all_runtimes)

    return df_runtimes


def _get_chunks_arg(parallel: bool) -> None | Dict[str, str]:
    if not parallel:
        return None
    elif parallel:
        return {"time": "auto"}


def _set_xr_config(parallel: bool):
    if not parallel:
        xr.set_options(use_flox=True)
    elif parallel:
        xr.set_options(use_flox=False)

        # Setup the Dask client using local distributed scheduler. This client
        # will be automatically used by Xarray when calling .compute()/.load().
        Client()


def _get_xcdat_runtime(ds: xr.Dataset, parallel: bool, var_key: str, api: str) -> float:
    start = 0.0
    end = 0.0

    try:
        start = timeit.default_timer()
        ds_res = _run_xcdat_api(ds, var_key, api)

        if parallel:
            ds_res.compute()

        end = timeit.default_timer()
    except (RuntimeError, _ArrayMemoryError) as e:
        # Retry the code again if it is thet NetCDF error.
        if "RuntimeError: NetCDF: Not a valid ID" in str(e):
            start = timeit.default_timer()
            ds_res = _run_xcdat_api(ds, var_key, api)

            if parallel:
                ds_res.compute()

            end = timeit.default_timer()
        else:
            print(e)

    runtime = end - start

    return runtime


def _run_xcdat_api(ds: xr.Dataset, var_key: str, api: str) -> xr.Dataset:
    if api == "spatial_avg":
        return ds.spatial.average(var_key, axis=["X", "Y"], lat_bounds=(-30, 30))
    elif api == "temporal_avg":
        return ds.temporal.average(var_key, weighted=True)
    elif api == "group_avg":
        return ds.temporal.group_average(var_key, freq="month", weighted=True)
    elif api == "climatology":
        return ds.temporal.climatology(var_key, freq="month", weighted=True)
    elif api == "departures":
        return ds.temporal.departures(var_key, freq="month", weighted=True)


def get_cdat_runtimes(repeat: int) -> pd.DataFrame:
    """Get the CDAT API runtimes (only supports serial).

    Parameters
    ----------
    repeat : int
        Number of samples to take for each API call.

    Returns
    -------
    pd.DataFrame
        A DataFrame of runtimes for CDAT APIs.
    """
    print("Getting CDAT runtimes (serial-only).")

    all_runtimes = []

    # For each file and api, get the runtime N number of times.
    for idx, (fsize, finfo) in enumerate(FILES_DICT.items()):
        xml_path = finfo["xml_path"]
        var_key = finfo["var_key"]

        print(f"Case ({idx+1}) - ")
        print(f" * file size: {fsize}, variable: '{var_key}', path: {xml_path!r}")

        # Generate time bounds if they are missing.
        ds = cdms2.open(xml_path)
        t_var = ds[var_key]
        t_var.getTime().getBounds()

        reg = cdutil.region.domain(latitude=(-30.0, 30.0))
        t_var_reg = reg.select(t_var)

        for api in APIS_TO_BENCHMARK:
            print(f"  * API: {api}")
            api_runtimes = []

            for idx in range(0, repeat):
                runtime = _get_cdat_runtime(t_var_reg, api)
                api_runtimes.append(runtime)

                print(f"    * Runtime ({(idx+1)} of {repeat}): {runtime}")

            min_runtime = min(api_runtimes)
            print(f"  * Min Runtime (out of {repeat} runs): {min_runtime}")

            entry = {
                "pkg": "cdat",
                "gb": fsize.split("_")[0],
                "api": api,
                f"runtime_serial": min_runtime,
            }
            all_runtimes.append(entry)

    df_runtimes = pd.DataFrame(all_runtimes)

    return df_runtimes


def _get_cdat_runtime(t_var: cdms2.dataset.FileVariable, api: str) -> float:
    start = 0.0
    end = 0.0

    try:
        start = timeit.default_timer()
        _run_cdat_api(t_var, api)

        end = timeit.default_timer()

        runtime = end - start
    except _ArrayMemoryError as e:
        print(e)

        runtime = 0

    return runtime


def _run_cdat_api(
    t_var: cdms2.dataset.FileVariable, api: str
) -> cdms2.tvariable.TransientVariable:
    if api == "spatial_avg":
        return cdutil.averager(t_var, axis="xy", weights="weighted")
    elif api == "temporal_avg":
        return cdutil.averager(t_var, axis="t", weights="weighted")
    elif api == "climatology":
        return cdutil.ANNUALCYCLE.climatology(t_var)
    elif api == "departures":
        return cdutil.ANNUALCYCLE.departures(t_var)


def _sort_dataframe(df: pd.DataFrame):
    return df.sort_values(by=["pkg", "api", "gb"])


if __name__ == "__main__":
    repeat = 5

    # 1. Get xCDAT runtimes.
    # xCDAT serial
    df_xc_serial = get_xcdat_runtimes(repeat, parallel=False)
    df_xc_serial = _sort_dataframe(df_xc_serial)
    df_xc_serial.to_csv(f"{XC_FILENAME}_serial.csv", index=False)

    # xCDAT parallel
    df_xc_parallel = get_xcdat_runtimes(parallel=True, repeat=repeat)
    df_xc_parallel = df_xc_parallel.sort_values(by=["pkg", "api", "gb"])
    df_xc_parallel.to_csv(f"{XC_FILENAME}_parallel.csv", index=False)

    df_xc_times = pd.merge(df_xc_serial, df_xc_parallel, on=["pkg", "gb", "api"])
    df_xc_times.to_csv(f"{XC_FILENAME}.csv", index=False)
    df_xc_times = _sort_dataframe(df_xc_times)

    # 2. Get CDAT runtimes.
    df_cdat_times = get_cdat_runtimes(repeat=repeat)
    df_cdat_times.to_csv(f"{CD_FILENAME}.csv", index=False)
