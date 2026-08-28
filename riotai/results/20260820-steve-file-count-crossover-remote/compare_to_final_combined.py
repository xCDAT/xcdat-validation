"""Compare remote-Kerchunk timings with the 20260416 baseline.

Example:
    python compare_to_final_combined.py --remote-csv remote_kerchunk.csv \
        --out-csv remote_vs_final_combined.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).parent
DEFAULT_BASELINE = ROOT_DIR.parent / "20260416-steve-file-count-crossover" / "final_combined.csv"
TIMING_PREFIXES = ("open_", "load_", "temporal_", "spatial_")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote-csv", required=True, help="Remote benchmark CSV")
    parser.add_argument(
        "--baseline-csv", default=DEFAULT_BASELINE, help="Baseline benchmark CSV"
    )
    parser.add_argument("--out-csv", required=True, help="Comparison CSV to write")
    return parser.parse_args()


def _read_csv(path: str | Path, label: str) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path)
    except Exception as error:
        raise SystemExit(f"Could not read {label} CSV {path}: {error}") from error
    if "dataset_id" not in frame:
        raise SystemExit(f"{label.capitalize()} CSV is missing required column: dataset_id")
    if frame["dataset_id"].isna().any() or frame["dataset_id"].duplicated().any():
        raise SystemExit(f"{label.capitalize()} CSV has missing or duplicate dataset_id values")
    return frame


def _timing_columns(frame: pd.DataFrame) -> set[str]:
    return {
        column
        for column in frame
        if column.startswith(TIMING_PREFIXES)
        and "ratio" not in column
        and "task" not in column
    }


def main() -> None:
    args = _parse_args()
    remote = _read_csv(Path(args.remote_csv), "remote")
    baseline = _read_csv(Path(args.baseline_csv), "baseline")

    remote_only = sorted(set(remote.dataset_id) - set(baseline.dataset_id))
    baseline_only = sorted(set(baseline.dataset_id) - set(remote.dataset_id))
    print(f"Unmatched remote IDs ({len(remote_only)}): {', '.join(remote_only) or 'none'}")
    print(f"Unmatched baseline IDs ({len(baseline_only)}): {', '.join(baseline_only) or 'none'}")

    timing_columns = sorted(_timing_columns(remote) & _timing_columns(baseline))
    retained = ["dataset_id", "status", "netcdf_file_count"]
    remote_columns = [column for column in retained if column in remote] + timing_columns
    baseline_columns = [column for column in retained if column in baseline] + timing_columns
    comparison = remote[remote_columns].merge(
        baseline[baseline_columns], on="dataset_id", how="inner", suffixes=("_remote", "_baseline")
    )
    count_columns = {"netcdf_file_count_remote", "netcdf_file_count_baseline"}
    if count_columns.issubset(comparison.columns):
        unequal_counts = comparison[
            comparison["netcdf_file_count_remote"] != comparison["netcdf_file_count_baseline"]
        ]
        if not unequal_counts.empty:
            print(
                "WARNING: netcdf_file_count differs for matched dataset IDs: "
                + ", ".join(unequal_counts["dataset_id"])
            )

    for column in timing_columns:
        remote_values = pd.to_numeric(comparison[f"{column}_remote"], errors="coerce")
        baseline_values = pd.to_numeric(comparison[f"{column}_baseline"], errors="coerce")
        comparison[f"{column}_delta"] = remote_values - baseline_values
        comparison[f"{column}_ratio"] = remote_values.div(
            baseline_values.mask(baseline_values == 0)
        )

    comparison.to_csv(args.out_csv, index=False)
    print(f"Wrote {len(comparison)} matched rows to {args.out_csv}")


if __name__ == "__main__":
    main()
