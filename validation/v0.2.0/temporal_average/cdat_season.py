#%%
# flake8: noqa F401
import cdms2
import cdutil
import numpy as np
import pandas as pd
import xarray as xr
import xcdat  # noqa: F401
from cdms2.tvariable import TransientVariable

# %%
ds = cdms2.open("./input/demo_data/CMIP5_demo_data/psl_Amon_ACCESS1-0_historical_r1i1p1_185001-200512.nc")
t_var = ds("psl")

#%%
season = cdutil.SEASONALCYCLE.climatology(t_var)
annual = cdutil.ANNUALCYCLE.climatology(t_var)
#%%
season_times = season.getTime().asComponentTime()
annual_times = annual.getTime().asComponentTime()


#%%
annual = cdutil.ANNUALCYCLE(t_var)


# %%
#%% For October and December
OD = cdutil.times.Seasons("OD")
#%%
OD.climatology(t_var)
OD(t_var)

#%% For January and Feb
JF = cdutil.times.Seasons("JF")
JF.climatology(t_var)
# %%
JJ = cdutil.times.Seasons("JJ")

# %%
JJ
