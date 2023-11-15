# %%
# https://docs.dask.org/en/latest/scheduling.html#standalone-python-scripts
# https://examples.dask.org/xarray.html#Start-Dask-Client-for-Dashboard
from glob import glob

import xcdat as xc
from dask.distributed import Client

dir_path = "/p/css03/esgf_publish/CMIP6/CMIP/NCAR/CESM2/historical/r1i1p1f1/day/tas/gn/v20190308/*.nc"
file_paths = glob(dir_path)
var_key = "tas"

ds = xc.open_mfdataset(file_paths, chunks={"time": "auto"})
ds_res = ds.spatial.average(var_key, axis=["X", "Y"])

# %%
if __name__ == "__main__":
    client = Client()
    ds_res_comp = ds_res.compute()

# %%
# Dask will automatically close the client when the Python kernel terminates.
# https://stackoverflow.com/questions/72179613/does-dask-localcluster-shutdown-when-kernel-restarts
# To manually close, you can also run:
# client.close()
