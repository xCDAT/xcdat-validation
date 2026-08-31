"""Inspect attribute drift for the HAMMOZ hur kerchunk dataset.

This script targets the ``attribute_mismatch`` case in ``results.csv`` for the
HAMMOZ ``hur`` dataset. It opens both kerchunk and NetCDF views directly and
prints the differing dataset and variable attributes, separating CF-significant
keys from publication or provenance drift.

Example usage:
    conda run --no-capture-output -n xcdat_test_stable_min \
        python riotai/results/20260605-metadata-cf-validation/discrepancy-check/3_check_hammoz_attr_drift.py
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Any

import xarray as xr
import xcdat as xc


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_RESULTS_CSV = ROOT_DIR / "../results.csv"
DEFAULT_DATASET_ID = (
    "CMIP6.CMIP.HAMMOZ-Consortium.MPI-ESM-1-2-HAM."
    "piControl.r1i1p1f1.Amon.hur.gn.kerchunk.json"
)
CF_SIGNIFICANT_KEYS = {"standard_name", "long_name", "units", "axis", "calendar", "bounds"}
PROVENANCE_KEYS = {"creation_date", "history", "tracking_id"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect attribute differences for the HAMMOZ hur kerchunk dataset "
            "and classify them as CF-significant or publication/provenance drift."
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


def sorted_netcdf_files(data_dir: str) -> list[str]:
    directory = Path(data_dir)
    return sorted(
        str(directory / name)
        for name in os.listdir(directory)
        if name.endswith(".nc")
    )


def open_kerchunk_dataset(kerchunk_file: str) -> xr.Dataset:
    with xr.set_options(file_cache_maxsize=1):
        return xc.open_dataset(kerchunk_file, engine="kerchunk", chunks={})


def open_netcdf_dataset(netcdf_files: list[str]) -> xr.Dataset:
    with xr.set_options(file_cache_maxsize=1):
        return xc.open_mfdataset(netcdf_files, chunks={}, join="exact")


def diff_attrs(left: dict[str, Any], right: dict[str, Any]) -> dict[str, dict[str, Any]]:
    diffs: dict[str, dict[str, Any]] = {}
    for key in sorted(set(left) | set(right)):
        left_value = left.get(key)
        right_value = right.get(key)
        if left_value != right_value:
            diffs[key] = {"kerchunk": left_value, "netcdf": right_value}
    return diffs


def classify_key(key: str) -> str:
    if key in CF_SIGNIFICANT_KEYS:
        return "cf-significant"
    if key in PROVENANCE_KEYS:
        return "provenance"
    return "publication-or-other"


def print_scope(scope: str, diffs: dict[str, dict[str, Any]]) -> None:
    if not diffs:
        print(f"{scope}: no differences")
        return

    print(f"{scope}: {len(diffs)} difference(s)")
    for key, values in diffs.items():
        print(f"  - {key} [{classify_key(key)}]")
        print(f"    kerchunk: {values['kerchunk']}")
        print(f"    netcdf:   {values['netcdf']}")


def main() -> int:
    args = parse_args()
    row = load_row(args.results_csv, args.dataset_id)

    ds_kerchunk: xr.Dataset | None = None
    ds_netcdf: xr.Dataset | None = None

    try:
        netcdf_files = sorted_netcdf_files(row["data_dir"])
        ds_kerchunk = open_kerchunk_dataset(row["kerchunk_file"])
        ds_netcdf = open_netcdf_dataset(netcdf_files)

        dataset_diffs = diff_attrs(ds_kerchunk.attrs, ds_netcdf.attrs)
        variable_diffs = diff_attrs(ds_kerchunk[row["var_id"]].attrs, ds_netcdf[row["var_id"]].attrs)

        print(f"DATASET: {row['dataset_id']}")
        print(f"NetCDF dir: {row['data_dir']}")
        print(f"Kerchunk:   {row['kerchunk_file']}")
        print()
        print_scope("dataset attrs", dataset_diffs)
        print()
        print_scope(f"variable attrs ({row['var_id']})", variable_diffs)

        print()
        print("Interpretation note:")
        if any(classify_key(key) == "cf-significant" for key in dataset_diffs | variable_diffs):
            print("  At least one differing key is CF-significant, so this should not be ignored automatically.")
        else:
            print("  Differences are outside the current CF-significant key set and may be candidates for ignore rules.")
        return 0
    finally:
        if ds_kerchunk is not None:
            ds_kerchunk.close()
        if ds_netcdf is not None:
            ds_netcdf.close()


if __name__ == "__main__":
    raise SystemExit(main())