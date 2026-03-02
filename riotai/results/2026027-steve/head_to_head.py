"""
Controlled Kerchunk vs NetCDF Benchmark (xCDAT-Based)

Disk-chunk–preserving benchmark comparing kerchunk-backed datasets
and native NetCDF datasets under realistic xCDAT diagnostic workflows.

Characteristics
---------------
• Preserves on-disk chunking (`chunks={}`); no rechunking.
• Uses identical NetCDF file lists derived from kerchunk references.
• Applies a fixed timestep slice (`FIXED_TIMESTEPS`) for controlled workload.
    • Defaults to 240 timesteps to balance runtime and representativeness.
    • mon: ~20 years
    • day: ~8 months
• Measures four phases independently:
    1. Open (metadata graph construction)
    2. Load (materialization of fixed slice)
    3. Temporal reduction (annual mean on fixed slice)
    4. Spatial reduction (area average on fixed slice)
• Temporal and spatial phases separate Dask graph-build and compute time.

Stratified Design
-----------------
• Benchmarks are executed separately by frequency (e.g., day, mon).
  • hr-misc is not included because it is a heterogeneous mix of frequencies.
• File selection within each frequency is deterministic and stratified
  (evenly spaced across the sorted file list) to ensure structural coverage
  while remaining reproducible.
• Results are interpreted within-frequency; cross-frequency runtime
  comparisons are not meaningful due to differing temporal resolution,
  file segmentation, and graph structure.

Diagnostics Collected
---------------------
• NetCDF file count
• Time dimension length
• Time chunk statistics
• Dask task counts
• Physical dataset size (GB)
• Slice workload size (GB)

Execution is sequential and deterministic to minimize system noise.

Purpose
-------
Enable storage-layout–faithful backend comparison with sufficient
metadata to explain performance differences. Not intended as a
throughput or scaling benchmark.

Usage
-----
salloc --nodes 1 --qos interactive --constraint cpu --time 04:00:00 --account mXXXX
conda activate xcdat_test_stable_min
python riotai/results/2026027-steve/head_to_head.py
"""

from __future__ import annotations

from datetime import datetime

import glob
import json
import logging
import os
import time
import gc

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import tqdm
from joblib import Parallel, delayed

import xcdat as xc
import dask


# ============================================================
# Configuration
# ============================================================

FIXED_TIMESTEPS: int = 240
NTESTS: int = 3
NFILES: int = 5  # number per frequency

KERCHUNK_DIRECTORY: str = (
    "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/ta/historical"
)

_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_CSV: str = f"benchmark_{_TS}.csv"

# Configure Dask to use the local threaded scheduler without creating a
# distributed Client. This mirrors typical xarray/xCDAT user workflows,
# where Dask runs in-process with a thread pool. `num_workers` limits
# parallel task execution to avoid oversubscription and improve
# reproducibility of wall-clock timing.
dask.config.set(scheduler="threads", num_workers=8)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("benchmark")

# Suppress verbose fsspec logging from kerchunk.
logging.getLogger("fsspec").setLevel(logging.ERROR)


# ============================================================
# Public API
# ============================================================


def main() -> None:
    frequencies = ["day", "mon"]
    all_results = []

    for freq in frequencies:
        freq_dir = os.path.join(KERCHUNK_DIRECTORY, freq)
        if not os.path.isdir(freq_dir):
            continue

        logger.info(f"Running frequency: {freq}")

        all_files = sorted(
            glob.glob(os.path.join(freq_dir, "**", "*.json"), recursive=True)
        )

        if not all_files:
            logger.warning(f"No files found for frequency: {freq}")
            continue

        # -------- Deterministic Stratified Selection --------
        if len(all_files) <= NFILES:
            kerchunk_files = all_files
        else:
            indices = np.linspace(0, len(all_files) - 1, NFILES, dtype=int)
            kerchunk_files = [all_files[i] for i in indices]
        # -----------------------------------------------------

        items = []
        for fn in kerchunk_files:
            refs = _load_kerchunk_refs(fn)
            netcdf_files = _extract_netcdf_files(refs)
            if not netcdf_files:
                continue
            vid = _infer_vid(fn)
            items.append((fn, refs, netcdf_files, vid))

        results = Parallel(n_jobs=1)(
            delayed(run_benchmark)(fn, refs, netcdf_files, vid, NTESTS)
            for fn, refs, netcdf_files, vid in tqdm.tqdm(items)
        )

        if not results:
            logger.warning(f"No benchmark results for frequency: {freq}")
            continue

        df = pd.DataFrame(results)
        df["frequency"] = freq

        _plot_results(df, freq)
        all_results.extend(results)

    pd.DataFrame(all_results).to_csv(OUT_CSV, index=False)


def run_benchmark(
    kerchunk_fn: str,
    refs: dict,
    netcdf_files: list[str],
    vid: str,
    ntests: int,
) -> dict:

    results: dict = {
        "file": kerchunk_fn,
        "variable": vid,
    }

    results.update(_collect_backend_metadata(kerchunk_fn, netcdf_files, vid))

    metrics = {
        "open": {},
        "load": {},
        "temporal_build": {},
        "temporal_compute": {},
        "spatial_build": {},
        "spatial_compute": {},
    }

    for tool in ["kerchunk", "netcdf"]:

        _warmup_open(kerchunk_fn, netcdf_files, tool)

        open_times = []
        load_times = []
        temporal_build_times = []
        temporal_compute_times = []
        spatial_build_times = []
        spatial_compute_times = []

        for _ in range(ntests):
            open_times.append(_time_open(kerchunk_fn, netcdf_files, tool))
            load_times.append(_time_load(kerchunk_fn, netcdf_files, vid, tool))

            tb, tc = _time_temporal(kerchunk_fn, netcdf_files, vid, tool)
            sb, sc = _time_spatial(kerchunk_fn, netcdf_files, vid, tool)

            temporal_build_times.append(tb)
            temporal_compute_times.append(tc)
            spatial_build_times.append(sb)
            spatial_compute_times.append(sc)

            gc.collect()

        if ntests > 1:
            open_times = open_times[1:]
            load_times = load_times[1:]
            temporal_build_times = temporal_build_times[1:]
            temporal_compute_times = temporal_compute_times[1:]
            spatial_build_times = spatial_build_times[1:]
            spatial_compute_times = spatial_compute_times[1:]

        metrics["open"][tool] = float(np.nanmedian(open_times))
        metrics["load"][tool] = float(np.nanmedian(load_times))
        metrics["temporal_build"][tool] = float(np.nanmedian(temporal_build_times))
        metrics["temporal_compute"][tool] = float(np.nanmedian(temporal_compute_times))
        metrics["spatial_build"][tool] = float(np.nanmedian(spatial_build_times))
        metrics["spatial_compute"][tool] = float(np.nanmedian(spatial_compute_times))

    results.update(
        {
            "open_kerchunk": metrics["open"]["kerchunk"],
            "open_netcdf": metrics["open"]["netcdf"],
            "load_kerchunk": metrics["load"]["kerchunk"],
            "load_netcdf": metrics["load"]["netcdf"],
            "temporal_build_kerchunk": metrics["temporal_build"]["kerchunk"],
            "temporal_build_netcdf": metrics["temporal_build"]["netcdf"],
            "temporal_compute_kerchunk": metrics["temporal_compute"]["kerchunk"],
            "temporal_compute_netcdf": metrics["temporal_compute"]["netcdf"],
            "spatial_build_kerchunk": metrics["spatial_build"]["kerchunk"],
            "spatial_build_netcdf": metrics["spatial_build"]["netcdf"],
            "spatial_compute_kerchunk": metrics["spatial_compute"]["kerchunk"],
            "spatial_compute_netcdf": metrics["spatial_compute"]["netcdf"],
        }
    )

    return results


# ============================================================
# Private Helpers
# ============================================================


def _compute_physical_size_gb(netcdf_files: list[str]) -> float:
    total_bytes = sum(os.path.getsize(f) for f in netcdf_files if os.path.exists(f))

    return total_bytes / (1024**3)


def _compute_slice_size_gb(da) -> float | None:
    try:
        if "time" in da.dims:
            n = min(FIXED_TIMESTEPS, da.sizes["time"])
            da = da.isel(time=slice(0, n))

        return da.nbytes / (1024**3)
    except Exception:
        return None


def _collect_backend_metadata(
    kerchunk_fn: str, netcdf_files: list[str], vid: str
) -> dict:

    ds = xc.open_dataset(kerchunk_fn, engine="kerchunk", chunks={})
    try:
        da = ds[vid]

        return {
            "time_len": int(da.sizes.get("time", -1)),
            "size_gb_physical": _compute_physical_size_gb(netcdf_files),
            "size_gb_slice": _compute_slice_size_gb(da),
        }
    finally:
        ds.close()


def _load_kerchunk_refs(fn: str) -> dict:
    with open(fn) as f:
        return json.load(f)


def _extract_netcdf_files(refs: dict) -> list[str]:
    return sorted(
        {
            value[0]
            for value in refs.get("refs", {}).values()
            if isinstance(value, list) and value
        }
    )


def _infer_vid(kerchunk_fn: str) -> str:
    base = os.path.basename(kerchunk_fn)
    parts = base.split(".")
    return parts[7] if len(parts) > 7 else "ta"


def _open_dataset(kerchunk_fn: str, netcdf_files: list[str], tool: str):
    if tool == "kerchunk":
        return xc.open_dataset(kerchunk_fn, engine="kerchunk", chunks={})

    return xc.open_mfdataset(netcdf_files, chunks={}, combine="by_coords")


def _apply_fixed_time_slice(ds, vid: str):
    if "time" in ds[vid].dims:
        n = min(FIXED_TIMESTEPS, ds[vid].sizes["time"])

        return ds.isel(time=slice(0, n))

    return ds


def _warmup_open(kerchunk_fn: str, netcdf_files: list[str], tool: str) -> None:
    ds = _open_dataset(kerchunk_fn, netcdf_files, tool)
    ds.close()


def _time_open(kerchunk_fn: str, netcdf_files: list[str], tool: str) -> float:
    s = time.perf_counter()
    ds = _open_dataset(kerchunk_fn, netcdf_files, tool)
    e = time.perf_counter()

    ds.close()

    return e - s


def _time_load(kerchunk_fn: str, netcdf_files: list[str], vid: str, tool: str) -> float:
    ds = _open_dataset(kerchunk_fn, netcdf_files, tool)
    ds = _apply_fixed_time_slice(ds, vid)

    s = time.perf_counter()
    ds[vid].compute()
    e = time.perf_counter()

    ds.close()

    return e - s


def _time_temporal(
    kerchunk_fn: str, netcdf_files: list[str], vid: str, tool: str
) -> tuple[float, float]:
    ds = _open_dataset(kerchunk_fn, netcdf_files, tool)
    ds = _apply_fixed_time_slice(ds, vid)

    s_build = time.perf_counter()
    ds = ds.bounds.add_missing_bounds()
    expr = ds.temporal.group_average(vid, freq="year")
    e_build = time.perf_counter()

    s_compute = time.perf_counter()
    expr.compute()
    e_compute = time.perf_counter()

    ds.close()

    return e_build - s_build, e_compute - s_compute


def _time_spatial(
    kerchunk_fn: str, netcdf_files: list[str], vid: str, tool: str
) -> tuple[float, float]:
    ds = _open_dataset(kerchunk_fn, netcdf_files, tool)
    ds = _apply_fixed_time_slice(ds, vid)

    s_build = time.perf_counter()
    ds = ds.bounds.add_missing_bounds()
    expr = ds.spatial.average(vid)
    e_build = time.perf_counter()

    s_compute = time.perf_counter()
    expr.compute()
    e_compute = time.perf_counter()

    ds.close()

    return e_build - s_build, e_compute - s_compute


def _plot_results(df: pd.DataFrame, freq: str) -> None:
    if df.empty:
        logger.warning(f"Empty DataFrame for frequency: {freq}, skipping plot.")

        return

    df["temporal_total_kerchunk"] = (
        df["temporal_build_kerchunk"] + df["temporal_compute_kerchunk"]
    )
    df["temporal_total_netcdf"] = (
        df["temporal_build_netcdf"] + df["temporal_compute_netcdf"]
    )
    df["spatial_total_kerchunk"] = (
        df["spatial_build_kerchunk"] + df["spatial_compute_kerchunk"]
    )
    df["spatial_total_netcdf"] = (
        df["spatial_build_netcdf"] + df["spatial_compute_netcdf"]
    )

    plt.figure(figsize=(9, 9))

    panels = [
        ("Open", "open_kerchunk", "open_netcdf"),
        ("Load", "load_kerchunk", "load_netcdf"),
        ("Temporal", "temporal_total_kerchunk", "temporal_total_netcdf"),
        ("Spatial", "spatial_total_kerchunk", "spatial_total_netcdf"),
    ]

    for i, (title, kcol, ncol) in enumerate(panels):
        plt.subplot(2, 2, i + 1)
        x = df[kcol]
        y = df[ncol]
        mv = max(float(np.nanmax(x)), float(np.nanmax(y)), 1.0)
        plt.scatter(x, y)
        plt.plot([0, mv], [0, mv], "k:")
        plt.title(title)
        plt.xlim(0, mv)
        plt.ylim(0, mv)

    plt.suptitle(f"Frequency: {freq}")
    plt.tight_layout()
    plt.savefig(f"benchmark_{freq}_{_TS}.png", dpi=300)
    plt.close()


if __name__ == "__main__":
    main()
