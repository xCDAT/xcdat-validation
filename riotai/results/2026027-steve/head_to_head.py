"""
Clean Kerchunk vs NetCDF Benchmark (xCDAT-Based)

This module implements a controlled benchmarking framework to compare
kerchunk-backed datasets and native NetCDF datasets under realistic
xCDAT diagnostic workflows.

The benchmark measures four isolated phases:

    1. Dataset open (metadata access)
    2. Variable load (fixed timestep materialization)
    3. Temporal reduction (annual mean)
    4. Spatial reduction (area average)

Each phase is timed independently to attribute performance differences
to specific components of the workflow.

Changes from Original Benchmark
-------------------------------

Backend Fairness
- Both backends are opened with `chunks={}` to ensure Dask-backed lazy arrays.
- No rechunking is performed; on-disk chunk layout is preserved.
- JSON parsing is decoupled from NetCDF opening so kerchunk reference
  parsing does not contaminate native NetCDF open timings.
- Open, load, temporal, and spatial phases are fully isolated.

Workload Control
- A fixed number of timesteps (`FIXED_TIMESTEPS = 240`) is used for
  load benchmarking to ensure consistent logical work across datasets.
- 10–20 files are sampled to balance variability coverage with runtime.

Timing Rigor
- `time.perf_counter()` is used for high-resolution, monotonic timing.
- The first run is dropped internally to reduce cold-cache and
  initialization bias.
- A metadata warm-up open is performed before timing loops to isolate
  steady-state performance.

System Noise Control
- Benchmarks run sequentially (`n_jobs=1`) to avoid filesystem and
  scheduler contention affecting measurements.

Goal
----
Provide a clean, apples-to-apples backend comparison under realistic
xCDAT diagnostic workflows while collecting diagnostic metadata
(chunk structure, task counts, file counts) to explain observed
performance differences.

This module is intended for controlled backend evaluation rather than
large-scale population throughput testing.
"""

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

from joblib import Parallel, delayed
import tqdm
import matplotlib.pyplot as plt


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("benchmark")


logging.getLogger("fsspec").setLevel(logging.ERROR)
logging.getLogger("kerchunk").setLevel(logging.ERROR)
logging.getLogger("xarray").setLevel(logging.ERROR)
logging.getLogger("xcdat").setLevel(logging.ERROR)

# ============================================================
# Configuration
# ============================================================

FIXED_TIMESTEPS = 240


# ============================================================
# Helpers
# ============================================================


def extract_netcdf_path_from_json(fn):
    with open(fn, "r") as file:
        refs = json.load(file)

    for key in refs["refs"]:
        if isinstance(refs["refs"][key], list):
            return os.path.dirname(refs["refs"][key][0]) + "/"

    return None


def get_kerchunk_metadata_stats(fn):
    with open(fn, "r") as file:
        refs = json.load(file)

    ref_dict = refs.get("refs", {})
    netcdf_files = set()

    for value in ref_dict.values():
        if isinstance(value, list) and len(value) > 0:
            netcdf_files.add(value[0])

    return len(netcdf_files), len(ref_dict)


def get_variable_chunk_stats(fn, vid):
    ds = xc.open_dataset(fn, engine="kerchunk", chunks={})
    da = ds[vid]

    if hasattr(da.data, "chunks") and da.data.chunks is not None:
        chunk_sizes = tuple(c[0] for c in da.data.chunks)
        total_chunks = int(np.prod([len(c) for c in da.data.chunks]))
        task_count = len(da.data.__dask_graph__())
    else:
        chunk_sizes = None
        total_chunks = None
        task_count = None

    ds.close()
    return chunk_sizes, total_chunks, task_count


def open_dataset(kerchunk_fn, netcdf_path, tool):
    if tool == "kerchunk":
        return xc.open_dataset(kerchunk_fn, engine="kerchunk", chunks={})
    elif tool == "netcdf":
        return xc.open_mfdataset(netcdf_path, chunks={})


# ============================================================
# Benchmark Phases
# ============================================================


def time_open(kerchunk_fn, netcdf_path, tool):
    s = time.perf_counter()
    ds = open_dataset(kerchunk_fn, netcdf_path, tool)
    e = time.perf_counter()
    ds.close()
    return e - s


def time_load(kerchunk_fn, netcdf_path, vid, tool):
    ds = open_dataset(kerchunk_fn, netcdf_path, tool)
    da = ds[vid]

    if "time" in da.dims:
        n = min(FIXED_TIMESTEPS, da.sizes["time"])
        da = da.isel(time=slice(0, n))

    s = time.perf_counter()
    da.compute()
    e = time.perf_counter()

    ds.close()
    return e - s


def time_temporal(kerchunk_fn, netcdf_path, vid, tool):
    ds = open_dataset(kerchunk_fn, netcdf_path, tool)
    ds = ds.bounds.add_missing_bounds()

    s = time.perf_counter()
    ds.temporal.group_average(vid, freq="year").compute()
    e = time.perf_counter()

    ds.close()
    return e - s


def time_spatial(kerchunk_fn, netcdf_path, vid, tool):
    ds = open_dataset(kerchunk_fn, netcdf_path, tool)
    ds = ds.bounds.add_missing_bounds()

    s = time.perf_counter()
    ds.spatial.average(vid).compute()
    e = time.perf_counter()

    ds.close()
    return e - s


# ============================================================
# Driver
# ============================================================


def run_benchmark(kerchunk_fn, netcdf_path, vid, ntests):

    logger.info(f"Starting benchmark: {os.path.basename(kerchunk_fn)} | var={vid}")

    num_netcdf_files, num_kerchunk_refs = get_kerchunk_metadata_stats(kerchunk_fn)
    chunk_sizes, total_chunks, task_count = get_variable_chunk_stats(kerchunk_fn, vid)

    results = {
        "file": kerchunk_fn,
        "variable": vid,
        "num_netcdf_files": num_netcdf_files,
        "num_kerchunk_refs": num_kerchunk_refs,
        "chunk_sizes": str(chunk_sizes),
        "total_chunks": total_chunks,
        "dask_task_count": task_count,
    }

    metrics = {"open": {}, "load": {}, "temporal": {}, "spatial": {}}

    for tool in ["kerchunk", "netcdf"]:

        logger.info(f"  Backend: {tool}")

        # Warm metadata (not timed)
        try:
            ds = open_dataset(kerchunk_fn, netcdf_path, tool)
            ds.close()
        except Exception as e:
            logger.error(f"    Warm-up failed for {tool}: {e}")
            raise

        open_times = []
        load_times = []
        temporal_times = []
        spatial_times = []

        for i in range(ntests):
            logger.info(f"    Iteration {i+1}/{ntests}")

            try:
                open_times.append(time_open(kerchunk_fn, netcdf_path, tool))
                load_times.append(time_load(kerchunk_fn, netcdf_path, vid, tool))
                temporal_times.append(
                    time_temporal(kerchunk_fn, netcdf_path, vid, tool)
                )
                spatial_times.append(time_spatial(kerchunk_fn, netcdf_path, vid, tool))
            except Exception as e:
                logger.error(f"    Failure during iteration {i+1}: {e}")
                open_times.append(np.nan)
                load_times.append(np.nan)
                temporal_times.append(np.nan)
                spatial_times.append(np.nan)

            gc.collect()

        if ntests > 1:
            open_times = open_times[1:]
            load_times = load_times[1:]
            temporal_times = temporal_times[1:]
            spatial_times = spatial_times[1:]

        metrics["open"][tool] = np.nanmedian(open_times)
        metrics["load"][tool] = np.nanmedian(load_times)
        metrics["temporal"][tool] = np.nanmedian(temporal_times)
        metrics["spatial"][tool] = np.nanmedian(spatial_times)

        logger.info(
            f"    Medians ({tool}) | "
            f"open={metrics['open'][tool]:.3f}s | "
            f"load={metrics['load'][tool]:.3f}s | "
            f"temporal={metrics['temporal'][tool]:.3f}s | "
            f"spatial={metrics['spatial'][tool]:.3f}s"
        )

    results.update(
        {
            "open_kerchunk": metrics["open"]["kerchunk"],
            "open_netcdf": metrics["open"]["netcdf"],
            "load_kerchunk": metrics["load"]["kerchunk"],
            "load_netcdf": metrics["load"]["netcdf"],
            "temporal_kerchunk": metrics["temporal"]["kerchunk"],
            "temporal_netcdf": metrics["temporal"]["netcdf"],
            "spatial_kerchunk": metrics["spatial"]["kerchunk"],
            "spatial_netcdf": metrics["spatial"]["netcdf"],
        }
    )

    logger.info(f"Finished benchmark: {os.path.basename(kerchunk_fn)}\n")

    return results


# ============================================================
# Parameters
# ============================================================

kerchunk_directory = "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/"
ntests = 2
nfiles = 20

kerchunk_files = glob.glob(kerchunk_directory + "ta*/historical/*/*")

random.seed(42)
kerchunk_files = random.sample(kerchunk_files, k=nfiles)

file_pairs = [(fn, extract_netcdf_path_from_json(fn)) for fn in kerchunk_files]

# ============================================================
# Run
# ============================================================
logger.info(f"Running benchmark on {len(file_pairs)} files | ntests={ntests}")
results = Parallel(n_jobs=1)(
    delayed(run_benchmark)(
        kerchunk_fn,
        netcdf_path,
        kerchunk_fn.split("/")[-1].split(".")[7],
        ntests,
    )
    for kerchunk_fn, netcdf_path in tqdm.tqdm(file_pairs)
)
logger.info("Benchmark run complete.")
df = pd.DataFrame(results)

df.to_csv(
    os.path.join(os.path.dirname(__file__), "head_to_head_clean.csv"),
    index=False,
)

# ============================================================
# Plot
# ============================================================

plt.figure(figsize=(8, 8))

for i, key in enumerate(["open", "load", "temporal", "spatial"]):
    plt.subplot(2, 2, i + 1)

    x = df[f"{key}_kerchunk"]
    y = df[f"{key}_netcdf"]

    mv = max(x.max(skipna=True), y.max(skipna=True))

    plt.scatter(x, y)
    plt.plot([0, mv], [0, mv], "k:")
    plt.xlabel("Kerchunk [s]")
    plt.ylabel("NetCDF [s]")
    plt.title(key.capitalize())
    plt.xlim(0, mv)
    plt.ylim(0, mv)

plt.tight_layout()

plt.savefig(
    os.path.join(os.path.dirname(__file__), "head_to_head_clean.png"),
    dpi=300,
    bbox_inches="tight",
)

plt.close()
