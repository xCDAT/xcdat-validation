import cartopy.crs as ccrs
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import xcdat as xc
from cartopy.util import add_cyclic_point

# %% open the dataset
dpath = "/p/user_pub/work/CMIP6/CMIP/E3SM-Project/E3SM-2-0/historical/r1i1p1f1/Amon/ts/gr/v20220830/"
ds = xc.open_mfdataset(dpath)

# %% calculate monthly departures
ds_anom = ds.temporal.departures("ts", freq="month")

# %% compute global average
ds_anom_global = ds_anom.spatial.average("ts")

# %% calculate annual averages
ds_anom_global_ann = ds_anom_global.temporal.group_average("ts", freq="year")


# %%
def mycolormap():
    """Combine two colormap to generate a new colormap for blue-white(middle)-yellow-red

    Returns
    -------
    matplotlib colormap
    """
    # Adjust colormap

    # sample the colormaps that you want to use. Use 128 from each so we get 256
    # colors in total
    colors1 = plt.cm.Blues_r(np.linspace(0.0, 1, 127))
    colors2 = plt.cm.YlOrBr(np.linspace(0, 1, 127))

    # add white in the middle
    colors1 = np.append(colors1, [[0, 0, 0, 0]], axis=0)
    colors2 = np.vstack((np.array([0, 0, 0, 0]), colors2))

    # combine them and build a new colormap
    colors = np.vstack((colors1, colors2))
    mymap = mcolors.LinearSegmentedColormap.from_list("my_colormap", colors)

    return mymap


# %% make plot
plt.figure(figsize=(6.5, 8))
font = {"size": 11}

plt.rc("font", **font)

# Anomaly map
plt.subplot(2, 1, 1, projection=ccrs.Mollweide())
ts_anom, lon = add_cyclic_point(ds_anom.ts.isel(time=8), coord=ds_anom.lon)
plt.contourf(
    lon,
    ds_anom.lat,
    ts_anom,
    levels=np.arange(-4, 4.01, 0.25),
    transform=ccrs.PlateCarree(),
    cmap=mycolormap(),
    extend="both",
)
plt.colorbar(
    label="[K]", orientation="horizontal", ticks=np.arange(-4.0, 4.01, 1), shrink=0.9
)
ax = plt.gca()
ax.coastlines()
plt.title("")


# Anomaly map
plt.subplot(2, 1, 2)
ds_anom_global.ts.plot(color="gray")
ds_anom_global_ann.ts.plot(color="k")
# update spines
ax = plt.gca()
# Move left and bottom spines outward by 10 points
ax.spines.left.set_position(("outward", 10))
ax.spines.bottom.set_position(("outward", 10))
# Hide the right and top spines
ax.spines.right.set_visible(False)
ax.spines.top.set_visible(False)
# Only show ticks on the left and bottom spines
ax.yaxis.set_ticks_position("left")
ax.xaxis.set_ticks_position("bottom")
ax.set_ylabel("Surface Temperature Anomalies [K]")

# plot labels
f = plt.gcf()
f.text(0.2, 1.025, "A. Surface Temperature Anomalies (September 1850)", fontsize=12)
f.text(0.2, 0.475, "B. Global Mean Surface Temperature Anomalies", fontsize=12)

plt.tight_layout()
plt.savefig("fig2.png", bbox_inches="tight")
plt.show()
