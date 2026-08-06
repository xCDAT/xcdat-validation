"""Reproduce differing time-coordinate counts across three backends.

Requires VirtualiZarr >= 2, xCDAT, and access to the NERSC paths below.
"""

from pathlib import Path

import xcdat as xc
from obspec_utils.registry import ObjectStoreRegistry
from obstore.store import LocalStore
from virtualizarr import open_virtual_mfdataset
from virtualizarr.parsers import HDFParser


NC_DIR = Path(
    "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/HighResMIP/"
    "ECMWF/ECMWF-IFS-HR/highresSST-present/r5i1p1f1/Amon/pr/gr/v20181119"
)
KERCHUNK_PATH = Path(
    "/global/cfs/projectdirs/m4931/kerchunk/pr/highresSST-present/mon/"
    "CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1."
    "Amon.pr.gr.v20181119.kerchunk.json"
)


def main() -> None:
    nc_paths = sorted(NC_DIR.glob("*.nc"))
    if not nc_paths:
        raise FileNotFoundError(f"No NetCDF files found under {NC_DIR}")

    registry = ObjectStoreRegistry({f"file://{NC_DIR}": LocalStore(prefix=NC_DIR)})

    ds_kerchunk = xc.open_dataset(KERCHUNK_PATH, engine="kerchunk", chunks={})
    ds_virtualizarr = open_virtual_mfdataset(
        [path.as_uri() for path in nc_paths],
        registry=registry,
        parser=HDFParser(),
        loadable_variables=["time"],
    )
    ds_netcdf4 = xc.open_mfdataset(
        [str(path) for path in nc_paths], engine="netcdf4", chunks={}
    )

    try:
        for name, dataset in {
            "Kerchunk": ds_kerchunk,
            "VirtualiZarr": ds_virtualizarr,
            "netCDF4": ds_netcdf4,
        }.items():
            print(f"{name}: {dataset.sizes['time']} time coordinates")
    finally:
        ds_kerchunk.close()
        ds_virtualizarr.close()
        ds_netcdf4.close()


if __name__ == "__main__":
    main()
