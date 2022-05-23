# xCDAT Validation

`validation/` stores Python scripts and Jupyter Notebooks to validate `xarray` and `xCDAT` against `CDAT` packages (`cdms2`, `cdutil`, and `genutil`) CDAT vs. xarray/xCDAT comparison notebooks

## `/prototyping`

The content in this directory explores `xarray` and its capabilities compared to the `CDAT` packages. The main objective was solution pathfinding before development began on`xcdat`.

- `/temporal_average`

  - [Annual cycle](/prototyping/temporal_average/climatology/annual_cycle_cdat_xarray.ipynb)
  - [Annual cycle climatology](/prototyping/temporal_average/climatology/annual_cycle_climatology_cdat_xarray.ipynb)
  - [Annual cycle departure](/prototyping/temporal_average/climatology/annual_cycle_departure_cdat_xarray.ipynb)
  - [Seasonal average](/prototyping/temporal_average/timeseries/seasonal_averages_cdat_xarray.ipynb)

- `/spatial_average`
  - [Spatial average](/prototyping/spatial_average/spatial_averaging_cdat_xarray.ipynb)
- `/landsea_mask`
  - [Land Sea mask](/prototyping/landsea_mask/landsea_mask.ipynb)

## `/v0.2.0`

- `/temporal_average`
  - [Floating point comparisons](/v0.2.0/temporal_average/floating_point_comparisons.ipynb)
  - [Runtime comparisons](/v0.2.0/temporal_average/runtime_comparison.ipynb)
  - [Departures API plot comparisons](/v0.2.0/temporal_average/plot_comparison_annual_cycle_departs.ipynb)

## `/v1.0.0`

- `/horizontal_regridding`
  - [API comparison (CDAT vs. xCDAT)](/v1.0.0/horizontal_regridding/regrid_cdat_xcdat.ipynb)
  - [API comparison (CDAT vs. xarray)](/v1.0.0/horizontal_regridding/regrid_cdat_xarray.ipynb)
  - [API comparison (CDAT vs. xarray vs. xCDAT)](/v1.0.0/horizontal_regridding/regrid_cdat_xarray_xcdat.ipynb)

- `/temporal_average`
  - [Simple averages with time dimension removed](/v1.0.0/temporal_average/floating_point_comparison.ipynb)
