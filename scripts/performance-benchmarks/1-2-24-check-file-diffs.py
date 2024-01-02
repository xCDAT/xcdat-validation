# %%
import os
from glob import glob

import xarray as xr
import xcdat as xc

paths1 = "/p/css03/esgf_publish/CMIP6/CMIP/NCAR/CESM2/historical/r1i1p1f1/day/ta/gn/v20190308/"
paths2 = "/p/css03/esgf_publish/CMIP6/CMIP/CCCma/CanESM5/historical/r1i1p2f1/CFday/ta/gn/v20190429/"
paths3 = "/p/css03/esgf_publish/CMIP6/CMIP/MOHC/HadGEM3-GC31-MM/historical/r2i1p1f3/day/ta/gn/v20191218"

paths1_glob = glob(os.path.join(paths1, "*.nc"))
paths2_glob = glob(os.path.join(paths2, "*.nc"))
paths3_glob = glob(os.path.join(paths3, "*.nc"))

# %%
# SerializationWarning: variable 'ta' has multiple fill values {1e+20, 1e+20}, decoding all values to NaN.
ds1 = xc.open_mfdataset(
    paths1_glob, chunks={"time": "auto"}, add_bounds=["X", "Y", "T"], parallel=True
)
ds2 = xc.open_mfdataset(
    paths2_glob, chunks={"time": "auto"}, add_bounds=["X", "Y", "T"], parallel=True
)
ds3 = xc.open_mfdataset(
    paths3_glob[0], chunks={"time": "auto"}, add_bounds=["X", "Y", "T"], parallel=True
)

# %%
