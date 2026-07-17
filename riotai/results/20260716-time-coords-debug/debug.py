# %%
import csv
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np
import xcdat as xc
from xarray.coding.times import infer_calendar_name


NC_DIR = Path(
    "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/HighResMIP/"
    "ECMWF/ECMWF-IFS-HR/highresSST-present/r5i1p1f1/Amon/pr/gr/v20181119"
)
KERCHUNK_PATH = Path(
    "/global/cfs/projectdirs/m4931/kerchunk/pr/highresSST-present/mon/"
    "CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1."
    "Amon.pr.gr.v20181119.kerchunk.json"
)
OUTPUT_DIR = Path(__file__).resolve().parent


def expand_templates(value: str, templates: dict) -> str:
    for _ in range(len(templates) + 1):
        expanded = re.sub(
            r"\{\{([^{}]+)\}\}",
            lambda match: str(templates.get(match.group(1), match.group(0))),
            value,
        )
        if expanded == value:
            return value
        value = expanded

    return value


def referenced_nc_file(reference, templates: dict) -> str | None:
    if isinstance(reference, list) and reference and isinstance(reference[0], str):
        candidate = reference[0]
    elif isinstance(reference, str) and ".nc" in reference:
        candidate = reference
    else:
        return None

    candidate = expand_templates(candidate, templates)
    match = re.search(r"[^\"'\s]+?\.nc(?:\?[^\"'\s]*)?", candidate)
    return match.group(0) if match else None


def source_path(source: str) -> Path:
    parsed = urlparse(source)
    path = parsed.path if parsed.scheme else source.split("?", maxsplit=1)[0]
    return Path(unquote(path))


def read_kerchunk_sources(path: Path) -> list[str]:
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)

    references = data.get("refs", data)
    templates = data.get("templates", {})
    sources = {
        source
        for reference in references.values()
        if (source := referenced_nc_file(reference, templates)) is not None
    }
    return sorted(sources)


def calendar_types(time_coordinate) -> tuple[str | None, str]:
    declared = time_coordinate.encoding.get("calendar")
    if declared is None:
        declared = time_coordinate.attrs.get("calendar")

    return declared, infer_calendar_name(time_coordinate.values)


def time_units(time_coordinate) -> str | None:
    return time_coordinate.encoding.get("units") or time_coordinate.attrs.get("units")


def calendar_month(value) -> str:
    if isinstance(value, np.datetime64):
        return np.datetime_as_string(value, unit="M")

    return f"{value.year:04d}-{value.month:02d}"


def write_summary(path: Path, metrics: dict) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("metric", "value"))
        writer.writerows(metrics.items())


def write_file_differences(
    path: Path, local_only: list[str], kerchunk_only: list[str]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("difference", "filename"))
        writer.writerows(("local_only", name) for name in local_only)
        writer.writerows(("kerchunk_only", name) for name in kerchunk_only)


def write_time_differences(path: Path, comparisons: dict[str, Counter]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("comparison", "coordinate", "count"))
        for comparison, differences in comparisons.items():
            writer.writerows(
                (comparison, str(value), differences[value])
                for value in sorted(differences)
            )


def main() -> None:
    local_files = sorted(NC_DIR.glob("*.nc"))
    if not local_files:
        raise FileNotFoundError(f"No NetCDF files found under {NC_DIR}")

    sources = read_kerchunk_sources(KERCHUNK_PATH)
    source_paths = [source_path(source) for source in sources]
    local_names = {path.name for path in local_files}
    kerchunk_names = {path.name for path in source_paths}
    local_only_files = sorted(local_names - kerchunk_names)
    kerchunk_only_files = sorted(kerchunk_names - local_names)

    with (
        xc.open_dataset(
            str(KERCHUNK_PATH), engine="kerchunk", chunks={}
        ) as ds_kc,
        xc.open_mfdataset(
            [str(path) for path in local_files], engine="netcdf4", chunks={}
        ) as ds_nc,
    ):
        nc_time_values = ds_nc["time"].values.ravel()
        kc_time_values = ds_kc["time"].values.ravel()
        nc_time_counts = Counter(nc_time_values)
        kc_time_counts = Counter(kc_time_values)
        nc_month_counts = Counter(
            calendar_month(value) for value in ds_nc["time"].values
        )
        kc_month_counts = Counter(
            calendar_month(value) for value in ds_kc["time"].values
        )
        differences = {
            "exact_netcdf_only": nc_time_counts - kc_time_counts,
            "exact_kerchunk_only": kc_time_counts - nc_time_counts,
            "month_netcdf_only": nc_month_counts - kc_month_counts,
            "month_kerchunk_only": kc_month_counts - nc_month_counts,
        }

        nc_declared_calendar, nc_inferred_calendar = calendar_types(ds_nc["time"])
        kc_declared_calendar, kc_inferred_calendar = calendar_types(ds_kc["time"])
        nc_only_count = sum(differences["exact_netcdf_only"].values())
        kc_only_count = sum(differences["exact_kerchunk_only"].values())
        time_length_difference = ds_nc.sizes["time"] - ds_kc.sizes["time"]

        metrics = {
            "netcdf_directory": NC_DIR,
            "kerchunk_json": KERCHUNK_PATH,
            "local_netcdf_file_count": len(local_files),
            "kerchunk_source_file_count": len(sources),
            "kerchunk_sources_in_netcdf_directory": all(
                path.parent == NC_DIR for path in source_paths
            ),
            "file_counts_match": len(local_files) == len(sources),
            "source_filenames_match": local_names == kerchunk_names,
            "local_only_file_count": len(local_only_files),
            "kerchunk_only_file_count": len(kerchunk_only_files),
            "netcdf_time_length": ds_nc.sizes["time"],
            "kerchunk_time_length": ds_kc.sizes["time"],
            "time_length_difference": time_length_difference,
            "netcdf_time_start": min(nc_time_values),
            "netcdf_time_end": max(nc_time_values),
            "kerchunk_time_start": min(kc_time_values),
            "kerchunk_time_end": max(kc_time_values),
            "netcdf_time_units": time_units(ds_nc["time"]),
            "kerchunk_time_units": time_units(ds_kc["time"]),
            "netcdf_declared_calendar": nc_declared_calendar,
            "kerchunk_declared_calendar": kc_declared_calendar,
            "declared_calendars_match": nc_declared_calendar
            == kc_declared_calendar,
            "netcdf_inferred_calendar": nc_inferred_calendar,
            "kerchunk_inferred_calendar": kc_inferred_calendar,
            "inferred_calendars_match": nc_inferred_calendar
            == kc_inferred_calendar,
            "exact_time_coordinates_match": nc_time_counts == kc_time_counts,
            "calendar_months_match": nc_month_counts == kc_month_counts,
            "netcdf_unique_month_count": len(nc_month_counts),
            "kerchunk_unique_month_count": len(kc_month_counts),
            "netcdf_duplicate_month_occurrences": sum(
                count - 1 for count in nc_month_counts.values() if count > 1
            ),
            "kerchunk_duplicate_month_occurrences": sum(
                count - 1 for count in kc_month_counts.values() if count > 1
            ),
            "netcdf_only_timestamp_count": nc_only_count,
            "kerchunk_only_timestamp_count": kc_only_count,
            "exact_difference_reconciles": nc_only_count - kc_only_count
            == time_length_difference,
            "netcdf_only_month_count": sum(
                differences["month_netcdf_only"].values()
            ),
            "kerchunk_only_month_count": sum(
                differences["month_kerchunk_only"].values()
            ),
        }

    output_paths = {
        "summary": OUTPUT_DIR / "comparison_summary.csv",
        "files": OUTPUT_DIR / "file_differences.csv",
        "times": OUTPUT_DIR / "time_differences.csv",
    }
    write_summary(output_paths["summary"], metrics)
    write_file_differences(
        output_paths["files"], local_only_files, kerchunk_only_files
    )
    write_time_differences(output_paths["times"], differences)

    print(f"Files: {len(local_files)} NetCDF, {len(sources)} Kerchunk sources")
    print(
        f"Times: {metrics['netcdf_time_length']} NetCDF, "
        f"{metrics['kerchunk_time_length']} Kerchunk"
    )
    for label, path in output_paths.items():
        print(f"{label.capitalize()} CSV: {path}")


if __name__ == "__main__":
    main()