import xarray as xr

path = "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk/tas/historical/mon/CMIP6.CMIP.CNRM-CERFACS.CNRM-CM6-1.historical.r14i1p1f2.Amon.tas.gr.v20191004.kerchunk.json"
ds1 = xr.open_dataset(path, engine="kerchunk")
ds2 = xr.open_dataset(path, engine="kerchunk", chunks={})

#%%
print(ds1.tas)
print(ds2.tas)
# %%
