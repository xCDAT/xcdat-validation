"""
Controlled Kerchunk vs NetCDF Benchmark (xCDAT-Based) — Single-pair run

Runs the kerchunk-backed vs. native NetCDF benchmark for a single
specified pair:
  - DATA_DIR: directory containing NetCDF files
  - KERCHUNK_DATA_FILE: kerchunk reference JSON for the same dataset

Produces CSV + PNG outputs in the script directory.
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
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import xcdat as xc
import dask

# ============================================================
# Configuration — set to the two specific paths requested
# ============================================================
FIXED_TIMESTEPS: int = 240
NTESTS: int = 3

DATA_DIR = "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3-Veg/piControl/r1i1p1f1/Amon/tas/gr/v20210419"
KERCHUNK_DATA_FILE = "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/tas/piControl/mon/CMIP6.CMIP.EC-Earth-Consortium.EC-Earth3-Veg.piControl.r1i1p1f1.Amon.tas.gr.v20210419.kerchunk.json"

_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
ROOT_DIR = os.path.dirname(__file__)
OUT_CSV: str = os.path.join(ROOT_DIR, f"{_TS}_kerchunk_vs_netcdf.csv")

# Configure Dask to use local threaded scheduler (no distributed client)
dask.config.set(scheduler="threads", num_workers=8)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("benchmark")
logging.getLogger("fsspec").setLevel(logging.ERROR)

# ============================================================
# Public API
# ============================================================1


def main() -> None:
    logger.info("Starting single-pair kerchunk vs netcdf benchmark")
    logger.info(f"DATA_DIR = {DATA_DIR}")
    logger.info(f"KERCHUNK_DATA_FILE = {KERCHUNK_DATA_FILE}")

    # Load kerchunk refs and extract netcdf files from it when possible.
    if not os.path.exists(KERCHUNK_DATA_FILE):
        raise FileNotFoundError(f"Kerchunk reference not found: {KERCHUNK_DATA_FILE}")

    refs = _load_kerchunk_refs(KERCHUNK_DATA_FILE)
    netcdf_files_from_refs = _extract_netcdf_files(refs)

    # If kerchunk refs don't include file list, fall back to directory glob.
    if netcdf_files_from_refs:
        netcdf_files = [f for f in netcdf_files_from_refs if os.path.exists(f)]
        missing = len(netcdf_files_from_refs) - len(netcdf_files)
        if missing:
            logger.warning(
                f"{missing} files referenced in kerchunk are missing on disk."
            )
    else:
        logger.info("No files found in kerchunk refs — falling back to DATA_DIR glob.")
        netcdf_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.nc")))

    if not netcdf_files:
        raise RuntimeError("No NetCDF files discovered for benchmarking.")

    var_id = _infer_var_id(KERCHUNK_DATA_FILE)
    logger.info(f"Inferred variable id: {var_id}")
    logger.info(
        f"Using {len(netcdf_files)} NetCDF files (total size: {_compute_physical_size_gb(netcdf_files):.2f} GB)"
    )

    # Run benchmark for the single pair (kerchunk JSON vs extracted NetCDF file list)
    r = run_benchmark(KERCHUNK_DATA_FILE, netcdf_files, var_id, NTESTS)
    if r is None:
        raise RuntimeError("Benchmark failed or was skipped for this dataset.")

    # Add identifying columns
    r["kerchunk_file"] = KERCHUNK_DATA_FILE
    r["data_dir"] = DATA_DIR

    df = pd.DataFrame([r])
    df.to_csv(OUT_CSV, index=False)
    logger.info(f"Results written to {OUT_CSV}")

    _plot_results_single(df)
    logger.info("Plot saved")


# ============================================================
# Benchmark (unchanged logic, single-pair focused)
# ============================================================


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
        logger.info(f"Benchmarking tool: {tool}")
        open_times: list[float] = []
        load_times: list[float] = []
        temporal_build_times: list[float] = []
        temporal_compute_times: list[float] = []
        temporal_graph_counts: list[int | None] = []
        spatial_build_times: list[float] = []
        spatial_compute_times: list[float] = []

        for it in range(ntests):
            logger.info(f"  Iteration {it+1}/{ntests} — open")
            open_times.append(_time_open(kerchunk_fn, netcdf_files, tool))

            logger.info(f"  Iteration {it+1}/{ntests} — load")
            load_times.append(_time_load(kerchunk_fn, netcdf_files, var_id, tool))

            logger.info(f"  Iteration {it+1}/{ntests} — temporal (build+compute)")
            tb, tc, tg = _time_temporal(kerchunk_fn, netcdf_files, var_id, tool)
            if tb is None:
                logger.warning(
                    f"Skipping (temporal failed, tool={tool}): {os.path.basename(kerchunk_fn)}"
                )
                return None

            logger.info(f"  Iteration {it+1}/{ntests} — spatial (build+compute)")
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
# Private Helpers (unchanged)
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
    logger.info(f"    [{tool}] open: {e - s:.3f} s")
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
    logger.info(f"    [{tool}] load compute: {e - s:.3f} s")
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
    logger.info(
        f"    [{tool}] temporal build: {e_build - s_build:.3f} s, compute: {e_compute - s_compute:.3f} s, tasks: {graph_task_count}"
    )
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
    logger.info(
        f"    [{tool}] spatial build: {e_build - s_build:.3f} s, compute: {e_compute - s_compute:.3f} s"
    )
    return e_build - s_build, e_compute - s_compute


# ============================================================
# Plot / helpers for single-pair output
# ============================================================


def _plot_results_single(df: pd.DataFrame) -> None:
    # plot simple side-by-side comparison bar plot for core phases
    left = [
        "open_kerchunk",
        "load_kerchunk",
        "temporal_compute_kerchunk",
        "spatial_compute_kerchunk",
    ]
    right = [
        "open_netcdf",
        "load_netcdf",
        "temporal_compute_netcdf",
        "spatial_compute_netcdf",
    ]
    labels = ["open", "load", "temporal_compute", "spatial_compute"]

    k_vals = [df[c].iloc[0] for c in left]
    n_vals = [df[c].iloc[0] for c in right]

    x = np.arange(len(labels))
    width = 0.35

    plt.figure(figsize=(8, 4))
    plt.bar(x - width / 2, k_vals, width, label="kerchunk")
    plt.bar(x + width / 2, n_vals, width, label="netcdf")
    plt.xticks(x, labels, rotation=45)
    plt.ylabel("Seconds")
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(ROOT_DIR, f"{_TS}_kerchunk_vs_netcdf.png"), dpi=300)
    plt.close()


if __name__ == "__main__":
    main()
