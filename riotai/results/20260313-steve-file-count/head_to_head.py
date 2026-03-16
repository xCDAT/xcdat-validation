"""Controlled Kerchunk vs NetCDF Benchmark (xCDAT-based), file-count-focused

Disk-chunk-preserving benchmark comparing kerchunk-backed datasets and
native NetCDF datasets under xCDAT diagnostic workflows. This benchmark
tests different datasets with varying file counts to see the effects of storage
layout on performance.

Execution Model
---------------
- Uses Dask threaded scheduler with a fixed number of workers (no distributed
    cluster).
- BLAS/OpenMP threading disabled (OMP/MKL/OPENBLAS=1) to reduce
    oversubscription noise.
- Execution is sequential across datasets for reproducibility.
- Each phase is timed multiple times; first run discarded, median reported.

Workload Design
---------------
- Preserves on-disk chunking (chunks={}); no rechunking performed.
- Infers kerchunk JSON paths from each dataset directory and validates
    readability before benchmark execution.
- Uses NetCDF file lists from kerchunk references when available, with
    fallback to DATA_DIR *.nc discovery.
- Applies a fixed leading timestep slice (FIXED_TIMESTEPS).
    - Default: 240 timesteps.
    - Slice is positional and may not align with chunk boundaries.
    - Both backends preserve source chunking, so chunk-boundary effects are
        applied consistently.
- Measures four phases independently:
    1. Open (metadata parse + graph creation)
    2. Load (materialization of fixed slice)
    3. Temporal reduction (annual mean; build and compute timed separately)
    4. Spatial reduction (area average; build and compute timed separately)

Diagnostics and Reporting
-------------------------
Per dataset, records:
- Status and skip reason/error context
- NetCDF file count and physical size (GB)
- Time-axis/chunk metadata and Dask task counts
- Slice logical size (GB)
- Median phase timings (kerchunk vs NetCDF)
- Kerchunk-to-NetCDF timing ratios for selected phases

Outputs
-------
- Timestamped CSV written in the script directory
- Timing scatter plot (kerchunk vs NetCDF)

Purpose
-------
Provide a storage-layout-faithful, reproducible backend comparison for
single-node xCDAT workflows. Not intended as a distributed scaling benchmark.

Usage
-----
salloc --nodes 1 --qos interactive --constraint cpu --time 04:00:00 --account mXXXX
conda activate xcdat_test_stable_min
python riotai/results/20260313-steve-file-count/head_to_head.py
"""

from __future__ import annotations

import argparse
import gc
import glob
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime

import dask
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xcdat as xc

# Prevent multithreading in underlying libraries to reduce noise in timing
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"


# ============================================================
# Configuration
# ============================================================
FIXED_TIMESTEPS: int = 240
NTESTS: int = 3

# Detailed backend metadata requires opening all backend files once up-front.
# Disable for faster batch timing runs.
COLLECT_DETAILED_METADATA: bool = False

# If True, abort run when manifest/data/kerchunk path validation fails.
# If False, log validation errors and continue; missing entries are handled
# per-dataset as skipped rows later in the run.
STRICT_PATH_VALIDATION: bool = True

KERCHUNK_ROOT = "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk"

# Consolidated dataset definitions: (data_dir, kerchunk_json_path)
# Sorted by ascending nfiles.
DATASET_ENTRIES: list[tuple[str, str]] = [
    # nfiles=1
    (
        "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/ScenarioMIP/CCCma/CanESM5/ssp119/r3i1p2f1/Amon/tas/gn/v20190429/",
        "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/tas/ssp119/mon/CMIP6.ScenarioMIP.CCCma.CanESM5.ssp119.r3i1p2f1.Amon.tas.gn.v20190429.kerchunk.json",
    ),
    # nfiles=10
    (
        "/global/cfs/projectdirs/m4931/gsharing/user_pub_work/CMIP6/CMIP/E3SM-Project/E3SM-2-1/piControl/r1i1p1f1/Amon/tas/gr/v20240208/",
        "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/tas/piControl/mon/CMIP6.CMIP.E3SM-Project.E3SM-2-1.piControl.r1i1p1f1.Amon.tas.gr.v20240208.kerchunk.json",
    ),
    # nfiles=20
    (
        "/global/cfs/projectdirs/m4931/gsharing/user_pub_work/CMIP6/CMIP/E3SM-Project/E3SM-1-0/piControl/r1i1p1f1/Amon/tas/gr/v20190719/",
        "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/tas/piControl/mon/CMIP6.CMIP.E3SM-Project.E3SM-1-0.piControl.r1i1p1f1.Amon.tas.gr.v20190719.kerchunk.json",
    ),
    # nfiles=33
    (
        "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/CMIP/MPI-M/MPI-ESM1-2-HR/historical/r1i1p1f1/Amon/tas/gn/v20190710/",
        "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/tas/historical/mon/CMIP6.CMIP.MPI-M.MPI-ESM1-2-HR.historical.r1i1p1f1.Amon.tas.gn.v20190710.kerchunk.json",
    ),
    # nfiles=45
    (
        "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r130i1p1f1/Amon/tas/gr/v20200412/",
        "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/tas/historical/mon/CMIP6.CMIP.EC-Earth-Consortium.EC-Earth3.historical.r130i1p1f1.Amon.tas.gr.v20200412.kerchunk.json",
    ),
    # nfiles=50
    (
        "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/CMIP/MPI-M/MPI-ESM1-2-LR/piControl/r1i1p1f1/Amon/tas/gn/v20190710/",
        "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/tas/piControl/mon/CMIP6.CMIP.MPI-M.MPI-ESM1-2-LR.piControl.r1i1p1f1.Amon.tas.gn.v20190710.kerchunk.json",
    ),
    # nfiles=86
    (
        "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/ScenarioMIP/EC-Earth-Consortium/EC-Earth3/ssp245/r124i1p1f1/Amon/tas/gr/v20210401/",
        "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/tas/ssp245/mon/CMIP6.ScenarioMIP.EC-Earth-Consortium.EC-Earth3.ssp245.r124i1p1f1.Amon.tas.gr.v20210401.kerchunk.json",
    ),
    # nfiles=165
    (
        "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/CMIP/AWI/AWI-CM-1-1-MR/historical/r1i1p1f1/Amon/tas/gn/v20200720/",
        "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/tas/historical/mon/CMIP6.CMIP.AWI.AWI-CM-1-1-MR.historical.r1i1p1f1.Amon.tas.gn.v20200720.kerchunk.json",
    ),
    # nfiles=286
    (
        "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/ScenarioMIP/EC-Earth-Consortium/EC-Earth3-Veg/ssp585/r13i1p1f1/Amon/tas/gr/v20201020/",
        "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/tas/ssp585/mon/CMIP6.ScenarioMIP.EC-Earth-Consortium.EC-Earth3-Veg.ssp585.r13i1p1f1.Amon.tas.gr.v20201020.kerchunk.json",
    ),
    # nfiles=505
    (
        "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3-CC/piControl/r1i1p1f1/Amon/tas/gr/v20210330/",
        "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/tas/piControl/mon/CMIP6.CMIP.EC-Earth-Consortium.EC-Earth3-CC.piControl.r1i1p1f1.Amon.tas.gr.v20210330.kerchunk.json",
    ),
    # nfiles=604
    (
        "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/piControl/r2i1p1f1/Amon/tas/gr/v20210601/",
        "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/tas/piControl/mon/CMIP6.CMIP.EC-Earth-Consortium.EC-Earth3.piControl.r2i1p1f1.Amon.tas.gr.v20210601.kerchunk.json",
    ),
    # nfiles=780
    (
        "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/HighResMIP/EC-Earth-Consortium/EC-Earth3P/hist-1950/r3i1p2f1/Amon/pr/gr/v20190215/",
        "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/pr/hist-1950/mon/CMIP6.HighResMIP.EC-Earth-Consortium.EC-Earth3P.hist-1950.r3i1p2f1.Amon.pr.gr.v20190215.kerchunk.json",
    ),
    # nfiles=1020
    (
        "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/HighResMIP/EC-Earth-Consortium/EC-Earth3P/highres-future/r3i1p2f1/Amon/pr/gr/v20190215/",
        "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/pr/highres-future/mon/CMIP6.HighResMIP.EC-Earth-Consortium.EC-Earth3P.highres-future.r3i1p2f1.Amon.pr.gr.v20190215.kerchunk.json",
    ),
    # nfiles=1344
    (
        "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/HighResMIP/EC-Earth-Consortium/EC-Earth3P/control-1950/r3i1p2f1/Amon/pr/gr/v20190215/",
        "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/pr/control-1950/mon/CMIP6.HighResMIP.EC-Earth-Consortium.EC-Earth3P.control-1950.r3i1p2f1.Amon.pr.gr.v20190215.kerchunk.json",
    ),
    # nfiles=2000
    (
        "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3-Veg/piControl/r1i1p1f1/Amon/tas/gr/v20210419/",
        "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/tas/piControl/mon/CMIP6.CMIP.EC-Earth-Consortium.EC-Earth3-Veg.piControl.r1i1p1f1.Amon.tas.gr.v20210419.kerchunk.json",
    ),
]

_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
ROOT_DIR = os.path.dirname(__file__)
DEFAULT_OUT_CSV: str = os.path.join(ROOT_DIR, f"{_TS}_kerchunk_vs_netcdf_batch.csv")
DEFAULT_OUT_PLOT_TIMING: str = os.path.join(ROOT_DIR, f"{_TS}_timing_vs_nfiles.png")
DEFAULT_OUT_PLOT_RATIO: str = os.path.join(ROOT_DIR, f"{_TS}_ratio_vs_nfiles.png")


# Configure Dask to use local threaded scheduler (no distributed client)
dask.config.set(scheduler="threads", num_workers=8)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("benchmark")
logging.getLogger("fsspec").setLevel(logging.ERROR)


@dataclass(frozen=True)
class DatasetSpec:
    data_dir: str
    dataset_id: str
    kerchunk_file: str | None
    var_id: str | None
    inference_error: str | None


@dataclass(frozen=True)
class RunConfig:
    ntests: int
    min_files: int | None
    max_files: int | None
    out_csv: str
    resume_csv: str | None
    skip_plot: bool
    plot_timing: str


def _parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Controlled kerchunk vs netcdf benchmark with dataset sharding, "
            "resume, and checkpointing"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Shard A (<= 1020 files)\n"
            "  python head_to_head.py --max-files 1020 --out-csv shard_le_1020.csv "
            "--resume-csv shard_le_1020.csv --skip-plot\n\n"
            "  # Shard B (>= 1021 files)\n"
            "  python head_to_head.py --min-files 1021 --out-csv shard_gt_1020.csv "
            "--resume-csv shard_gt_1020.csv --skip-plot"
        ),
    )
    parser.add_argument(
        "--min-files",
        type=int,
        default=None,
        help="Only benchmark datasets with resolved netcdf_file_count >= this value",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Only benchmark datasets with resolved netcdf_file_count <= this value",
    )
    parser.add_argument(
        "--out-csv",
        type=str,
        default=DEFAULT_OUT_CSV,
        help="Output CSV path (checkpointed after each dataset)",
    )
    parser.add_argument(
        "--resume-csv",
        type=str,
        default=None,
        help="Existing CSV to resume from (skips already-present dataset_id rows)",
    )
    parser.add_argument(
        "--skip-plot",
        action="store_true",
        help="Skip timing plot generation during benchmark run",
    )
    parser.add_argument(
        "--plot-timing",
        type=str,
        default=DEFAULT_OUT_PLOT_TIMING,
        help="Timing plot output path (ignored with --skip-plot)",
    )
    parser.add_argument(
        "--ntests",
        type=int,
        default=NTESTS,
        help=(
            "Iterations per backend. Default is 3 so warmup is discarded and median "
            "is computed over remaining runs."
        ),
    )

    args = parser.parse_args()

    if args.ntests < 1:
        parser.error("--ntests must be >= 1")

    if args.min_files is not None and args.max_files is not None:
        if args.min_files > args.max_files:
            parser.error("--min-files cannot be greater than --max-files")

    return RunConfig(
        ntests=args.ntests,
        min_files=args.min_files,
        max_files=args.max_files,
        out_csv=args.out_csv,
        resume_csv=args.resume_csv,
        skip_plot=args.skip_plot,
        plot_timing=args.plot_timing,
    )


# ============================================================
# Public API
# ============================================================


def main() -> None:
    config = _parse_args()

    logger.info("Starting manifest-driven kerchunk vs netcdf benchmark")
    logger.info(f"Configured dataset count: {len(DATASET_ENTRIES)}")
    logger.info(
        "Run config | ntests=%d | min_files=%s | max_files=%s | out_csv=%s",
        config.ntests,
        config.min_files,
        config.max_files,
        config.out_csv,
    )

    if not _validate_manifest_paths(DATASET_ENTRIES):
        if STRICT_PATH_VALIDATION:
            logger.error(
                "Path validation failed and STRICT_PATH_VALIDATION=True. "
                "Fix missing paths and rerun."
            )
            return
        logger.warning(
            "Path validation failed, but STRICT_PATH_VALIDATION=False. "
            "Continuing run with per-dataset skip handling."
        )

    rows_by_dataset_id = _load_resume_rows(config.resume_csv)
    if rows_by_dataset_id:
        logger.info(
            "Loaded %d rows from resume CSV: %s",
            len(rows_by_dataset_id),
            config.resume_csv,
        )

    specs = [_build_dataset_spec(entry) for entry in DATASET_ENTRIES]

    for i, spec in enumerate(specs, start=1):
        if spec.dataset_id in rows_by_dataset_id:
            logger.info(
                f"[{i}/{len(specs)}] dataset={spec.dataset_id} | already present in resume CSV"
            )
            continue

        logger.info(f"[{i}/{len(specs)}] dataset={spec.dataset_id}")

        row: dict = {
            "dataset_id": spec.dataset_id,
            "data_dir": spec.data_dir,
            "kerchunk_file": spec.kerchunk_file,
            "variable": spec.var_id,
            "kerchunk_exists": None,
            "status": "pending",
            "skip_reason": None,
            "error": None,
        }

        if not os.path.isdir(spec.data_dir):
            row["status"] = "skipped"
            row["skip_reason"] = "missing_data_dir"
            rows_by_dataset_id[spec.dataset_id] = row
            _save_checkpoint(rows_by_dataset_id, config.out_csv)
            logger.warning(f"Skipping missing data directory: {spec.data_dir}")
            continue

        if spec.inference_error is not None:
            row["status"] = "skipped"
            row["skip_reason"] = spec.inference_error
            rows_by_dataset_id[spec.dataset_id] = row
            _save_checkpoint(rows_by_dataset_id, config.out_csv)
            logger.warning(f"Skipping {spec.dataset_id}: {spec.inference_error}")
            continue

        if not spec.kerchunk_file:
            row["status"] = "skipped"
            row["skip_reason"] = "kerchunk_inference_failed"
            rows_by_dataset_id[spec.dataset_id] = row
            _save_checkpoint(rows_by_dataset_id, config.out_csv)
            logger.warning(f"Skipping {spec.dataset_id}: kerchunk path not inferred")
            continue

        row["kerchunk_exists"] = os.path.exists(spec.kerchunk_file)
        if not row["kerchunk_exists"]:
            row["status"] = "skipped"
            row["skip_reason"] = "kerchunk_not_found"
            rows_by_dataset_id[spec.dataset_id] = row
            _save_checkpoint(rows_by_dataset_id, config.out_csv)
            logger.warning(
                f"Skipping {spec.dataset_id}: kerchunk file does not exist ({spec.kerchunk_file})"
            )
            continue

        readable, read_reason = _is_readable_file(spec.kerchunk_file)
        if not readable:
            row["status"] = "skipped"
            row["skip_reason"] = read_reason
            rows_by_dataset_id[spec.dataset_id] = row
            _save_checkpoint(rows_by_dataset_id, config.out_csv)
            logger.warning(
                f"Skipping {spec.dataset_id}: kerchunk file unavailable ({read_reason})"
            )
            continue

        try:
            refs = _load_kerchunk_refs(spec.kerchunk_file)
        except Exception as e:
            row["status"] = "skipped"
            row["skip_reason"] = f"kerchunk_read_error:{type(e).__name__}"
            row["error"] = str(e)
            rows_by_dataset_id[spec.dataset_id] = row
            _save_checkpoint(rows_by_dataset_id, config.out_csv)
            logger.warning(
                f"Skipping {spec.dataset_id}: could not parse kerchunk refs ({e})"
            )
            continue

        netcdf_files = _resolve_netcdf_files(spec.data_dir, refs)
        if not netcdf_files:
            row["status"] = "skipped"
            row["skip_reason"] = "no_netcdf_files"
            rows_by_dataset_id[spec.dataset_id] = row
            _save_checkpoint(rows_by_dataset_id, config.out_csv)
            logger.warning(f"Skipping {spec.dataset_id}: no NetCDF files found")
            continue

        nfiles = len(netcdf_files)
        if config.min_files is not None and nfiles < config.min_files:
            logger.info(
                "Skipping %s due to --min-files=%d (nfiles=%d)",
                spec.dataset_id,
                config.min_files,
                nfiles,
            )
            continue
        if config.max_files is not None and nfiles > config.max_files:
            logger.info(
                "Skipping %s due to --max-files=%d (nfiles=%d)",
                spec.dataset_id,
                config.max_files,
                nfiles,
            )
            continue

        var_id = spec.var_id or _infer_var_id(spec.kerchunk_file)
        row["variable"] = var_id

        logger.info(
            f"Running benchmark | files={nfiles} | var={var_id} | "
            f"size_gb={_compute_physical_size_gb(netcdf_files):.3f}"
        )

        try:
            result = run_benchmark(
                spec.kerchunk_file,
                netcdf_files,
                var_id,
                config.ntests,
            )
        except Exception as e:
            row["status"] = "failed"
            row["error"] = f"{type(e).__name__}: {e}"
            rows_by_dataset_id[spec.dataset_id] = row
            _save_checkpoint(rows_by_dataset_id, config.out_csv)
            logger.exception(f"Failed dataset {spec.dataset_id}: {e}")
            continue

        if result is None:
            row["status"] = "skipped"
            row["skip_reason"] = "benchmark_returned_none"
            rows_by_dataset_id[spec.dataset_id] = row
            _save_checkpoint(rows_by_dataset_id, config.out_csv)
            logger.warning(f"Skipping {spec.dataset_id}: benchmark returned None")
            continue

        row.update(result)
        row["status"] = "ok"
        row.update(_compute_ratio_fields(row))
        rows_by_dataset_id[spec.dataset_id] = row
        _save_checkpoint(rows_by_dataset_id, config.out_csv)

        gc.collect()

    df = pd.DataFrame(rows_by_dataset_id.values())
    _ensure_schema_columns(df)
    if not df.empty and {"netcdf_file_count", "dataset_id"}.issubset(df.columns):
        df = df.sort_values(["netcdf_file_count", "dataset_id"], na_position="last")

    df.to_csv(config.out_csv, index=False)
    logger.info(f"Results written to {config.out_csv}")
    if not df.empty:
        logger.info(f"Status counts:\n{df['status'].value_counts(dropna=False)}")

    if config.skip_plot:
        logger.info("Skipping timing plot generation (--skip-plot)")
    else:
        _plot_results_batch(df, config.plot_timing)


# ============================================================
# Manifest helpers
# ============================================================


def _validate_manifest_paths(entries: list[tuple[str, str]]) -> bool:
    missing_data_dirs: list[str] = []
    unreadable_kerchunk_files: list[tuple[str, str | None]] = []

    for data_dir, kerchunk_path in entries:
        clean_dir = data_dir.rstrip("/")
        if not os.path.isdir(clean_dir):
            missing_data_dirs.append(clean_dir)

        readable, reason = _is_readable_file(kerchunk_path)
        if not readable:
            unreadable_kerchunk_files.append((kerchunk_path, reason))

    if missing_data_dirs:
        logger.error("Missing data directories (%d):", len(missing_data_dirs))
        for path in missing_data_dirs:
            logger.error("  %s", path)

    if unreadable_kerchunk_files:
        logger.error("Unreadable kerchunk files (%d):", len(unreadable_kerchunk_files))
        for path, reason in unreadable_kerchunk_files:
            logger.error("  %s (%s)", path, reason)

    ok = not (missing_data_dirs or unreadable_kerchunk_files)
    if ok:
        logger.info(
            "Path validation passed (%d consolidated entries)",
            len(entries),
        )

    return ok


def _build_dataset_spec(entry: tuple[str, str]) -> DatasetSpec:
    data_dir, kerchunk_file = entry
    clean_dir = data_dir.rstrip("/")

    dataset_id = os.path.basename(kerchunk_file).removesuffix(".kerchunk.json")
    var_id = _infer_var_id(kerchunk_file)
    return DatasetSpec(
        data_dir=clean_dir,
        dataset_id=dataset_id,
        kerchunk_file=kerchunk_file,
        var_id=var_id,
        inference_error=None,
    )


def _is_readable_file(path: str) -> tuple[bool, str | None]:
    try:
        with open(path, "rb"):
            pass
    except FileNotFoundError:
        return False, "kerchunk_not_found"
    except PermissionError:
        return False, "kerchunk_permission_denied"
    except OSError as e:
        return False, f"kerchunk_os_error:{type(e).__name__}"

    return True, None


def _resolve_netcdf_files(data_dir: str, refs: dict) -> list[str]:
    netcdf_files_from_refs = _extract_netcdf_files(refs)

    if netcdf_files_from_refs:
        netcdf_files = [f for f in netcdf_files_from_refs if os.path.exists(f)]
        missing = len(netcdf_files_from_refs) - len(netcdf_files)
        if missing:
            logger.warning(
                f"{missing} files referenced in kerchunk are missing on disk"
            )

        if netcdf_files:
            return sorted(netcdf_files)

        logger.warning(
            "No readable source files from kerchunk refs; falling back to DATA_DIR"
        )

    return sorted(glob.glob(os.path.join(data_dir, "*.nc")))


def _load_resume_rows(path: str | None) -> dict[str, dict]:
    if path is None:
        return {}

    if not os.path.exists(path):
        logger.warning("Resume CSV does not exist: %s", path)
        return {}

    try:
        df = pd.read_csv(path)
    except Exception as e:
        logger.warning("Failed to read resume CSV %s: %s", path, e)
        return {}

    if "dataset_id" not in df.columns:
        logger.warning("Resume CSV missing dataset_id column: %s", path)
        return {}

    rows_by_dataset_id: dict[str, dict] = {}
    for _, series in df.iterrows():
        dataset_id = series.get("dataset_id")
        if pd.isna(dataset_id):
            continue
        rows_by_dataset_id[str(dataset_id)] = series.to_dict()

    return rows_by_dataset_id


def _save_checkpoint(rows_by_dataset_id: dict[str, dict], out_csv: str) -> None:
    df = pd.DataFrame(rows_by_dataset_id.values())
    _ensure_schema_columns(df)
    if not df.empty and {"netcdf_file_count", "dataset_id"}.issubset(df.columns):
        df = df.sort_values(["netcdf_file_count", "dataset_id"], na_position="last")
    df.to_csv(out_csv, index=False)


# ============================================================
# Benchmark core (kept close to original implementation)
# ============================================================


def run_benchmark(
    kerchunk_fn: str,
    netcdf_files: list[str],
    var_id: str,
    ntests: int,
) -> dict | None:

    results: dict = {
        "file": kerchunk_fn,
        "variable": var_id,
        "netcdf_file_count": len(netcdf_files),
        "size_gb_physical": _compute_physical_size_gb(netcdf_files),
    }

    if COLLECT_DETAILED_METADATA:
        results.update(_collect_backend_metadata(kerchunk_fn, netcdf_files, var_id))
        if results.get("skip"):
            return None
    else:
        logger.info(
            "Skipping detailed backend metadata collection "
            "(COLLECT_DETAILED_METADATA=False)"
        )

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
            logger.info(f"  Iteration {it+1}/{ntests} - open")
            open_times.append(_time_open(kerchunk_fn, netcdf_files, tool))

            logger.info(f"  Iteration {it+1}/{ntests} - load")
            load_times.append(_time_load(kerchunk_fn, netcdf_files, var_id, tool))

            logger.info(f"  Iteration {it+1}/{ntests} - temporal (build+compute)")
            tb, tc, tg = _time_temporal(kerchunk_fn, netcdf_files, var_id, tool)
            if tb is None:
                logger.warning(
                    f"Skipping (temporal failed, tool={tool}): {os.path.basename(kerchunk_fn)}"
                )
                return None

            logger.info(f"  Iteration {it+1}/{ntests} - spatial (build+compute)")
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
# Private helpers
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

    ds_k = xc.open_dataset(kerchunk_fn, engine="kerchunk", chunks={})
    try:
        results.update(_extract_backend_metadata(ds_k, var_id, "kerchunk"))
    finally:
        ds_k.close()

    try:
        ds_n = xc.open_mfdataset(
            netcdf_files,
            chunks={},
            join="exact",
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

    try:
        ds = ds.bounds.add_missing_bounds()
    except Exception:
        ds.close()
        return None, None, None

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

    try:
        s_compute = time.perf_counter()
        expr.compute()
        e_compute = time.perf_counter()
    except Exception:
        ds.close()
        return None, None, None

    ds.close()
    logger.info(
        f"    [{tool}] temporal build: {e_build - s_build:.3f} s, "
        f"compute: {e_compute - s_compute:.3f} s, tasks: {graph_task_count}"
    )
    return e_build - s_build, e_compute - s_compute, graph_task_count


def _time_spatial(
    kerchunk_fn: str, netcdf_files: list[str], var_id: str, tool: str
) -> tuple[float, float] | tuple[None, None]:

    ds = _open_dataset(kerchunk_fn, netcdf_files, tool)
    ds = _apply_fixed_time_slice(ds, var_id)

    try:
        ds = ds.bounds.add_missing_bounds()
    except Exception:
        ds.close()
        return None, None

    try:
        s_build = time.perf_counter()
        expr = ds.spatial.average(var_id)
        e_build = time.perf_counter()
    except Exception:
        ds.close()
        return None, None

    try:
        s_compute = time.perf_counter()
        expr.compute()
        e_compute = time.perf_counter()
    except Exception:
        ds.close()
        return None, None

    ds.close()
    logger.info(
        f"    [{tool}] spatial build: {e_build - s_build:.3f} s, "
        f"compute: {e_compute - s_compute:.3f} s"
    )
    return e_build - s_build, e_compute - s_compute


# ============================================================
# Output helpers
# ============================================================


def _safe_ratio(numerator, denominator) -> float:
    if numerator is None or denominator is None:
        return float("nan")

    if pd.isna(numerator) or pd.isna(denominator):
        return float("nan")

    if float(denominator) == 0.0:
        return float("nan")

    return float(numerator) / float(denominator)


def _compute_ratio_fields(row: dict) -> dict[str, float]:
    return {
        "open_ratio": _safe_ratio(row.get("open_kerchunk"), row.get("open_netcdf")),
        "load_ratio": _safe_ratio(row.get("load_kerchunk"), row.get("load_netcdf")),
        "temporal_compute_ratio": _safe_ratio(
            row.get("temporal_compute_kerchunk"), row.get("temporal_compute_netcdf")
        ),
        "spatial_compute_ratio": _safe_ratio(
            row.get("spatial_compute_kerchunk"), row.get("spatial_compute_netcdf")
        ),
    }


def _ensure_schema_columns(df: pd.DataFrame) -> None:
    expected_cols = [
        "dataset_id",
        "data_dir",
        "kerchunk_file",
        "status",
        "kerchunk_exists",
        "skip_reason",
        "error",
        "variable",
        "netcdf_file_count",
        "size_gb_physical",
        "open_ratio",
        "load_ratio",
        "temporal_compute_ratio",
        "spatial_compute_ratio",
    ]

    for col in expected_cols:
        if col not in df.columns:
            df[col] = np.nan


def _fmt_nfiles_label(n: float | int) -> str:
    n_int = int(n)
    if n_int >= 1000:
        return f"{n_int / 1000:.1f}k".replace(".0k", "k")
    return str(n_int)


def _plot_results_batch(df: pd.DataFrame, out_plot_timing: str) -> None:
    ok_df = df[df["status"] == "ok"].copy()
    if ok_df.empty:
        logger.warning("No successful rows. Skipping plots.")
        return

    ok_df["temporal_total_kerchunk"] = (
        ok_df["temporal_build_kerchunk"] + ok_df["temporal_compute_kerchunk"]
    )
    ok_df["temporal_total_netcdf"] = (
        ok_df["temporal_build_netcdf"] + ok_df["temporal_compute_netcdf"]
    )
    ok_df["spatial_total_kerchunk"] = (
        ok_df["spatial_build_kerchunk"] + ok_df["spatial_compute_kerchunk"]
    )
    ok_df["spatial_total_netcdf"] = (
        ok_df["spatial_build_netcdf"] + ok_df["spatial_compute_netcdf"]
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
        x = ok_df[kcol]
        y = ok_df[ncol]
        mv = max(float(np.nanmax(x)), float(np.nanmax(y)))
        if not np.isfinite(mv) or mv <= 0:
            mv = 1.0

        plt.scatter(x, y)
        offsets = [(4, 4), (4, -8), (-18, 4), (-18, -8)]
        for j, (xv, yv, nf) in enumerate(zip(x, y, ok_df["netcdf_file_count"])):
            dx, dy = offsets[j % len(offsets)]
            plt.annotate(
                _fmt_nfiles_label(nf),
                (xv, yv),
                xytext=(dx, dy),
                textcoords="offset points",
                fontsize=8,
                color="dimgray",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.7, pad=0.2),
            )

        plt.plot([0, mv], [0, mv], "k:")
        plt.title(title)
        plt.xlabel("Kerchunk [s]")
        plt.ylabel("NetCDF [s]")
        plt.xlim(0, mv)
        plt.ylim(0, mv)

    plt.suptitle("Frequency: Amon")
    plt.tight_layout()
    plt.savefig(out_plot_timing, dpi=300)
    plt.close()
    logger.info(f"Timing plot saved to {out_plot_timing}")


if __name__ == "__main__":
    main()
