#%%
import xcdat as xc


nc_path = "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/HighResMIP/ECMWF/ECMWF-IFS-HR/highresSST-present/r5i1p1f1/Amon/pr/gr/v20181119"
kc_path = "/global/cfs/projectdirs/m4931/kerchunk/pr/highresSST-present/mon/CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119.kerchunk.json"

#%%
ds_kc = xc.open_dataset(kc_path, engine="kerchunk", chunks={})
ds_nc = xc.open_mfdataset(nc_path, engine="netcdf4", chunks={})

#%%
ds_kc.time
# %%
ds_nc.time
#%%