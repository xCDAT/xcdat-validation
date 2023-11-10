import xcdat as xc
import xarray as xr
import numpy as np

# %% xcdat computation
# %% open the dataset
dpath = '/p/user_pub/work/CMIP6/CMIP/E3SM-Project/E3SM-2-0/historical/r1i1p1f1/Amon/ts/gr/v20220830/'
ds = xc.open_mfdataset(dpath)

# %% calculate monthly departures
ds_anom = ds.temporal.departures('ts', freq='month')

# %% compute global average
ds_anom_global = ds_anom.spatial.average('ts')

# %% calculate annual averages
ds_anom_global_ann = ds_anom_global.temporal.group_average('ts', freq='year')

# %% xarray computation
# %% open the dataset
dpath = '/p/user_pub/work/CMIP6/CMIP/E3SM-Project/E3SM-2-0/historical/r1i1p1f1/Amon/ts/gr/v20220830/'
ds = xr.open_mfdataset(dpath + '*.nc')

# %% calculate monthly departures
ts_monthly = ds.ts.groupby("time.month") # group by months
ts_monthly_clim = ts_monthly.mean(dim='time') # calculate climatology
ts_anom = ts_monthly - ts_monthly_clim  # difference to determine anomalies

# %% compute global average
coslat = np.cos(np.deg2rad(ds.lat))
ts_anom_weighted = ts_anom.weighted(coslat)
ts_anom_global = ts_anom_weighted.mean(dim='lat').mean(dim='lon')

# %% calculate annual averages (https://ncar.github.io/esds/posts/2021/yearly-averages-xarray/)
days_in_month = ts_anom_global.time.dt.days_in_month
wgts = days_in_month.groupby("time.year") / days_in_month.groupby("time.year").sum()
temp_sum = (ts_anom_global * wgts).resample(time="AS").sum(dim="time")
denominator_sum = (wgts).resample(time="AS").sum(dim="time")
ts_anom_global_ann = temp_sum / denominator_sum

# %% get max absolute errors
print('Getting Max Absolute Errors')
eanom = np.max(np.abs(ds_anom.ts.values - ts_anom.values))
print('MAA for [time, lat, lon] anomaly value: ', eanom)

eanom = np.max(np.abs(ds_anom_global.ts.values - ts_anom_global.values))
print('MAA for [time] annual average anomaly value: ', eanom)

eanom = np.max(np.abs(ds_anom_global_ann.ts.values - ts_anom_global_ann.values))
print('MAA for [time] global average annual average anomaly value: ', eanom)
