from pathlib import Path

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

# Open all NetCDF files in NETCDF_DIR as xarray Dataset objects.
netcdf_files = sorted(NETCDF_DIR.glob("*.nc"))
ds_nc = xr.open_mfdataset(netcdf_files, chunks={}, engine="netcdf4", data_vars="all")


# Open the newly generated Kerchunk reference file as an xarray Dataset.
ds_kc = xr.open_dataset(
    str(KERCHUNK_PATH),
    engine="kerchunk",
    chunks={}
)

# Open the original Kerchunk reference file as an xarray Dataset.
ds_kc_og = xr.open_dataset(
    str(ORIGINAL_KERCHUNK_PATH),
    engine="kerchunk",
    chunks={}
)


print("NetCDF dims:", ds_nc.sizes)
print("Original Kerchunk dims:", ds_kc_og.sizes)
print("New Kerchunk dims:", ds_kc.sizes)