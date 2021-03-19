#!/bin/env python
# -*- coding: utf-8 -*-

"""

Stephen Po-Chedley 19 March 2021

Example I/O operations with xarray.

@author: pochedls
"""

import xrw
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt

# lets get some dataset paths
dpaths = xrw.get_cmip_paths(mip_era='CMIP6', experiment='historical', variable='tas', frequency='mon', model='CESM2', verbose=False)

decimalTime = np.arange(1979+1/24., 2015, 1/12.)

for dpath in dpaths:
    ds = xr.open_mfdataset(dpath + '*.nc', combine='by_coords')
    print(ds.variant_label)
    tas = ds['tas']
    # subselect satellite era
    tas = tas.sel(time=slice('1979-01-01', '2014-12-31'))
    # generate weights
    lat = tas.lat
    lon = tas.lon
    time = tas.time
    weights = np.cos(np.deg2rad(lat))
    weights.name = 'weights'
    # take weighted average
    tasw = tas.weighted(weights)
    tasm = tasw.mean(('lon', 'lat'))
    # get anomaly
    climatology = tasm.groupby('time.month').mean('time')
    tasma = tasm.groupby('time.month') - climatology
    ds.close()
    # plot time series
    plt.plot(decimalTime, tasma)
plt.xlabel('Year')
plt.ylabel('GMSAT Anomaly [K]')
plt.show()


