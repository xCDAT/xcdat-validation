"""
Controlled Kerchunk vs NetCDF Benchmark (xCDAT-Based)

Disk-chunk–preserving benchmark comparing kerchunk-backed datasets
and native NetCDF datasets under realistic xCDAT diagnostic workflows.

Execution Model
---------------
• Uses Dask threaded scheduler with a fixed number of workers (no distributed cluster).
• BLAS/OpenMP threading disabled (OMP/MKL/OPENBLAS=1) to reduce oversubscription noise.
• Execution is sequential across datasets for reproducibility.
• Each phase timed multiple times; first run discarded, median reported.

Workload Design
---------------
• Preserves on-disk chunking (`chunks={}`); no rechunking performed.
• Uses identical NetCDF file lists derived from kerchunk references.
• Deterministic stratified file selection within each frequency.
• Applies a fixed leading timestep slice (`FIXED_TIMESTEPS`).
    • Default: 240 timesteps.
    • mon ≈ 20 years; day ≈ 8 months.
    • Slice is positional and may not align with chunk boundaries.
    • Partial chunks may therefore be read in full; both backends
      preserve identical on-disk chunking, so any chunk-level
      amplification affects them symmetrically.
• Measures four phases independently:
    1. Open (metadata parsing + Dask graph construction)
    2. Load (materialization of fixed slice)
    3. Temporal reduction (annual mean; build and compute timed separately)
    4. Spatial reduction (area average; build and compute timed separately)

Stratified Design
-----------------
• Benchmarks executed separately for `mon` and `day`.
• `hr-misc` excluded due to heterogeneous cadence.
• Results interpreted within-frequency; cross-frequency runtime
  comparisons are not meaningful.

Diagnostics and Reporting
-------------------------
Per dataset:
• NetCDF file count
• Time dimension length
• Time chunk minimum and count
• Dask task count (pre-compute graph size)
• Physical dataset size (GB)
• Slice logical size (GB)
• Median phase timings (kerchunk vs NetCDF)

Purpose
-------
Provide a storage-layout–faithful, reproducible backend comparison.
Not intended as a throughput scaling or distributed performance benchmark.

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

# Prevent multithreading in underlying libraries to reduce noise in timing
# measurements.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import tqdm

import xcdat as xc
import dask


# ============================================================
# Configuration
# ============================================================

FIXED_TIMESTEPS: int = 240
NTESTS: int = 3
NFILES: int = 10  # number per frequency

KERCHUNK_DIRECTORY: str = (
    "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/ta/historical"
)

_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
ROOT_DIR = os.path.dirname(__file__)
# Output CSV will be written to the same directory as this script
OUT_CSV: str = os.path.join(ROOT_DIR, f"{_TS}_benchmark.csv")

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
    all_results: list[dict] = []

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

        # Stratified sampling of kerchunk files to limit total runtime
        if len(all_files) <= NFILES:
            kerchunk_files = all_files
        else:
            indices = np.linspace(0, len(all_files) - 1, NFILES, dtype=int)
            kerchunk_files = [all_files[i] for i in indices]

        items: list[tuple[str, list[str], str]] = []
        for fn in kerchunk_files:
            refs = _load_kerchunk_refs(fn)
            netcdf_files = _extract_netcdf_files(refs)
            if not netcdf_files:
                continue
            var_id = _infer_var_id(fn)
            items.append((fn, netcdf_files, var_id))

        results: list[dict] = []
        for fn, netcdf_files, var_id in tqdm.tqdm(items):
            r = run_benchmark(fn, netcdf_files, var_id, NTESTS)
            if r is not None:
                results.append(r)

        if not results:
            logger.warning(f"No benchmark results for frequency: {freq}")
            continue

        for r in results:
            r["frequency"] = freq

        df = pd.DataFrame(results)

        _plot_results(df, freq)
        _log_median_ratios(df, freq)

        all_results.extend(results)

    pd.DataFrame(all_results).to_csv(OUT_CSV, index=False)


def run_benchmark(
    kerchunk_fn: str,
    netcdf_files: list[str],
    var_id: str,
    ntests: int,
) -> dict:

    results: dict = {
        "file": kerchunk_fn,
        "variable": var_id,
    }

    results.update(_collect_backend_metadata(kerchunk_fn, netcdf_files, var_id))
    if results.get("skip"):
        return None

    logger.info(
        f"{os.path.basename(kerchunk_fn)} | "
        f"files={results.get('netcdf_file_count')} | "
        f"time_len(k/n)={results.get('kerchunk_time_len')}/{results.get('netcdf_time_len')} | "
        f"time_chunks(k/n)={results.get('kerchunk_time_chunk_count')}/{results.get('netcdf_time_chunk_count')} | "
        f"post_slice_time_chunks(k/n)={results.get('kerchunk_post_slice_time_chunk_count')}/"
        f"{results.get('netcdf_post_slice_time_chunk_count')} | "
        f"size_gb={results.get('size_gb_physical', float('nan')):.2f}"
    )

    metrics = {
        "open": {},
        "load": {},
        "temporal_build": {},
        "temporal_compute": {},
        "temporal_graph": {},
        "spatial_build": {},
        "spatial_compute": {},
    }

    for tool in ["kerchunk", "netcdf"]:
        open_times: list[float] = []
        load_times: list[float] = []
        temporal_build_times: list[float] = []
        temporal_compute_times: list[float] = []
        temporal_graph_counts: list[int | None] = []
        spatial_build_times: list[float] = []
        spatial_compute_times: list[float] = []

        for _ in range(ntests):
            open_times.append(_time_open(kerchunk_fn, netcdf_files, tool))
            load_times.append(_time_load(kerchunk_fn, netcdf_files, var_id, tool))

            tb, tc, tg = _time_temporal(kerchunk_fn, netcdf_files, var_id, tool)
            if tb is None:
                logger.warning(
                    f"Skipping (temporal failed, tool={tool}): {os.path.basename(kerchunk_fn)}"
                )
                return None

            sb, sc = _time_spatial(kerchunk_fn, netcdf_files, var_id, tool)
            if sb is None:
                logger.warning(
                    f"Skipping (spatial failed, tool={tool}): {os.path.basename(kerchunk_fn)}"
                )
                return None

            temporal_build_times.append(tb)
            temporal_compute_times.append(tc)
            temporal_graph_counts.append(tg)
            spatial_build_times.append(sb)
            spatial_compute_times.append(sc)

            gc.collect()

        # discard warmup
        if ntests > 1:
            open_times = open_times[1:]
            load_times = load_times[1:]
            temporal_build_times = temporal_build_times[1:]
            temporal_compute_times = temporal_compute_times[1:]
            temporal_graph_counts = temporal_graph_counts[1:]
            spatial_build_times = spatial_build_times[1:]
            spatial_compute_times = spatial_compute_times[1:]

        metrics["open"][tool] = float(np.nanmedian(open_times))
        metrics["load"][tool] = float(np.nanmedian(load_times))
        metrics["temporal_build"][tool] = float(np.nanmedian(temporal_build_times))
        metrics["temporal_compute"][tool] = float(np.nanmedian(temporal_compute_times))
        metrics["spatial_build"][tool] = float(np.nanmedian(spatial_build_times))
        metrics["spatial_compute"][tool] = float(np.nanmedian(spatial_compute_times))

        # median graph task count (ignore None)
        tg_vals = [v for v in temporal_graph_counts if v is not None]
        metrics["temporal_graph"][tool] = int(np.median(tg_vals)) if tg_vals else None

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
            "temporal_graph_tasks_kerchunk": metrics["temporal_graph"]["kerchunk"],
            "temporal_graph_tasks_netcdf": metrics["temporal_graph"]["netcdf"],
            "spatial_build_kerchunk": metrics["spatial_build"]["kerchunk"],
            "spatial_build_netcdf": metrics["spatial_build"]["netcdf"],
            "spatial_compute_kerchunk": metrics["spatial_compute"]["kerchunk"],
            "spatial_compute_netcdf": metrics["spatial_compute"]["netcdf"],
        }
    )

    logger.info(
        f"{os.path.basename(kerchunk_fn)} | "
        f"open: {results['open_kerchunk']:.2f}/{results['open_netcdf']:.2f} | "
        f"load: {results['load_kerchunk']:.2f}/{results['load_netcdf']:.2f} | "
        f"temporal: {results['temporal_compute_kerchunk']:.2f}/{results['temporal_compute_netcdf']:.2f} | "
        f"spatial: {results['spatial_compute_kerchunk']:.2f}/{results['spatial_compute_netcdf']:.2f} | "
        f"temporal_graph_tasks: {results['temporal_graph_tasks_kerchunk']}/"
        f"{results['temporal_graph_tasks_netcdf']}"
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
    kerchunk_fn: str, netcdf_files: list[str], var_id: str
) -> dict:

    results = {
        "netcdf_file_count": len(netcdf_files),
        "size_gb_physical": _compute_physical_size_gb(netcdf_files),
    }

    # Kerchunk
    ds_k = xc.open_dataset(kerchunk_fn, engine="kerchunk", chunks={})
    try:
        results.update(_extract_backend_metadata(ds_k, var_id, "kerchunk"))
    finally:
        ds_k.close()

    # NetCDF (real-world defaults, but fail fast on coord mismatch)
    try:
        ds_n = xc.open_mfdataset(
            netcdf_files,
            chunks={},
            join="exact",  # prevent silent coordinate union
        )
    except Exception as e:
        logger.warning(
            f"Skipping (NetCDF open failed - coord mismatch): "
            f"{os.path.basename(kerchunk_fn)} | {e}"
        )
        return {"skip": True}

    try:
        results.update(_extract_backend_metadata(ds_n, var_id, "netcdf"))
    finally:
        ds_n.close()

    return results


def _extract_backend_metadata(ds, var_id: str, backend: str) -> dict:
    da = ds[var_id]
    time_len = int(da.sizes.get("time", -1))

    # Full-dataset time chunk stats
    time_chunk_min = None
    time_chunk_count = None
    if hasattr(da, "chunks") and da.chunks is not None and "time" in da.dims:
        axis = da.get_axis_num("time")
        chunks = np.asarray(da.chunks[axis], dtype=int)
        time_chunk_min = int(chunks.min())
        time_chunk_count = int(len(chunks))

    try:
        full_task_count = len(da.data.__dask_graph__())
    except Exception:
        full_task_count = None

    # Post-slice stats (slice is what load/reductions operate on)
    post_slice_time_chunk_count = None
    post_slice_task_count = None
    if "time" in da.dims:
        n = min(FIXED_TIMESTEPS, da.sizes["time"])
        da_slice = da.isel(time=slice(0, n))

        if hasattr(da_slice, "chunks") and da_slice.chunks is not None:
            axis = da_slice.get_axis_num("time")
            chunks = np.asarray(da_slice.chunks[axis], dtype=int)
            post_slice_time_chunk_count = int(len(chunks))

        try:
            post_slice_task_count = len(da_slice.data.__dask_graph__())
        except Exception:
            post_slice_task_count = None

    size_gb_slice = _compute_slice_size_gb(da)

    return {
        f"{backend}_time_len": time_len,
        f"{backend}_time_chunk_min": time_chunk_min,
        f"{backend}_time_chunk_count": time_chunk_count,
        f"{backend}_dask_task_count": full_task_count,
        f"{backend}_post_slice_time_chunk_count": post_slice_time_chunk_count,
        f"{backend}_post_slice_dask_task_count": post_slice_task_count,
        f"{backend}_size_gb_slice": size_gb_slice,
    }


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


def _infer_var_id(kerchunk_fn: str) -> str:
    base = os.path.basename(kerchunk_fn)
    parts = base.split(".")
    return parts[7] if len(parts) > 7 else "ta"


def _open_dataset(kerchunk_fn: str, netcdf_files: list[str], tool: str):
    if tool == "kerchunk":
        return xc.open_dataset(kerchunk_fn, engine="kerchunk", chunks={})

    return xc.open_mfdataset(netcdf_files, chunks={}, join="exact")


def _apply_fixed_time_slice(ds, var_id: str):
    if "time" in ds[var_id].dims:
        n = min(FIXED_TIMESTEPS, ds[var_id].sizes["time"])
        return ds.isel(time=slice(0, n))
    return ds


def _time_open(kerchunk_fn: str, netcdf_files: list[str], tool: str) -> float:
    s = time.perf_counter()
    ds = _open_dataset(kerchunk_fn, netcdf_files, tool)
    e = time.perf_counter()
    ds.close()
    return e - s


def _time_load(
    kerchunk_fn: str, netcdf_files: list[str], var_id: str, tool: str
) -> float:
    ds = _open_dataset(kerchunk_fn, netcdf_files, tool)
    ds = _apply_fixed_time_slice(ds, var_id)

    s = time.perf_counter()
    ds[var_id].compute()
    e = time.perf_counter()

    ds.close()
    return e - s


def _time_temporal(
    kerchunk_fn: str, netcdf_files: list[str], var_id: str, tool: str
) -> tuple[float, float, int | None] | tuple[None, None, None]:

    ds = _open_dataset(kerchunk_fn, netcdf_files, tool)
    ds = _apply_fixed_time_slice(ds, var_id)

    # Preprocessing (not timed)
    try:
        ds = ds.bounds.add_missing_bounds()
    except Exception:
        ds.close()
        return None, None, None

    # Build timing
    try:
        s_build = time.perf_counter()
        expr = ds.temporal.group_average(var_id, freq="year")
        e_build = time.perf_counter()
    except Exception:
        ds.close()
        return None, None, None

    try:
        graph_task_count = len(expr.data.__dask_graph__())
    except Exception:
        graph_task_count = None

    # Compute timing
    try:
        s_compute = time.perf_counter()
        expr.compute()
        e_compute = time.perf_counter()
    except Exception:
        ds.close()
        return None, None, None

    ds.close()
    return e_build - s_build, e_compute - s_compute, graph_task_count


def _time_spatial(
    kerchunk_fn: str, netcdf_files: list[str], var_id: str, tool: str
) -> tuple[float, float] | tuple[None, None]:

    ds = _open_dataset(kerchunk_fn, netcdf_files, tool)
    ds = _apply_fixed_time_slice(ds, var_id)

    # Preprocessing (not timed)
    try:
        ds = ds.bounds.add_missing_bounds()
    except Exception:
        ds.close()
        return None, None

    # Build timing
    try:
        s_build = time.perf_counter()
        expr = ds.spatial.average(var_id)
        e_build = time.perf_counter()
    except Exception:
        ds.close()
        return None, None

    # Compute timing
    try:
        s_compute = time.perf_counter()
        expr.compute()
        e_compute = time.perf_counter()
    except Exception:
        ds.close()
        return None, None

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

        mv = max(float(np.nanmax(x)), float(np.nanmax(y)))
        if not np.isfinite(mv) or mv <= 0:
            mv = 1.0

        plt.scatter(x, y)
        plt.plot([0, mv], [0, mv], "k:")
        plt.title(title)
        plt.xlabel("Kerchunk [s]")
        plt.ylabel("NetCDF [s]")
        plt.xlim(0, mv)
        plt.ylim(0, mv)

    plt.suptitle(f"Frequency: {freq}")
    plt.tight_layout()
    plt.savefig(os.path.join(ROOT_DIR, f"{_TS}_benchmark_{freq}.png"), dpi=300)
    plt.close()


def _log_median_ratios(df: pd.DataFrame, freq: str) -> None:
    df["open_ratio"] = df["open_kerchunk"] / df["open_netcdf"]
    df["load_ratio"] = df["load_kerchunk"] / df["load_netcdf"]
    df["temporal_ratio"] = (
        df["temporal_compute_kerchunk"] / df["temporal_compute_netcdf"]
    )
    df["spatial_ratio"] = df["spatial_compute_kerchunk"] / df["spatial_compute_netcdf"]

    logger.info(
        f"{freq} median ratios | "
        f"open: {df['open_ratio'].median():.2f} | "
        f"load: {df['load_ratio'].median():.2f} | "
        f"temporal: {df['temporal_ratio'].median():.2f} | "
        f"spatial: {df['spatial_ratio'].median():.2f}"
    )


if __name__ == "__main__":
    main()
