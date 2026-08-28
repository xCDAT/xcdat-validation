"""Controlled Kerchunk vs NetCDF Benchmark (xCDAT-based), file-count-focused

Disk-chunk-preserving benchmark comparing kerchunk-backed datasets and
native NetCDF datasets under xCDAT diagnostic workflows. This benchmark
tests datasets selected from a flattened `json_to_netcdf_table.csv` inventory
with varying file counts to see storage-layout effects on performance.

Execution Model
---------------
- Uses Dask threaded scheduler with a fixed number of workers (no distributed
    cluster).
- BLAS/OpenMP threading disabled (OMP/MKL/OPENBLAS=1) to reduce
    oversubscription noise.
- Preprocesses dataset-table rows into file-count bins, then runs a
    deterministic sequential subset for reproducibility.
- Each phase is timed multiple times; first run discarded, median reported.

Workload Design
---------------
- Preserves on-disk chunking (chunks={}); no rechunking performed.
- Reads kerchunk JSON paths and NetCDF file lists directly from the dataset
    table produced by `riotai/scripts/json_to_netcdf_table.py`.
- Validates kerchunk readability and source NetCDF availability before
    benchmark execution.
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
conda env create -f riotai/test_stable_min.yml
conda activate xcdat_test_stable_min
python riotai/scripts/json_to_netcdf_table.py

# Recommended: use 5 shard jobs for balance of efficiency and timeout safety.
# Prepare datasets once by frequency. Output goes to riotai/json_to_netcdf_maps.
# Resume by rerunning the same command with the same shard CSV.
python riotai/scripts/prepare_datasets.py \
--target-frequency Amon

# nfiles 25-149
salloc --nodes 1 --qos interactive --constraint cpu --time 02:00:00 --account m4581
conda activate xcdat_test_stable_min
python riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py \
--target-frequency Amon \
--bins 25-49,50-99,100-149 \
--out-csv run_25_149.csv \
--resume-csv run_25_149.csv \
--skip-plot

# nfiles 150-299
salloc --nodes 1 --qos interactive --constraint cpu --time 03:00:00 --account m4581
conda activate xcdat_test_stable_min
python riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py \
--target-frequency Amon \
--bins 150-199,200-299 \
--out-csv run_150_299.csv \
--resume-csv run_150_299.csv \
--skip-plot

# nfiles 300-499
salloc --nodes 1 --qos interactive --constraint cpu --time 04:00:00 --account m4581
conda activate xcdat_test_stable_min
python riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py \
--target-frequency Amon \
--bins 300-499 \
--out-csv run_300_499.csv \
--resume-csv run_300_499.csv \
--skip-plot

# nfiles 500-749
salloc --nodes 1 --qos interactive --constraint cpu --time 04:00:00 --account m4581
conda activate xcdat_test_stable_min
python riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py \
--target-frequency Amon \
--bins 500-749 \
--out-csv run_500_749.csv \
--resume-csv run_500_749.csv \
--skip-plot

# nfiles 750-1000
salloc --nodes 1 --qos interactive --constraint cpu --time 04:00:00 --account m4581
conda activate xcdat_test_stable_min
python riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py \
--target-frequency Amon \
--bins 750-1000 \
--out-csv run_750_1000.csv \
--resume-csv run_750_1000.csv \
--skip-plot
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import gc
import json
import logging
import os
import socket
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import urlopen

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

NFILES_BINS: list[tuple[str, int, int | None]] = [
    ("25-49", 25, 49),
    ("50-99", 50, 99),
    ("100-149", 100, 149),
    ("150-199", 150, 199),
    ("200-299", 200, 299),
    ("300-499", 300, 499),
    ("500-749", 500, 749),
    ("750-1000", 750, 1000),
]
SUPPORTED_NFILES_BIN_LABELS: tuple[str, ...] = tuple(
    label for label, _, _ in NFILES_BINS
)

_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_OUT_CSV: str = str(ROOT_DIR / f"{_TS}_kerchunk_vs_netcdf_batch.csv")
DEFAULT_OUT_PLOT_TIMING: str = str(ROOT_DIR / f"{_TS}_timing_vs_nfiles.png")
DEFAULT_OUT_PLOT_RATIO: str = str(ROOT_DIR / f"{_TS}_ratio_vs_nfiles.png")
JSON_TO_NETCDF_MAPS_DIR: Path = (
    Path(__file__).resolve().parents[2] / "json_to_netcdf_maps"
)
DEFAULT_DATASET_TABLE_CSV: str = str(
    JSON_TO_NETCDF_MAPS_DIR / "json_to_netcdf_table.csv"
)
DEFAULT_TARGET_FREQUENCY: str = "Amon"
LOCAL_KERCHUNK_ROOT: Path = Path("/global/cfs/projectdirs/m4931/kerchunk")
DEFAULT_REMOTE_KERCHUNK_ROOT: str = (
    "https://esgf-node.ornl.gov/thredds/fileServer/user_pub_work/kerchunk"
)


def _prepared_datasets_csv_path(
    target_frequency: str = DEFAULT_TARGET_FREQUENCY,
) -> str:
    return str(JSON_TO_NETCDF_MAPS_DIR / f"prepared_datasets_{target_frequency}.csv")


def _resolve_script_relative_path(path: str | None) -> str | None:
    if path is None:
        return None

    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = ROOT_DIR / resolved

    return str(resolved)


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
    remote_kerchunk_file: str | None = None


@dataclass(frozen=True)
class PreparedDataset:
    spec: DatasetSpec
    netcdf_files: tuple[str, ...]
    nfiles: int
    nfiles_bin: str
    bin_selected_rank: int


@dataclass(frozen=True)
class RunConfig:
    ntests: int
    datasets_per_bin: int | None
    dataset_table_csv: str
    target_frequency: str
    bins: tuple[str, ...]
    min_files: int | None
    max_files: int | None
    out_csv: str
    resume_csv: str | None
    skip_plot: bool
    plot_timing: str
    remote_kerchunk_root: str
    cache_mode: str


def _parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Controlled kerchunk vs netcdf benchmark with bin-aware dataset "
            "selection, resume, and checkpointing"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Recommended sharding: 5 jobs total. Combine smaller bins, isolate "
            "large-file bins, and rerun same command to resume.\n\n"
            "Examples:\n"
            "  python riotai/scripts/prepare_datasets.py "
            "--target-frequency Amon\n\n"
            "  python riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py "
            "--target-frequency Amon --bins 25-49,50-99,100-149 --out-csv run_25_149.csv "
            "--resume-csv run_25_149.csv --skip-plot\n\n"
            "  python riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py "
            "--target-frequency Amon --bins 150-199,200-299 --out-csv run_150_299.csv "
            "--resume-csv run_150_299.csv --skip-plot\n\n"
            "  python riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py "
            "--target-frequency Amon --bins 300-499 --out-csv run_300_499.csv "
            "--resume-csv run_300_499.csv --skip-plot\n\n"
            "  python riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py "
            "--target-frequency Amon --bins 500-749 --out-csv run_500_749.csv "
            "--resume-csv run_500_749.csv --skip-plot\n\n"
            "  python riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py "
            "--target-frequency Amon --bins 750-1000 --out-csv run_750_1000.csv "
            "--resume-csv run_750_1000.csv --skip-plot"
        ),
    )
    parser.add_argument(
        "--remote-kerchunk-root",
        default=DEFAULT_REMOTE_KERCHUNK_ROOT,
        help="Public HTTP(S) root corresponding to the local Kerchunk inventory root",
    )
    parser.add_argument(
        "--cache-mode",
        choices=("warm", "uncontrolled"),
        default="warm",
        help="'warm' discards the first iteration; 'uncontrolled' retains all iterations.",
    )
    parser.add_argument(
        "--datasets-per-bin",
        type=int,
        default=None,
        help=(
            "Optional cap on prepared datasets per bin during benchmark run. "
            "Default: use all datasets present in prepared CSV for each bin."
        ),
    )
    parser.add_argument(
        "--dataset-table-csv",
        type=str,
        default=DEFAULT_DATASET_TABLE_CSV,
        help=(
            "CSV produced by riotai/scripts/json_to_netcdf_table.py with "
            "json_path, filepaths, and num_files columns"
        ),
    )
    parser.add_argument(
        "--target-frequency",
        type=str,
        default=DEFAULT_TARGET_FREQUENCY,
        help="Target frequency used to choose prepared_datasets_<freq>.csv",
    )
    parser.add_argument(
        "--bins",
        type=str,
        default=",".join(SUPPORTED_NFILES_BIN_LABELS),
        help=(
            "Comma-separated file-count bins to run. Supported: "
            + ", ".join(SUPPORTED_NFILES_BIN_LABELS)
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
        help=(
            "Output CSV path (checkpointed after each dataset). Relative paths "
            "are resolved against this script directory."
        ),
    )
    parser.add_argument(
        "--resume-csv",
        type=str,
        default=None,
        help=(
            "Existing CSV to resume from (skips already-present dataset_id rows). "
            "Relative paths are resolved against this script directory."
        ),
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
        help=(
            "Timing plot output path (ignored with --skip-plot). Relative paths "
            "are resolved against this script directory."
        ),
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

    if args.datasets_per_bin is not None and args.datasets_per_bin < 1:
        parser.error("--datasets-per-bin must be >= 1")

    if args.min_files is not None and args.max_files is not None:
        if args.min_files > args.max_files:
            parser.error("--min-files cannot be greater than --max-files")

    parsed_root = urlparse(args.remote_kerchunk_root)
    if parsed_root.scheme not in {"http", "https"} or not parsed_root.netloc:
        parser.error("--remote-kerchunk-root must be an absolute HTTP(S) URL")

    bins = tuple(
        dict.fromkeys(part.strip() for part in args.bins.split(",") if part.strip())
    )
    if not bins:
        parser.error("--bins must include at least one supported bin label")

    invalid_bins = [label for label in bins if label not in SUPPORTED_NFILES_BIN_LABELS]
    if invalid_bins:
        parser.error(
            "Unsupported --bins value(s): "
            + ", ".join(invalid_bins)
            + ". Supported: "
            + ", ".join(SUPPORTED_NFILES_BIN_LABELS)
        )

    return RunConfig(
        ntests=args.ntests,
        datasets_per_bin=args.datasets_per_bin,
        dataset_table_csv=args.dataset_table_csv,
        target_frequency=args.target_frequency,
        bins=bins,
        min_files=args.min_files,
        max_files=args.max_files,
        out_csv=_resolve_script_relative_path(args.out_csv),
        resume_csv=_resolve_script_relative_path(args.resume_csv),
        skip_plot=args.skip_plot,
        plot_timing=_resolve_script_relative_path(args.plot_timing),
        remote_kerchunk_root=args.remote_kerchunk_root.rstrip("/"),
        cache_mode=args.cache_mode,
    )


# ============================================================
# Public API
# ============================================================


def main() -> None:
    config = _parse_args()

    logger.info("Starting bin-aware kerchunk vs netcdf benchmark")
    prepared_datasets_csv = _prepared_datasets_csv_path(config.target_frequency)
    logger.info(
        "Run config | ntests=%d | datasets_per_bin=%s | dataset_table_csv=%s | "
        "prepared_datasets_csv=%s | target_frequency=%s | bins=%s | min_files=%s | "
        "max_files=%s | out_csv=%s",
        config.ntests,
        config.datasets_per_bin,
        config.dataset_table_csv,
        prepared_datasets_csv,
        config.target_frequency,
        ",".join(config.bins),
        config.min_files,
        config.max_files,
        config.out_csv,
    )

    rows_by_dataset_id = _load_resume_rows(config.resume_csv)
    if rows_by_dataset_id:
        logger.info(
            "Loaded %d rows from resume CSV: %s",
            len(rows_by_dataset_id),
            config.resume_csv,
        )

    prepared_datasets = load_prepared_datasets_csv(prepared_datasets_csv)
    selected_datasets = _filter_prepared_datasets(
        prepared_datasets,
        config.bins,
        config.datasets_per_bin,
    )
    candidates_by_bin = _group_datasets_by_bin(prepared_datasets)
    _log_bin_selection_summary(candidates_by_bin, selected_datasets, rows_by_dataset_id)

    if not selected_datasets:
        logger.warning("No datasets selected after preprocessing and bin filters")

    for i, dataset in enumerate(selected_datasets, start=1):
        spec = dataset.spec
        if spec.dataset_id in rows_by_dataset_id:
            logger.info(
                "[%d/%d] dataset=%s | bin=%s | already present in resume CSV",
                i,
                len(selected_datasets),
                spec.dataset_id,
                dataset.nfiles_bin,
            )
            continue

        logger.info(
            "[%d/%d] dataset=%s | bin=%s | rank=%d | nfiles=%d",
            i,
            len(selected_datasets),
            spec.dataset_id,
            dataset.nfiles_bin,
            dataset.bin_selected_rank,
            dataset.nfiles,
        )

        row: dict = {
            "dataset_id": spec.dataset_id,
            "data_dir": spec.data_dir,
            "kerchunk_file": spec.kerchunk_file,
            "remote_kerchunk_file": _remote_kerchunk_url(
                str(spec.kerchunk_file), config.remote_kerchunk_root
            ),
            "client_hostname": socket.gethostname(),
            "cache_mode": config.cache_mode,
            "frequency": config.target_frequency,
            "variable": spec.var_id,
            "kerchunk_exists": True,
            "status": "pending",
            "skip_reason": None,
            "error": None,
            "netcdf_file_count": dataset.nfiles,
            "nfiles_bin": dataset.nfiles_bin,
            "bin_selected_rank": dataset.bin_selected_rank,
        }

        var_id = spec.var_id or _infer_var_id(spec.kerchunk_file)
        row["variable"] = var_id

        logger.info(
            f"Running benchmark | files={dataset.nfiles} | bin={dataset.nfiles_bin} | "
            f"var={var_id} | remote_json={row['remote_kerchunk_file']}"
        )

        try:
            result = run_remote_kerchunk_benchmark(
                row["remote_kerchunk_file"], var_id, config.ntests, config.cache_mode
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
# Dataset selection helpers
# ============================================================


def _parse_csv_filepaths(value) -> tuple[str, ...]:
    if pd.isna(value):
        return ()

    if isinstance(value, list):
        parsed = value
    else:
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return ()

    if not isinstance(parsed, list):
        return ()

    filepaths = [str(path) for path in parsed if isinstance(path, str) and path]
    return tuple(filepaths)


def _infer_data_dir_from_filepaths(netcdf_files: tuple[str, ...]) -> str:
    if not netcdf_files:
        return ""

    if len(netcdf_files) == 1:
        return os.path.dirname(netcdf_files[0])

    common_path = os.path.commonpath(netcdf_files)
    if common_path.endswith(".nc"):
        return os.path.dirname(common_path)

    return common_path.rstrip("/")


def load_prepared_datasets_csv(path: str) -> list[PreparedDataset]:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Prepared datasets CSV does not exist: {path}. "
            "Run riotai/scripts/prepare_datasets.py first."
        )

    df = pd.read_csv(path)
    required_columns = {
        "dataset_id",
        "kerchunk_file",
        "variable",
        "netcdf_file_count",
        "nfiles_bin",
        "bin_selected_rank",
        "filepaths",
    }
    missing_columns = sorted(required_columns - set(df.columns))
    if missing_columns:
        raise ValueError(
            "Prepared datasets CSV is missing required columns: "
            + ", ".join(missing_columns)
        )

    selected_datasets: list[PreparedDataset] = []
    for _, row in df.iterrows():
        netcdf_files = _parse_csv_filepaths(row["filepaths"])
        data_dir = row.get("data_dir")
        if pd.isna(data_dir) or not str(data_dir):
            data_dir = _infer_data_dir_from_filepaths(netcdf_files)

        spec = DatasetSpec(
            data_dir=str(data_dir),
            dataset_id=str(row["dataset_id"]),
            kerchunk_file=str(row["kerchunk_file"]),
            var_id=str(row["variable"]),
            inference_error=None,
        )
        selected_datasets.append(
            PreparedDataset(
                spec=spec,
                netcdf_files=netcdf_files,
                nfiles=int(row["netcdf_file_count"]),
                nfiles_bin=str(row["nfiles_bin"]),
                bin_selected_rank=int(row["bin_selected_rank"]),
            )
        )

    return selected_datasets


def _group_datasets_by_bin(
    datasets: list[PreparedDataset],
) -> dict[str, list[PreparedDataset]]:
    grouped: dict[str, list[PreparedDataset]] = {
        label: [] for label in SUPPORTED_NFILES_BIN_LABELS
    }
    for dataset in datasets:
        if dataset.nfiles_bin in grouped:
            grouped[dataset.nfiles_bin].append(dataset)
    return grouped


def _filter_prepared_datasets(
    datasets: list[PreparedDataset],
    bins: tuple[str, ...],
    datasets_per_bin: int | None,
) -> list[PreparedDataset]:
    grouped = _group_datasets_by_bin(datasets)
    selected: list[PreparedDataset] = []

    for label in SUPPORTED_NFILES_BIN_LABELS:
        if label not in bins:
            continue

        candidates = sorted(
            grouped[label],
            key=lambda dataset: (
                dataset.bin_selected_rank,
                dataset.nfiles,
                dataset.spec.dataset_id,
            ),
        )
        limit = len(candidates) if datasets_per_bin is None else datasets_per_bin
        selected.extend(candidates[:limit])

    return selected


def _log_bin_selection_summary(
    candidates_by_bin: dict[str, list[PreparedDataset]],
    selected_datasets: list[PreparedDataset],
    rows_by_dataset_id: dict[str, dict],
) -> None:
    selected_by_bin: dict[str, list[PreparedDataset]] = defaultdict(list)
    pending_by_bin: dict[str, list[PreparedDataset]] = defaultdict(list)

    for dataset in selected_datasets:
        selected_by_bin[dataset.nfiles_bin].append(dataset)
        if dataset.spec.dataset_id not in rows_by_dataset_id:
            pending_by_bin[dataset.nfiles_bin].append(dataset)

    logger.info("Per-bin selection summary:")
    for label in SUPPORTED_NFILES_BIN_LABELS:
        discovered = len(candidates_by_bin[label])
        selected = len(selected_by_bin[label])
        pending = len(pending_by_bin[label])
        logger.info(
            "  bin=%s | discovered=%d | selected=%d | pending=%d",
            label,
            discovered,
            selected,
            pending,
        )
        if selected_by_bin[label]:
            selected_names = ", ".join(
                dataset.spec.dataset_id for dataset in selected_by_bin[label]
            )
            logger.info("  bin=%s | selected_dataset_ids=%s", label, selected_names)


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


def _remote_kerchunk_url(local_path: str, remote_root: str) -> str:
    """Map a presentation-inventory JSON path to its public ORNL URL."""
    try:
        relative = Path(local_path).relative_to(LOCAL_KERCHUNK_ROOT)
    except ValueError as error:
        raise ValueError(
            f"Kerchunk path is not below {LOCAL_KERCHUNK_ROOT}: {local_path}"
        ) from error
    return f"{remote_root}/{quote(relative.as_posix(), safe='/')}"


def run_remote_kerchunk_benchmark(
    kerchunk_url: str, var_id: str, ntests: int, cache_mode: str
) -> dict:
    """Run the presentation workload through only public Kerchunk I/O."""
    metrics: dict[str, list[float]] = {
        "open": [], "load": [], "temporal_build": [], "temporal_compute": [],
        "spatial_build": [], "spatial_compute": [],
    }
    task_counts: list[int | None] = []
    for _ in range(ntests):
        metrics["open"].append(_time_open(kerchunk_url, [], "kerchunk"))
        metrics["load"].append(_time_load(kerchunk_url, [], var_id, "kerchunk"))
        tb, tc, tasks = _time_temporal(kerchunk_url, [], var_id, "kerchunk")
        sb, sc = _time_spatial(kerchunk_url, [], var_id, "kerchunk")
        if tb is None or sb is None:
            raise RuntimeError("Remote Kerchunk diagnostic failed")
        metrics["temporal_build"].append(tb)
        metrics["temporal_compute"].append(tc)
        metrics["spatial_build"].append(sb)
        metrics["spatial_compute"].append(sc)
        task_counts.append(tasks)
        gc.collect()

    if cache_mode == "warm" and ntests > 1:
        metrics = {name: values[1:] for name, values in metrics.items()}
        task_counts = task_counts[1:]

    result = {f"{name}_kerchunk": float(np.nanmedian(values)) for name, values in metrics.items()}
    result["temporal_graph_tasks_kerchunk"] = (
        int(np.median([value for value in task_counts if value is not None]))
        if any(value is not None for value in task_counts) else None
    )
    return result


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
        "frequency",
        "variable",
        "netcdf_file_count",
        "nfiles_bin",
        "bin_selected_rank",
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

    if "open_netcdf" not in ok_df or ok_df["open_netcdf"].isna().all():
        ok_df["temporal_total_kerchunk"] = (
            ok_df["temporal_build_kerchunk"] + ok_df["temporal_compute_kerchunk"]
        )
        ok_df["spatial_total_kerchunk"] = (
            ok_df["spatial_build_kerchunk"] + ok_df["spatial_compute_kerchunk"]
        )
        plt.figure(figsize=(9, 9))
        for i, (title, column) in enumerate([
            ("Open", "open_kerchunk"), ("Load", "load_kerchunk"),
            ("Temporal", "temporal_total_kerchunk"),
            ("Spatial", "spatial_total_kerchunk"),
        ]):
            plt.subplot(2, 2, i + 1)
            plt.scatter(ok_df["netcdf_file_count"], ok_df[column])
            plt.title(title)
            plt.xlabel("Source files (presentation binning)")
            plt.ylabel("Remote Kerchunk time [s]")
        plt.suptitle("Presentation-aligned external-client Kerchunk benchmark")
        plt.tight_layout()
        plt.savefig(out_plot_timing, dpi=300)
        plt.close()
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

    frequency_title = "unknown"
    if "frequency" in ok_df.columns:
        freq_values = [str(v) for v in ok_df["frequency"].dropna().unique() if str(v)]
        if freq_values:
            frequency_title = ", ".join(freq_values)

    plt.suptitle(f"Frequency: {frequency_title}")
    plt.tight_layout()
    plt.savefig(out_plot_timing, dpi=300)
    plt.close()
    logger.info(f"Timing plot saved to {out_plot_timing}")


if __name__ == "__main__":
    main()
