#!/usr/bin/env python3
"""Create and validate a Kerchunk reference for monthly precipitation.

The reference is compared with the same source files opened through xarray's
``netcdf4`` engine. Only metadata and coordinate arrays are read; precipitation
chunks are not loaded.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from kerchunk.combine import MultiZarrToZarr
from kerchunk.hdf import SingleHdf5ToZarr
import xarray as xr

# The path to the NetCDF source files used to create the Kerchunk reference.
NETCDF_DIR = Path(
    "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/HighResMIP/"
    "ECMWF/ECMWF-IFS-HR/highresSST-present/r5i1p1f1/Amon/pr/gr/v20181119"
)
# The path to the original Kerchunk reference file with the incorrect time coordinates
# and missing references (50 referenced, 15 missing).
ORIGINAL_KERCHUNK_PATH = Path(
    "/global/cfs/projectdirs/m4931/kerchunk/pr/highresSST-present/mon/"
    "CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1."
    "Amon.pr.gr.v20181119.kerchunk.json"
)
# The path to the newly generated Kerchunk reference file with the correct time coordinates and all references.
KERCHUNK_PATH = Path(__file__).with_name(
    "CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present."
    "r5i1p1f1.Amon.pr.gr.v20181119.kerchunk.json"
)

# The expected number of source NetCDF files referenced in the Kerchunk reference.
EXPECTED_SOURCE_FILE_COUNT = 65


def main() -> None:
    """Create a reference from every source file, then validate it."""
    files = sorted(NETCDF_DIR.glob("*.nc"))
    references = [SingleHdf5ToZarr(str(path), str(path)).translate() for path in files]
    reference = MultiZarrToZarr(
        [str(path) for path in files],
        indicts=references,
        remote_protocol="file",
        coo_map={"time": "cf:time"},
        concat_dims=["time"],
    ).translate()
    reference.setdefault("meta", {})["sources"] = [str(path) for path in files]

    output_path = KERCHUNK_PATH.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as stream:
        json.dump(reference, stream, indent=2)
        stream.write("\n")

    summary = _validate_reference(output_path, files)
    print(f"Wrote and validated {output_path}")
    print(f"Validation summary:\n{summary}")

def _validate_reference(output_path: Path, source_files: list[Path]) -> str:
    """Validate the new reference and report differences in the original one."""
    with output_path.open(encoding="utf-8") as stream:
        reference = json.load(stream)
    _assert_reference_sources(reference, source_files)

    with ORIGINAL_KERCHUNK_PATH.open(encoding="utf-8") as stream:
        original_reference = json.load(stream)

    ds_kerchunk = None
    ds_netcdf4 = None
    ds_kerchunk_og = None

    try:
        ds_kerchunk = xr.open_dataset(str(output_path), engine="kerchunk", chunks={})
        ds_netcdf4 = xr.open_mfdataset(
            [str(path) for path in source_files],
            engine="netcdf4",
            chunks={},
            data_vars="all",
        )
        ds_kerchunk_og = xr.open_dataset(
            str(ORIGINAL_KERCHUNK_PATH), engine="kerchunk", chunks={}
        )
        _assert_datasets_match(ds_kerchunk, ds_netcdf4)
        return _validation_summary(
            source_files,
            ds_kerchunk,
            ds_netcdf4,
            ds_kerchunk_og,
            original_reference,
        )
    finally:
        for dataset in (ds_kerchunk, ds_netcdf4, ds_kerchunk_og):
            if dataset is not None:
                dataset.close()


def _assert_reference_sources(reference: dict, source_files: list[Path]) -> None:
    """Ensure the reference points to exactly the files used to create it."""
    expected = {str(path) for path in source_files}
    metadata_sources = set(reference.get("meta", {}).get("sources", []))
    tuple_sources = _tuple_sources(reference)

    for name, actual in (("metadata", metadata_sources), ("reference tuples", tuple_sources)):
        if actual != expected:
            raise RuntimeError(
                f"{name} do not match the input files "
                f"(missing: {sorted(expected - actual)}; "
                f"unexpected: {sorted(actual - expected)})."
            )


def _tuple_sources(reference: dict) -> set[str]:
    """Return the source paths in non-inline Kerchunk reference tuples."""
    return {
        value[0]
        for value in reference.get("refs", {}).values()
        if isinstance(value, list)
        and len(value) >= 3
        and isinstance(value[0], str)
        and isinstance(value[1], int)
        and isinstance(value[2], int)
    }


def _assert_datasets_match(kerchunk_ds: xr.Dataset, netcdf4_ds: xr.Dataset) -> None:
    """Compare schemas and coordinates without reading data-variable chunks."""
    if dict(kerchunk_ds.sizes) != dict(netcdf4_ds.sizes):
        raise RuntimeError(
            f"Dimensions differ: Kerchunk={dict(kerchunk_ds.sizes)}, "
            f"netCDF4={dict(netcdf4_ds.sizes)}."
        )

    if set(kerchunk_ds.variables) != set(netcdf4_ds.variables):
        raise RuntimeError("Kerchunk and netCDF4 have different variable names.")

    for name in kerchunk_ds.variables:
        kerchunk_var, netcdf4_var = kerchunk_ds[name], netcdf4_ds[name]
        if (kerchunk_var.dims, kerchunk_var.dtype) != (
            netcdf4_var.dims,
            netcdf4_var.dtype,
        ):
            raise RuntimeError(f"Variable schema differs for {name!r}.")

    try:
        xr.testing.assert_identical(
            kerchunk_ds.coords.to_dataset(), netcdf4_ds.coords.to_dataset()
        )
    except AssertionError as error:
        raise RuntimeError(f"Coordinate values or attributes differ: {error}") from error


def _validation_summary(
    source_files: list[Path],
    dataset: xr.Dataset,
    netcdf4_dataset: xr.Dataset,
    original_dataset: xr.Dataset,
    original_reference: dict,
) -> str:
    """Describe the corrected-reference validation and original-reference defects."""
    dimensions = _format_dimensions(dataset)
    variables = ", ".join(sorted(dataset.variables))
    coordinates = ", ".join(sorted(dataset.coords))
    time = dataset["time"]
    time_values = time.values
    units = time.attrs.get("units", time.encoding.get("units", "decoded"))
    calendar = time.attrs.get("calendar", time.encoding.get("calendar", "standard"))

    summary = [
            f"  Source files: {len(source_files)} (metadata and reference tuples match)",
            "  Kerchunk vs netCDF4: MATCH",
            f"    Dimensions: match ({dimensions})",
            f"    Variable names: match ({variables})",
            "    Variable schemas: match (dimensions and dtypes)",
            f"    Coordinates: match ({coordinates})",
            "    Time coordinate: match "
            f"({len(time_values)} values; {time_values[0]} to {time_values[-1]}; "
            f"units={units!r}; calendar={calendar!r})",
    ]
    return "\n".join(
        [*summary, _original_comparison_summary(
            source_files, original_reference, original_dataset, netcdf4_dataset
        )]
    )


def _original_comparison_summary(
    source_files: list[Path],
    original_reference: dict,
    original_dataset: xr.Dataset,
    netcdf4_dataset: xr.Dataset,
) -> str:
    """Describe the expected differences in the known-bad original reference."""
    expected_sources = {str(path) for path in source_files}
    original_sources = _tuple_sources(original_reference)
    missing = sorted(expected_sources - original_sources)
    original_time = list(original_dataset["time"].values)
    netcdf4_time = list(netcdf4_dataset["time"].values)

    lines = [
        "  Original Kerchunk vs netCDF4: DIFFERENT (expected diagnostic)",
        f"    Referenced source files: {len(original_sources)} of {len(source_files)} "
        f"({len(missing)} missing)",
        "    Dimensions: "
        f"{'match' if dict(original_dataset.sizes) == dict(netcdf4_dataset.sizes) else 'different'} "
        f"(original: {_format_dimensions(original_dataset)}; "
        f"netCDF4: {_format_dimensions(netcdf4_dataset)})",
        "    Variable names: "
        f"{'match' if set(original_dataset.variables) == set(netcdf4_dataset.variables) else 'different'}",
        "    Coordinates: "
        f"{'match' if original_dataset.coords.to_dataset().equals(netcdf4_dataset.coords.to_dataset()) else 'different'}",
        "    Dataset values: "
        f"{'match' if original_dataset.equals(netcdf4_dataset) else 'different'} "
        "(Dataset.equals; attributes excluded)",
        f"    Time coordinate: {_time_difference(original_time, netcdf4_time)}",
    ]
    if missing:
        lines.append("    Missing files: " + ", ".join(Path(path).name for path in missing))
    return "\n".join(lines)


def _format_dimensions(dataset: xr.Dataset) -> str:
    """Format dataset dimensions for a summary line."""
    return ", ".join(f"{name}={size}" for name, size in dataset.sizes.items())


def _time_difference(original: list, netcdf4: list) -> str:
    """Describe the first time-coordinate mismatch, if any."""
    for index, (old, new) in enumerate(zip(original, netcdf4)):
        if old != new:
            return (
                f"different at index {index} (original={old}, netCDF4={new}; "
                f"{len(original)} vs {len(netcdf4)} values)"
            )
    if len(original) != len(netcdf4):
        return f"different lengths ({len(original)} vs {len(netcdf4)} values)"
    return f"match ({len(original)} values)"


def run() -> None:
    """Run in a worker thread when called from an IPython/Jupyter kernel."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        main()
    else:
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(main).result()


if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        raise SystemExit(f"error: {error}") from error
