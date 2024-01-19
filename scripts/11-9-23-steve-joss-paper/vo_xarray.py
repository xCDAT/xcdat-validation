import numpy as np
import xarray as xr

# 1. Open the dataset.
dpath = (
    "/p/user_pub/work/CMIP6/CMIP/E3SM-Project/"
    "E3SM-2-0/historical/r1i1p1f1/Amon/ts/gr/v20220830/"
)
ds = xr.open_mfdataset(dpath + "*.nc")

# 2. Calculate monthly departures.
ts_mon = ds.ts.groupby("time.month")
ts_mon_clim = ts_mon.mean(dim="time")
ts_anom = ts_mon - ts_mon_clim

# 3. Compute global average.
coslat = np.cos(np.deg2rad(ds.lat))
ts_anom_wgt = ts_anom.weighted(coslat)
ts_anom_global = ts_anom_wgt.mean(dim="lat").mean(dim="lon")

# 4. Calculate annual averages.
# ncar.github.io/esds/posts/2021/yearly-averages-xarray/
mon_len = ts_anom_global.time.dt.days_in_month
mon_len_by_year = mon_len.groupby("time.year")
wgts = mon_len_by_year / mon_len_by_year.sum()

temp_sum = ts_anom_global * wgts
temp_sum = temp_sum.resample(time="AS").sum(dim="time")
denom_sum = (wgts).resample(time="AS").sum(dim="time")

ts_anom_global_ann = temp_sum / denom_sum
