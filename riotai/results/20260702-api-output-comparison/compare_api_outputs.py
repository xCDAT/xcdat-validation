"""Validate xCDAT API output parity between kerchunk and NetCDF backends.

This script reuses the prepared-dataset selection and checkpoint/resume pattern
from the RIOTAI backend benchmark and metadata validation workflows, but
compares computed xCDAT outputs instead of timings or raw metadata.

Validated xCDAT operations
--------------------------
- temporal annual average via ``ds.temporal.group_average(var_id, freq="year")``
- spatial average via ``ds.spatial.average(var_id)``
- horizontal regridding via
  ``ds.regridder.horizontal(var_id, output_grid, tool="xesmf", method="bilinear")``
- vertical regridding via
  ``ds.regridder.vertical(var_id, output_grid, method="log", ...)``

Execution model
---------------
- Reads datasets from ``prepared_datasets_<freq>.csv`` produced by
  ``riotai/scripts/prepare_datasets.py``.
- Opens datasets exactly as existing RIOTAI scripts do:
  - kerchunk: ``xc.open_dataset(..., engine="kerchunk", chunks={})``
  - netcdf: ``xc.open_mfdataset(..., join="exact", chunks={})``
- Applies a fixed leading time slice before running operations to keep runtime
  bounded and make backend comparisons consistent.
- Emits one terminal CSV row per ``(dataset_id, operation)``.

Outputs
-------
- checkpointed CSV written after every dataset-operation pair
- compact markdown summary aggregated by operation

Example usage
-------------
    salloc --nodes 1 --qos interactive --constraint cpu --time 04:00:00 --account m4581
    conda activate xcdat_test_stable_min
    python riotai/results/20260702-api-output-comparison/compare_api_outputs.py \
        --target-frequency Amon \
        --bins 100-149 \
        --datasets-per-bin 1 \
        --operations vertical \
        --out-csv smoke.csv \
        --resume-csv smoke.csv

    # Three bins with five datasets each
    python riotai/results/20260702-api-output-comparison/compare_api_outputs.py \
        --target-frequency Amon \
        --bins 25-49,50-99,100-149 \
        --datasets-per-bin 5 \
        --operations temporal,spatial,horizontal,vertical \
        --out-csv run_3bins_5datasets.csv \
        --resume-csv run_3bins_5datasets.csv \
        --summary-md run_3bins_5datasets_summary.md
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gc
import json
import logging
import math
import os
import sys
from dataclasses import dataclass
import datetime as dt
from pathlib import Path
from typing import Any

import dask
import numpy as np
import pandas as pd
import xarray as xr
import xcdat as xc


# Reduce oversubscription noise and keep behavior aligned with other RIOTAI runs.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"


# ============================================================
# Configuration
# ============================================================
RTOL = 1e-6
ATOL = 1e-8
FIXED_TIMESTEPS = 240
AXIS_KEYS: tuple[str, ...] = ("T", "Y", "X", "Z")
OPERATIONS: tuple[str, ...] = ("temporal", "spatial", "horizontal", "vertical")
HORIZONTAL_TARGET_GRID_CONFIG: dict[str, Any] = {
    "lat_start": -88,
    "lat_stop": 88,
    "lat_step": 4,
    "lon_start": 2,
    "lon_stop": 358,
    "lon_step": 4,
    "lat_name": "lat",
    "lon_name": "lon",
}
VERTICAL_TARGET_PLEVS: tuple[int, ...] = (
    100000,
    92500,
    85000,
    75000,
    70000,
    60000,
    50000,
    40000,
    30000,
    25000,
    20000,
    15000,
    10000,
    7000,
    5000,
    3000,
    1000,
    500,
    300,
    100,
)
TEMPORAL_OPERATION_CONFIG: dict[str, Any] = {"freq": "year"}
SPATIAL_OPERATION_CONFIG: dict[str, Any] = {"axis": ["X", "Y"], "weights": "generate"}
HORIZONTAL_OPERATION_CONFIG: dict[str, Any] = {
    "tool": "xesmf",
    "method": "bilinear",
    "target_grid": HORIZONTAL_TARGET_GRID_CONFIG,
}
VERTICAL_OPERATION_CONFIG: dict[str, Any] = {
    "tool": "xgcm",
    "method": "log",
    "target_plevs_pa": list(VERTICAL_TARGET_PLEVS),
}
DEFAULT_OPERATION_CONFIGS: dict[str, dict[str, Any]] = {
    "temporal": TEMPORAL_OPERATION_CONFIG,
    "spatial": SPATIAL_OPERATION_CONFIG,
    "horizontal": HORIZONTAL_OPERATION_CONFIG,
    "vertical": VERTICAL_OPERATION_CONFIG,
}
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
SKIPPED_DATASET_REASONS: dict[str, str] = {
    (
        "CMIP6.CMIP.MOHC.HadGEM3-GC31-MM.piControl.r1i1p1f1."
        "Amon.ta.gn.v20190920"
    ): "Known to stall during backend data checks; skipped intentionally.",
}

ROOT_DIR = Path(__file__).resolve().parent
JSON_TO_NETCDF_MAPS_DIR = Path(__file__).resolve().parents[2] / "json_to_netcdf_maps"
DEFAULT_TARGET_FREQUENCY = "Amon"
_TS = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
DEFAULT_OUT_CSV = str(ROOT_DIR / f"{_TS}_api_output_comparison.csv")
DEFAULT_SUMMARY_MD = str(ROOT_DIR / f"{_TS}_summary.md")


dask.config.set(scheduler="threads", num_workers=8)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("api_output_comparison")
logging.getLogger("fsspec").setLevel(logging.ERROR)


@dataclass(frozen=True)
class DatasetSpec:
    data_dir: str
    dataset_id: str
    kerchunk_file: str
    var_id: str


@dataclass(frozen=True)
class PreparedDataset:
    spec: DatasetSpec
    netcdf_files: tuple[str, ...]
    nfiles: int
    nfiles_bin: str
    bin_selected_rank: int


@dataclass(frozen=True)
class RunConfig:
    target_frequency: str
    bins: tuple[str, ...]
    min_files: int | None
    max_files: int | None
    datasets_per_bin: int | None
    fixed_timesteps: int
    rtol: float
    atol: float
    operations: tuple[str, ...]
    out_csv: str
    resume_csv: str | None
    summary_md: str
    resume_summary_md: str | None


@dataclass(frozen=True)
class ResumeSummaryConfig:
    target_frequency: str | None = None
    bins: tuple[str, ...] | None = None
    min_files: int | None = None
    max_files: int | None = None
    datasets_per_bin: int | None = None
    fixed_timesteps: int | None = None
    rtol: float | None = None
    atol: float | None = None
    operations: tuple[str, ...] | None = None
    out_csv: str | None = None
    resume_csv: str | None = None
    summary_md: str | None = None
    recorded_total_rows: int | None = None


def _prepared_datasets_csv_path(
    target_frequency: str = DEFAULT_TARGET_FREQUENCY,
) -> str:
    return str(JSON_TO_NETCDF_MAPS_DIR / f"prepared_datasets_{target_frequency}.csv")


def _resolve_script_relative_path(path: str | None) -> str | None:
    if path is None:
        return None

    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        cwd_candidate = Path.cwd() / resolved
        script_candidate = ROOT_DIR / resolved
        if cwd_candidate.exists():
            resolved = cwd_candidate
        elif script_candidate.exists():
            resolved = script_candidate
        elif len(resolved.parts) > 1:
            resolved = cwd_candidate
        else:
            resolved = script_candidate

    return str(resolved)


def _explicit_cli_flags(argv: list[str]) -> set[str]:
    flags: set[str] = set()
    for token in argv:
        if not token.startswith("--"):
            continue
        flag = token.split("=", 1)[0]
        flags.add(flag)
    return flags


def _strip_optional_backticks(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped.startswith("`") and stripped.endswith("`"):
        return stripped[1:-1]
    return stripped


def _parse_summary_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = _strip_optional_backticks(value)
    if normalized == "None":
        return None
    return int(normalized)


def _parse_summary_optional_float(value: str | None) -> float | None:
    if value is None:
        return None
    normalized = _strip_optional_backticks(value)
    if normalized == "None":
        return None
    return float(normalized)


def _resolve_summary_artifact_path(summary_path: str, value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _strip_optional_backticks(value)
    if normalized == "None" or not normalized:
        return None
    resolved = Path(normalized).expanduser()
    if not resolved.is_absolute():
        resolved = Path(summary_path).resolve().parent / resolved
    return str(resolved)


def _load_resume_summary_config(path: str | None) -> ResumeSummaryConfig:
    if path is None:
        return ResumeSummaryConfig()

    if not os.path.exists(path):
        raise FileNotFoundError(f"Resume summary markdown does not exist: {path}")

    run_config_values: dict[str, str] = {}
    recorded_total_rows: int | None = None
    in_run_config = False

    for raw_line in Path(path).read_text().splitlines():
        line = raw_line.strip()
        if line == "## Run Configuration":
            in_run_config = True
            continue
        if line.startswith("## ") and line != "## Run Configuration":
            in_run_config = False
        if in_run_config and line.startswith("- ") and ":" in line:
            key, value = line[2:].split(":", 1)
            run_config_values[key.strip()] = value.strip()
            continue
        if line.startswith("- Total rows:"):
            _, value = line.split(":", 1)
            recorded_total_rows = int(value.strip())

    bins_value = run_config_values.get("bins")
    operations_value = run_config_values.get("operations")

    bins = None
    if bins_value is not None:
        bins = tuple(
            dict.fromkeys(
                part.strip()
                for part in _strip_optional_backticks(bins_value).split(",")
                if part.strip()
            )
        )

    operations = None
    if operations_value is not None:
        operations = tuple(
            dict.fromkeys(
                part.strip()
                for part in _strip_optional_backticks(operations_value).split(",")
                if part.strip()
            )
        )

    target_frequency = run_config_values.get("target_frequency")
    if target_frequency is not None:
        target_frequency = _strip_optional_backticks(target_frequency)

    return ResumeSummaryConfig(
        target_frequency=target_frequency,
        bins=bins,
        min_files=_parse_summary_optional_int(run_config_values.get("min_files")),
        max_files=_parse_summary_optional_int(run_config_values.get("max_files")),
        datasets_per_bin=_parse_summary_optional_int(
            run_config_values.get("datasets_per_bin")
        ),
        fixed_timesteps=_parse_summary_optional_int(
            run_config_values.get("fixed_timesteps")
        ),
        rtol=_parse_summary_optional_float(run_config_values.get("rtol")),
        atol=_parse_summary_optional_float(run_config_values.get("atol")),
        operations=operations,
        out_csv=_resolve_summary_artifact_path(path, run_config_values.get("out_csv")),
        resume_csv=_resolve_summary_artifact_path(
            path, run_config_values.get("resume_csv")
        ),
        summary_md=_resolve_summary_artifact_path(
            path, run_config_values.get("summary_md")
        ),
        recorded_total_rows=recorded_total_rows,
    )


def _parse_args() -> RunConfig:
    explicit_flags = _explicit_cli_flags(sys.argv[1:])
    parser = argparse.ArgumentParser(
        description=(
            "Validate xCDAT backend parity for temporal, spatial, horizontal, "
            "and vertical operations."
        )
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
            "Comma-separated file-count bins to validate. Supported: "
            + ", ".join(SUPPORTED_NFILES_BIN_LABELS)
        ),
    )
    parser.add_argument(
        "--min-files",
        type=int,
        default=None,
        help="Only include datasets with netcdf_file_count >= this value",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Only include datasets with netcdf_file_count <= this value",
    )
    parser.add_argument(
        "--datasets-per-bin",
        type=int,
        default=None,
        help=(
            "Optional cap on datasets per selected bin. Useful for smoke checks; "
            "default is to validate every prepared dataset in the bin."
        ),
    )
    parser.add_argument(
        "--fixed-timesteps",
        type=int,
        default=FIXED_TIMESTEPS,
        help=(
            "Apply a leading positional time slice before running operations. "
            "Set to 0 to disable slicing."
        ),
    )
    parser.add_argument(
        "--rtol",
        type=float,
        default=RTOL,
        help="Relative tolerance used for output value comparisons.",
    )
    parser.add_argument(
        "--atol",
        type=float,
        default=ATOL,
        help="Absolute tolerance used for output value comparisons.",
    )
    parser.add_argument(
        "--operations",
        type=str,
        default=",".join(OPERATIONS),
        help=(
            "Comma-separated operation list. Supported: " + ", ".join(OPERATIONS)
        ),
    )
    parser.add_argument(
        "--out-csv",
        type=str,
        default=DEFAULT_OUT_CSV,
        help=(
            "Checkpointed output CSV path. Relative paths resolve against this "
            "script directory."
        ),
    )
    parser.add_argument(
        "--resume-csv",
        type=str,
        default=None,
        help=(
            "Existing CSV to resume from. Rows with matching dataset_id and "
            "operation values are skipped."
        ),
    )
    parser.add_argument(
        "--summary-md",
        type=str,
        default=DEFAULT_SUMMARY_MD,
        help="Markdown summary output path.",
    )
    parser.add_argument(
        "--resume-summary-md",
        type=str,
        default=None,
        help=(
            "Existing summary markdown to resume from. When provided, missing "
            "CLI options are filled from the summary's Run Configuration block, "
            "including the resume CSV path."
        ),
    )

    args = parser.parse_args()

    args.resume_summary_md = _resolve_script_relative_path(args.resume_summary_md)
    resume_summary = _load_resume_summary_config(args.resume_summary_md)

    if args.resume_summary_md is not None:
        if "--target-frequency" not in explicit_flags and resume_summary.target_frequency:
            args.target_frequency = resume_summary.target_frequency
        if "--bins" not in explicit_flags and resume_summary.bins:
            args.bins = ",".join(resume_summary.bins)
        if "--min-files" not in explicit_flags and resume_summary.min_files is not None:
            args.min_files = resume_summary.min_files
        if "--max-files" not in explicit_flags and resume_summary.max_files is not None:
            args.max_files = resume_summary.max_files
        if (
            "--datasets-per-bin" not in explicit_flags
            and resume_summary.datasets_per_bin is not None
        ):
            args.datasets_per_bin = resume_summary.datasets_per_bin
        if (
            "--fixed-timesteps" not in explicit_flags
            and resume_summary.fixed_timesteps is not None
        ):
            args.fixed_timesteps = resume_summary.fixed_timesteps
        if "--rtol" not in explicit_flags and resume_summary.rtol is not None:
            args.rtol = resume_summary.rtol
        if "--atol" not in explicit_flags and resume_summary.atol is not None:
            args.atol = resume_summary.atol
        if "--operations" not in explicit_flags and resume_summary.operations:
            args.operations = ",".join(resume_summary.operations)
        if "--out-csv" not in explicit_flags and resume_summary.out_csv:
            args.out_csv = resume_summary.out_csv
        if "--resume-csv" not in explicit_flags:
            args.resume_csv = resume_summary.resume_csv or resume_summary.out_csv
        if "--summary-md" not in explicit_flags and resume_summary.summary_md:
            args.summary_md = resume_summary.summary_md

    if args.min_files is not None and args.max_files is not None:
        if args.min_files > args.max_files:
            parser.error("--min-files cannot be greater than --max-files")

    if args.datasets_per_bin is not None and args.datasets_per_bin < 1:
        parser.error("--datasets-per-bin must be >= 1")

    if args.fixed_timesteps < 0:
        parser.error("--fixed-timesteps must be >= 0")

    if args.rtol < 0 or args.atol < 0:
        parser.error("--rtol and --atol must be >= 0")

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

    operations = tuple(
        dict.fromkeys(part.strip() for part in args.operations.split(",") if part.strip())
    )
    if not operations:
        parser.error("--operations must include at least one supported value")

    invalid_ops = [name for name in operations if name not in OPERATIONS]
    if invalid_ops:
        parser.error(
            "Unsupported --operations value(s): "
            + ", ".join(invalid_ops)
            + ". Supported: "
            + ", ".join(OPERATIONS)
        )

    return RunConfig(
        target_frequency=args.target_frequency,
        bins=bins,
        min_files=args.min_files,
        max_files=args.max_files,
        datasets_per_bin=args.datasets_per_bin,
        fixed_timesteps=args.fixed_timesteps,
        rtol=args.rtol,
        atol=args.atol,
        operations=operations,
        out_csv=_resolve_script_relative_path(args.out_csv),
        resume_csv=_resolve_script_relative_path(args.resume_csv),
        summary_md=_resolve_script_relative_path(args.summary_md),
        resume_summary_md=args.resume_summary_md,
    )


def main() -> None:
    config = _parse_args()
    prepared_datasets_csv = _prepared_datasets_csv_path(config.target_frequency)
    resume_summary = _load_resume_summary_config(config.resume_summary_md)

    logger.info("Starting backend API output comparison run")
    logger.info(
        "Run config | target_frequency=%s | bins=%s | min_files=%s | max_files=%s | "
        "datasets_per_bin=%s | fixed_timesteps=%s | rtol=%s | atol=%s | "
        "operations=%s | prepared_datasets_csv=%s | out_csv=%s | summary_md=%s | "
        "resume_summary_md=%s",
        config.target_frequency,
        ",".join(config.bins),
        config.min_files,
        config.max_files,
        config.datasets_per_bin,
        config.fixed_timesteps,
        config.rtol,
        config.atol,
        ",".join(config.operations),
        prepared_datasets_csv,
        config.out_csv,
        config.summary_md,
        config.resume_summary_md,
    )

    rows_by_key = _load_resume_rows(config.resume_csv)
    if rows_by_key:
        logger.info(
            "Loaded %d rows from resume CSV: %s",
            len(rows_by_key),
            config.resume_csv,
        )
    if config.resume_summary_md is not None:
        logger.info("Loaded resume summary markdown: %s", config.resume_summary_md)
        if resume_summary.recorded_total_rows is not None:
            logger.info(
                "Resume summary recorded total_rows=%d | resume_csv_rows=%d",
                resume_summary.recorded_total_rows,
                len(rows_by_key),
            )
            if resume_summary.recorded_total_rows != len(rows_by_key):
                logger.warning(
                    "Resume summary row count differs from resume CSV | summary=%d | csv=%d",
                    resume_summary.recorded_total_rows,
                    len(rows_by_key),
                )

    prepared_datasets = load_prepared_datasets_csv(prepared_datasets_csv)
    selected_datasets = _filter_prepared_datasets(prepared_datasets, config)
    candidates_by_bin = _group_datasets_by_bin(prepared_datasets)
    _log_bin_selection_summary(candidates_by_bin, selected_datasets, rows_by_key)

    if not selected_datasets:
        logger.warning("No datasets selected after preprocessing and bin filters")

    total_pairs = len(selected_datasets) * len(config.operations)
    pair_index = 0

    for dataset in selected_datasets:
        spec = dataset.spec
        pending_operations = [
            operation
            for operation in config.operations
            if _row_key(spec.dataset_id, operation) not in rows_by_key
        ]

        if not pending_operations:
            pair_index += len(config.operations)
            continue

        if spec.dataset_id in SKIPPED_DATASET_REASONS:
            skip_reason = SKIPPED_DATASET_REASONS[spec.dataset_id]
            for operation in config.operations:
                pair_index += 1
                row_key = _row_key(spec.dataset_id, operation)
                if row_key in rows_by_key:
                    logger.info(
                        "[%d/%d] dataset=%s | operation=%s | already present in resume CSV",
                        pair_index,
                        total_pairs,
                        spec.dataset_id,
                        operation,
                    )
                    continue

                logger.warning(
                    "[%d/%d] dataset=%s | operation=%s | skipping | reason=%s",
                    pair_index,
                    total_pairs,
                    spec.dataset_id,
                    operation,
                    skip_reason,
                )
                row = _make_base_row(dataset, config, operation)
                row.update(_skip_result(skip_reason))
                rows_by_key[row_key] = row
                _save_checkpoint(rows_by_key, config.out_csv)
                _write_summary_markdown(rows_by_key, config.summary_md, config)
                gc.collect()
            continue

        dataset_context = open_dataset_pair_for_validation(
            kerchunk_file=spec.kerchunk_file,
            netcdf_files=list(dataset.netcdf_files),
            var_id=spec.var_id,
            fixed_timesteps=config.fixed_timesteps,
            dataset_label=spec.dataset_id,
        )

        try:
            for operation in config.operations:
                pair_index += 1
                row_key = _row_key(spec.dataset_id, operation)

                if row_key in rows_by_key:
                    logger.info(
                        "[%d/%d] dataset=%s | operation=%s | already present in resume CSV",
                        pair_index,
                        total_pairs,
                        spec.dataset_id,
                        operation,
                    )
                    continue

                logger.info(
                    "[%d/%d] dataset=%s | operation=%s | bin=%s | rank=%d | nfiles=%d | var=%s",
                    pair_index,
                    total_pairs,
                    spec.dataset_id,
                    operation,
                    dataset.nfiles_bin,
                    dataset.bin_selected_rank,
                    dataset.nfiles,
                    spec.var_id,
                )

                row = _make_base_row(dataset, config, operation)

                try:
                    row.update(
                        validate_dataset_operation_pair_from_open_datasets(
                            opened_pair=dataset_context,
                            var_id=spec.var_id,
                            operation=operation,
                            config=config,
                            dataset_label=spec.dataset_id,
                        )
                    )
                except Exception as exc:
                    logger.exception(
                        "Unexpected failure for dataset=%s operation=%s",
                        spec.dataset_id,
                        operation,
                    )
                    categories = ["unexpected_validation_error"]
                    row.update(
                        {
                            "status": "error",
                            "skip_reason": None,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                            "failure_categories_json": _json_dumps(categories),
                            "primary_failure_category": categories[0],
                            "diagnostics_json": _json_dumps(
                                {"unexpected_exception": f"{type(exc).__name__}: {exc}"}
                            ),
                        }
                    )

                rows_by_key[row_key] = row
                _save_checkpoint(rows_by_key, config.out_csv)
                _write_summary_markdown(rows_by_key, config.summary_md, config)
                gc.collect()
        finally:
            close_opened_dataset_pair(dataset_context)

    logger.info("API output comparison run complete")
    _write_summary_markdown(rows_by_key, config.summary_md, config)
    _log_final_results_summary(rows_by_key)
    logger.info("Results written to %s", config.out_csv)
    logger.info("Summary written to %s", config.summary_md)


def _make_base_row(
    dataset: PreparedDataset,
    config: RunConfig,
    operation: str,
) -> dict[str, Any]:
    spec = dataset.spec
    return {
        "row_key": _row_key(spec.dataset_id, operation),
        "dataset_id": spec.dataset_id,
        "data_dir": spec.data_dir,
        "kerchunk_file": spec.kerchunk_file,
        "frequency": config.target_frequency,
        "var_id": spec.var_id,
        "netcdf_file_count": dataset.nfiles,
        "nfiles_bin": dataset.nfiles_bin,
        "bin_selected_rank": dataset.bin_selected_rank,
        "operation": operation,
        "operation_config_json": _json_dumps(_operation_config(operation)),
        "status": "pending",
        "skip_reason": None,
        "error_type": None,
        "error_message": None,
        "structure_match": None,
        "dims_match": None,
        "dtype_match": None,
        "coords_match": None,
        "data_match": None,
        "rtol": config.rtol,
        "atol": config.atol,
        "mismatching_elements": None,
        "mismatching_percent": None,
        "max_abs_diff": None,
        "max_rel_diff": None,
        "nan_mismatch_count": None,
        "axis_T_kerchunk": None,
        "axis_T_netcdf": None,
        "axis_Y_kerchunk": None,
        "axis_Y_netcdf": None,
        "axis_X_kerchunk": None,
        "axis_X_netcdf": None,
        "axis_Z_kerchunk": None,
        "axis_Z_netcdf": None,
        "all_checks_pass": None,
        "failure_categories_json": None,
        "primary_failure_category": None,
        "diagnostics_json": None,
    }


def _skip_result(skip_reason: str) -> dict[str, Any]:
    categories = ["operation_not_applicable"]
    return {
        "status": "skipped",
        "skip_reason": skip_reason,
        "error_type": None,
        "error_message": None,
        "all_checks_pass": False,
        "failure_categories_json": _json_dumps(categories),
        "primary_failure_category": categories[0],
        "diagnostics_json": _json_dumps({"skip_reason": skip_reason}),
    }


def _parse_csv_filepaths(value: Any) -> tuple[str, ...]:
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

    prepared: list[PreparedDataset] = []
    for _, row in df.iterrows():
        netcdf_files = _parse_csv_filepaths(row["filepaths"])
        data_dir = row.get("data_dir")
        if pd.isna(data_dir) or not str(data_dir):
            data_dir = _infer_data_dir_from_filepaths(netcdf_files)

        var_id = str(row["variable"]) if not pd.isna(row["variable"]) else ""
        if not var_id:
            var_id = _infer_var_id(str(row["kerchunk_file"]))

        prepared.append(
            PreparedDataset(
                spec=DatasetSpec(
                    data_dir=str(data_dir),
                    dataset_id=str(row["dataset_id"]),
                    kerchunk_file=str(row["kerchunk_file"]),
                    var_id=var_id,
                ),
                netcdf_files=netcdf_files,
                nfiles=int(row["netcdf_file_count"]),
                nfiles_bin=str(row["nfiles_bin"]),
                bin_selected_rank=int(row["bin_selected_rank"]),
            )
        )

    return prepared


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


def _within_file_limits(
    dataset: PreparedDataset,
    min_files: int | None,
    max_files: int | None,
) -> bool:
    if min_files is not None and dataset.nfiles < min_files:
        return False
    if max_files is not None and dataset.nfiles > max_files:
        return False
    return True


def _filter_prepared_datasets(
    datasets: list[PreparedDataset],
    config: RunConfig,
) -> list[PreparedDataset]:
    grouped = _group_datasets_by_bin(datasets)
    selected: list[PreparedDataset] = []

    for label in SUPPORTED_NFILES_BIN_LABELS:
        if label not in config.bins:
            continue

        candidates = [
            dataset
            for dataset in grouped[label]
            if _within_file_limits(dataset, config.min_files, config.max_files)
        ]
        candidates = sorted(
            candidates,
            key=lambda dataset: (
                dataset.bin_selected_rank,
                dataset.nfiles,
                dataset.spec.dataset_id,
            ),
        )
        limit = len(candidates)
        if config.datasets_per_bin is not None:
            limit = min(limit, config.datasets_per_bin)
        selected.extend(candidates[:limit])

    return selected


def _log_bin_selection_summary(
    candidates_by_bin: dict[str, list[PreparedDataset]],
    selected_datasets: list[PreparedDataset],
    rows_by_key: dict[str, dict[str, Any]],
) -> None:
    selected_by_bin: dict[str, list[PreparedDataset]] = defaultdict(list)
    pending_by_bin: dict[str, list[PreparedDataset]] = defaultdict(list)

    selected_row_keys = set(rows_by_key)
    for dataset in selected_datasets:
        selected_by_bin[dataset.nfiles_bin].append(dataset)
        dataset_pending = False
        for operation in OPERATIONS:
            if _row_key(dataset.spec.dataset_id, operation) not in selected_row_keys:
                dataset_pending = True
                break
        if dataset_pending:
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


def _row_key(dataset_id: str, operation: str) -> str:
    return f"{dataset_id}::{operation}"


def _load_resume_rows(path: str | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}

    if not os.path.exists(path):
        logger.warning("Resume CSV does not exist: %s", path)
        return {}

    try:
        df = pd.read_csv(path)
    except Exception as exc:
        logger.warning("Failed to read resume CSV %s: %s", path, exc)
        return {}

    if "dataset_id" not in df.columns or "operation" not in df.columns:
        logger.warning(
            "Resume CSV missing dataset_id and/or operation columns: %s",
            path,
        )
        return {}

    rows_by_key: dict[str, dict[str, Any]] = {}
    for _, series in df.iterrows():
        dataset_id = series.get("dataset_id")
        operation = series.get("operation")
        if pd.isna(dataset_id) or pd.isna(operation):
            continue
        rows_by_key[_row_key(str(dataset_id), str(operation))] = series.to_dict()

    return rows_by_key


def _save_checkpoint(rows_by_key: dict[str, dict[str, Any]], out_csv: str) -> None:
    df = pd.DataFrame(rows_by_key.values())
    _ensure_schema_columns(df)
    if not df.empty and {"netcdf_file_count", "dataset_id", "operation"}.issubset(
        df.columns
    ):
        df = df.sort_values(
            ["netcdf_file_count", "dataset_id", "operation"],
            na_position="last",
        )
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)


def _ensure_schema_columns(df: pd.DataFrame) -> None:
    expected_cols = [
        "row_key",
        "dataset_id",
        "data_dir",
        "kerchunk_file",
        "frequency",
        "var_id",
        "netcdf_file_count",
        "nfiles_bin",
        "bin_selected_rank",
        "operation",
        "operation_config_json",
        "status",
        "skip_reason",
        "error_type",
        "error_message",
        "structure_match",
        "dims_match",
        "dtype_match",
        "coords_match",
        "data_match",
        "rtol",
        "atol",
        "mismatching_elements",
        "mismatching_percent",
        "max_abs_diff",
        "max_rel_diff",
        "nan_mismatch_count",
        "axis_T_kerchunk",
        "axis_T_netcdf",
        "axis_Y_kerchunk",
        "axis_Y_netcdf",
        "axis_X_kerchunk",
        "axis_X_netcdf",
        "axis_Z_kerchunk",
        "axis_Z_netcdf",
        "all_checks_pass",
        "failure_categories_json",
        "primary_failure_category",
        "diagnostics_json",
    ]

    for col in expected_cols:
        if col not in df.columns:
            df[col] = pd.NA


def open_dataset_pair_for_validation(
    kerchunk_file: str,
    netcdf_files: list[str],
    var_id: str,
    fixed_timesteps: int,
    dataset_label: str | None = None,
) -> dict[str, Any]:
    log_prefix = f"[{dataset_label}] " if dataset_label else ""
    diagnostics: dict[str, Any] = {
        "kerchunk_file_exists": os.path.exists(kerchunk_file),
        "netcdf_file_count_resolved": len(netcdf_files),
        "missing_netcdf_files": [path for path in netcdf_files if not os.path.exists(path)],
    }

    logger.info(
        "%sdataset open start | var=%s | netcdf_files=%d",
        log_prefix,
        var_id,
        len(netcdf_files),
    )

    if not diagnostics["kerchunk_file_exists"]:
        diagnostics["open_error_type"] = "kerchunk_file_missing"
        diagnostics["open_error_message"] = (
            f"Kerchunk reference file does not exist: {kerchunk_file}"
        )
        return {"kerchunk_ds": None, "netcdf_ds": None, "diagnostics": diagnostics}

    if diagnostics["missing_netcdf_files"]:
        diagnostics["open_error_type"] = "netcdf_file_missing"
        diagnostics["open_error_message"] = (
            "One or more NetCDF files do not exist "
            f"({len(diagnostics['missing_netcdf_files'])} missing)"
        )
        return {"kerchunk_ds": None, "netcdf_ds": None, "diagnostics": diagnostics}

    kerchunk_ds = None
    netcdf_ds = None

    with xr.set_options(file_cache_maxsize=1):
        try:
            logger.info("%sopening kerchunk dataset", log_prefix)
            kerchunk_ds = _open_kerchunk_dataset(kerchunk_file)
            kerchunk_ds = _apply_fixed_time_slice(
                kerchunk_ds,
                var_id,
                fixed_timesteps,
            )
            logger.info("%skerchunk open complete", log_prefix)
        except Exception as exc:
            diagnostics["kerchunk_open_error"] = f"{type(exc).__name__}: {exc}"
            diagnostics["open_error_type"] = "kerchunk_open_failed"
            diagnostics["open_error_message"] = str(exc)
            _safe_close(kerchunk_ds)
            return {"kerchunk_ds": None, "netcdf_ds": None, "diagnostics": diagnostics}

        try:
            logger.info("%sopening NetCDF dataset", log_prefix)
            netcdf_ds = _open_netcdf_dataset(netcdf_files)
            netcdf_ds = _apply_fixed_time_slice(
                netcdf_ds,
                var_id,
                fixed_timesteps,
            )
            logger.info("%sNetCDF open complete", log_prefix)
        except Exception as exc:
            diagnostics["netcdf_open_error"] = f"{type(exc).__name__}: {exc}"
            diagnostics["open_error_type"] = "netcdf_open_failed"
            diagnostics["open_error_message"] = str(exc)
            _safe_close(kerchunk_ds)
            _safe_close(netcdf_ds)
            return {"kerchunk_ds": None, "netcdf_ds": None, "diagnostics": diagnostics}

    source_axis_result = _compare_cf_axes(kerchunk_ds, netcdf_ds)
    diagnostics["source_axes"] = source_axis_result["diagnostics"]
    logger.info("%sdataset open complete", log_prefix)
    return {
        "kerchunk_ds": kerchunk_ds,
        "netcdf_ds": netcdf_ds,
        "diagnostics": diagnostics,
    }


def validate_dataset_operation_pair_from_open_datasets(
    *,
    opened_pair: dict[str, Any],
    var_id: str,
    operation: str,
    config: RunConfig,
    dataset_label: str | None = None,
) -> dict[str, Any]:
    log_prefix = (
        f"[{dataset_label}][{operation}] " if dataset_label else f"[{operation}] "
    )
    diagnostics = {
        "operation": operation,
        "operation_config": _operation_config(operation),
    }
    diagnostics.update(_copy_jsonable_dict(opened_pair["diagnostics"]))

    logger.info("%svalidation start | var=%s", log_prefix, var_id)

    kerchunk_ds = opened_pair.get("kerchunk_ds")
    netcdf_ds = opened_pair.get("netcdf_ds")
    if kerchunk_ds is None or netcdf_ds is None:
        return _error_result(
            error_type=str(diagnostics.get("open_error_type", "dataset_open_failed")),
            error_message=str(
                diagnostics.get("open_error_message", "Dataset pair failed to open")
            ),
            diagnostics=diagnostics,
        )

    output_k = None
    output_n = None
    try:
        exec_k = _run_operation_for_backend(
            backend="kerchunk",
            ds=kerchunk_ds,
            var_id=var_id,
            operation=operation,
            config=config,
        )
        exec_n = _run_operation_for_backend(
            backend="netcdf",
            ds=netcdf_ds,
            var_id=var_id,
            operation=operation,
            config=config,
        )
        diagnostics["backend_execution"] = {
            "kerchunk": exec_k["diagnostics"],
            "netcdf": exec_n["diagnostics"],
        }

        pair_status = _resolve_pair_status(exec_k, exec_n)
        if pair_status["status"] != "ok":
            diagnostics["pair_resolution"] = pair_status
            return _pair_status_to_result(pair_status, diagnostics)

        output_k = exec_k["output"]
        output_n = exec_n["output"]

        output_axis_result = _compare_cf_axes(output_k, output_n)
        structure_result = _compare_output_structure(
            output_k,
            output_n,
            var_id,
            rtol=config.rtol,
            atol=config.atol,
        )
        data_result = _compare_output_data(
            output_k[var_id],
            output_n[var_id],
            rtol=config.rtol,
            atol=config.atol,
        )

        diagnostics["output_axes"] = output_axis_result["diagnostics"]
        diagnostics["structure"] = structure_result["diagnostics"]
        diagnostics["data"] = data_result["diagnostics"]

        all_checks_pass = bool(
            output_axis_result["match"]
            and structure_result["match"]
            and data_result["match"]
        )
        categories = _derive_failure_categories(
            status="ok",
            axis_match=output_axis_result["match"],
            dims_match=structure_result["dims_match"],
            dtype_match=structure_result["dtype_match"],
            coords_match=structure_result["coords_match"],
            data_match=data_result["match"],
        )
        logger.info(
            "%svalidation complete | all_checks_pass=%s | categories=%s",
            log_prefix,
            all_checks_pass,
            ",".join(categories) if categories else "none",
        )

        result = {
            "status": "ok",
            "skip_reason": None,
            "error_type": None,
            "error_message": None,
            "structure_match": structure_result["match"],
            "dims_match": structure_result["dims_match"],
            "dtype_match": structure_result["dtype_match"],
            "coords_match": structure_result["coords_match"],
            "data_match": data_result["match"],
            "rtol": config.rtol,
            "atol": config.atol,
            "mismatching_elements": data_result["mismatching_elements"],
            "mismatching_percent": data_result["mismatching_percent"],
            "max_abs_diff": data_result["max_abs_diff"],
            "max_rel_diff": data_result["max_rel_diff"],
            "nan_mismatch_count": data_result["nan_mismatch_count"],
            "all_checks_pass": all_checks_pass,
            "failure_categories_json": _json_dumps(categories),
            "primary_failure_category": categories[0] if categories else None,
            "diagnostics_json": _json_dumps(diagnostics),
        }
        result.update(_axis_fields_from_result(output_axis_result))
        return result
    finally:
        _safe_close(output_k)
        _safe_close(output_n)


def _open_kerchunk_dataset(path: str) -> xr.Dataset:
    return xc.open_dataset(path, engine="kerchunk", chunks={})


def _open_netcdf_dataset(paths: list[str]) -> xr.Dataset:
    return xc.open_mfdataset(paths, chunks={}, join="exact")


def _apply_fixed_time_slice(
    ds: xr.Dataset,
    var_id: str,
    fixed_timesteps: int,
) -> xr.Dataset:
    if fixed_timesteps <= 0:
        return ds
    if var_id not in ds.variables:
        return ds
    if "time" in ds[var_id].dims:
        n = min(fixed_timesteps, ds[var_id].sizes["time"])
        return ds.isel(time=slice(0, n))
    return ds


def _run_operation_for_backend(
    *,
    backend: str,
    ds: xr.Dataset,
    var_id: str,
    operation: str,
    config: RunConfig,
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {"backend": backend}
    output_ds = None
    working_ds = ds
    cleanup_datasets: list[xr.Dataset] = []

    if var_id not in ds.variables:
        diagnostics["reason"] = "target_variable_missing"
        return {
            "status": "skipped",
            "skip_reason": f"{backend}_target_variable_missing:{var_id}",
            "diagnostics": diagnostics,
            "output": None,
        }

    if operation == "temporal":
        has_time = "time" in ds[var_id].dims or _resolve_axis_name(ds, "T")[0] is not None
        diagnostics["time_axis_name"] = _resolve_axis_name(ds, "T")[0]
        if not has_time:
            diagnostics["reason"] = "no_time_axis"
            return {
                "status": "skipped",
                "skip_reason": f"{backend}_no_time_axis",
                "diagnostics": diagnostics,
                "output": None,
            }
    elif operation in {"spatial", "horizontal"}:
        y_name, _ = _resolve_axis_name(ds, "Y")
        x_name, _ = _resolve_axis_name(ds, "X")
        diagnostics["x_axis_name"] = x_name
        diagnostics["y_axis_name"] = y_name
        if x_name is None or y_name is None:
            diagnostics["reason"] = "missing_spatial_axes"
            return {
                "status": "skipped",
                "skip_reason": f"{backend}_missing_spatial_axes",
                "diagnostics": diagnostics,
                "output": None,
            }
    elif operation == "vertical":
        z_name, _ = _resolve_axis_name(ds, "Z")
        diagnostics["z_axis_name"] = z_name
        if z_name is None:
            diagnostics["reason"] = "missing_vertical_axis"
            return {
                "status": "skipped",
                "skip_reason": f"{backend}_missing_vertical_axis",
                "diagnostics": diagnostics,
                "output": None,
            }

    if operation in {"temporal", "spatial", "horizontal"}:
        working_ds, dropped_coords = _drop_non_dimension_coords(working_ds)
        diagnostics["dropped_non_dim_coords"] = dropped_coords
        if working_ds is not ds:
            cleanup_datasets.append(working_ds)

    try:
        if operation in {"spatial", "horizontal", "vertical"}:
            bounds_axes = _bounds_axes_for_operation(operation)
            bounded_ds = working_ds.bounds.add_missing_bounds(axes=list(bounds_axes))
            if bounded_ds is not working_ds:
                cleanup_datasets.append(bounded_ds)
            working_ds = bounded_ds
            diagnostics["added_missing_bounds"] = True
            diagnostics["added_missing_bounds_axes"] = list(bounds_axes)
        else:
            diagnostics["added_missing_bounds"] = False
    except Exception as exc:
        diagnostics["bounds_prepare_error"] = f"{type(exc).__name__}: {exc}"
        return {
            "status": "skipped",
            "skip_reason": f"{backend}_bounds_prepare_failed",
            "diagnostics": diagnostics,
            "output": None,
        }

    try:
        if operation == "temporal":
            logger.info("[%s] running temporal group_average", backend)
            output_ds = working_ds.temporal.group_average(var_id, freq="year")
        elif operation == "spatial":
            logger.info("[%s] running spatial average", backend)
            output_ds = working_ds.spatial.average(var_id)
        elif operation == "horizontal":
            logger.info("[%s] running horizontal regrid", backend)
            output_ds = working_ds.regridder.horizontal(
                var_id,
                _build_horizontal_target_grid(),
                tool="xesmf",
                method="bilinear",
            )
        elif operation == "vertical":
            vertical_kwargs, vertical_reason = _build_vertical_regrid_kwargs(
                working_ds,
                var_id,
            )
            diagnostics["vertical_kwargs"] = _serialize_vertical_kwargs(vertical_kwargs)
            if vertical_kwargs is None:
                diagnostics["reason"] = vertical_reason
                logger.info(
                    "[%s] skipping vertical regrid | reason=%s",
                    backend,
                    vertical_reason,
                )
                return {
                    "status": "skipped",
                    "skip_reason": f"{backend}_{vertical_reason}",
                    "diagnostics": diagnostics,
                    "output": None,
                }
            logger.info(
                "[%s] running vertical regrid | kwargs=%s",
                backend,
                diagnostics["vertical_kwargs"],
            )
            output_ds = working_ds.regridder.vertical(
                var_id,
                _build_vertical_target_grid(),
                method="log",
                **vertical_kwargs,
            )
        else:
            raise ValueError(f"Unsupported operation: {operation}")

        output_ds = output_ds.load()
        diagnostics["output_var_dims"] = list(output_ds[var_id].dims)
        diagnostics["output_var_shape"] = list(output_ds[var_id].shape)
        diagnostics["output_var_dtype"] = str(output_ds[var_id].dtype)
        return {
            "status": "ok",
            "skip_reason": None,
            "diagnostics": diagnostics,
            "output": output_ds,
        }
    except Exception as exc:
        diagnostics["operation_error"] = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "[%s] %s failed | %s",
            backend,
            operation,
            diagnostics["operation_error"],
        )
        return {
            "status": "error",
            "error_type": f"{operation}_operation_failed",
            "error_message": str(exc),
            "diagnostics": diagnostics,
            "output": None,
        }
    finally:
        for cleanup_ds in reversed(cleanup_datasets):
            if cleanup_ds is not ds:
                _safe_close(cleanup_ds)


def _resolve_pair_status(
    exec_k: dict[str, Any],
    exec_n: dict[str, Any],
) -> dict[str, Any]:
    if exec_k["status"] == "ok" and exec_n["status"] == "ok":
        return {"status": "ok"}

    if exec_k["status"] == "skipped" and exec_n["status"] == "skipped":
        reason_k = exec_k.get("skip_reason") or "kerchunk_skipped"
        reason_n = exec_n.get("skip_reason") or "netcdf_skipped"
        canonical = _canonical_skip_reason(reason_k, reason_n)
        return {
            "status": "skipped",
            "skip_reason": canonical,
            "error_type": None,
            "error_message": None,
        }

    if exec_k["status"] == "error" or exec_n["status"] == "error":
        if exec_k["status"] == "error" and exec_n["status"] == "error":
            return {
                "status": "error",
                "error_type": "operation_failed_both_backends",
                "error_message": (
                    f"kerchunk={exec_k.get('error_type')}:{exec_k.get('error_message')} | "
                    f"netcdf={exec_n.get('error_type')}:{exec_n.get('error_message')}"
                ),
            }
        failing = exec_k if exec_k["status"] == "error" else exec_n
        successful_backend = "netcdf" if exec_k["status"] == "error" else "kerchunk"
        return {
            "status": "error",
            "error_type": "operation_failed_one_backend",
            "error_message": (
                f"{failing['diagnostics'].get('backend')} failed while {successful_backend} "
                "completed successfully: "
                f"{failing.get('error_type')}:{failing.get('error_message')}"
            ),
        }

    if exec_k["status"] != exec_n["status"]:
        return {
            "status": "error",
            "error_type": "operation_eligibility_mismatch",
            "error_message": (
                f"kerchunk={exec_k.get('status')}:{exec_k.get('skip_reason')} | "
                f"netcdf={exec_n.get('status')}:{exec_n.get('skip_reason')}"
            ),
        }

    return {
        "status": "error",
        "error_type": "unhandled_pair_status",
        "error_message": f"kerchunk={exec_k['status']} netcdf={exec_n['status']}",
    }


def _pair_status_to_result(
    pair_status: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    if pair_status["status"] == "skipped":
        categories = ["operation_not_applicable"]
        return {
            "status": "skipped",
            "skip_reason": pair_status["skip_reason"],
            "error_type": None,
            "error_message": None,
            "all_checks_pass": False,
            "failure_categories_json": _json_dumps(categories),
            "primary_failure_category": categories[0],
            "diagnostics_json": _json_dumps(diagnostics),
        }

    return _error_result(
        error_type=pair_status.get("error_type", "pair_resolution_error"),
        error_message=pair_status.get("error_message", "Unknown pair-resolution failure"),
        diagnostics=diagnostics,
    )


def _error_result(
    *,
    error_type: str,
    error_message: str,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    categories = _derive_failure_categories(
        status="error",
        error_type=error_type,
    )
    return {
        "status": "error",
        "skip_reason": None,
        "error_type": error_type,
        "error_message": error_message,
        "all_checks_pass": False,
        "failure_categories_json": _json_dumps(categories),
        "primary_failure_category": categories[0] if categories else None,
        "diagnostics_json": _json_dumps(diagnostics),
    }


def _build_horizontal_target_grid() -> xr.Dataset:
    lat = xc.create_axis(
        HORIZONTAL_TARGET_GRID_CONFIG["lat_name"],
        np.arange(
            HORIZONTAL_TARGET_GRID_CONFIG["lat_start"],
            HORIZONTAL_TARGET_GRID_CONFIG["lat_stop"] + HORIZONTAL_TARGET_GRID_CONFIG["lat_step"] / 2,
            HORIZONTAL_TARGET_GRID_CONFIG["lat_step"],
        ),
        attrs={"units": "degrees_north", "axis": "Y"},
    )
    lon = xc.create_axis(
        HORIZONTAL_TARGET_GRID_CONFIG["lon_name"],
        np.arange(
            HORIZONTAL_TARGET_GRID_CONFIG["lon_start"],
            HORIZONTAL_TARGET_GRID_CONFIG["lon_stop"] + HORIZONTAL_TARGET_GRID_CONFIG["lon_step"] / 2,
            HORIZONTAL_TARGET_GRID_CONFIG["lon_step"],
        ),
        attrs={"units": "degrees_east", "axis": "X"},
    )
    return xc.create_grid(x=lon, y=lat)


def _build_vertical_target_grid() -> xr.Dataset:
    lev = xc.create_axis(
        "lev",
        np.asarray(VERTICAL_TARGET_PLEVS, dtype=np.float64),
        attrs={"units": "Pa", "axis": "Z", "positive": "down"},
    )
    return xc.create_grid(z=lev)


def _bounds_axes_for_operation(operation: str) -> tuple[str, ...]:
    if operation in {"spatial", "horizontal"}:
        return ("X", "Y")
    if operation == "vertical":
        return ("Z",)
    return ()


def _drop_non_dimension_coords(ds: xr.Dataset) -> tuple[xr.Dataset, list[str]]:
    coord_names = [name for name in ds.coords if name not in ds.dims]
    if not coord_names:
        return ds, []
    return ds.reset_coords(names=coord_names, drop=True), coord_names


def _build_vertical_regrid_kwargs(
    ds: xr.Dataset,
    var_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    z_name, z_error = _resolve_axis_name(ds, "Z")
    if z_name is None:
        return None, "missing_vertical_axis"

    z_coord = ds.coords[z_name]
    if _is_pressure_like_vertical_coord(z_coord):
        # Pressure-level coordinates can be remapped directly; asking xCDAT to
        # "infer" target_data incorrectly pushes it down the hybrid-coordinate
        # path, which expects CF formula_terms metadata.
        return {"tool": "xgcm"}, None

    pressure = _find_pressure_target_data(ds, var_id, z_name)
    if pressure is not None:
        return {"tool": "xgcm", "target_data": pressure}, None

    if z_error:
        return None, "vertical_axis_resolution_failed"
    return None, "vertical_pressure_target_unavailable"


def _find_pressure_target_data(
    ds: xr.Dataset,
    var_id: str,
    z_name: str,
) -> xr.DataArray | None:
    for name in ("pressure", "air_pressure", "pres", "pfull"):
        candidate = _get_var_case_insensitive(ds, name)
        if candidate is None:
            continue
        if _pressure_candidate_matches_var(candidate, ds[var_id], z_name):
            return _normalize_pressure_candidate(candidate, ds[var_id])

    z_coord = ds.coords[z_name]
    formula_terms = z_coord.attrs.get("formula_terms")
    if isinstance(formula_terms, str) and formula_terms.strip():
        pressure = _pressure_from_formula_terms(ds, ds[var_id], formula_terms)
        if pressure is not None:
            return pressure

    pressure = _pressure_from_common_hybrid_vars(ds, ds[var_id])
    if pressure is not None:
        return pressure

    return None


def _pressure_candidate_matches_var(
    candidate: xr.DataArray,
    var: xr.DataArray,
    z_name: str,
) -> bool:
    if z_name not in candidate.dims:
        return False
    return set(candidate.dims).issubset(set(var.dims))


def _normalize_pressure_candidate(
    candidate: xr.DataArray,
    var: xr.DataArray,
) -> xr.DataArray:
    normalized = candidate
    dim_order = [dim for dim in var.dims if dim in normalized.dims]
    normalized = normalized.transpose(*dim_order, ...)
    return normalized


def _pressure_from_formula_terms(
    ds: xr.Dataset,
    var: xr.DataArray,
    formula_terms: str,
) -> xr.DataArray | None:
    mapping = _parse_formula_terms(formula_terms)
    ps = _get_var_from_mapping(ds, mapping, "ps")
    if ps is None:
        return None

    ap = _get_var_from_mapping(ds, mapping, "ap")
    b = _get_var_from_mapping(ds, mapping, "b")
    if ap is not None and b is not None:
        pressure = ap + b * ps
        return _normalize_pressure_candidate(pressure, var)

    a = _get_var_from_mapping(ds, mapping, "a")
    p0 = _get_var_from_mapping(ds, mapping, "p0")
    if a is not None and b is not None and p0 is not None:
        pressure = a * p0 + b * ps
        return _normalize_pressure_candidate(pressure, var)

    return None


def _pressure_from_common_hybrid_vars(
    ds: xr.Dataset,
    var: xr.DataArray,
) -> xr.DataArray | None:
    ps = _get_var_case_insensitive(ds, "ps")
    if ps is None:
        ps = _get_var_case_insensitive(ds, "surface_air_pressure")

    ap = _get_var_case_insensitive(ds, "ap")
    b = _get_var_case_insensitive(ds, "b")
    if ps is not None and ap is not None and b is not None:
        pressure = ap + b * ps
        return _normalize_pressure_candidate(pressure, var)

    a = _get_var_case_insensitive(ds, "a")
    if a is None:
        a = _get_var_case_insensitive(ds, "hyam")
    if b is None:
        b = _get_var_case_insensitive(ds, "hybm")
    p0 = _get_var_case_insensitive(ds, "p0")
    if p0 is None:
        p0 = _get_var_case_insensitive(ds, "P0")
    if ps is not None and a is not None and b is not None and p0 is not None:
        pressure = a * p0 + b * ps
        return _normalize_pressure_candidate(pressure, var)

    return None


def _parse_formula_terms(formula_terms: str) -> dict[str, str]:
    tokens = formula_terms.replace(",", " ").split()
    mapping: dict[str, str] = {}
    i = 0
    while i < len(tokens) - 1:
        key = tokens[i].rstrip(":").strip()
        value = tokens[i + 1].strip()
        if tokens[i].endswith(":"):
            mapping[key] = value
            i += 2
        else:
            i += 1
    return mapping


def _get_var_from_mapping(
    ds: xr.Dataset,
    mapping: dict[str, str],
    key: str,
) -> xr.DataArray | None:
    value = mapping.get(key)
    if value is None:
        return None
    return _get_var_case_insensitive(ds, value)


def _get_var_case_insensitive(ds: xr.Dataset, name: str) -> xr.DataArray | None:
    if name in ds.variables:
        return ds[name]

    lower_name = name.lower()
    for candidate in ds.variables:
        if candidate.lower() == lower_name:
            return ds[candidate]
    return None


def _is_pressure_like_vertical_coord(coord: xr.DataArray) -> bool:
    units = str(coord.attrs.get("units", "")).strip().lower()
    if units in {"pa", "pascal", "pascals", "hpa", "mbar", "mb"}:
        return True

    standard_name = str(coord.attrs.get("standard_name", "")).strip().lower()
    if standard_name == "air_pressure":
        return True

    positive = str(coord.attrs.get("positive", "")).strip().lower()
    return positive in {"up", "down"} and coord.ndim == 1 and "formula_terms" not in coord.attrs


def _serialize_vertical_kwargs(kwargs: dict[str, Any] | None) -> dict[str, Any] | None:
    if kwargs is None:
        return None

    serialized: dict[str, Any] = {}
    for key, value in kwargs.items():
        if isinstance(value, xr.DataArray):
            serialized[key] = {
                "kind": "DataArray",
                "dims": list(value.dims),
                "shape": list(value.shape),
                "dtype": str(value.dtype),
                "name": value.name,
            }
        else:
            serialized[key] = _scalar_to_jsonable(value)
    return serialized


def _operation_config(operation: str) -> dict[str, Any]:
    if operation in DEFAULT_OPERATION_CONFIGS:
        return _copy_jsonable_dict(DEFAULT_OPERATION_CONFIGS[operation])
    raise ValueError(f"Unsupported operation: {operation}")


def _compare_output_structure(
    ds_k: xr.Dataset,
    ds_n: xr.Dataset,
    var_id: str,
    *,
    rtol: float,
    atol: float,
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {}

    if var_id not in ds_k.variables or var_id not in ds_n.variables:
        diagnostics["reason"] = "target variable missing from one or both outputs"
        diagnostics["kerchunk_has_var"] = var_id in ds_k.variables
        diagnostics["netcdf_has_var"] = var_id in ds_n.variables
        return {
            "match": False,
            "dims_match": False,
            "dtype_match": False,
            "coords_match": False,
            "diagnostics": diagnostics,
        }

    var_k = ds_k[var_id]
    var_n = ds_n[var_id]

    diagnostics["kerchunk_dims"] = list(var_k.dims)
    diagnostics["netcdf_dims"] = list(var_n.dims)
    diagnostics["kerchunk_shape"] = list(var_k.shape)
    diagnostics["netcdf_shape"] = list(var_n.shape)
    diagnostics["kerchunk_dtype"] = str(var_k.dtype)
    diagnostics["netcdf_dtype"] = str(var_n.dtype)
    diagnostics["kerchunk_coord_names"] = sorted(str(name) for name in var_k.coords)
    diagnostics["netcdf_coord_names"] = sorted(str(name) for name in var_n.coords)

    dims_match = var_k.dims == var_n.dims and var_k.shape == var_n.shape
    dtype_match = str(var_k.dtype) == str(var_n.dtype)

    coord_names_k = set(var_k.coords)
    coord_names_n = set(var_n.coords)
    missing_coord_names = sorted(coord_names_n - coord_names_k)
    extra_coord_names = sorted(coord_names_k - coord_names_n)
    diagnostics["missing_coord_names_in_kerchunk"] = missing_coord_names
    diagnostics["extra_coord_names_in_kerchunk"] = extra_coord_names

    coord_value_mismatches: dict[str, Any] = {}
    coords_match = not missing_coord_names and not extra_coord_names
    for coord_name in sorted(coord_names_k & coord_names_n):
        cmp_result = _compare_dataarrays(
            ds_k.coords[coord_name],
            ds_n.coords[coord_name],
            rtol=rtol,
            atol=atol,
        )
        if not cmp_result["match"]:
            coords_match = False
            coord_value_mismatches[coord_name] = cmp_result["diagnostics"]
    diagnostics["coord_value_mismatches"] = coord_value_mismatches

    return {
        "match": bool(dims_match and dtype_match and coords_match),
        "dims_match": bool(dims_match),
        "dtype_match": bool(dtype_match),
        "coords_match": bool(coords_match),
        "diagnostics": diagnostics,
    }


def _compare_output_data(
    var_k: xr.DataArray,
    var_n: xr.DataArray,
    *,
    rtol: float,
    atol: float,
) -> dict[str, Any]:
    stripped_k = xr.DataArray(
        var_k.load().values,
        dims=var_k.dims,
        name=var_k.name,
    )
    stripped_n = xr.DataArray(
        var_n.load().values,
        dims=var_n.dims,
        name=var_n.name,
    )
    cmp_result = _compare_dataarrays(stripped_k, stripped_n, rtol=rtol, atol=atol)
    diagnostics = dict(cmp_result["diagnostics"])

    mismatch_mask = diagnostics.get("mismatch_mask")
    mismatching_elements = None
    mismatching_percent = None
    if isinstance(mismatch_mask, np.ndarray):
        mismatching_elements = int(np.count_nonzero(mismatch_mask))
        total = int(mismatch_mask.size)
        mismatching_percent = float((mismatching_elements * 100.0) / total) if total else 0.0
        diagnostics["mismatch_mask"] = None

    return {
        "match": cmp_result["match"],
        "diagnostics": diagnostics,
        "mismatching_elements": mismatching_elements,
        "mismatching_percent": mismatching_percent,
        "max_abs_diff": cmp_result["max_abs_diff"],
        "max_rel_diff": cmp_result["max_rel_diff"],
        "nan_mismatch_count": cmp_result["nan_mismatch_count"],
    }


def _compare_dataarrays(
    left: xr.DataArray,
    right: xr.DataArray,
    *,
    rtol: float,
    atol: float,
) -> dict[str, Any]:
    left_loaded = left.load()
    right_loaded = right.load()

    diagnostics: dict[str, Any] = {
        "left_dims": list(left_loaded.dims),
        "right_dims": list(right_loaded.dims),
        "left_shape": list(left_loaded.shape),
        "right_shape": list(right_loaded.shape),
        "left_dtype": str(left_loaded.dtype),
        "right_dtype": str(right_loaded.dtype),
    }

    if left_loaded.dims != right_loaded.dims or left_loaded.shape != right_loaded.shape:
        diagnostics["reason"] = "dimension or shape mismatch"
        return {
            "match": False,
            "diagnostics": diagnostics,
            "max_abs_diff": None,
            "max_rel_diff": None,
            "nan_mismatch_count": None,
        }

    left_values = np.asarray(left_loaded.values)
    right_values = np.asarray(right_loaded.values)

    if _is_numeric_dtype(left_values.dtype) and _is_numeric_dtype(right_values.dtype):
        left_nan = (
            np.isnan(left_values)
            if np.issubdtype(left_values.dtype, np.floating)
            else np.zeros(left_values.shape, dtype=bool)
        )
        right_nan = (
            np.isnan(right_values)
            if np.issubdtype(right_values.dtype, np.floating)
            else np.zeros(right_values.shape, dtype=bool)
        )
        nan_mismatch_mask = left_nan != right_nan
        nan_mismatch_count = int(np.count_nonzero(nan_mismatch_mask))

        mismatch_mask = np.zeros(left_values.shape, dtype=bool)
        max_abs_diff = None
        max_rel_diff = None
        valid_mask = ~(left_nan | right_nan)
        if np.any(valid_mask):
            abs_diff = np.abs(left_values[valid_mask] - right_values[valid_mask])
            max_abs_diff = float(np.max(abs_diff))

            denom = np.abs(right_values[valid_mask])
            rel_diff = np.divide(
                abs_diff,
                denom,
                out=np.full(abs_diff.shape, np.nan, dtype=float),
                where=denom != 0,
            )
            if not np.all(np.isnan(rel_diff)):
                max_rel_diff = float(np.nanmax(rel_diff))

            mismatch_mask[valid_mask] = ~np.isclose(
                left_values[valid_mask],
                right_values[valid_mask],
                rtol=rtol,
                atol=atol,
                equal_nan=True,
            )

        mismatch_mask = mismatch_mask | nan_mismatch_mask
        match = not bool(np.any(mismatch_mask))
        if not match:
            diagnostics["reason"] = "numeric values differ beyond tolerance"
            diagnostics["first_mismatch"] = _first_numeric_mismatch(
                left_values,
                right_values,
                mismatch_mask,
            )

        diagnostics["nan_mismatch_count"] = nan_mismatch_count
        diagnostics["max_abs_diff"] = max_abs_diff
        diagnostics["max_rel_diff"] = max_rel_diff
        diagnostics["mismatch_mask"] = mismatch_mask
        return {
            "match": match,
            "diagnostics": diagnostics,
            "max_abs_diff": max_abs_diff,
            "max_rel_diff": max_rel_diff,
            "nan_mismatch_count": nan_mismatch_count,
        }

    equal = np.array_equal(left_values, right_values)
    if not equal:
        diagnostics["reason"] = "non-numeric values differ"
        diagnostics["first_mismatch"] = _first_mismatch(left_values, right_values)

    return {
        "match": bool(equal),
        "diagnostics": diagnostics,
        "max_abs_diff": None,
        "max_rel_diff": None,
        "nan_mismatch_count": None,
    }


def _compare_cf_axes(ds_k: xr.Dataset, ds_n: xr.Dataset) -> dict[str, Any]:
    resolved_names: dict[str, dict[str, str | None]] = {}
    diagnostics = {
        "axis_resolution_errors": {},
        "ignored_symmetric_axis_resolution_errors": {},
        "axis_mismatch_reasons": [],
    }
    match = True

    for axis_key in AXIS_KEYS:
        k_name, k_error = _resolve_axis_name(ds_k, axis_key)
        n_name, n_error = _resolve_axis_name(ds_n, axis_key)
        resolved_names[axis_key] = {"kerchunk": k_name, "netcdf": n_name}

        if k_error or n_error:
            error_payload = {
                "kerchunk": k_error,
                "netcdf": n_error,
            }
            if (
                k_name is None
                and n_name is None
                and k_error
                and n_error
                and k_error == n_error
            ):
                diagnostics["ignored_symmetric_axis_resolution_errors"][axis_key] = (
                    error_payload
                )
            else:
                diagnostics["axis_resolution_errors"][axis_key] = error_payload
                match = False

        if k_name != n_name:
            diagnostics["axis_mismatch_reasons"].append(
                {
                    "axis": axis_key,
                    "kerchunk": k_name,
                    "netcdf": n_name,
                }
            )
            if not (k_name is None and n_name is None):
                match = False

    return {
        "match": match,
        "resolved_names": resolved_names,
        "diagnostics": diagnostics,
    }


def _axis_fields_from_result(axis_result: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for axis_key in AXIS_KEYS:
        fields[f"axis_{axis_key}_kerchunk"] = axis_result["resolved_names"][axis_key][
            "kerchunk"
        ]
        fields[f"axis_{axis_key}_netcdf"] = axis_result["resolved_names"][axis_key][
            "netcdf"
        ]
    return fields


def _resolve_axis_name(ds: xr.Dataset, axis_key: str) -> tuple[str | None, str | None]:
    try:
        coord = xc.get_dim_coords(ds, axis_key)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"

    if coord is None:
        return None, None

    name = getattr(coord, "name", None)
    if name:
        return str(name), None

    if isinstance(coord, xr.Dataset):
        coord_names = list(coord.coords)
        if len(coord_names) == 1:
            return coord_names[0], None

    return None, f"Unable to resolve a single coordinate name for axis {axis_key}"


def _canonical_skip_reason(reason_k: str, reason_n: str) -> str:
    def _strip_backend_prefix(reason: str) -> str:
        for prefix in ("kerchunk_", "netcdf_"):
            if reason.startswith(prefix):
                return reason[len(prefix) :]
        return reason

    core_k = _strip_backend_prefix(reason_k)
    core_n = _strip_backend_prefix(reason_n)
    if core_k == core_n:
        return core_k
    return f"kerchunk={core_k};netcdf={core_n}"


def _derive_failure_categories(
    *,
    status: str,
    axis_match: bool | None = None,
    dims_match: bool | None = None,
    dtype_match: bool | None = None,
    coords_match: bool | None = None,
    data_match: bool | None = None,
    error_type: str | None = None,
) -> list[str]:
    if status == "error":
        if error_type in {"kerchunk_open_failed", "netcdf_open_failed"}:
            return ["open_decode_failure"]
        if error_type in {"kerchunk_file_missing", "netcdf_file_missing"}:
            return ["input_file_missing"]
        if error_type in {
            "operation_failed_one_backend",
            "operation_failed_both_backends",
            "operation_eligibility_mismatch",
        }:
            return ["backend_execution_mismatch"]
        return ["validation_error"]

    if status == "skipped":
        return ["operation_not_applicable"]

    categories: list[str] = []
    if axis_match is False:
        categories.append("cf_axis_detection_mismatch")
    if dims_match is False or dtype_match is False:
        categories.append("metadata_structure_mismatch")
    if coords_match is False:
        categories.append("coordinate_mismatch")
    if data_match is False:
        categories.append("data_mismatch")
    return categories


def _write_summary_markdown(
    rows_by_key: dict[str, dict[str, Any]],
    summary_md: str,
    config: RunConfig,
) -> None:
    df = pd.DataFrame(rows_by_key.values())
    _ensure_schema_columns(df)

    total_rows = len(df)
    if total_rows == 0:
        Path(summary_md).parent.mkdir(parents=True, exist_ok=True)
        Path(summary_md).write_text(
            "# Backend API Output Comparison Summary\n\nNo rows recorded yet.\n"
        )
        return

    status_lines = [
        "| operation | total | passed | failed_checks | errors | skipped |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for operation in OPERATIONS:
        subset = df[df["operation"] == operation]
        if subset.empty:
            continue
        passed = int(
            sum(
                _truthy(value)
                for value in subset.get("all_checks_pass", pd.Series(dtype=object)).tolist()
            )
        )
        errors = int(sum(value == "error" for value in subset["status"].tolist()))
        skipped = int(sum(value == "skipped" for value in subset["status"].tolist()))
        failed_checks = int(len(subset) - passed - errors - skipped)
        status_lines.append(
            f"| {operation} | {len(subset)} | {passed} | {failed_checks} | {errors} | {skipped} |"
        )

    skip_counter: Counter[str] = Counter()
    skip_examples: dict[str, list[str]] = defaultdict(list)
    for _, row in df.iterrows():
        if row.get("status") != "skipped":
            continue
        reason = str(row.get("skip_reason") or "unknown_skip")
        label = f"{row.get('operation')}::{reason}"
        skip_counter[label] += 1
        dataset_id = str(row.get("dataset_id"))
        if dataset_id and dataset_id not in skip_examples[label] and len(skip_examples[label]) < 5:
            skip_examples[label].append(dataset_id)

    skip_lines = ["| operation_and_reason | count | example_dataset_ids |", "| --- | ---: | --- |"]
    if skip_counter:
        for label, count in skip_counter.most_common():
            examples = ", ".join(skip_examples[label]) if skip_examples[label] else "-"
            skip_lines.append(f"| {label} | {count} | {examples} |")
    else:
        skip_lines.append("| none | 0 | - |")

    category_counter: Counter[str] = Counter()
    category_examples: dict[str, list[str]] = defaultdict(list)
    for _, row in df.iterrows():
        categories = _load_json_list(row.get("failure_categories_json"))
        dataset_label = f"{row.get('dataset_id')}::{row.get('operation')}"
        for category in categories:
            category_counter[category] += 1
            if (
                dataset_label
                and dataset_label not in category_examples[category]
                and len(category_examples[category]) < 5
            ):
                category_examples[category].append(dataset_label)

    category_lines = ["| failure_category | count | example_rows |", "| --- | ---: | --- |"]
    if category_counter:
        for category, count in category_counter.most_common():
            examples = ", ".join(category_examples[category]) if category_examples[category] else "-"
            category_lines.append(f"| {category} | {count} | {examples} |")
    else:
        category_lines.append("| none | 0 | - |")

    worst_abs_lines = _worst_case_lines(df, "max_abs_diff")
    worst_rel_lines = _worst_case_lines(df, "max_rel_diff")

    passed_total = int(sum(_truthy(value) for value in df["all_checks_pass"].tolist()))
    error_total = int(sum(value == "error" for value in df["status"].tolist()))
    skipped_total = int(sum(value == "skipped" for value in df["status"].tolist()))
    failed_total = total_rows - passed_total - error_total - skipped_total

    lines = [
        "# Backend API Output Comparison Summary",
        "",
        "## Run Configuration",
        "",
        * _run_configuration_markdown_lines(config),
        "",
        "## Operation Configuration",
        "",
        * _operation_configuration_markdown_lines(config.operations),
        "",
        f"- Total rows: {total_rows}",
        f"- Passed all checks: {passed_total}",
        f"- Failed validation checks: {failed_total}",
        f"- Execution errors: {error_total}",
        f"- Skipped rows: {skipped_total}",
        "",
        "## Pass/Fail by Operation",
        "",
        *status_lines,
        "",
        "## Common Skip Reasons",
        "",
        *skip_lines,
        "",
        "## Common Failure Categories",
        "",
        *category_lines,
        "",
        "## Worst Rows by Max Absolute Difference",
        "",
        *worst_abs_lines,
        "",
        "## Worst Rows by Max Relative Difference",
        "",
        *worst_rel_lines,
        "",
    ]

    Path(summary_md).parent.mkdir(parents=True, exist_ok=True)
    Path(summary_md).write_text("\n".join(lines) + "\n")


def _run_configuration_markdown_lines(config: RunConfig) -> list[str]:
    return [
        f"- target_frequency: `{config.target_frequency}`",
        f"- bins: `{','.join(config.bins)}`",
        f"- min_files: `{config.min_files}`",
        f"- max_files: `{config.max_files}`",
        f"- datasets_per_bin: `{config.datasets_per_bin}`",
        f"- fixed_timesteps: `{config.fixed_timesteps}`",
        f"- rtol: `{config.rtol}`",
        f"- atol: `{config.atol}`",
        f"- operations: `{','.join(config.operations)}`",
        f"- out_csv: `{config.out_csv}`",
        f"- resume_csv: `{config.resume_csv}`",
        f"- summary_md: `{config.summary_md}`",
        f"- resume_summary_md: `{config.resume_summary_md}`",
    ]


def _operation_configuration_markdown_lines(
    operations: tuple[str, ...],
) -> list[str]:
    lines: list[str] = []
    for operation in operations:
        lines.append(f"- {operation}: `{_json_dumps(_operation_config(operation))}`")
    return lines


def _log_final_results_summary(rows_by_key: dict[str, dict[str, Any]]) -> None:
    df = pd.DataFrame(rows_by_key.values())
    _ensure_schema_columns(df)

    total_rows = len(df)
    if total_rows == 0:
        logger.info("Final results summary: no rows recorded.")
        return

    passed_total = int(sum(_truthy(value) for value in df["all_checks_pass"].tolist()))
    error_total = int(sum(value == "error" for value in df["status"].tolist()))
    skipped_total = int(sum(value == "skipped" for value in df["status"].tolist()))
    failed_total = total_rows - passed_total - error_total - skipped_total

    lines = [
        "Final results summary:",
        f"  total_rows={total_rows}",
        f"  passed={passed_total}",
        f"  failed_checks={failed_total}",
        f"  errors={error_total}",
        f"  skipped={skipped_total}",
        "  per_operation:",
    ]

    for operation in OPERATIONS:
        subset = df[df["operation"] == operation]
        if subset.empty:
            continue
        op_passed = int(
            sum(
                _truthy(value)
                for value in subset.get("all_checks_pass", pd.Series(dtype=object)).tolist()
            )
        )
        op_errors = int(sum(value == "error" for value in subset["status"].tolist()))
        op_skipped = int(sum(value == "skipped" for value in subset["status"].tolist()))
        op_failed = int(len(subset) - op_passed - op_errors - op_skipped)
        lines.append(
            "    "
            f"{operation}: total={len(subset)}, passed={op_passed}, "
            f"failed_checks={op_failed}, errors={op_errors}, skipped={op_skipped}"
        )

    error_rows = df[df["status"] == "error"]
    if not error_rows.empty:
        lines.append("  error_details:")
        for _, row in error_rows.iterrows():
            lines.append(
                "    "
                f"{row['dataset_id']}::{row['operation']} | "
                f"error_type={row.get('error_type') or 'unknown'} | "
                f"message={_one_line_text(row.get('error_message'))}"
            )

    skipped_rows = df[df["status"] == "skipped"]
    if not skipped_rows.empty:
        lines.append("  skipped_details:")
        for _, row in skipped_rows.iterrows():
            lines.append(
                "    "
                f"{row['dataset_id']}::{row['operation']} | "
                f"reason={_one_line_text(row.get('skip_reason'))}"
            )

    logger.info("\n".join(lines))


def _worst_case_lines(df: pd.DataFrame, column: str) -> list[str]:
    subset = df[df["status"] == "ok"].copy()
    subset = subset[subset[column].notna()]
    lines = [
        "| operation | dataset_id | value |",
        "| --- | --- | ---: |",
    ]
    if subset.empty:
        lines.append("| none | - | - |")
        return lines

    subset[column] = pd.to_numeric(subset[column], errors="coerce")
    subset = subset.sort_values(column, ascending=False)
    for _, row in subset.head(10).iterrows():
        lines.append(
            f"| {row['operation']} | {row['dataset_id']} | {row[column]} |"
        )
    return lines


def _load_json_list(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _json_dumps(value: Any) -> str:
    return json.dumps(value, default=_json_default, sort_keys=True)


def _json_default(value: Any) -> Any:
    return _scalar_to_jsonable(value)


def _scalar_to_jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, float) and math.isnan(value):
            return None
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, xr.DataArray):
        return {
            "name": value.name,
            "dims": list(value.dims),
            "shape": list(value.shape),
            "dtype": str(value.dtype),
        }
    if isinstance(value, (list, tuple)):
        return [_scalar_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _scalar_to_jsonable(val) for key, val in value.items()}
    return str(value)


def _first_mismatch(left: np.ndarray, right: np.ndarray) -> dict[str, Any] | None:
    if left.shape != right.shape:
        return {
            "left_shape": list(left.shape),
            "right_shape": list(right.shape),
        }

    for index, (lval, rval) in enumerate(zip(left.flat, right.flat)):
        if lval != rval:
            return {
                "flat_index": index,
                "left": _scalar_to_jsonable(lval),
                "right": _scalar_to_jsonable(rval),
            }
    return None


def _first_numeric_mismatch(
    left: np.ndarray,
    right: np.ndarray,
    mismatch_mask: np.ndarray,
) -> dict[str, Any] | None:
    if left.shape != right.shape or mismatch_mask.shape != left.shape:
        return None

    mismatch_indices = np.argwhere(mismatch_mask)
    if mismatch_indices.size == 0:
        return None

    index_tuple = tuple(int(idx) for idx in mismatch_indices[0].tolist())
    return {
        "index": list(index_tuple),
        "left": _scalar_to_jsonable(left[index_tuple]),
        "right": _scalar_to_jsonable(right[index_tuple]),
    }


def _safe_close(ds: xr.Dataset | None) -> None:
    if ds is None:
        return
    try:
        ds.close()
    except Exception:
        pass


def close_opened_dataset_pair(opened_pair: dict[str, Any]) -> None:
    _safe_close(opened_pair.get("kerchunk_ds"))
    _safe_close(opened_pair.get("netcdf_ds"))


def _copy_jsonable_dict(value: dict[str, Any]) -> dict[str, Any]:
    copied = _scalar_to_jsonable(value)
    if isinstance(copied, dict):
        return copied
    return {}


def _is_numeric_dtype(dtype: np.dtype) -> bool:
    return np.issubdtype(dtype, np.number)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def _one_line_text(value: Any, limit: int = 240) -> str:
    if value is None:
        return "None"
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _infer_var_id(kerchunk_fn: str) -> str:
    parts = Path(kerchunk_fn).name.split(".")
    return parts[7] if len(parts) > 7 else "ta"


if __name__ == "__main__":
    main()
