import numpy as np
import xarray as xr

# 1. Open the dataset.
dpath = (
    "/p/user_pub/work/CMIP6/CMIP/E3SM-Project/"
    "E3SM-2-0/historical/r1i1p1f1/Amon/ts/gr/v20220830/"
)
ds = xr.open_mfdataset(dpath + '*.nc')

# 2. Calculate monthly departures.
ts_monthly = ds.ts.groupby("time.month") # group by months
ts_monthly_clim = ts_monthly.mean(dim='time') # calculate climatology
ts_anom = ts_monthly - ts_monthly_clim  # difference to determine anomalies

# 3. Compute global average.
coslat = np.cos(np.deg2rad(ds.lat))
ts_anom_weighted = ts_anom.weighted(coslat)
ts_anom_global = ts_anom_weighted.mean(dim='lat').mean(dim='lon')

 # 4. Calculate annual averages
 # Source: https://ncar.github.io/esds/posts/2021/yearly-averages-xarray/
days_in_month = ts_anom_global.time.dt.days_in_month
wgts = days_in_month.groupby("time.year") / days_in_month.groupby("time.year").sum()
temp_sum = (ts_anom_global * wgts).resample(time="AS").sum(dim="time")
denominator_sum = (wgts).resample(time="AS").sum(dim="time")
ts_anom_global_ann = temp_sum / denominator_sum

