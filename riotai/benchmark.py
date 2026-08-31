"""
benchmark.py

Utilities for benchmarking xarray dataset open performance using
Kerchunk JSON references versus raw NetCDF collections.

Designed for climate / CMIP / E3SM-style datasets on HPC or cloud storage.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import logging
import random
import time
import warnings
from typing import Callable, Mapping, TypedDict

import numpy as np
from tqdm import tqdm
import xarray as xr
import xcdat as xc
import pandas as pd

logger = logging.getLogger(__name__)

# Number of parallel worker processes to use per frequency.
# Tuned to limit filesystem metadata pressure for file-heavy datasets
# (e.g., daily or sub-daily data) while allowing more parallelism for monthly
# data.
WORKERS_BY_FREQUENCY = {
    "Amon": 4,
    "Imon": 4,
    "ImonAnt": 4,
    "ImonGre": 4,
    "day": 1,
    "AERhr": 1,
    "CFsubhr": 1,
    "3hr": 1,
    "E1hr": 1,
}


JsonPath = str
NetCDFFileList = list[str]
DatasetMapping = Mapping[JsonPath, NetCDFFileList]


class RawMetric(TypedDict):
    frequency: str
    json: str
    num_netcdf_files: int
    timesteps: int
    dims: dict[str, int]
    kerchunk_time: float
    netcdf_time: float


class AggMetric(TypedDict):
    freq: str
    n: int
    sample_size_target: int
    coverage: float
    sampling: str
    mean_netcdf_files: int
    median_netcdf_files: int
    kerchunk_median: float
    netcdf_median: float
    kerchunk_mean: float
    netcdf_mean: float


def benchmark_all_frequencies(
    freq_json_netcdf_map: Mapping[str, DatasetMapping],
    sample_size: int = 40,
    warmup: bool = True,
    rng: random.Random | None = None,
    freqs: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Benchmark all frequencies in the provided mapping.

    Parameters
    ----------
    freq_json_netcdf_map : Mapping[str, DatasetMapping]
        Mapping from frequency (str) to a mapping of Kerchunk JSON file paths (str)
        to lists of NetCDF file paths (list of str).
    sample_size : int, optional
        Number of samples to benchmark per frequency (default is 40).
    warmup : bool, optional
        Whether to perform a warm-up open before benchmarking (default is True).
    rng : random.Random or None, optional
        Random number generator for reproducible sampling (default is None).

    Returns
    -------
    tuple of pd.DataFrame
        DataFrames containing raw and aggregate benchmark metrics.
    """
    all_raw_metrics: list[RawMetric] = []
    all_agg_metrics: list[AggMetric] = []

    for frequency, dataset_mapping in freq_json_netcdf_map.items():
        if frequency is not None and frequency not in freqs:
            continue

        sampled_dataset_items = _sample_items(dataset_mapping, sample_size, rng)
        raw_metrics, sampled_dataset_items = _benchmark_frequency(
            frequency, sampled_dataset_items, warmup
        )

        all_raw_metrics.extend(raw_metrics)

        agg_metrics = _get_agg_metrics(
            raw_metrics,
            frequency,
            sample_size,
            sampled_dataset_items,
        )

        all_agg_metrics.append(agg_metrics)

    df_raw_metrics = pd.DataFrame(all_raw_metrics)
    df_agg_metrics = pd.DataFrame(all_agg_metrics)

    return df_raw_metrics, df_agg_metrics


# -----------------------------------------------------------------------------
# Benchmark core
# -----------------------------------------------------------------------------
def _benchmark_frequency(
    freq: str,
    sampled_items: list[tuple[str, list[str]]],
    warmup: bool = True,
) -> tuple[list[RawMetric], list[tuple[str, list[str]]]]:
    """
    Benchmark Kerchunk vs NetCDF open performance for a single frequency.

    Parameters
    ----------
    freq : str
        Frequency name (e.g., "Amon", "day", "AERhr").
    sampled_items : list of (str, list of str)
        Sampled (json_file, netcdf_files) pairs to benchmark.
    warmup : bool, default=True
        Whether to perform an unrecorded warm-up open.

    Returns
    -------
    tuple
        (raw_metrics, sampled_items)
    """
    logger.info(f"\n=== Benchmarking {freq} ===")

    # Warm-up to avoid cache effects, remains serial.
    if warmup and sampled_items:
        _run_warmup(sampled_items, freq)

    raw_metrics: list[RawMetric] = []
    max_workers = WORKERS_BY_FREQUENCY[freq]

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                _benchmark_single_item,
                freq,
                json_file,
                netcdf_files,
            )
            for json_file, netcdf_files in sampled_items
        ]

        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc="Comparing I/O speed",
            mininterval=5,
        ):
            result = future.result()
            if result is not None:
                raw_metrics.append(result)

    return raw_metrics, sampled_items


def _benchmark_single_item(
    freq: str,
    json_file: str,
    netcdf_files: list[str],
) -> RawMetric | None:
    try:
        kc_time = _time_call(_open_kerchunk, json_file)
    except Exception:
        return None

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning)
            nc_time = _time_call(_open_netcdf, netcdf_files)
    except Exception:
        return None

    dims, timesteps = _get_dims_and_timesteps(json_file)

    return {
        "frequency": freq,
        "json": json_file,
        "num_netcdf_files": len(netcdf_files),
        "timesteps": timesteps,
        "dims": dims,
        "kerchunk_time": kc_time,
        "netcdf_time": nc_time,
    }


def _sample_items(
    mapping: DatasetMapping,
    sample_size: int,
    rng: random.Random | None = None,
) -> list[tuple[str, list[str]]]:
    """
    Randomly sample dataset entries from a JSON → NetCDF mapping.
    """
    # A new random.Random instance seeded with 42 is used for reproducibility.
    if rng is None:
        rng = random.Random(42)

    items = sorted(mapping.items())

    return rng.sample(items, min(sample_size, len(items)))


def _run_warmup(sampled_items: list[tuple[str, list[str]]], freq: str) -> None:
    logger.info("  * Performing warm-up open...")
    json_file, netcdf_files = sampled_items[0]

    try:
        _open_kerchunk(json_file)
        _open_netcdf(netcdf_files)
    except Exception as e:
        logger.info(f"  * Warm-up failed for {freq}: {e}")


def _get_dims_and_timesteps(json_file: str) -> tuple[dict[str, int], int]:
    """
    Get the dimension names and number of time steps in an xarray Dataset.

    Parameters
    ----------
    json_file : str
        Path to the Kerchunk JSON reference file.

    Returns
    -------
    tuple
        (dimension sizes, number of time steps)
    """
    with xr.open_dataset(json_file, engine="kerchunk") as ds:
        time_dim = xc.get_dim_coords(ds, "T")
        timesteps = len(time_dim) if time_dim is not None else 0

        return dict(ds.sizes), timesteps


def _time_call(fn: Callable[..., None], *args) -> float:
    """
    Measure wall-clock execution time of a callable.

    Parameters
    ----------
    fn : callable
        Function to execute.
    *args
        Positional arguments passed to the function.

    Returns
    -------
    float
        Elapsed time in seconds.
    """
    t0 = time.perf_counter()
    fn(*args)
    return time.perf_counter() - t0


def _open_kerchunk(json_file: str) -> None:
    """
    Open a Kerchunk JSON reference file using xarray.

    This function measures *open cost only* and does not read any data.

    Parameters
    ----------
    json_file : str
        Path to the Kerchunk JSON reference file.

    Returns
    -------
    None
    """
    with xc.open_dataset(json_file, engine="kerchunk"):
        pass


def _open_netcdf(netcdf_files: list[str]) -> None:
    """
    Open a collection of NetCDF files using xarray.open_mfdataset.

    Uses minimal metadata options to avoid benchmarking merge or conflict
    resolution overhead.

    Parameters
    ----------
    netcdf_files : list of str
        List of NetCDF file paths to open.

    Returns
    -------
    None
    """
    with xc.open_mfdataset(
        netcdf_files,
        combine="by_coords",
        compat="override",
        coords="minimal",
        data_vars="minimal",
        parallel=False,
        chunks={},
    ):
        pass


def _get_agg_metrics(
    raw_metrics: list[RawMetric],
    freq: str,
    sample_size: int,
    sampled_items: list[tuple[str, list[str]]],
) -> AggMetric | None:
    """
    Compute aggregate metrics from raw timing data.

    Parameters
    ----------
    raw_metrics : list of dict
        List of raw benchmark metrics.
    freq : str
        Frequency name.
    sample_size : int
        Target sample size.
    sampled_items : list
        Actual sampled (json, netcdf_files) pairs.

    Returns
    -------
    dict or None
        Aggregate metrics including mean and median times.
    """
    kc_times = [m["kerchunk_time"] for m in raw_metrics]
    nc_times = [m["netcdf_time"] for m in raw_metrics]

    if not kc_times or not nc_times:
        return None

    agg_metrics = {
        # --- Sample size / statistical context ---
        "freq": freq,
        "n": len(kc_times),
        "sample_size_target": sample_size,
        "coverage": float(min(1.0, len(sampled_items) / sample_size)),
        "sampling": "exhaustive" if len(sampled_items) < sample_size else "random",
        # --- Workload characterization ---
        "mean_netcdf_files": (
            int(np.mean([len(nc) for _, nc in sampled_items])) if sampled_items else 0
        ),
        "median_netcdf_files": (
            int(np.median([len(nc) for _, nc in sampled_items])) if sampled_items else 0
        ),
        # --- Metrics ---
        "kerchunk_median": float(np.median(kc_times)),
        "netcdf_median": float(np.median(nc_times)),
        "kerchunk_mean": float(np.mean(kc_times)),
        "netcdf_mean": float(np.mean(nc_times)),
    }

    return agg_metrics
