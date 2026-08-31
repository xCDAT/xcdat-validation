"""Inspect time-coordinate differences for affected ECMWF kerchunk datasets.

This script reads the metadata/CF validation results CSV, selects the ECMWF
datasets flagged with ``time_decode_mismatch`` by default, and opens both the
kerchunk and NetCDF views directly with xCDAT. It prints a compact report for
each dataset so the time-axis issue can be inspected without re-running the
full validation workflow.

Example usage:
    conda run --no-capture-output -n xcdat_test_stable_min \
        python riotai/results/20260605-metadata-cf-validation/discrepancy-check/1_check_ecmwf_time_coords.py

    conda run --no-capture-output -n xcdat_test_stable_min \
        python riotai/results/20260605-metadata-cf-validation/discrepancy-check/1_check_ecmwf_time_coords.py \
        --output ecmwf_time_report.md --output-format markdown
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
DEFAULT_RESULTS_CSV = ROOT_DIR / "results.csv"
DEFAULT_OUTPUT_FORMAT = "text"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Open affected ECMWF kerchunk/NetCDF dataset pairs and print "
            "time-coordinate diagnostics."
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
        action="append",
        default=[],
        help=(
            "Optional dataset_id to inspect. Repeat to inspect multiple IDs. "
            "If omitted, the script inspects ECMWF rows with time_decode_mismatch."
        ),
    )
    parser.add_argument(
        "--show-value-examples",
        type=int,
        default=5,
        help="Number of unmatched time values to print from each side.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output file path for the report.",
    )
    parser.add_argument(
        "--output-format",
        choices=("text", "markdown", "csv"),
        default=DEFAULT_OUTPUT_FORMAT,
        help="Output format to use when --output is set.",
    )
    return parser.parse_args()


def load_target_rows(results_csv: Path, dataset_ids: list[str]) -> list[dict[str, str]]:
    with results_csv.open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    if dataset_ids:
        wanted = set(dataset_ids)
        selected = [row for row in rows if row.get("dataset_id") in wanted]
    else:
        selected = [
            row
            for row in rows
            if row.get("primary_failure_category") == "time_decode_mismatch"
            and "ECMWF" in (row.get("dataset_id") or "")
        ]

    selected.sort(key=lambda row: row.get("dataset_id", ""))
    return selected


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


def format_time_value(value: Any) -> str:
    return "None" if value is None else str(value)


def describe_time_range(kerchunk_time: xr.DataArray, netcdf_time: xr.DataArray) -> list[str]:
    messages: list[str] = []

    if kerchunk_time.size and netcdf_time.size:
        k_first = kerchunk_time.values[0]
        n_first = netcdf_time.values[0]
        k_last = kerchunk_time.values[-1]
        n_last = netcdf_time.values[-1]

        if k_first != n_first:
            messages.append(
                "start differs: kerchunk="
                f"{format_time_value(k_first)} vs netcdf={format_time_value(n_first)}"
            )
        if k_last != n_last:
            messages.append(
                "end differs: kerchunk="
                f"{format_time_value(k_last)} vs netcdf={format_time_value(n_last)}"
            )

    if kerchunk_time.size != netcdf_time.size:
        messages.append(
            f"length differs: kerchunk={kerchunk_time.size} vs netcdf={netcdf_time.size}"
        )

    return messages


def first_unmatched_values(
    source_values: list[Any],
    other_values: list[Any],
    limit: int,
) -> list[str]:
    other_set = set(other_values)
    unmatched: list[str] = []
    for value in source_values:
        if value not in other_set:
            unmatched.append(format_time_value(value))
            if len(unmatched) >= limit:
                break
    return unmatched


def inspect_row(row: dict[str, str], show_value_examples: int) -> dict[str, Any]:
    dataset_id = row["dataset_id"]
    data_dir = row["data_dir"]
    kerchunk_file = row["kerchunk_file"]
    netcdf_files = sorted_netcdf_files(data_dir)

    ds_kerchunk: xr.Dataset | None = None
    ds_netcdf: xr.Dataset | None = None

    try:
        ds_kerchunk = open_kerchunk_dataset(kerchunk_file)
        ds_netcdf = open_netcdf_dataset(netcdf_files)

        time_kerchunk = ds_kerchunk.coords["time"].load()
        time_netcdf = ds_netcdf.coords["time"].load()

        kerchunk_values = time_kerchunk.values.tolist()
        netcdf_values = time_netcdf.values.tolist()
        summaries = describe_time_range(time_kerchunk, time_netcdf)

        extra_in_kerchunk = first_unmatched_values(
            kerchunk_values,
            netcdf_values,
            show_value_examples,
        )
        missing_from_kerchunk = first_unmatched_values(
            netcdf_values,
            kerchunk_values,
            show_value_examples,
        )

        return {
            "dataset_id": dataset_id,
            "netcdf_dir": data_dir,
            "kerchunk_file": kerchunk_file,
            "netcdf_file_count": len(netcdf_files),
            "kerchunk_time_length": time_kerchunk.size,
            "netcdf_time_length": time_netcdf.size,
            "kerchunk_time_start": format_time_value(
                time_kerchunk.values[0] if time_kerchunk.size else None
            ),
            "netcdf_time_start": format_time_value(
                time_netcdf.values[0] if time_netcdf.size else None
            ),
            "kerchunk_time_end": format_time_value(
                time_kerchunk.values[-1] if time_kerchunk.size else None
            ),
            "netcdf_time_end": format_time_value(
                time_netcdf.values[-1] if time_netcdf.size else None
            ),
            "summary_messages": summaries,
            "extra_in_kerchunk": extra_in_kerchunk,
            "missing_from_kerchunk": missing_from_kerchunk,
        }
    finally:
        if ds_kerchunk is not None:
            ds_kerchunk.close()
        if ds_netcdf is not None:
            ds_netcdf.close()


def render_text_report(report: dict[str, Any]) -> str:
    lines = [
        f"DATASET: {report['dataset_id']}",
        f"  NetCDF dir: {report['netcdf_dir']}",
        f"  Kerchunk:   {report['kerchunk_file']}",
        f"  NetCDF files: {report['netcdf_file_count']}",
        (
            "  Time lengths: "
            f"kerchunk={report['kerchunk_time_length']}, netcdf={report['netcdf_time_length']}"
        ),
        (
            "  Time start:   "
            f"kerchunk={report['kerchunk_time_start']}, netcdf={report['netcdf_time_start']}"
        ),
        (
            "  Time end:     "
            f"kerchunk={report['kerchunk_time_end']}, netcdf={report['netcdf_time_end']}"
        ),
    ]

    for message in report["summary_messages"]:
        lines.append(f"  Summary: {message}")

    if report["extra_in_kerchunk"]:
        lines.append("  Example values only in kerchunk:")
        lines.extend(f"    - {value}" for value in report["extra_in_kerchunk"])
    if report["missing_from_kerchunk"]:
        lines.append("  Example values only in netcdf:")
        lines.extend(f"    - {value}" for value in report["missing_from_kerchunk"])

    return "\n".join(lines)


def render_markdown_report(reports: list[dict[str, Any]], results_csv: Path) -> str:
    lines = [
        "# ECMWF Time Coordinate Report",
        "",
        f"- Source CSV: `{results_csv}`",
        f"- Dataset count: {len(reports)}",
        "",
    ]

    for report in reports:
        lines.extend(
            [
                f"## {report['dataset_id']}",
                "",
                f"- NetCDF dir: `{report['netcdf_dir']}`",
                f"- Kerchunk file: `{report['kerchunk_file']}`",
                f"- NetCDF files: {report['netcdf_file_count']}",
                (
                    "- Time lengths: "
                    f"kerchunk={report['kerchunk_time_length']}, netcdf={report['netcdf_time_length']}"
                ),
                (
                    "- Time start: "
                    f"kerchunk={report['kerchunk_time_start']}, netcdf={report['netcdf_time_start']}"
                ),
                (
                    "- Time end: "
                    f"kerchunk={report['kerchunk_time_end']}, netcdf={report['netcdf_time_end']}"
                ),
            ]
        )

        if report["summary_messages"]:
            lines.append("- Summary:")
            lines.extend(f"  - {message}" for message in report["summary_messages"])
        if report["extra_in_kerchunk"]:
            lines.append("- Example values only in kerchunk:")
            lines.extend(f"  - {value}" for value in report["extra_in_kerchunk"])
        if report["missing_from_kerchunk"]:
            lines.append("- Example values only in netcdf:")
            lines.extend(f"  - {value}" for value in report["missing_from_kerchunk"])

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_csv_report(output_path: Path, reports: list[dict[str, Any]]) -> None:
    fieldnames = [
        "dataset_id",
        "netcdf_dir",
        "kerchunk_file",
        "netcdf_file_count",
        "kerchunk_time_length",
        "netcdf_time_length",
        "kerchunk_time_start",
        "netcdf_time_start",
        "kerchunk_time_end",
        "netcdf_time_end",
        "summary_messages",
        "extra_in_kerchunk",
        "missing_from_kerchunk",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for report in reports:
            writer.writerow(
                {
                    **report,
                    "summary_messages": " | ".join(report["summary_messages"]),
                    "extra_in_kerchunk": " | ".join(report["extra_in_kerchunk"]),
                    "missing_from_kerchunk": " | ".join(report["missing_from_kerchunk"]),
                }
            )


def write_output(
    output_path: Path,
    output_format: str,
    reports: list[dict[str, Any]],
    results_csv: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_format == "text":
        body = "\n\n".join(render_text_report(report) for report in reports) + "\n"
        output_path.write_text(body)
        return
    if output_format == "markdown":
        output_path.write_text(render_markdown_report(reports, results_csv))
        return
    if output_format == "csv":
        write_csv_report(output_path, reports)
        return

    raise ValueError(f"Unsupported output format: {output_format}")


def main() -> int:
    args = parse_args()
    rows = load_target_rows(args.results_csv, args.dataset_id)

    if not rows:
        print("No matching dataset rows found.")
        return 1

    reports = [inspect_row(row, args.show_value_examples) for row in rows]

    print(f"Inspecting {len(rows)} dataset(s) from {args.results_csv}")
    for index, report in enumerate(reports, start=1):
        if index > 1:
            print()
        print(render_text_report(report))

    if args.output is not None:
        write_output(args.output, args.output_format, reports, args.results_csv)
        print()
        print(f"Wrote {args.output_format} report to {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())