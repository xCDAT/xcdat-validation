"""Compare time coordinates exposed by Kerchunk, netCDF4, and VirtualiZarr.

Requires Python, xarray, kerchunk, netCDF4, virtualizarr, obstore, and an
ObjectStoreRegistry provider: virtualizarr.registry for 2.0 or obspec-utils for
newer VirtualiZarr. Only the time coordinate is evaluated; precipitation data
are not loaded.

Environment setup (example):
conda create -n mvce python xarray kerchunk netCDF4 virtualizarr obstore obspec-utils

"""

from pathlib import Path
import sys

import xarray as xr
from obstore.store import LocalStore
from virtualizarr import open_virtual_dataset
from virtualizarr.parsers.kerchunk.json import KerchunkJSONParser

try:
    from virtualizarr.registry import ObjectStoreRegistry
except ImportError:
    from obspec_utils.registry import ObjectStoreRegistry


NC_DIR = Path(
    "/global/cfs/cdirs/e3sm/www/vo13/kerchunk-mvce/v20181119"
)
KERCHUNK_PATH = Path(
    "/global/cfs/cdirs/e3sm/www/vo13/kerchunk-mvce/CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119.kerchunk.json"
)


def stable_time_value(value: object) -> str:
    """Return a comparable, human-readable representation for datetime-like values."""
    isoformat = getattr(value, "isoformat", None)
    if isoformat is not None:
        try:
            return isoformat(sep=" ")
        except TypeError:
            return isoformat()

    return str(value)


def coordinate_values(dataset: object) -> list[str]:
    """Evaluate only the time coordinate and normalize it for comparison."""
    return [stable_time_value(value) for value in dataset["time"].values]


def coordinate_attribute(dataset: object, name: str) -> object:
    time = dataset["time"]

    return time.attrs.get(name, time.encoding.get(name, "<not set>"))


def print_diagnostics(name: str, dataset: object) -> list[str]:
    values = coordinate_values(dataset)
    months = [value[:7] for value in values]
    duplicate_months = len(months) - len(set(months))
    monotonic = all(left <= right for left, right in zip(values, values[1:]))

    print(f"{name}:")
    print(f"  time length: {len(values)}")
    print(f"  first 3: {values[:3]}")
    print(f"  last 3: {values[-3:]}")
    print(f"  time units: {coordinate_attribute(dataset, 'units')!r}")
    print(f"  time calendar: {coordinate_attribute(dataset, 'calendar')!r}")
    print(f"  monotonic ascending: {monotonic}")
    print(f"  unique months: {len(set(months))}")
    print(f"  duplicate month occurrences: {duplicate_months}")

    return values


def first_mismatch(left: list[str], right: list[str]) -> tuple[int, str, str] | None:
    for index, (left_value, right_value) in enumerate(zip(left, right)):
        if left_value != right_value:
            return index, left_value, right_value

    if len(left) != len(right):
        index = min(len(left), len(right))
        return index, left[index] if index < len(left) else "<end>", right[index] if index < len(right) else "<end>"

    return None


def print_comparison(
    left_name: str, left_values: list[str], right_name: str, right_values: list[str]
) -> None:
    mismatch = first_mismatch(left_values, right_values)
    if mismatch is None:
        if (left_name, right_name) == ("Kerchunk", "netCDF4"):
            print("Coordinate sequences: identical")
        else:
            print(f"{left_name} vs {right_name}: identical")
        return

    index, left_value, right_value = mismatch
    if (left_name, right_name) == ("Kerchunk", "netCDF4"):
        print(
            "First mismatch: "
            f"index {index} (Kerchunk={left_value}, netCDF4={right_value})"
        )
        return
    print(
        f"First mismatch ({left_name} vs {right_name}): "
        f"index {index} ({left_name}={left_value}, {right_name}={right_value})"
    )


def main() -> int:
    if not NC_DIR.is_dir():
        print(f"ERROR: NetCDF directory does not exist: {NC_DIR}", file=sys.stderr)
        return 2

    if not KERCHUNK_PATH.is_file():
        print(
            f"ERROR: Kerchunk reference file does not exist: {KERCHUNK_PATH}",
            file=sys.stderr,
        )
        return 2

    nc_paths = sorted(NC_DIR.glob("*.nc"))
    if not nc_paths:
        print(f"ERROR: no NetCDF (*.nc) files found under: {NC_DIR}", file=sys.stderr)
        return 2

    print(f"Source NetCDF file count: {len(nc_paths)}")
    ds_kerchunk = None
    ds_netcdf4 = None
    ds_virtualizarr = None

    try:
        try:
            ds_kerchunk = xr.open_dataset(
                str(KERCHUNK_PATH), engine="kerchunk", chunks={}
            )
        except Exception as error:
            print(f"ERROR: failed to open Kerchunk dataset: {error}", file=sys.stderr)
            return 1
        try:
            ds_netcdf4 = xr.open_mfdataset(
                [str(path) for path in nc_paths], engine="netcdf4", chunks={}
            )
        except Exception as error:
            print(f"ERROR: failed to open netCDF4 dataset: {error}", file=sys.stderr)
            return 1

        try:
            ds_virtualizarr = open_virtual_dataset(
                url=KERCHUNK_PATH.resolve().as_uri(),
                registry=ObjectStoreRegistry({"file://": LocalStore()}),
                parser=KerchunkJSONParser(),
                loadable_variables=["time"],
                decode_times=True,
            )
        except Exception as error:
            print(f"ERROR: failed to open VirtualiZarr dataset: {error}", file=sys.stderr)
            return 1

        kerchunk_values = print_diagnostics("Kerchunk", ds_kerchunk)
        netcdf4_values = print_diagnostics("netCDF4", ds_netcdf4)
        virtualizarr_values = print_diagnostics("VirtualiZarr (Kerchunk)", ds_virtualizarr)
        print_comparison("Kerchunk", kerchunk_values, "netCDF4", netcdf4_values)
        print_comparison("VirtualiZarr (Kerchunk)", virtualizarr_values, "Kerchunk", kerchunk_values)
        print_comparison("VirtualiZarr (Kerchunk)", virtualizarr_values, "netCDF4", netcdf4_values)
        return 0
    finally:
        for dataset in (ds_kerchunk, ds_netcdf4, ds_virtualizarr):
            if dataset is not None:
                dataset.close()


if __name__ == "__main__":
    raise SystemExit(main())
