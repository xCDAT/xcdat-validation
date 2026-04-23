"""Precompute dataset selection used by head_to_head.py.

This script resolves selected datasets once, validates kerchunk and NetCDF
paths, assigns file-count bins, and writes result to
`riotai/json_to_netcdf_maps/prepared_datasets_<frequency>.csv`.
`head_to_head.py` then reads that prepared file directly on later runs.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import sys

import pandas as pd

JSON_TO_NETCDF_MAPS_DIR: Path = (
    Path(__file__).resolve().parents[1] / "json_to_netcdf_maps"
)
DEFAULT_DATASET_TABLE_CSV: str = str(
    JSON_TO_NETCDF_MAPS_DIR / "json_to_netcdf_table.csv"
)
DEFAULT_TARGET_FREQUENCY: str = "Amon"

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
DEFAULT_DATASETS_PER_BIN_BY_LABEL: dict[str, int] = {
    "25-49": 10,
    "50-99": 10,
    "100-149": 10,
    "150-199": 10,
    "200-299": 10,
    "300-499": 10,
    "500-749": 10,
    "750-1000": 10,
}


@dataclass(frozen=True)
class DatasetSpec:
    data_dir: str
    dataset_id: str
    kerchunk_file: str | None
    var_id: str | None
    inference_error: str | None


@dataclass(frozen=True)
class PreparedDataset:
    spec: DatasetSpec
    netcdf_files: tuple[str, ...]
    nfiles: int
    nfiles_bin: str
    bin_selected_rank: int


def _prepared_datasets_csv_path(
    target_frequency: str = DEFAULT_TARGET_FREQUENCY,
) -> str:
    return str(JSON_TO_NETCDF_MAPS_DIR / f"prepared_datasets_{target_frequency}.csv")


def _datasets_per_bin_for_label(label: str, override: int | None = None) -> int:
    if override is not None:
        return override
    return DEFAULT_DATASETS_PER_BIN_BY_LABEL[label]


def _load_dataset_table(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Dataset table CSV does not exist: {path}")

    df = pd.read_csv(path)
    required_columns = {"json_path", "filepaths", "num_files"}
    missing_columns = sorted(required_columns - set(df.columns))
    if missing_columns:
        raise ValueError(
            "Dataset table CSV is missing required columns: "
            + ", ".join(missing_columns)
        )

    return df.reset_index(drop=True)


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


def _infer_var_id(kerchunk_fn: str) -> str:
    base = os.path.basename(kerchunk_fn)
    parts = base.split(".")
    return parts[7] if len(parts) > 7 else "ta"


def _build_dataset_spec_from_row(
    row: pd.Series,
) -> tuple[DatasetSpec, tuple[str, ...], int]:
    kerchunk_file = str(row["json_path"])
    dataset_id = os.path.basename(kerchunk_file).removesuffix(".kerchunk.json")
    netcdf_files = _parse_csv_filepaths(row["filepaths"])
    data_dir = _infer_data_dir_from_filepaths(netcdf_files)
    var_id = row.get("variable")
    if pd.isna(var_id) or not str(var_id):
        var_id = _infer_var_id(kerchunk_file)

    try:
        nfiles = int(row["num_files"])
    except (TypeError, ValueError):
        nfiles = len(netcdf_files)

    inference_error = None
    if not netcdf_files:
        inference_error = "no_filepaths_in_dataset_table"

    return (
        DatasetSpec(
            data_dir=data_dir,
            dataset_id=dataset_id,
            kerchunk_file=kerchunk_file,
            var_id=str(var_id),
            inference_error=inference_error,
        ),
        netcdf_files,
        nfiles,
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


def _prepared_dataset_to_row(dataset: PreparedDataset) -> dict[str, object]:
    return {
        "dataset_id": dataset.spec.dataset_id,
        "data_dir": dataset.spec.data_dir,
        "kerchunk_file": dataset.spec.kerchunk_file,
        "variable": dataset.spec.var_id,
        "netcdf_file_count": dataset.nfiles,
        "nfiles_bin": dataset.nfiles_bin,
        "bin_selected_rank": dataset.bin_selected_rank,
        "filepaths": json.dumps(list(dataset.netcdf_files)),
    }


def write_prepared_datasets_csv(
    selected_datasets: list[PreparedDataset],
    out_csv: str,
) -> None:
    rows = [_prepared_dataset_to_row(dataset) for dataset in selected_datasets]
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(
            ["nfiles_bin", "bin_selected_rank", "netcdf_file_count", "dataset_id"],
            na_position="last",
        )
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)


def load_prepared_datasets_csv(path: str) -> list[PreparedDataset]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Prepared datasets CSV does not exist: {path}")

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

    datasets: list[PreparedDataset] = []
    for _, row in df.iterrows():
        netcdf_files = _parse_csv_filepaths(row["filepaths"])
        data_dir = row.get("data_dir")
        if pd.isna(data_dir) or not str(data_dir):
            data_dir = _infer_data_dir_from_filepaths(netcdf_files)

        datasets.append(
            PreparedDataset(
                spec=DatasetSpec(
                    data_dir=str(data_dir),
                    dataset_id=str(row["dataset_id"]),
                    kerchunk_file=str(row["kerchunk_file"]),
                    var_id=str(row["variable"]),
                    inference_error=None,
                ),
                netcdf_files=netcdf_files,
                nfiles=int(row["netcdf_file_count"]),
                nfiles_bin=str(row["nfiles_bin"]),
                bin_selected_rank=int(row["bin_selected_rank"]),
            )
        )

    return datasets


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("prepare_datasets")


def _select_rows_with_pandas(
    dataset_table_csv: str,
    target_frequency: str,
    bins: tuple[str, ...],
    datasets_per_bin: int | None,
    random_seed: int,
    min_files: int | None,
    max_files: int | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = _load_dataset_table(dataset_table_csv).copy()

    if "frequency" not in df.columns:
        raise ValueError("Dataset table CSV missing required column: frequency")

    df = df[df["frequency"] == target_frequency].copy()
    df["__row_order"] = range(len(df))
    df["num_files"] = pd.to_numeric(df["num_files"], errors="coerce")
    df = df.dropna(subset=["num_files"]).copy()
    df["num_files"] = df["num_files"].astype(int)

    if min_files is not None:
        df = df[df["num_files"] >= min_files].copy()

    if max_files is not None:
        df = df[df["num_files"] <= max_files].copy()

    bin_edges = [NFILES_BINS[0][1] - 1]
    bin_edges.extend(
        float("inf") if max_nfiles is None else max_nfiles
        for _, _, max_nfiles in NFILES_BINS
    )
    bin_labels = [label for label, _, _ in NFILES_BINS]

    df["nfiles_bin"] = pd.cut(
        df["num_files"],
        bins=bin_edges,
        labels=bin_labels,
        right=True,
        include_lowest=True,
    )
    df = df[df["nfiles_bin"].isin(bins)].copy()
    candidate_rows = df.copy()

    selected_frames: list[pd.DataFrame] = []
    for offset, label in enumerate(SUPPORTED_NFILES_BIN_LABELS):
        if label not in bins:
            continue

        bin_df = candidate_rows[candidate_rows["nfiles_bin"] == label].copy()
        if bin_df.empty:
            continue

        sampled = bin_df.sample(
            n=len(bin_df),
            random_state=random_seed + offset,
            replace=False,
        ).copy()
        sampled = sampled.sort_values(["num_files", "__row_order"], kind="stable")
        sampled["bin_candidate_rank"] = range(1, len(sampled) + 1)
        selected_frames.append(sampled)

    if selected_frames:
        selected_rows = pd.concat(selected_frames, ignore_index=True)
    else:
        selected_rows = candidate_rows.iloc[0:0].copy()
        selected_rows["bin_candidate_rank"] = pd.Series(dtype=int)

    selected_rows["bin_candidate_rank"] = selected_rows["bin_candidate_rank"].astype(
        int
    )
    return candidate_rows, selected_rows


def _validate_selected_rows(
    selected_rows: pd.DataFrame,
    datasets_per_bin: int | None,
) -> list[PreparedDataset]:
    selected_datasets: list[PreparedDataset] = []
    selected_counts: dict[str, int] = {
        label: 0 for label in SUPPORTED_NFILES_BIN_LABELS
    }
    candidate_counts: dict[str, int] = {
        label: int((selected_rows["nfiles_bin"] == label).sum())
        for label in SUPPORTED_NFILES_BIN_LABELS
    }
    current_bin: str | None = None

    logger.info("Starting validation of %d candidate datasets", len(selected_rows))

    for _, row in selected_rows.iterrows():
        spec, netcdf_files_from_table, nfiles = _build_dataset_spec_from_row(row)
        nfiles_bin = str(row["nfiles_bin"])
        target_count = _datasets_per_bin_for_label(nfiles_bin, datasets_per_bin)

        if nfiles_bin != current_bin:
            current_bin = nfiles_bin
            logger.info(
                "Validating bin=%s | candidates=%d | target=%d",
                nfiles_bin,
                candidate_counts[nfiles_bin],
                target_count,
            )

        if selected_counts[nfiles_bin] >= target_count:
            continue

        if spec.inference_error is not None:
            logger.warning("Skipping %s: %s", spec.dataset_id, spec.inference_error)
            continue

        if nfiles != len(netcdf_files_from_table):
            logger.warning(
                "Using num_files=%d from dataset table for %s, but filepaths has %d entries",
                nfiles,
                spec.dataset_id,
                len(netcdf_files_from_table),
            )

        if not spec.kerchunk_file:
            logger.warning("Skipping %s: kerchunk path not inferred", spec.dataset_id)
            continue

        readable, read_reason = _is_readable_file(spec.kerchunk_file)
        if not readable:
            logger.warning(
                "Skipping %s: kerchunk file unavailable (%s)",
                spec.dataset_id,
                read_reason,
            )
            continue

        netcdf_files = tuple(
            path for path in netcdf_files_from_table if os.path.exists(path)
        )
        missing = len(netcdf_files_from_table) - len(netcdf_files)
        if missing:
            logger.warning(
                "Skipping %s: %d NetCDF files from dataset table are missing on disk",
                spec.dataset_id,
                missing,
            )
            continue

        if not netcdf_files:
            logger.warning("Skipping %s: no NetCDF files found", spec.dataset_id)
            continue

        selected_counts[nfiles_bin] += 1
        bin_selected_rank = selected_counts[nfiles_bin]
        logger.info(
            "Selected dataset %s | bin=%s | rank=%d/%d | nfiles=%d",
            spec.dataset_id,
            nfiles_bin,
            bin_selected_rank,
            target_count,
            nfiles,
        )
        selected_datasets.append(
            PreparedDataset(
                spec=spec,
                netcdf_files=netcdf_files,
                nfiles=nfiles,
                nfiles_bin=nfiles_bin,
                bin_selected_rank=bin_selected_rank,
            )
        )

    return selected_datasets


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Precompute and write frequency-specific prepared dataset selection "
            "consumed by head_to_head.py"
        )
    )
    parser.add_argument(
        "--target-frequency",
        type=str,
        default=DEFAULT_TARGET_FREQUENCY,
        help="Frequency to filter from json_to_netcdf_table.csv",
    )
    parser.add_argument(
        "--dataset-table-csv",
        type=str,
        default=DEFAULT_DATASET_TABLE_CSV,
        help="Input dataset table CSV from json_to_netcdf_table.py",
    )
    parser.add_argument(
        "--out-csv",
        type=str,
        default=None,
        help=(
            "Output path for prepared datasets CSV. Default: "
            "riotai/json_to_netcdf_maps/prepared_datasets_<target-frequency>.csv"
        ),
    )
    parser.add_argument(
        "--datasets-per-bin",
        type=int,
        default=None,
        help=(
            "Optional override for all bins. Default is 20/bin for 25-149 and "
            "10/bin for 150+."
        ),
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=42,
        help="Random seed for reproducible per-bin sampling",
    )
    parser.add_argument(
        "--bins",
        type=str,
        default=",".join(SUPPORTED_NFILES_BIN_LABELS),
        help="Comma-separated bins to prepare",
    )
    parser.add_argument(
        "--replace-bin",
        type=str,
        action="append",
        default=None,
        help=(
            "Refresh only the given bin in an existing prepared CSV. "
            "May be passed multiple times."
        ),
    )
    parser.add_argument(
        "--min-files",
        type=int,
        default=None,
        help="Optional lower bound for num_files",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Optional upper bound for num_files",
    )
    args = parser.parse_args()

    if args.datasets_per_bin is not None and args.datasets_per_bin < 1:
        parser.error("--datasets-per-bin must be >= 1")

    if args.min_files is not None and args.max_files is not None:
        if args.min_files > args.max_files:
            parser.error("--min-files cannot be greater than --max-files")

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

    args.bins = bins
    replace_bins = tuple(dict.fromkeys(args.replace_bin or []))
    invalid_replace_bins = [
        label for label in replace_bins if label not in SUPPORTED_NFILES_BIN_LABELS
    ]
    if invalid_replace_bins:
        parser.error(
            "Unsupported --replace-bin value(s): "
            + ", ".join(invalid_replace_bins)
            + ". Supported: "
            + ", ".join(SUPPORTED_NFILES_BIN_LABELS)
        )
    if replace_bins:
        args.bins = replace_bins
    args.replace_bin = replace_bins
    if args.out_csv is None:
        args.out_csv = _prepared_datasets_csv_path(args.target_frequency)
    return args


def main() -> None:
    args = _parse_args()
    logger.info(
        "Preparing datasets | frequency=%s | bins=%s | datasets_per_bin=%s | input=%s | output=%s",
        args.target_frequency,
        ",".join(args.bins),
        args.datasets_per_bin,
        args.dataset_table_csv,
        args.out_csv,
    )
    candidate_rows, selected_rows = _select_rows_with_pandas(
        dataset_table_csv=args.dataset_table_csv,
        target_frequency=args.target_frequency,
        bins=args.bins,
        datasets_per_bin=args.datasets_per_bin,
        random_seed=args.random_seed,
        min_files=args.min_files,
        max_files=args.max_files,
    )
    logger.info(
        "Candidate selection complete | filtered_rows=%d | validation_queue=%d",
        len(candidate_rows),
        len(selected_rows),
    )
    selected_datasets = _validate_selected_rows(
        selected_rows,
        datasets_per_bin=args.datasets_per_bin,
    )

    if args.replace_bin:
        existing_datasets = load_prepared_datasets_csv(args.out_csv)
        kept_datasets = [
            dataset
            for dataset in existing_datasets
            if dataset.nfiles_bin not in args.replace_bin
        ]
        selected_datasets = kept_datasets + selected_datasets
        logger.info(
            "Replace-bin mode: refreshed bins=%s | kept existing datasets=%d",
            ",".join(args.replace_bin),
            len(kept_datasets),
        )

    write_prepared_datasets_csv(selected_datasets, args.out_csv)

    logger.info("Prepared dataset CSV written to %s", args.out_csv)
    logger.info("Filtered frequency: %s", args.target_frequency)
    logger.info("Selected %d datasets total", len(selected_datasets))
    logger.info("Sampling seed: %d", args.random_seed)
    logger.info(
        "Per-bin defaults: %s",
        ", ".join(
            f"{label}={DEFAULT_DATASETS_PER_BIN_BY_LABEL[label]}"
            for label in SUPPORTED_NFILES_BIN_LABELS
        ),
    )
    for label in SUPPORTED_NFILES_BIN_LABELS:
        if label not in args.bins:
            continue
        logger.info(
            "bin=%s | discovered=%d | candidate_pool=%d | validated=%d | target=%d",
            label,
            int((candidate_rows["nfiles_bin"] == label).sum()),
            int((selected_rows["nfiles_bin"] == label).sum()),
            sum(dataset.nfiles_bin == label for dataset in selected_datasets),
            _datasets_per_bin_for_label(label, args.datasets_per_bin),
        )


if __name__ == "__main__":
    main()
