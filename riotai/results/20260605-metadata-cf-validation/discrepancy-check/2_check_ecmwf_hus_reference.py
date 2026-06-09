"""Inspect the missing ECMWF hus kerchunk reference and suggest likely matches.

This script targets the ECMWF ``hus`` case flagged as ``input_file_missing`` in
``results.csv``. It checks the missing path recorded in the validation output,
lists nearby candidate files from the same directory, and highlights likely
filename-resolution variants such as ``.gr.kerchunk.json`` and
``.gr.v*.kerchunk.json``.

Example usage:
    python riotai/results/20260605-metadata-cf-validation/discrepancy-check/2_check_ecmwf_hus_reference.py
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_RESULTS_CSV = ROOT_DIR / "../results.csv"
DEFAULT_DATASET_ID = (
    "CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950."
    "r1i1p1f1.Amon.hus.grkerchunk.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect the missing ECMWF hus kerchunk reference path and suggest "
            "candidate files from the same directory."
        )
    )
    parser.add_argument(
        "--results-csv",
        type=Path,
        default=DEFAULT_RESULTS_CSV,
        help="Path to the metadata/CF validation results CSV.",
    )
    parser.add_argument(
        "--dataset-id",
        default=DEFAULT_DATASET_ID,
        help="Dataset ID to inspect.",
    )
    return parser.parse_args()


def load_row(results_csv: Path, dataset_id: str) -> dict[str, str]:
    with results_csv.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("dataset_id") == dataset_id:
                return row
    raise ValueError(f"Dataset ID not found in {results_csv}: {dataset_id}")


def candidate_files(directory: Path, prefix: str) -> list[Path]:
    return sorted(path for path in directory.glob(f"{prefix}*") if path.is_file())


def main() -> int:
    args = parse_args()
    row = load_row(args.results_csv, args.dataset_id)

    missing_path = Path(row["kerchunk_file"])
    directory = missing_path.parent
    dataset_id = row["dataset_id"]

    print(f"DATASET: {dataset_id}")
    print(f"Recorded missing path: {missing_path}")
    print(f"Parent directory exists: {directory.exists()}")

    if not directory.exists():
        print("Directory is missing, so no filename candidates can be inspected.")
        return 1

    prefix = missing_path.name.split(".gr", 1)[0] + ".gr"
    matches = candidate_files(directory, prefix)

    print(f"Candidate file count in {directory}: {len(matches)}")
    if not matches:
        print("No candidate kerchunk files found with the same dataset prefix.")
        return 0

    print("Candidate files:")
    for path in matches:
        label = []
        if path.name == missing_path.name:
            label.append("exact")
        if ".gr.kerchunk.json" in path.name:
            label.append("dot-before-kerchunk")
        if ".gr.v" in path.name and path.name.endswith(".kerchunk.json"):
            label.append("versioned")
        suffix = f" [{' ,'.join(label)}]" if label else ""
        print(f"  - {path}{suffix}")

    print()
    print("Likely resolution note:")
    print(
        "  The recorded missing file uses '.grkerchunk.json', while nearby files "
        "may use '.gr.kerchunk.json' or '.gr.v<version>.kerchunk.json'."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())