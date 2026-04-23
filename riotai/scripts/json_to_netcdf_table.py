"""Flatten frequency-grouped JSON→NetCDF mappings into a tabular dataset.

The input mapping is expected to have this shape:

{
  "Amon": {
    "/path/to/file.kerchunk.json": ["/path/to/file1.nc", "/path/to/file2.nc"]
  },
  "day": {
    ...
  }
}

This script converts the nested mapping into one record per kerchunk JSON path
with:

* frequency
* variable
* json_path
* filepaths
* num_files

CSV is the default output because it is easy to inspect, diff, and reuse for
analysis. A JSON records output is also available when preserving list-valued
columns matters more than spreadsheet-style workflows.

Usage:
salloc --nodes 1 --qos interactive --time 02:00:00 --constraint cpu --account=e3sm
conda env create -f riotai/test_stable_min.yml
conda activate xcdat_test_stable_min
python riotai/scripts/json_to_netcdf_table.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


INPUT_PATH = (
    Path(__file__).resolve().parents[1] / "json_to_netcdf_maps" / "json_to_netcdf.json"
)
OUTPUT_FORMAT = "csv"
OUTPUT_PATH = None


def _require_pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise ImportError(
            "This script requires pandas in the Python environment where it is run."
        ) from exc

    return pd


def load_mapping(path: Path) -> dict[str, dict[str, list[str]]]:
    if not path.exists():
        raise FileNotFoundError(f"Input mapping does not exist: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("Expected the top-level mapping to be a JSON object.")

    return data


def extract_variable(json_path: str, frequency: str) -> str:
    """Extract the variable token that follows the frequency token."""
    filename = Path(json_path).name

    if filename.endswith(".json"):
        filename = filename[: -len(".json")]

    if filename.endswith(".kerchunk"):
        filename = filename[: -len(".kerchunk")]
    elif filename.endswith("kerchunk"):
        filename = filename[: -len("kerchunk")]

    parts = filename.split(".")

    try:
        freq_index = parts.index(frequency)
    except ValueError:
        return "unknown"

    if freq_index + 1 >= len(parts):
        return "unknown"

    return parts[freq_index + 1]


def build_dataframe(
    freq_to_json_to_netcdf: dict[str, dict[str, list[str]]],
) -> "pd.DataFrame":
    pd = _require_pandas()
    records: list[dict[str, Any]] = []

    for frequency, json_to_netcdf in freq_to_json_to_netcdf.items():
        if not isinstance(json_to_netcdf, dict):
            continue

        for json_path, filepaths in json_to_netcdf.items():
            normalized_filepaths = sorted(set(filepaths or []))
            records.append(
                {
                    "frequency": frequency,
                    "variable": extract_variable(json_path, frequency),
                    "json_path": json_path,
                    "filepaths": normalized_filepaths,
                    "num_files": len(normalized_filepaths),
                }
            )

    dataframe = pd.DataFrame.from_records(
        records,
        columns=["frequency", "variable", "json_path", "filepaths", "num_files"],
    )

    if dataframe.empty:
        return dataframe

    return dataframe.sort_values(
        by=["frequency", "variable", "num_files", "json_path"],
        ascending=[True, True, False, True],
        kind="stable",
    ).reset_index(drop=True)


def resolve_output_path(
    input_path: Path, output_path: Path | None = None, output_format: str = "csv"
) -> Path:
    if output_path is not None:
        return output_path

    suffix = ".csv" if output_format == "csv" else ".json"
    return input_path.with_name(f"{input_path.stem}_table{suffix}")


def write_output(
    dataframe: "pd.DataFrame", output_path: Path, output_format: str
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_format == "csv":
        csv_ready = dataframe.copy()
        csv_ready["filepaths"] = csv_ready["filepaths"].apply(
            lambda paths: json.dumps(paths)
        )
        csv_ready.to_csv(output_path, index=False)
        return

    records = dataframe.to_dict(orient="records")
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(records, file, indent=2)


def convert_mapping(
    input_path: Path | str = INPUT_PATH,
    output_path: Path | str | None = OUTPUT_PATH,
    output_format: str = OUTPUT_FORMAT,
) -> tuple["pd.DataFrame", Path]:
    """Build the flat table and write it to disk.

    This function is designed for interactive use, for example:

    >>> from riotai.scripts.json_to_netcdf_table import convert_mapping
    >>> df, path = convert_mapping()
    """
    input_path = Path(input_path).resolve()
    normalized_output_path = (
        Path(output_path).resolve() if output_path is not None else None
    )
    resolved_output_path = resolve_output_path(
        input_path, normalized_output_path, output_format
    ).resolve()

    mapping = load_mapping(input_path)
    dataframe = build_dataframe(mapping)
    write_output(dataframe, resolved_output_path, output_format)

    return dataframe, resolved_output_path


def main() -> tuple["pd.DataFrame", Path]:
    dataframe, output_path = convert_mapping()
    print(f"Wrote {len(dataframe)} rows to {output_path}")
    return dataframe, output_path


if __name__ == "__main__":
    main()
