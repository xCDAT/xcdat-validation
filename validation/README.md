# xCDAT Validation

`validation/` stores Python scripts and Jupyter Notebooks to validate `xarray` and `xCDAT` against `CDAT` packages (`cdms2`, `cdutil`, and `genutil`) CDAT vs. xarray/xCDAT comparison notebooks

## `/prototyping`

The content in this directory explores `xarray` and its capabilities compared to the `CDAT` packages. The main objective was solution pathfinding before development began on`xcdat`.

- `/temporal_average`

  - [Annual cycle](/validation/prototyping/temporal_average/climatology/annual_cycle_cdat_xarray.ipynb)
  - [Annual cycle climatology](/validation/prototyping/temporal_average/climatology/annual_cycle_climatology_cdat_xarray.ipynb)
  - [Annual cycle departure](/validation/prototyping/temporal_average/climatology/annual_cycle_departure_cdat_xarray.ipynb)
  - [Seasonal average](/validation/prototyping/temporal_average/timeseries/seasonal_averages_cdat_xarray.ipynb)

- `/spatial_average`
  - [Spatial average](/validation/prototyping/spatial_average/spatial_averaging_cdat_xarray.ipynb)

- `/landsea_mask`
  - [Land Sea mask](/validation/prototyping/landsea_mask/landsea_mask.ipynb)

## `/v0.1.0`

- [Demo opening and analyzing datasets](/validation/v0.1.0/demo_open_dataset.ipynb)

## `/v0.2.0`

- `/temporal_average`
  - [Floating point comparisons](/validation/v0.2.0/temporal_average/floating_point_comparisons.ipynb)
  - [Runtime comparisons](/validation/v0.2.0/temporal_average/runtime_comparison.ipynb)
  - [Departures API plot comparisons](/validation/v0.2.0/temporal_average/plot_comparison_annual_cycle_departs.ipynb)

## `/v1.0.0`

- `/horizontal_regridding`
  - [API comparison (CDAT vs. xCDAT)](/validation/v1.0.0/horizontal_regridding/regrid_cdat_xcdat.ipynb)
  - [API comparison (CDAT vs. xarray)](/validation/v1.0.0/horizontal_regridding/regrid_cdat_xarray.ipynb)
  - [API comparison (CDAT vs. xarray vs. xCDAT)](/validation/v1.0.0/horizontal_regridding/regrid_cdat_xarray_xcdat.ipynb)

- `/temporal_average`
  - [Simple averages floating point comparison](/validation/v1.0.0/temporal_average/floating_point_comparison.ipynb)
