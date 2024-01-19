"""
This script checks the shapes of the variables in each dataset to ensure
consistency in time coordinates.

The 7 GB and 12 GB datasets do not have a `plev` Z axis. The 12 GB dataset has
the most number of time coordinates. The rest of the datasets are pretty consistent
with time coordinates and plev, and the number of lat/lon coordinates scale up
appropriately with the file size.
"""
import os
from glob import glob

import xarray as xr
import xcdat as xc

# Directories
fp_7gb = "/p/css03/esgf_publish/CMIP6/CMIP/NCAR/CESM2/historical/r1i1p1f1/day/tas/gn/v20190308/"
fp_12gb = "/p/css03/esgf_publish/CMIP6/CMIP/MRI/MRI-ESM2-0/amip/r1i1p1f1/3hr/tas/gn/v20190829/"
fp_22gb = "/p/css03/esgf_publish/CMIP6/CMIP/MOHC/UKESM1-0-LL/historical/r5i1p1f3/day/ta/gn/v20191115/"
fp_50gb = "/p/css03/esgf_publish/CMIP6/CMIP/NCAR/CESM2/historical/r1i1p1f1/day/ta/gn/v20190308/"
fp_105gb = "/p/css03/esgf_publish/CMIP6/CMIP/MOHC/HadGEM3-GC31-MM/historical/r2i1p1f3/day/ta/gn/v20191218"

# Filepaths
glob_7gb = glob(os.path.join(fp_7gb, "*.nc"))
glob_12gb = glob(os.path.join(fp_12gb, "*.nc"))
glob_22gb = glob(os.path.join(fp_22gb, "*.nc"))
glob_50gb = glob(os.path.join(fp_50gb, "*.nc"))
glob_105gb = glob(os.path.join(fp_105gb, "*.nc"))

# %%
# 7 GB
# SerializationWarning: variable 'ta' has multiple fill values {1e+20, 1e+20}, decoding all values to NaN.
ds_7gb = xc.open_mfdataset(
    glob_7gb, chunks={"time": "auto"}, add_bounds=["X", "Y", "T"], parallel=True
)

# Frozen({'time': 60226, 'lat': 192, 'lon': 288})
print(ds_7gb.tas.sizes)

# 12 GB
ds_12gb = xc.open_mfdataset(
    glob_12gb, chunks={"time": "auto"}, add_bounds=["X", "Y", "T"], parallel=True
)

# Frozen({'time': 105192, 'lat': 160, 'lon': 320})
print(ds_12gb.tas.sizes)

# 22 GB
ds_22gb = xc.open_mfdataset(
    glob_22gb, chunks={"time": "auto"}, add_bounds=["X", "Y", "T"], parallel=True
)

# Frozen({'time': 59400, 'plev': 8, 'lat': 144, 'lon': 192})
print(ds_22gb.ta.sizes)

# 50 GB
ds_50gb = xc.open_mfdataset(
    glob_50gb, chunks={"time": "auto"}, add_bounds=["X", "Y", "T"], parallel=True
)

# Frozen({'time': 60226, 'plev': 8, 'lat': 192, 'lon': 288})
print(ds_50gb.ta.sizes)

# 105 GB
ds_105gb = xc.open_mfdataset(
    glob_105gb, chunks={"time": "auto"}, add_bounds=["X", "Y", "T"], parallel=True
)

# Frozen({'time': 59400, 'plev': 8, 'lat': 324, 'lon': 432})
print(ds_105gb.ta.sizes)
