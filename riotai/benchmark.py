"""
benchmark.py

Utilities for benchmarking xarray dataset open performance using
Kerchunk JSON references versus raw NetCDF collections.

Designed for climate / CMIP / E3SM-style datasets on HPC or cloud storage.
"""

from __future__ import annotations

import random
import time
import warnings
from typing import Callable, Iterable, Mapping, Optional

import numpy as np
from tqdm import tqdm
import xarray as xc


JsonPath = str
NetCDFFileList = list[str]
DatasetMapping = Mapping[JsonPath, NetCDFFileList]


def compare_io_speed(json_path: str, netcdf_paths: list[str]):
    """
    Compare I/O speed between kerchunk (open_dataset) and NetCDF (open_mfdataset).
    Prints the time taken to open each dataset.
    """
    # Time kerchunk open
    print(f"Kerchunk JSON path: {json_path}")
    print(f"NetCDF file paths: {netcdf_paths}")
    t0 = time.perf_counter()
    _ = xc.open_dataset(json_path, engine="kerchunk")
    t1 = time.perf_counter()
    kc_time = t1 - t0

    # Time NetCDF open
    t0 = time.perf_counter()
    _ = xc.open_mfdataset(netcdf_paths, chunks={})
    t1 = time.perf_counter()
    nc_time = t1 - t0

    print(f"Kerchunk open_dataset time: {kc_time:.4f} seconds")
    print(f"NetCDF open_mfdataset time: {nc_time:.4f} seconds")


# -----------------------------------------------------------------------------
# Dataset open helpers
# -----------------------------------------------------------------------------


def open_kerchunk(json_file: str) -> None:
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


def open_netcdf(netcdf_files: list[str]) -> None:
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


# -----------------------------------------------------------------------------
# Timing utilities
# -----------------------------------------------------------------------------


def time_call(fn: Callable[..., None], *args) -> float:
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


# -----------------------------------------------------------------------------
# Sampling utilities
# -----------------------------------------------------------------------------


def sample_items(
    mapping: DatasetMapping,
    sample_size: int,
    rng: Optional[random.Random] = None,
) -> list[tuple[str, list[str]]]:
    """
    Randomly sample dataset entries from a JSON → NetCDF mapping.

    Parameters
    ----------
    mapping : mapping
        Mapping from Kerchunk JSON path to list of NetCDF files.
    sample_size : int
        Maximum number of items to sample.
    rng : random.Random, optional
        Random number generator instance for reproducibility.

    Returns
    -------
    list of (str, list of str)
        Sampled (json_file, netcdf_files) pairs.
    """
    rng = rng or random
    items = list(mapping.items())
    return rng.sample(items, min(sample_size, len(items)))


# -----------------------------------------------------------------------------
# Benchmark core
# -----------------------------------------------------------------------------


def benchmark_frequency(
    freq: str,
    freq_to_json_to_netcdf: Mapping[str, DatasetMapping],
    sample_size: int = 40,
    warmup: bool = True,
    rng: Optional[random.Random] = None,
) -> Optional[dict[str, float]]:
    """
    Benchmark Kerchunk vs NetCDF open performance for a single frequency.

    Parameters
    ----------
    freq : str
        Frequency name (e.g., "Amon", "day", "AERhr").
    freq_to_json_to_netcdf : mapping
        Mapping from frequency → (JSON → NetCDF file list).
    sample_size : int, default=40
        Number of datasets to sample.
    warmup : bool, default=True
        Whether to perform an unrecorded warm-up open.
    rng : random.Random, optional
        Random number generator for reproducible sampling.

    Returns
    -------
    dict or None
        Dictionary with timing statistics, or None if benchmarking failed.

        Keys:
        - "kerchunk_mean"
        - "kerchunk_median"
        - "netcdf_mean"
        - "netcdf_median"
        - "n"
    Notes:
    -----
    Warm-up: exclude the first open to avoid one-time initialization and
    filesystem cache effects that would otherwise bias timing results.
    """
    print(f"\n=== Benchmarking {freq} ===")

    json_to_netcdf = freq_to_json_to_netcdf.get(freq)
    if not json_to_netcdf:
        return None

    sampled_items = sample_items(json_to_netcdf, sample_size, rng)

    kc_times: list[float] = []
    nc_times: list[float] = []

    if warmup:
        print("  * Performing warm-up open...")
        json_file, netcdf_files = sampled_items[0]

        try:
            open_kerchunk(json_file)
            open_netcdf(netcdf_files)
        except Exception as e:
            print(f"  * Warm-up failed for {freq}: {e}")

            return None

    for json_file, netcdf_files in tqdm(
        sampled_items, desc="Comparing I/O speed", mininterval=5
    ):
        kc_times.append(time_call(open_kerchunk, json_file))

        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning)
                nc_times.append(time_call(open_netcdf, netcdf_files))
        except Exception as e:
            print(f"  * Skipping NetCDF error in {freq}: {e}")

            continue

    if not kc_times or not nc_times:
        return None

    return {
        # --- Performance results ---
        "kerchunk_mean": float(np.mean(kc_times)),
        "kerchunk_median": float(np.median(kc_times)),
        "netcdf_mean": float(np.mean(nc_times)),
        "netcdf_median": float(np.median(nc_times)),
        # --- Sample size / statistical context ---
        "n": min(len(kc_times), len(nc_times)),
        "sample_size_target": sample_size,
        "coverage": float(min(1.0, len(sampled_items) / sample_size)),
        "sampling": "exhaustive" if len(sampled_items) < sample_size else "random",
        # --- Workload characterization ---
        "median_netcdf_files": (
            int(np.median([len(nc) for _, nc in sampled_items])) if sampled_items else 0
        ),
    }


# -----------------------------------------------------------------------------
# Convenience helpers
# -----------------------------------------------------------------------------


def benchmark_all_frequencies(
    frequencies: Iterable[str],
    freq_to_json_to_netcdf: Mapping[str, DatasetMapping],
    sample_size: int = 40,
    warmup: bool = True,
    rng: Optional[random.Random] = None,
) -> dict[str, dict[str, float]]:
    """
    Benchmark all specified frequencies.

    Parameters
    ----------
    frequencies : iterable of str
        Frequency names to benchmark.
    freq_to_json_to_netcdf : mapping
        Mapping from frequency → (JSON → NetCDF file list).
    sample_size : int, default=40
        Number of datasets sampled per frequency.
    warmup : bool, default=True
        Whether to perform warm-up opens.
    rng : random.Random, optional
        Random number generator for reproducibility.

    Returns
    -------
    dict
        Mapping from frequency name to benchmark result dictionary.
    """
    results: dict[str, dict[str, float]] = {}

    for freq in frequencies:
        result = benchmark_frequency(
            freq=freq,
            freq_to_json_to_netcdf=freq_to_json_to_netcdf,
            sample_size=sample_size,
            warmup=warmup,
            rng=rng,
        )
        if result is not None:
            results[freq] = result

    return results
