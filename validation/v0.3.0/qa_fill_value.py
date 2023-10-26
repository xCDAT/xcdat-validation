#%%
import cdms2
import cdutil
import numpy as np
import xcdat

# %% explicit method
fn = '/p/user_pub/climate_work/pochedley1/surface/gistemp1200_GHCNv4_ERSSTv5.nc'
v = "tempanomaly"

#%%
# open dataset
ds = xcdat.open_dataset(fn)

#%%
ds[v].encoding["_FillValue"]
#%%
# xarray does not automatically use the _FillValue
print(ds[v].values[0])

#%%
fill_value = ds.tempanomaly.encoding["_FillValue"]
scale_factor = ds.tempanomaly.encoding["scale_factor"]
# Apply the fill value
ds["tempanomaly_fillna"] = ds.tempanomaly.fillna(fill_value * scale_factor)
print(ds["tempanomaly_fillna"].values[0])

#%%
# Now let's see what CDAT does
ds_cdat = cdms2.open(fn)

#%%
# Check the fill value is the same
ds_cdat(v).fill_value
#%%
# CDAT applies the fill value differently.
print(ds_cdat(v).data[0])


# %%
