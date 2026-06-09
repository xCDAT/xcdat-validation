"""Validate metadata and CF handling parity between kerchunk and NetCDF.

This script reuses the prepared-dataset selection model from the file-count
benchmark workflow, but replaces timing loops with a single backend-pair
validation pass per dataset.

Checks performed per dataset:
- dataset structure and dtype parity
- target-variable numeric parity within tolerance
- xCDAT CF axis resolution parity
- decoded time coordinate parity
- bounds metadata/value parity, plus ``add_missing_bounds()`` usability
- attribute preservation at dataset, variable, and axis-coordinate scopes

Ignored differences:
- provenance-only attribute drift for ``creation_date``, ``history``, and
  ``tracking_id``; these are recorded in diagnostics but do not fail
  ``attrs_match``
- symmetric xCDAT axis-resolution failures where both backends fail the same
  way and neither resolves an axis name; these are recorded but do not fail
  ``cf_axes_match``
- target-variable, axis-coordinate, and bounds-array comparison failures where
  the numeric values and NaN pattern are identical within tolerance and the
  only difference is extra non-dimension coordinate metadata (for example a
  scalar ``height`` coordinate attached on one backend); these are recorded but
  do not fail ``data_match`` or ``bounds_match``

Still treated as mismatches:
- CF-significant attribute differences such as ``standard_name``, ``long_name``,
  ``units``, ``axis``, ``calendar``, and ``bounds``
- real structure, dtype, decoded-time, axis-name, or bounds differences
- asymmetric axis-resolution failures or cases where only one backend resolves
  an axis

Outputs:
- checkpointed CSV with one terminal row per dataset
- compact markdown summary of pass/fail counts, common failure categories, and
  ignored-difference categories

Example usage:
    salloc --nodes 1 --qos interactive --constraint cpu --time 02:00:00 --account m4581
    conda activate xcdat_test_stable_min
    python riotai/results/20260605-metadata-cf-validation/validate_metadata_cf.py \
        --target-frequency Amon \
        --bins 25-49,50-99,100-149 \
        --datasets-per-bin 10 \
        --out-csv results.csv \
        --resume-csv results.csv
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gc
import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr
import xcdat as xc


RTOL = 1e-6
ATOL = 1e-8
AXIS_KEYS: tuple[str, ...] = ("T", "Y", "X", "Z")
ALLOWED_ATTR_KEYS: tuple[str, ...] = (
    "standard_name",
    "long_name",
    "units",
    "axis",
    "calendar",
    "bounds",
)
IGNORED_PROVENANCE_ATTR_KEYS: tuple[str, ...] = (
    "creation_date",
    "history",
    "tracking_id",
)
SKIPPED_DATASET_REASONS: dict[str, str] = {
    (
        "CMIP6.CMIP.MOHC.HadGEM3-GC31-MM.piControl.r1i1p1f1."
        "Amon.ta.gn.v20190920"
    ): "Known to stall during data check; skipped intentionally.",
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
ROOT_DIR = Path(__file__).resolve().parent
JSON_TO_NETCDF_MAPS_DIR = Path(__file__).resolve().parents[2] / "json_to_netcdf_maps"
DEFAULT_TARGET_FREQUENCY = "Amon"
_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
DEFAULT_OUT_CSV = str(ROOT_DIR / f"{_TS}_metadata_cf_validation.csv")
DEFAULT_SUMMARY_MD = str(ROOT_DIR / f"{_TS}_summary.md")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("metadata_cf_validation")
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
    out_csv: str
    resume_csv: str | None
    summary_md: str


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


def _parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Validate metadata, CF axis resolution, decoded time handling, "
            "bounds, and data parity between kerchunk and NetCDF backends."
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
            "Existing CSV to resume from. Rows with matching dataset_id values "
            "are skipped."
        ),
    )
    parser.add_argument(
        "--summary-md",
        type=str,
        default=DEFAULT_SUMMARY_MD,
        help="Markdown summary output path.",
    )

    args = parser.parse_args()

    if args.min_files is not None and args.max_files is not None:
        if args.min_files > args.max_files:
            parser.error("--min-files cannot be greater than --max-files")

    if args.datasets_per_bin is not None and args.datasets_per_bin < 1:
        parser.error("--datasets-per-bin must be >= 1")

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
        target_frequency=args.target_frequency,
        bins=bins,
        min_files=args.min_files,
        max_files=args.max_files,
        datasets_per_bin=args.datasets_per_bin,
        out_csv=_resolve_script_relative_path(args.out_csv),
        resume_csv=_resolve_script_relative_path(args.resume_csv),
        summary_md=_resolve_script_relative_path(args.summary_md),
    )


def main() -> None:
    config = _parse_args()
    prepared_datasets_csv = _prepared_datasets_csv_path(config.target_frequency)

    logger.info("Starting metadata/CF validation run")
    logger.info(
        "Run config | target_frequency=%s | bins=%s | min_files=%s | max_files=%s | "
        "datasets_per_bin=%s | prepared_datasets_csv=%s | out_csv=%s | summary_md=%s",
        config.target_frequency,
        ",".join(config.bins),
        config.min_files,
        config.max_files,
        config.datasets_per_bin,
        prepared_datasets_csv,
        config.out_csv,
        config.summary_md,
    )

    rows_by_dataset_id = _load_resume_rows(config.resume_csv)
    if rows_by_dataset_id:
        logger.info(
            "Loaded %d rows from resume CSV: %s",
            len(rows_by_dataset_id),
            config.resume_csv,
        )

    prepared_datasets = load_prepared_datasets_csv(prepared_datasets_csv)
    selected_datasets = _filter_prepared_datasets(prepared_datasets, config)
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
            "[%d/%d] dataset=%s | bin=%s | rank=%d | nfiles=%d | var=%s",
            i,
            len(selected_datasets),
            spec.dataset_id,
            dataset.nfiles_bin,
            dataset.bin_selected_rank,
            dataset.nfiles,
            spec.var_id,
        )

        row = _make_base_row(dataset, config.target_frequency)
        if spec.dataset_id in SKIPPED_DATASET_REASONS:
            skip_reason = SKIPPED_DATASET_REASONS[spec.dataset_id]
            logger.warning(
                "[%d/%d] dataset=%s | skipping validation | reason=%s",
                i,
                len(selected_datasets),
                spec.dataset_id,
                skip_reason,
            )
            row.update(_skip_result(skip_reason))
            rows_by_dataset_id[spec.dataset_id] = row
            _save_checkpoint(rows_by_dataset_id, config.out_csv)
            _write_summary_markdown(rows_by_dataset_id, config.summary_md)
            gc.collect()
            continue

        try:
            row.update(
                validate_dataset_pair(
                    kerchunk_file=spec.kerchunk_file,
                    netcdf_files=list(dataset.netcdf_files),
                    var_id=spec.var_id,
                    dataset_label=spec.dataset_id,
                )
            )
        except Exception as exc:
            logger.exception("Unexpected failure for dataset %s", spec.dataset_id)
            row.update(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "failure_categories_json": _json_dumps(["unexpected_validation_error"]),
                    "primary_failure_category": "unexpected_validation_error",
                }
            )

        rows_by_dataset_id[spec.dataset_id] = row
        _save_checkpoint(rows_by_dataset_id, config.out_csv)
        _write_summary_markdown(rows_by_dataset_id, config.summary_md)
        gc.collect()

    logger.info("Validation run complete")
    _write_summary_markdown(rows_by_dataset_id, config.summary_md)
    logger.info("Results written to %s", config.out_csv)
    logger.info("Summary written to %s", config.summary_md)


def _make_base_row(dataset: PreparedDataset, frequency: str) -> dict[str, Any]:
    spec = dataset.spec
    return {
        "dataset_id": spec.dataset_id,
        "data_dir": spec.data_dir,
        "kerchunk_file": spec.kerchunk_file,
        "frequency": frequency,
        "var_id": spec.var_id,
        "netcdf_file_count": dataset.nfiles,
        "nfiles_bin": dataset.nfiles_bin,
        "bin_selected_rank": dataset.bin_selected_rank,
        "status": "pending",
        "error_type": None,
        "error_message": None,
        "structure_match": None,
        "data_match": None,
        "cf_axes_match": None,
        "time_decode_match": None,
        "bounds_match": None,
        "attrs_match": None,
        "all_checks_pass": None,
        "axis_T_kerchunk": None,
        "axis_T_netcdf": None,
        "axis_Y_kerchunk": None,
        "axis_Y_netcdf": None,
        "axis_X_kerchunk": None,
        "axis_X_netcdf": None,
        "axis_Z_kerchunk": None,
        "axis_Z_netcdf": None,
        "max_abs_diff_target": None,
        "max_rel_diff_target": None,
        "target_nan_mismatch_count": None,
        "mismatched_dims_json": None,
        "mismatched_coordinate_names_json": None,
        "missing_bounds_vars_json": None,
        "missing_attrs_json": None,
        "attr_mismatch_keys_json": None,
        "failure_categories_json": None,
        "primary_failure_category": None,
        "diagnostics_json": None,
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
    rows_by_dataset_id: dict[str, dict[str, Any]],
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

    if "dataset_id" not in df.columns:
        logger.warning("Resume CSV missing dataset_id column: %s", path)
        return {}

    rows_by_dataset_id: dict[str, dict[str, Any]] = {}
    for _, series in df.iterrows():
        dataset_id = series.get("dataset_id")
        if pd.isna(dataset_id):
            continue
        rows_by_dataset_id[str(dataset_id)] = series.to_dict()

    return rows_by_dataset_id


def _save_checkpoint(rows_by_dataset_id: dict[str, dict[str, Any]], out_csv: str) -> None:
    df = pd.DataFrame(rows_by_dataset_id.values())
    _ensure_schema_columns(df)
    if not df.empty and {"netcdf_file_count", "dataset_id"}.issubset(df.columns):
        df = df.sort_values(["netcdf_file_count", "dataset_id"], na_position="last")
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)


def _ensure_schema_columns(df: pd.DataFrame) -> None:
    expected_cols = [
        "dataset_id",
        "data_dir",
        "kerchunk_file",
        "frequency",
        "var_id",
        "netcdf_file_count",
        "nfiles_bin",
        "bin_selected_rank",
        "status",
        "error_type",
        "error_message",
        "structure_match",
        "data_match",
        "cf_axes_match",
        "time_decode_match",
        "bounds_match",
        "attrs_match",
        "all_checks_pass",
        "axis_T_kerchunk",
        "axis_T_netcdf",
        "axis_Y_kerchunk",
        "axis_Y_netcdf",
        "axis_X_kerchunk",
        "axis_X_netcdf",
        "axis_Z_kerchunk",
        "axis_Z_netcdf",
        "max_abs_diff_target",
        "max_rel_diff_target",
        "target_nan_mismatch_count",
        "mismatched_dims_json",
        "mismatched_coordinate_names_json",
        "missing_bounds_vars_json",
        "missing_attrs_json",
        "attr_mismatch_keys_json",
        "failure_categories_json",
        "primary_failure_category",
        "diagnostics_json",
    ]

    for col in expected_cols:
        if col not in df.columns:
            df[col] = pd.NA


def validate_dataset_pair(
    kerchunk_file: str,
    netcdf_files: list[str],
    var_id: str,
    dataset_label: str | None = None,
) -> dict[str, Any]:
    log_prefix = f"[{dataset_label}] " if dataset_label else ""
    diagnostics: dict[str, Any] = {
        "kerchunk_file_exists": os.path.exists(kerchunk_file),
        "netcdf_file_count_resolved": len(netcdf_files),
        "missing_netcdf_files": [path for path in netcdf_files if not os.path.exists(path)],
    }

    logger.info(
        "%svalidation start | var=%s | netcdf_files=%d",
        log_prefix,
        var_id,
        len(netcdf_files),
    )

    if not diagnostics["kerchunk_file_exists"]:
        logger.warning("%skerchunk reference file missing: %s", log_prefix, kerchunk_file)
        return _error_result(
            "kerchunk_file_missing",
            f"Kerchunk reference file does not exist: {kerchunk_file}",
            diagnostics,
        )

    if diagnostics["missing_netcdf_files"]:
        logger.warning(
            "%smissing %d NetCDF files before open",
            log_prefix,
            len(diagnostics["missing_netcdf_files"]),
        )
        return _error_result(
            "netcdf_file_missing",
            f"One or more NetCDF files do not exist ({len(diagnostics['missing_netcdf_files'])} missing)",
            diagnostics,
        )

    kerchunk_ds = None
    netcdf_ds = None
    logger.info("%sopening kerchunk dataset", log_prefix)
    try:
        kerchunk_ds = _open_kerchunk_dataset(kerchunk_file)
        logger.info("%skerchunk open complete", log_prefix)
    except Exception as exc:
        diagnostics["kerchunk_open_error"] = f"{type(exc).__name__}: {exc}"
        logger.warning("%skerchunk open failed: %s", log_prefix, diagnostics["kerchunk_open_error"])
        return _error_result("kerchunk_open_failed", str(exc), diagnostics)

    logger.info("%sopening NetCDF dataset", log_prefix)
    try:
        netcdf_ds = _open_netcdf_dataset(netcdf_files)
        logger.info("%sNetCDF open complete", log_prefix)
    except Exception as exc:
        diagnostics["netcdf_open_error"] = f"{type(exc).__name__}: {exc}"
        logger.warning("%sNetCDF open failed: %s", log_prefix, diagnostics["netcdf_open_error"])
        return _error_result("netcdf_open_failed", str(exc), diagnostics)

    try:
        logger.info("%srunning check: cf_axes", log_prefix)
        axis_result = _compare_cf_axes(kerchunk_ds, netcdf_ds)
        _log_validation_check_result(log_prefix, "cf_axes", axis_result)

        logger.info("%srunning check: structure", log_prefix)
        structure_result = _compare_structure(kerchunk_ds, netcdf_ds, var_id, axis_result)
        _log_validation_check_result(log_prefix, "structure", structure_result)

        logger.info("%srunning check: data", log_prefix)
        data_result = _compare_data_contents(
            kerchunk_ds,
            netcdf_ds,
            var_id,
            axis_result,
            rtol=RTOL,
            atol=ATOL,
        )
        _log_validation_check_result(log_prefix, "data", data_result)

        logger.info("%srunning check: time_decode", log_prefix)
        time_result = _compare_time_decoding(kerchunk_ds, netcdf_ds, axis_result)
        _log_validation_check_result(log_prefix, "time_decode", time_result)

        logger.info("%srunning check: bounds", log_prefix)
        bounds_result = _compare_bounds(kerchunk_ds, netcdf_ds, axis_result)
        _log_validation_check_result(log_prefix, "bounds", bounds_result)

        logger.info("%srunning check: attrs", log_prefix)
        attrs_result = _compare_attrs(kerchunk_ds, netcdf_ds, var_id, axis_result)
        _log_validation_check_result(log_prefix, "attrs", attrs_result)

        diagnostics.update(
            {
                "structure": structure_result["diagnostics"],
                "data": data_result["diagnostics"],
                "cf_axes": axis_result["diagnostics"],
                "time_decode": time_result["diagnostics"],
                "bounds": bounds_result["diagnostics"],
                "attrs": attrs_result["diagnostics"],
            }
        )

        all_checks_pass = all(
            [
                structure_result["match"],
                data_result["match"],
                axis_result["match"],
                time_result["match"],
                bounds_result["match"],
                attrs_result["match"],
            ]
        )
        categories = _derive_failure_categories(
            structure_match=structure_result["match"],
            data_match=data_result["match"],
            cf_axes_match=axis_result["match"],
            time_decode_match=time_result["match"],
            bounds_match=bounds_result["match"],
            attrs_match=attrs_result["match"],
            status="ok",
        )
        logger.info(
            "%svalidation complete | all_checks_pass=%s | categories=%s",
            log_prefix,
            all_checks_pass,
            ",".join(categories) if categories else "none",
        )

        return {
            "status": "ok",
            "error_type": None,
            "error_message": None,
            "structure_match": structure_result["match"],
            "data_match": data_result["match"],
            "cf_axes_match": axis_result["match"],
            "time_decode_match": time_result["match"],
            "bounds_match": bounds_result["match"],
            "attrs_match": attrs_result["match"],
            "all_checks_pass": all_checks_pass,
            "axis_T_kerchunk": axis_result["resolved_names"]["T"]["kerchunk"],
            "axis_T_netcdf": axis_result["resolved_names"]["T"]["netcdf"],
            "axis_Y_kerchunk": axis_result["resolved_names"]["Y"]["kerchunk"],
            "axis_Y_netcdf": axis_result["resolved_names"]["Y"]["netcdf"],
            "axis_X_kerchunk": axis_result["resolved_names"]["X"]["kerchunk"],
            "axis_X_netcdf": axis_result["resolved_names"]["X"]["netcdf"],
            "axis_Z_kerchunk": axis_result["resolved_names"]["Z"]["kerchunk"],
            "axis_Z_netcdf": axis_result["resolved_names"]["Z"]["netcdf"],
            "max_abs_diff_target": data_result["max_abs_diff_target"],
            "max_rel_diff_target": data_result["max_rel_diff_target"],
            "target_nan_mismatch_count": data_result["target_nan_mismatch_count"],
            "mismatched_dims_json": _json_dumps(structure_result["diagnostics"]["dim_mismatches"]),
            "mismatched_coordinate_names_json": _json_dumps(
                structure_result["diagnostics"]["coordinate_name_mismatches"]
            ),
            "missing_bounds_vars_json": _json_dumps(bounds_result["diagnostics"]["missing_bounds_vars"]),
            "missing_attrs_json": _json_dumps(attrs_result["diagnostics"]["missing_allowed_attrs"]),
            "attr_mismatch_keys_json": _json_dumps(
                attrs_result["diagnostics"]["allowed_attr_mismatch_keys"]
            ),
            "failure_categories_json": _json_dumps(categories),
            "primary_failure_category": categories[0] if categories else None,
            "diagnostics_json": _json_dumps(diagnostics),
        }
    finally:
        _safe_close(kerchunk_ds)
        _safe_close(netcdf_ds)


def _error_result(
    error_type: str,
    error_message: str,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    categories = _derive_failure_categories(
        structure_match=None,
        data_match=None,
        cf_axes_match=None,
        time_decode_match=None,
        bounds_match=None,
        attrs_match=None,
        status="error",
        error_type=error_type,
    )
    return {
        "status": "error",
        "error_type": error_type,
        "error_message": error_message,
        "failure_categories_json": _json_dumps(categories),
        "primary_failure_category": categories[0] if categories else error_type,
        "diagnostics_json": _json_dumps(diagnostics),
    }


def _skip_result(reason: str) -> dict[str, Any]:
    return {
        "status": "skipped",
        "error_type": "skipped_dataset",
        "error_message": reason,
        "failure_categories_json": _json_dumps(["skipped_dataset"]),
        "primary_failure_category": "skipped_dataset",
        "diagnostics_json": _json_dumps({"skip_reason": reason}),
    }


def _open_kerchunk_dataset(kerchunk_file: str) -> xr.Dataset:
    with xr.set_options(file_cache_maxsize=1):
        return xc.open_dataset(kerchunk_file, engine="kerchunk", chunks={})


def _open_netcdf_dataset(netcdf_files: list[str]) -> xr.Dataset:
    with xr.set_options(file_cache_maxsize=1):
        return xc.open_mfdataset(netcdf_files, chunks={}, join="exact")


def _log_validation_check_result(
    log_prefix: str,
    check_name: str,
    result: dict[str, Any],
) -> None:
    diagnostics = result.get("diagnostics", {})
    parts = [f"match={result.get('match')}"]

    reasons = diagnostics.get("reasons")
    if isinstance(reasons, list) and reasons:
        parts.append(f"reasons={len(reasons)}")

    if check_name == "cf_axes":
        axis_errors = diagnostics.get("axis_resolution_errors", {})
        ignored_axis_errors = diagnostics.get("ignored_symmetric_axis_resolution_errors", {})
        mismatches = diagnostics.get("axis_mismatch_reasons", [])
        if axis_errors:
            parts.append(f"axis_errors={len(axis_errors)}")
        if ignored_axis_errors:
            parts.append(f"ignored_axis_errors={len(ignored_axis_errors)}")
        if mismatches:
            parts.append(f"axis_name_mismatches={len(mismatches)}")
    elif check_name == "data":
        if result.get("max_abs_diff_target") is not None:
            parts.append(f"max_abs_diff_target={result['max_abs_diff_target']}")
        if result.get("target_nan_mismatch_count") is not None:
            parts.append(
                f"target_nan_mismatch_count={result['target_nan_mismatch_count']}"
            )
        ignored_data = 0
        if isinstance(diagnostics.get("target_variable"), dict) and diagnostics[
            "target_variable"
        ].get("ignored_reason"):
            ignored_data += 1
        ignored_data += sum(
            1
            for payload in diagnostics.get("coord_value_mismatches", {}).values()
            if isinstance(payload, dict) and payload.get("ignored_reason")
        )
        if ignored_data:
            parts.append(f"ignored_coord_diffs={ignored_data}")
    elif check_name == "bounds":
        missing_bounds = diagnostics.get("missing_bounds_vars", [])
        if missing_bounds:
            parts.append(f"missing_bounds_vars={len(missing_bounds)}")
        ignored_bounds = sum(
            len(payload)
            for payload in diagnostics.get("ignored_bounds_value_details", {}).values()
            if isinstance(payload, dict)
        )
        if ignored_bounds:
            parts.append(f"ignored_bounds_diffs={ignored_bounds}")
    elif check_name == "attrs":
        full_mismatches = diagnostics.get("full_attr_mismatches", {})
        ignored_mismatches = diagnostics.get("ignored_provenance_attr_mismatches", {})
        if full_mismatches:
            parts.append(f"attr_scopes_with_mismatches={len(full_mismatches)}")
        if ignored_mismatches:
            parts.append(
                f"ignored_provenance_attr_scopes={len(ignored_mismatches)}"
            )

    logger.info("%scheck result | %s | %s", log_prefix, check_name, " | ".join(parts))


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


def _compare_structure(
    ds_k: xr.Dataset,
    ds_n: xr.Dataset,
    var_id: str,
    axis_result: dict[str, Any],
) -> dict[str, Any]:
    data_vars_k = set(ds_k.data_vars)
    data_vars_n = set(ds_n.data_vars)
    coords_k = set(ds_k.coords)
    coords_n = set(ds_n.coords)

    missing_data_vars_in_kerchunk = sorted(data_vars_n - data_vars_k)
    extra_data_vars_in_kerchunk = sorted(data_vars_k - data_vars_n)
    missing_coords_in_kerchunk = sorted(coords_n - coords_k)
    extra_coords_in_kerchunk = sorted(coords_k - coords_n)

    dim_mismatches: dict[str, dict[str, int | None]] = {}
    for dim_name in sorted(set(ds_k.sizes) | set(ds_n.sizes)):
        size_k = ds_k.sizes.get(dim_name)
        size_n = ds_n.sizes.get(dim_name)
        if size_k != size_n:
            dim_mismatches[dim_name] = {"kerchunk": size_k, "netcdf": size_n}

    dtype_mismatches: dict[str, dict[str, str | None]] = {}
    if var_id in ds_k.variables or var_id in ds_n.variables:
        dtype_k = _dtype_or_none(ds_k.variables.get(var_id))
        dtype_n = _dtype_or_none(ds_n.variables.get(var_id))
        if dtype_k != dtype_n:
            dtype_mismatches[var_id] = {"kerchunk": dtype_k, "netcdf": dtype_n}

    for axis_key in AXIS_KEYS:
        k_name = axis_result["resolved_names"][axis_key]["kerchunk"]
        n_name = axis_result["resolved_names"][axis_key]["netcdf"]
        if k_name is None and n_name is None:
            continue
        dtype_k = _dtype_or_none(ds_k.coords.get(k_name)) if k_name else None
        dtype_n = _dtype_or_none(ds_n.coords.get(n_name)) if n_name else None
        if dtype_k != dtype_n:
            dtype_mismatches[f"{axis_key}_coord"] = {
                "kerchunk": dtype_k,
                "netcdf": dtype_n,
            }

    reasons: list[str] = []
    if var_id not in ds_k.variables:
        reasons.append(f"missing variable in kerchunk: {var_id}")
    if var_id not in ds_n.variables:
        reasons.append(f"missing variable in netcdf: {var_id}")
    reasons.extend(f"missing data variable in kerchunk: {name}" for name in missing_data_vars_in_kerchunk)
    reasons.extend(f"extra data variable in kerchunk: {name}" for name in extra_data_vars_in_kerchunk)
    reasons.extend(f"missing coordinate in kerchunk: {name}" for name in missing_coords_in_kerchunk)
    reasons.extend(f"extra coordinate in kerchunk: {name}" for name in extra_coords_in_kerchunk)
    reasons.extend(
        f"dimension size mismatch: {name} ({payload['kerchunk']} vs {payload['netcdf']})"
        for name, payload in dim_mismatches.items()
    )
    reasons.extend(
        f"dtype mismatch: {name} ({payload['kerchunk']} vs {payload['netcdf']})"
        for name, payload in dtype_mismatches.items()
    )

    diagnostics = {
        "missing_data_vars_in_kerchunk": missing_data_vars_in_kerchunk,
        "extra_data_vars_in_kerchunk": extra_data_vars_in_kerchunk,
        "missing_coords_in_kerchunk": missing_coords_in_kerchunk,
        "extra_coords_in_kerchunk": extra_coords_in_kerchunk,
        "coordinate_name_mismatches": {
            "missing_in_kerchunk": missing_coords_in_kerchunk,
            "extra_in_kerchunk": extra_coords_in_kerchunk,
        },
        "dim_mismatches": dim_mismatches,
        "dtype_mismatches": dtype_mismatches,
        "reasons": reasons,
    }
    return {"match": not reasons, "diagnostics": diagnostics}


def _compare_data_contents(
    ds_k: xr.Dataset,
    ds_n: xr.Dataset,
    var_id: str,
    axis_result: dict[str, Any],
    rtol: float,
    atol: float,
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "target_variable": {},
        "coord_value_mismatches": {},
        "reasons": [],
    }

    max_abs_diff_target = None
    max_rel_diff_target = None
    target_nan_mismatch_count = None
    match = True

    if var_id not in ds_k.variables or var_id not in ds_n.variables:
        diagnostics["reasons"].append(f"target variable missing for comparison: {var_id}")
        return {
            "match": False,
            "diagnostics": diagnostics,
            "max_abs_diff_target": max_abs_diff_target,
            "max_rel_diff_target": max_rel_diff_target,
            "target_nan_mismatch_count": target_nan_mismatch_count,
        }

    target_cmp = _compare_dataarrays(
        ds_k[var_id],
        ds_n[var_id],
        rtol=rtol,
        atol=atol,
        ignore_non_dim_coord_mismatches_when_values_equal=True,
    )
    diagnostics["target_variable"] = target_cmp["diagnostics"]
    max_abs_diff_target = target_cmp["max_abs_diff"]
    max_rel_diff_target = target_cmp["max_rel_diff"]
    target_nan_mismatch_count = target_cmp["nan_mismatch_count"]
    if not target_cmp["match"]:
        match = False
        diagnostics["reasons"].append("target variable values differ")

    for axis_key in ("Y", "X", "Z"):
        k_name = axis_result["resolved_names"][axis_key]["kerchunk"]
        n_name = axis_result["resolved_names"][axis_key]["netcdf"]
        if k_name is None and n_name is None:
            continue
        if not k_name or not n_name or k_name not in ds_k.coords or n_name not in ds_n.coords:
            match = False
            diagnostics["coord_value_mismatches"][axis_key] = {
                "kerchunk_coord": k_name,
                "netcdf_coord": n_name,
                "reason": "coordinate missing on one backend",
            }
            diagnostics["reasons"].append(f"{axis_key} coordinate missing on one backend")
            continue

        coord_cmp = _compare_dataarrays(
            ds_k.coords[k_name],
            ds_n.coords[n_name],
            rtol=rtol,
            atol=atol,
            ignore_non_dim_coord_mismatches_when_values_equal=True,
        )
        diagnostics["coord_value_mismatches"][axis_key] = coord_cmp["diagnostics"]
        if not coord_cmp["match"]:
            match = False
            diagnostics["reasons"].append(f"{axis_key} coordinate values differ")

    return {
        "match": match,
        "diagnostics": diagnostics,
        "max_abs_diff_target": max_abs_diff_target,
        "max_rel_diff_target": max_rel_diff_target,
        "target_nan_mismatch_count": target_nan_mismatch_count,
    }


def _compare_time_decoding(
    ds_k: xr.Dataset,
    ds_n: xr.Dataset,
    axis_result: dict[str, Any],
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {}

    k_name = axis_result["resolved_names"]["T"]["kerchunk"] or ("time" if "time" in ds_k.coords else None)
    n_name = axis_result["resolved_names"]["T"]["netcdf"] or ("time" if "time" in ds_n.coords else None)
    diagnostics["time_coord_name_kerchunk"] = k_name
    diagnostics["time_coord_name_netcdf"] = n_name

    if not k_name or not n_name or k_name not in ds_k.coords or n_name not in ds_n.coords:
        diagnostics["reason"] = "time coordinate missing on one backend"
        return {"match": False, "diagnostics": diagnostics}

    time_k = ds_k.coords[k_name].load()
    time_n = ds_n.coords[n_name].load()

    diagnostics["decoded_time_dtype_kerchunk"] = str(time_k.dtype)
    diagnostics["decoded_time_dtype_netcdf"] = str(time_n.dtype)
    diagnostics["decoded_time_class_kerchunk"] = _first_value_class_name(time_k)
    diagnostics["decoded_time_class_netcdf"] = _first_value_class_name(time_n)
    diagnostics["calendar_kerchunk"] = time_k.attrs.get("calendar")
    diagnostics["calendar_netcdf"] = time_n.attrs.get("calendar")
    diagnostics["units_kerchunk"] = time_k.attrs.get("units")
    diagnostics["units_netcdf"] = time_n.attrs.get("units")
    diagnostics["length_kerchunk"] = int(time_k.size)
    diagnostics["length_netcdf"] = int(time_n.size)
    diagnostics["first_value_kerchunk"] = _scalar_to_jsonable(time_k.values[0] if time_k.size else None)
    diagnostics["first_value_netcdf"] = _scalar_to_jsonable(time_n.values[0] if time_n.size else None)
    diagnostics["last_value_kerchunk"] = _scalar_to_jsonable(time_k.values[-1] if time_k.size else None)
    diagnostics["last_value_netcdf"] = _scalar_to_jsonable(time_n.values[-1] if time_n.size else None)

    match = True
    if diagnostics["decoded_time_dtype_kerchunk"] != diagnostics["decoded_time_dtype_netcdf"]:
        match = False
    if diagnostics["decoded_time_class_kerchunk"] != diagnostics["decoded_time_class_netcdf"]:
        match = False
    if diagnostics["calendar_kerchunk"] != diagnostics["calendar_netcdf"]:
        match = False
    if diagnostics["units_kerchunk"] != diagnostics["units_netcdf"]:
        match = False
    if diagnostics["length_kerchunk"] != diagnostics["length_netcdf"]:
        match = False

    value_cmp = _compare_dataarrays(time_k, time_n, rtol=0.0, atol=0.0)
    diagnostics["value_comparison"] = value_cmp["diagnostics"]
    if not value_cmp["match"]:
        match = False

    return {"match": match, "diagnostics": diagnostics}


def _compare_bounds(
    ds_k: xr.Dataset,
    ds_n: xr.Dataset,
    axis_result: dict[str, Any],
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "existing_bounds": {},
        "generated_bounds": {},
        "bounds_value_mismatch_details": {},
        "ignored_bounds_value_details": {},
        "missing_bounds_vars": [],
        "reasons": [],
    }
    match = True

    existing_k, existing_arrays_k = _collect_bounds_state(ds_k, axis_result)
    existing_n, existing_arrays_n = _collect_bounds_state(ds_n, axis_result)
    diagnostics["existing_bounds"] = {
        "kerchunk": existing_k,
        "netcdf": existing_n,
    }

    for axis_key in AXIS_KEYS:
        axis_match = _compare_bounds_axis(
            axis_key,
            existing_k.get(axis_key, {}),
            existing_n.get(axis_key, {}),
            existing_arrays_k.get(axis_key),
            existing_arrays_n.get(axis_key),
            diagnostics,
        )
        match = match and axis_match

    generated_k = ds_k.bounds.add_missing_bounds()
    generated_n = ds_n.bounds.add_missing_bounds()
    try:
        generated_state_k, generated_arrays_k = _collect_bounds_state(generated_k, axis_result)
        generated_state_n, generated_arrays_n = _collect_bounds_state(generated_n, axis_result)
        diagnostics["generated_bounds"] = {
            "kerchunk": generated_state_k,
            "netcdf": generated_state_n,
        }
        for axis_key in AXIS_KEYS:
            axis_match = _compare_bounds_axis(
                axis_key,
                generated_state_k.get(axis_key, {}),
                generated_state_n.get(axis_key, {}),
                generated_arrays_k.get(axis_key),
                generated_arrays_n.get(axis_key),
                diagnostics,
                generated=True,
            )
            match = match and axis_match
    finally:
        _safe_close(generated_k)
        _safe_close(generated_n)

    return {"match": match, "diagnostics": diagnostics}


def _compare_bounds_axis(
    axis_key: str,
    state_k: dict[str, Any],
    state_n: dict[str, Any],
    array_k: xr.DataArray | None,
    array_n: xr.DataArray | None,
    diagnostics: dict[str, Any],
    *,
    generated: bool = False,
) -> bool:
    match = True
    label = "generated" if generated else "existing"

    attr_k = state_k.get("bounds_attr")
    attr_n = state_n.get("bounds_attr")
    if attr_k != attr_n:
        match = False
        diagnostics["reasons"].append(f"{label} bounds attr mismatch on {axis_key}")

    exists_k = bool(state_k.get("bounds_var_exists"))
    exists_n = bool(state_n.get("bounds_var_exists"))
    if exists_k != exists_n:
        match = False
        diagnostics["missing_bounds_vars"].append(
            {
                "axis": axis_key,
                "stage": label,
                "kerchunk": state_k.get("bounds_var_name"),
                "netcdf": state_n.get("bounds_var_name"),
            }
        )
        diagnostics["reasons"].append(f"{label} bounds variable missing on one backend for {axis_key}")

    if not exists_k and not exists_n:
        return match

    if state_k.get("bounds_dims") != state_n.get("bounds_dims"):
        match = False
        diagnostics["reasons"].append(f"{label} bounds dims mismatch on {axis_key}")
    if state_k.get("bounds_dtype") != state_n.get("bounds_dtype"):
        match = False
        diagnostics["reasons"].append(f"{label} bounds dtype mismatch on {axis_key}")

    if array_k is None or array_n is None:
        return False

    cmp_result = _compare_dataarrays(
        array_k,
        array_n,
        rtol=RTOL,
        atol=ATOL,
        ignore_non_dim_coord_mismatches_when_values_equal=True,
    )
    cmp_diagnostics = cmp_result["diagnostics"]
    if cmp_result["match"] and "ignored_reason" in cmp_diagnostics:
        diagnostics.setdefault("ignored_bounds_value_details", {}).setdefault(
            label, {}
        )[axis_key] = cmp_diagnostics
    if not cmp_result["match"]:
        match = False
        diagnostics.setdefault("bounds_value_mismatch_details", {}).setdefault(
            label, {}
        )[axis_key] = cmp_diagnostics
        diagnostics["reasons"].append(f"{label} bounds values differ on {axis_key}")

    return match


def _collect_bounds_state(
    ds: xr.Dataset,
    axis_result: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, xr.DataArray | None]]:
    state: dict[str, dict[str, Any]] = {}
    arrays: dict[str, xr.DataArray | None] = {}

    for axis_key in AXIS_KEYS:
        coord_name = (
            axis_result["resolved_names"][axis_key]["kerchunk"]
            if coord_name_in_dataset(
                ds, axis_result["resolved_names"][axis_key]["kerchunk"]
            )
            else axis_result["resolved_names"][axis_key]["netcdf"]
        )
        if coord_name is None or coord_name not in ds.coords:
            state[axis_key] = {
                "coord_name": coord_name,
                "bounds_attr": None,
                "bounds_var_name": None,
                "bounds_var_exists": False,
                "bounds_dims": None,
                "bounds_dtype": None,
            }
            arrays[axis_key] = None
            continue

        coord = ds.coords[coord_name]
        bounds_name = coord.attrs.get("bounds")
        bounds_var_exists = bool(bounds_name and bounds_name in ds.variables)
        bounds_dims = None
        bounds_dtype = None
        bounds_array = None
        if bounds_var_exists:
            bounds_array = ds[bounds_name].load()
            bounds_dims = list(bounds_array.dims)
            bounds_dtype = str(bounds_array.dtype)

        state[axis_key] = {
            "coord_name": coord_name,
            "bounds_attr": bounds_name,
            "bounds_var_name": bounds_name,
            "bounds_var_exists": bounds_var_exists,
            "bounds_dims": bounds_dims,
            "bounds_dtype": bounds_dtype,
        }
        arrays[axis_key] = bounds_array

    return state, arrays


def coord_name_in_dataset(ds: xr.Dataset, coord_name: str | None) -> bool:
    return bool(coord_name and coord_name in ds.coords)


def _compare_attrs(
    ds_k: xr.Dataset,
    ds_n: xr.Dataset,
    var_id: str,
    axis_result: dict[str, Any],
) -> dict[str, Any]:
    full_mismatches: dict[str, Any] = {}
    ignored_mismatches: dict[str, Any] = {}
    allowed_attr_mismatch_keys: list[str] = []
    missing_allowed_attrs: list[str] = []

    scopes: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
        ("dataset", ds_k.attrs, ds_n.attrs),
    ]

    if var_id in ds_k.variables or var_id in ds_n.variables:
        scopes.append(
            (
                f"variable:{var_id}",
                ds_k[var_id].attrs if var_id in ds_k.variables else {},
                ds_n[var_id].attrs if var_id in ds_n.variables else {},
            )
        )

    for axis_key in AXIS_KEYS:
        k_name = axis_result["resolved_names"][axis_key]["kerchunk"]
        n_name = axis_result["resolved_names"][axis_key]["netcdf"]
        scopes.append(
            (
                f"axis:{axis_key}",
                ds_k.coords[k_name].attrs if k_name and k_name in ds_k.coords else {},
                ds_n.coords[n_name].attrs if n_name and n_name in ds_n.coords else {},
            )
        )

    for scope_name, attrs_k, attrs_n in scopes:
        scope_payload: dict[str, Any] = {}
        ignored_scope_payload: dict[str, Any] = {}
        all_keys = sorted(set(attrs_k) | set(attrs_n))
        for key in all_keys:
            value_k = attrs_k.get(key)
            value_n = attrs_n.get(key)
            if _jsonable_equal(value_k, value_n):
                continue

            mismatch_payload = {
                "kerchunk": _scalar_to_jsonable(value_k),
                "netcdf": _scalar_to_jsonable(value_n),
            }

            if key in IGNORED_PROVENANCE_ATTR_KEYS:
                ignored_scope_payload[key] = mismatch_payload
                continue

            scope_payload[key] = mismatch_payload

            if key in ALLOWED_ATTR_KEYS:
                allowed_attr_mismatch_keys.append(f"{scope_name}:{key}")
                if key not in attrs_k or key not in attrs_n:
                    missing_allowed_attrs.append(f"{scope_name}:{key}")

        if scope_payload:
            full_mismatches[scope_name] = scope_payload
        if ignored_scope_payload:
            ignored_mismatches[scope_name] = ignored_scope_payload

    diagnostics = {
        "allowed_attr_mismatch_keys": sorted(set(allowed_attr_mismatch_keys)),
        "missing_allowed_attrs": sorted(set(missing_allowed_attrs)),
        "full_attr_mismatches": full_mismatches,
        "ignored_provenance_attr_mismatches": ignored_mismatches,
    }
    return {"match": not full_mismatches, "diagnostics": diagnostics}


def _compare_dataarrays(
    left: xr.DataArray,
    right: xr.DataArray,
    *,
    rtol: float,
    atol: float,
    ignore_non_dim_coord_mismatches_when_values_equal: bool = False,
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
        left_nan = np.isnan(left_values) if np.issubdtype(left_values.dtype, np.floating) else np.zeros(left_values.shape, dtype=bool)
        right_nan = np.isnan(right_values) if np.issubdtype(right_values.dtype, np.floating) else np.zeros(right_values.shape, dtype=bool)
        nan_mismatch = int(np.count_nonzero(left_nan != right_nan))

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
            if np.all(np.isnan(rel_diff)):
                max_rel_diff = None
            else:
                max_rel_diff = float(np.nanmax(rel_diff))

        try:
            xr.testing.assert_allclose(left_loaded, right_loaded, rtol=rtol, atol=atol)
            match = nan_mismatch == 0
        except AssertionError as exc:
            reason = str(exc)
            if (
                ignore_non_dim_coord_mismatches_when_values_equal
                and nan_mismatch == 0
                and _numeric_values_equal_within_tolerance(
                    left_values,
                    right_values,
                    left_nan=left_nan,
                    right_nan=right_nan,
                    rtol=rtol,
                    atol=atol,
                )
                and _has_only_non_dimension_coordinate_differences(left_loaded, right_loaded)
            ):
                diagnostics["ignored_reason"] = reason
                diagnostics["reason"] = (
                    "ignored non-dimension coordinate differences with equal numeric values"
                )
                match = True
            else:
                diagnostics["reason"] = reason
                match = False

        diagnostics["nan_mismatch_count"] = nan_mismatch
        diagnostics["max_abs_diff"] = max_abs_diff
        diagnostics["max_rel_diff"] = max_rel_diff
        return {
            "match": match,
            "diagnostics": diagnostics,
            "max_abs_diff": max_abs_diff,
            "max_rel_diff": max_rel_diff,
            "nan_mismatch_count": nan_mismatch,
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


def _numeric_values_equal_within_tolerance(
    left_values: np.ndarray,
    right_values: np.ndarray,
    *,
    left_nan: np.ndarray,
    right_nan: np.ndarray,
    rtol: float,
    atol: float,
) -> bool:
    if left_values.shape != right_values.shape:
        return False
    if np.any(left_nan != right_nan):
        return False

    valid_mask = ~(left_nan | right_nan)
    if not np.any(valid_mask):
        return True

    return bool(
        np.allclose(
            left_values[valid_mask],
            right_values[valid_mask],
            rtol=rtol,
            atol=atol,
        )
    )


def _has_only_non_dimension_coordinate_differences(
    left: xr.DataArray,
    right: xr.DataArray,
) -> bool:
    if left.dims != right.dims:
        return False

    for dim_name in left.dims:
        left_has_dim_coord = dim_name in left.coords
        right_has_dim_coord = dim_name in right.coords
        if left_has_dim_coord != right_has_dim_coord:
            return False
        if left_has_dim_coord and right_has_dim_coord:
            if not _coord_values_equal(left.coords[dim_name], right.coords[dim_name]):
                return False

    return True


def _coord_values_equal(left: xr.DataArray, right: xr.DataArray) -> bool:
    if left.dims != right.dims or left.shape != right.shape:
        return False

    left_values = np.asarray(left.load().values)
    right_values = np.asarray(right.load().values)

    if _is_numeric_dtype(left_values.dtype) and _is_numeric_dtype(right_values.dtype):
        return bool(
            np.allclose(left_values, right_values, rtol=RTOL, atol=ATOL, equal_nan=True)
        )

    return bool(np.array_equal(left_values, right_values))


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


def _derive_failure_categories(
    *,
    structure_match: bool | None,
    data_match: bool | None,
    cf_axes_match: bool | None,
    time_decode_match: bool | None,
    bounds_match: bool | None,
    attrs_match: bool | None,
    status: str,
    error_type: str | None = None,
) -> list[str]:
    if status == "error":
        if error_type in {"kerchunk_open_failed", "netcdf_open_failed"}:
            return ["open_decode_failure"]
        if error_type in {"kerchunk_file_missing", "netcdf_file_missing"}:
            return ["input_file_missing"]
        return ["validation_error"]

    categories: list[str] = []
    if cf_axes_match is False:
        categories.append("cf_axis_detection_mismatch")
    if time_decode_match is False:
        categories.append("time_decode_mismatch")
    if bounds_match is False:
        categories.append("bounds_mismatch")
    if structure_match is False:
        categories.append("metadata_structure_mismatch")
    if data_match is False:
        categories.append("data_mismatch")
    if attrs_match is False:
        categories.append("attribute_mismatch")
    return categories


def _write_summary_markdown(
    rows_by_dataset_id: dict[str, dict[str, Any]],
    summary_md: str,
) -> None:
    df = pd.DataFrame(rows_by_dataset_id.values())
    _ensure_schema_columns(df)

    total_rows = len(df)
    if total_rows == 0:
        Path(summary_md).parent.mkdir(parents=True, exist_ok=True)
        Path(summary_md).write_text("# Metadata/CF Validation Summary\n\nNo rows recorded yet.\n")
        return

    bin_lines = [
        "| nfiles_bin | total | passed | failed_checks | errors | skipped |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for label in SUPPORTED_NFILES_BIN_LABELS:
        subset = df[df["nfiles_bin"] == label]
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
        bin_lines.append(
            f"| {label} | {len(subset)} | {passed} | {failed_checks} | {errors} | {skipped} |"
        )

    category_counter: Counter[str] = Counter()
    category_examples: dict[str, list[str]] = defaultdict(list)
    for _, row in df.iterrows():
        categories = _load_json_list(row.get("failure_categories_json"))
        dataset_id = str(row.get("dataset_id"))
        for category in categories:
            category_counter[category] += 1
            if dataset_id and dataset_id not in category_examples[category] and len(category_examples[category]) < 5:
                category_examples[category].append(dataset_id)

    category_lines = ["| failure_category | count | example_dataset_ids |", "| --- | ---: | --- |"]
    if category_counter:
        for category, count in category_counter.most_common():
            examples = ", ".join(category_examples[category]) if category_examples[category] else "-"
            category_lines.append(f"| {category} | {count} | {examples} |")
    else:
        category_lines.append("| none | 0 | - |")

    ignored_counter: Counter[str] = Counter()
    ignored_examples: dict[str, list[str]] = defaultdict(list)
    for _, row in df.iterrows():
        diagnostics = _load_json_dict(row.get("diagnostics_json"))
        ignored_categories = _collect_ignored_categories_from_diagnostics(diagnostics)
        dataset_id = str(row.get("dataset_id"))
        for category in ignored_categories:
            ignored_counter[category] += 1
            if dataset_id and dataset_id not in ignored_examples[category] and len(ignored_examples[category]) < 5:
                ignored_examples[category].append(dataset_id)

    ignored_lines = ["| ignored_category | count | example_dataset_ids |", "| --- | ---: | --- |"]
    if ignored_counter:
        for category, count in ignored_counter.most_common():
            examples = ", ".join(ignored_examples[category]) if ignored_examples[category] else "-"
            ignored_lines.append(f"| {category} | {count} | {examples} |")
    else:
        ignored_lines.append("| none | 0 | - |")

    family_counts = {
        "kerchunk_metadata_issues": sum(
            category_counter[key]
            for key in ("metadata_structure_mismatch", "bounds_mismatch", "attribute_mismatch")
        ),
        "decode_issues": sum(
            category_counter[key]
            for key in ("open_decode_failure", "time_decode_mismatch")
        ),
        "xcdat_interpretation_issues": category_counter["cf_axis_detection_mismatch"],
        "data_value_issues": category_counter["data_mismatch"],
    }

    passed_total = int(sum(_truthy(value) for value in df["all_checks_pass"].tolist()))
    error_total = int(sum(value == "error" for value in df["status"].tolist()))
    skipped_total = int(sum(value == "skipped" for value in df["status"].tolist()))
    failed_total = total_rows - passed_total - error_total - skipped_total

    lines = [
        "# Metadata/CF Validation Summary",
        "",
        f"- Total datasets: {total_rows}",
        f"- Passed all checks: {passed_total}",
        f"- Failed validation checks: {failed_total}",
        f"- Execution errors: {error_total}",
        f"- Skipped datasets: {skipped_total}",
        "",
        "## Pass/Fail by File-Count Bin",
        "",
        *bin_lines,
        "",
        "## Common Failure Categories",
        "",
        *category_lines,
        "",
        "## Ignored Differences",
        "",
        *ignored_lines,
        "",
        "## Failure Families",
        "",
        f"- Kerchunk metadata issues: {family_counts['kerchunk_metadata_issues']}",
        f"- Decode issues: {family_counts['decode_issues']}",
        f"- xCDAT interpretation issues: {family_counts['xcdat_interpretation_issues']}",
        f"- Data-value issues: {family_counts['data_value_issues']}",
        "",
    ]
    Path(summary_md).parent.mkdir(parents=True, exist_ok=True)
    Path(summary_md).write_text("\n".join(lines) + "\n")


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


def _load_json_dict(value: Any) -> dict[str, Any]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _collect_ignored_categories_from_diagnostics(
    diagnostics: dict[str, Any],
) -> list[str]:
    categories: list[str] = []

    attrs = diagnostics.get("attrs", {})
    if attrs.get("ignored_provenance_attr_mismatches"):
        categories.append("ignored_provenance_attrs")

    cf_axes = diagnostics.get("cf_axes", {})
    if cf_axes.get("ignored_symmetric_axis_resolution_errors"):
        categories.append("ignored_symmetric_axis_resolution")

    data = diagnostics.get("data", {})
    data_ignored = False
    if isinstance(data.get("target_variable"), dict) and data["target_variable"].get(
        "ignored_reason"
    ):
        data_ignored = True
    for payload in data.get("coord_value_mismatches", {}).values():
        if isinstance(payload, dict) and payload.get("ignored_reason"):
            data_ignored = True
            break
    if data_ignored:
        categories.append("ignored_data_non_dim_coord_diff")

    bounds = diagnostics.get("bounds", {})
    if bounds.get("ignored_bounds_value_details"):
        categories.append("ignored_bounds_non_dim_coord_diff")

    return categories


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
    if isinstance(value, (list, tuple)):
        return [_scalar_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _scalar_to_jsonable(val) for key, val in value.items()}
    return str(value)


def _jsonable_equal(left: Any, right: Any) -> bool:
    return _scalar_to_jsonable(left) == _scalar_to_jsonable(right)


def _first_value_class_name(da: xr.DataArray) -> str | None:
    if da.size == 0:
        return None
    return type(np.asarray(da.values).flat[0]).__name__


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


def _safe_close(ds: xr.Dataset | None) -> None:
    if ds is None:
        return
    try:
        ds.close()
    except Exception:
        pass


def _dtype_or_none(var: xr.DataArray | xr.Variable | None) -> str | None:
    if var is None:
        return None
    return str(var.dtype)


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


def _infer_var_id(kerchunk_fn: str) -> str:
    parts = Path(kerchunk_fn).name.split(".")
    return parts[7] if len(parts) > 7 else "ta"


if __name__ == "__main__":
    main()
