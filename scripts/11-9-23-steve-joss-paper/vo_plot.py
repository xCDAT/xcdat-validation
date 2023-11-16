import xcdat as xc
import numpy as np
import cartopy.crs as ccrs
from cartopy.util import add_cyclic_point
import matplotlib.pyplot as plt

# %% open the dataset
dpath = '/p/user_pub/work/CMIP6/CMIP/E3SM-Project/E3SM-2-0/historical/r1i1p1f1/Amon/ts/gr/v20220830/'
ds = xc.open_mfdataset(dpath)

# %% calculate monthly departures
ds_anom = ds.temporal.departures('ts', freq='month')

# %% compute global average
ds_anom_global = ds_anom.spatial.average('ts')

# %% calculate annual averages
ds_anom_global_ann = ds_anom_global.temporal.group_average('ts', freq='year')

# %% make plot
plt.figure(figsize=(6.5, 8))
font = {'size'   : 11}

plt.rc('font', **font)

# Anomaly map
plt.subplot(2, 1, 1, projection=ccrs.Mollweide())
ts_anom, lon = add_cyclic_point(ds_anom.ts.isel(time=2), coord=ds.lon)
plt.contourf(lon, ds.lat, ts_anom, levels=np.arange(-4, 4.01, 0.25), transform=ccrs.PlateCarree(), cmap=plt.cm.RdBu_r, extend='both')
plt.colorbar(orientation='horizontal', ticks=np.arange(-4., 4.01, 1), shrink=0.9)
ax = plt.gca()
ax.coastlines()
plt.title('')


# Anomaly map
plt.subplot(2, 1, 2)
ds_anom_global.ts.plot(color='gray')
ds_anom_global_ann.ts.plot(color='k')
# update spines
ax = plt.gca()
# Move left and bottom spines outward by 10 points
ax.spines.left.set_position(('outward', 10))
ax.spines.bottom.set_position(('outward', 10))
# Hide the right and top spines
ax.spines.right.set_visible(False)
ax.spines.top.set_visible(False)
# Only show ticks on the left and bottom spines
ax.yaxis.set_ticks_position('left')
ax.xaxis.set_ticks_position('bottom')

# plot labels
f = plt.gcf()
f.text(0.2, 0.96, 'A', fontsize=12)
f.text(0.2, 0.475, 'B', fontsize=12)

plt.tight_layout()
plt.savefig('fig2.png', bbox_inches='tight')
plt.show()


