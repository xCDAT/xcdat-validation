#%%
import cdms2
import cdutil
import numpy as np
import xcdat

# %% explicit method
fn = '/p/user_pub/climate_work/pochedley1/surface/gistemp1200_GHCNv4_ERSSTv5.nc'
offset = 270.
v = "tempanomaly"
#%%
# open dataset
ds = xcdat.open_dataset(fn)
encoding = ds[v].encoding
ds[v] = ds[v].astype("float32")
ds[v].encoding = encoding

# Apply fill value
fill_value = ds[v].encoding["_FillValue"]
scale_factor = ds[v].encoding["scale_factor"]# Apply the fill value
ds[v] = ds[v].fillna(fill_value * scale_factor)


# Apply offset
ds[v] = np.squeeze(ds[v]) + offset

# get weights
weights = ds.spatial.get_weights(axis=['Y', 'X'], lat_bounds=None, lon_bounds=None)

# reshape to match the data array
ntime = len(ds['time'])
weights = np.tile(np.expand_dims(weights, axis=0), (ntime, 1, 1))
weights = np.where(~np.isnan(ds[v]), weights, 0.)

# calculate spatial average
numerator = np.sum(weights*ds[v], axis=(1, 2))
denominator = np.sum(weights, axis=(1, 2))
ts_explicit = np.array(numerator / denominator)

# tidy up
ds.close()

#%%
ds_cdat = cdms2.open(fn)
ts = np.squeeze(ds_cdat(v)) + offset
ts_cdat = cdutil.averager(ts, axis="xy")

np.testing.assert_allclose(ts_explicit, ts_cdat.data, rtol=0, atol=0)

# %%
