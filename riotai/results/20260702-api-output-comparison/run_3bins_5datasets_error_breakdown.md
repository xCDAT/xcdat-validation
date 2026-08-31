# Run 3bins Error Breakdown by Dataset

This report was derived from:

- `run_3bins_5datasets.csv`
- `run_3bins_5datasets_summary.md`

## Overall Summary

Run configuration:

- target_frequency: `Amon`
- bins: `25-49,50-99,100-149`
- datasets_per_bin: `5`
- fixed_timesteps: `240`
- operations: `temporal,spatial,horizontal,vertical`

Top-level results:

- Total rows: `60`
- Passed all checks: `44`
- Failed validation checks: `6`
- Execution errors: `4`
- Skipped rows: `6`

Breakdown by operation:

| operation | total | passed | failed_checks | errors | skipped |
| --- | ---: | ---: | ---: | ---: | ---: |
| temporal | 15 | 13 | 2 | 0 | 0 |
| spatial | 15 | 13 | 2 | 0 | 0 |
| horizontal | 15 | 13 | 2 | 0 | 0 |
| vertical | 15 | 5 | 0 | 4 | 6 |

Top-level findings:

- Validation failures are concentrated in 2 HighResMIP ECMWF datasets, each failing `horizontal`, `spatial`, and `temporal`.
- Execution errors are concentrated in `vertical`, with the same `temp_unique` multi-chunk `apply_ufunc` failure occurring in 4 datasets.
- Skipped rows are all `vertical` cases with `skip_reason=missing_vertical_axis`.
- For the ECMWF validation failures, the dominant pattern is time-axis disagreement between kerchunk and NetCDF, including first-timestep mismatches and temporal outputs with `13` kerchunk years versus `20` NetCDF years.

Scope of this breakdown:

- This file details the `6` validation failures and `4` execution errors dataset by dataset.
- The `6` skipped vertical rows are summarized here for context but are not expanded as dataset error sections below.

## Datasets With Validation Failures (6 total)

### `CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119`

Affected operations: `horizontal`, `spatial`, `temporal`

Source paths:

- Kerchunk JSON: `/global/cfs/projectdirs/m4931/kerchunk/pr/highresSST-present/mon/CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119.kerchunk.json`
- NetCDF source dir: `/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/HighResMIP/ECMWF/ECMWF-IFS-HR/highresSST-present/r5i1p1f1/Amon/pr/gr/v20181119`
- Example NetCDF files: `pr_Amon_ECMWF-IFS-HR_highresSST-present_r5i1p1f1_gr_195001-195012.nc`, `pr_Amon_ECMWF-IFS-HR_highresSST-present_r5i1p1f1_gr_195101-195112.nc`

Interpretation note:

- Direct inspection of the kerchunk JSON shows `time/.zarray`, `time/.zattrs`, and `time/0` are present, so the problem is better described as a kerchunk time-axis mismatch or truncation issue rather than a completely missing time coordinate.
- The validation symptoms are consistent with that: horizontal and spatial runs disagree on the first time value (`1950-01-16 12:00:00` vs `1951-01-16 12:00:00`), while temporal output collapses to shape `[13, 361, 720]` on kerchunk versus `[20, 361, 720]` on NetCDF.

- `horizontal`
  - Failure categories: `coordinate_mismatch`, `data_mismatch`
  - Match flags: `structure_match=False`, `dims_match=True`, `dtype_match=True`, `coords_match=False`, `data_match=False`
  - Output structure matched on dims and dtype: dims `[time, lat, lon]` vs `[time, lat, lon]`, shape `[240, 45, 90]` vs `[240, 45, 90]`, dtype `float32` vs `float32`
  - Exact coordinate issue: time coordinate mismatch at `flat_index=0`, kerchunk=`1950-01-16 12:00:00`, netcdf=`1951-01-16 12:00:00`
  - Exact data issue: `mismatching_elements=965770.0`, `mismatching_percent=99.35905349794238`, `max_abs_diff=0.0006744196289218962`, `max_rel_diff=454259.0625`, `nan_mismatch_count=315900.0`

- `spatial`
  - Failure categories: `coordinate_mismatch`, `data_mismatch`
  - Match flags: `structure_match=False`, `dims_match=True`, `dtype_match=True`, `coords_match=False`, `data_match=False`
  - Output structure matched on dims and dtype: dims `[time]` vs `[time]`, shape `[240]` vs `[240]`, dtype `float64` vs `float64`
  - Exact coordinate issue: time coordinate mismatch at `flat_index=0`, kerchunk=`1950-01-16 12:00:00`, netcdf=`1951-01-16 12:00:00`
  - Exact data issue: `mismatching_elements=240.0`, `mismatching_percent=100.0`, `max_abs_diff=2.5335769050407314e-06`, `max_rel_diff=0.0749420825783765`, `nan_mismatch_count=78.0`

- `temporal`
  - Failure categories: `metadata_structure_mismatch`, `coordinate_mismatch`, `data_mismatch`
  - Match flags: `structure_match=False`, `dims_match=False`, `dtype_match=True`, `coords_match=False`, `data_match=False`
  - Exact structure issue: dims `[time, lat, lon]` vs `[time, lat, lon]`, but shape `[13, 361, 720]` vs `[20, 361, 720]`
  - Exact coordinate issue: time coordinate shape mismatch, kerchunk `left_shape=[13]` vs netcdf `right_shape=[20]`

### `CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json`

Affected operations: `horizontal`, `spatial`, `temporal`

Source paths:

- Kerchunk JSON: `/global/cfs/projectdirs/m4931/kerchunk/hus/hist-1950/mon/CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json`
- NetCDF source dir: `/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/HighResMIP/ECMWF/ECMWF-IFS-HR/hist-1950/r1i1p1f1/Amon/hus/gr/v20170915`
- Example NetCDF files: `hus_Amon_ECMWF-IFS-HR_hist-1950_r1i1p1f1_gr_195001-195012.nc`, `hus_Amon_ECMWF-IFS-HR_hist-1950_r1i1p1f1_gr_195101-195112.nc`

Interpretation note:

- Direct inspection of the kerchunk JSON shows `time/.zarray`, `time/.zattrs`, and `time/0` are present, so this also looks like a kerchunk time-axis mismatch or truncation issue rather than a fully absent time coordinate.
- The validation symptoms match the previous ECMWF case: horizontal and spatial runs disagree on the first time value (`1950-01-16 12:00:00` vs `1951-01-16 12:00:00`), while temporal output collapses to shape `[13, 19, 361, 720]` on kerchunk versus `[20, 19, 361, 720]` on NetCDF.

- `horizontal`
  - Failure categories: `coordinate_mismatch`, `data_mismatch`
  - Match flags: `structure_match=False`, `dims_match=True`, `dtype_match=True`, `coords_match=False`, `data_match=False`
  - Output structure matched on dims and dtype: dims `[time, plev, lat, lon]` vs `[time, plev, lat, lon]`, shape `[240, 19, 45, 90]` vs `[240, 19, 45, 90]`, dtype `float32` vs `float32`
  - Exact coordinate issue: time coordinate mismatch at `flat_index=0`, kerchunk=`1950-01-16 12:00:00`, netcdf=`1951-01-16 12:00:00`
  - Exact data issue: `mismatching_elements=18125812.0`, `mismatching_percent=98.14713017110678`, `max_abs_diff=0.015414523892104626`, `max_rel_diff=32.17081832885742`, `nan_mismatch_count=6002100.0`

- `spatial`
  - Failure categories: `coordinate_mismatch`, `data_mismatch`
  - Match flags: `structure_match=False`, `dims_match=True`, `dtype_match=True`, `coords_match=False`, `data_match=False`
  - Output structure matched on dims and dtype: dims `[time, plev]` vs `[time, plev]`, shape `[240, 19]` vs `[240, 19]`, dtype `float64` vs `float64`
  - Exact coordinate issue: time coordinate mismatch at `flat_index=0`, kerchunk=`1950-01-16 12:00:00`, netcdf=`1951-01-16 12:00:00`
  - Exact data issue: `mismatching_elements=4433.0`, `mismatching_percent=97.21491228070175`, `max_abs_diff=0.000878496923550005`, `max_rel_diff=0.3080181100053374`, `nan_mismatch_count=1482.0`

- `temporal`
  - Failure categories: `metadata_structure_mismatch`, `coordinate_mismatch`, `data_mismatch`
  - Match flags: `structure_match=False`, `dims_match=False`, `dtype_match=True`, `coords_match=False`, `data_match=False`
  - Exact structure issue: dims `[time, plev, lat, lon]` vs `[time, plev, lat, lon]`, but shape `[13, 19, 361, 720]` vs `[20, 19, 361, 720]`
  - Exact coordinate issue: time coordinate shape mismatch, kerchunk `left_shape=[13]` vs netcdf `right_shape=[20]`

## Datasets With Execution Errors (4 total)

All execution errors occurred in the `vertical` operation and share the same error pattern:

- `error_type=operation_failed_both_backends`
- Both backends failed with: `vertical_operation_failed: dimension temp_unique on 0th function argument to apply_ufunc with dask='parallelized' consists of multiple chunks, but is also a core dimension`
- Suggested fix from the error message: rechunk to a single chunk along `temp_unique` with `.chunk(dict(temp_unique=-1))`, or pass `allow_rechunk=True` in `dask_gufunc_kwargs` with the stated memory-usage caveat

### `CMIP6.CMIP.FIO-QLNM.FIO-ESM-2-0.piControl.r1i1p1f1.Amon.hus.gn.kerchunk.json`

Source paths:

- Kerchunk JSON: `/global/cfs/projectdirs/m4931/kerchunk/hus/piControl/mon/CMIP6.CMIP.FIO-QLNM.FIO-ESM-2-0.piControl.r1i1p1f1.Amon.hus.gn.kerchunk.json`
- NetCDF source dir: `/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/CMIP/FIO-QLNM/FIO-ESM-2-0/piControl/r1i1p1f1/Amon/hus/gn/v20201016`
- Example NetCDF files: `hus_Amon_FIO-ESM-2-0_piControl_r1i1p1f1_gn_040001-040912.nc`, `hus_Amon_FIO-ESM-2-0_piControl_r1i1p1f1_gn_041001-041912.nc`

- `vertical`
  - Failure category: `backend_execution_mismatch`
  - Exact error: both kerchunk and netcdf raised the same `temp_unique` multi-chunk `apply_ufunc` error during vertical processing

### `CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json`

Source paths:

- Kerchunk JSON: `/global/cfs/projectdirs/m4931/kerchunk/hus/hist-1950/mon/CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json`
- NetCDF source dir: `/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/HighResMIP/ECMWF/ECMWF-IFS-HR/hist-1950/r1i1p1f1/Amon/hus/gr/v20170915`
- Example NetCDF files: `hus_Amon_ECMWF-IFS-HR_hist-1950_r1i1p1f1_gr_195001-195012.nc`, `hus_Amon_ECMWF-IFS-HR_hist-1950_r1i1p1f1_gr_195101-195112.nc`

- `vertical`
  - Failure category: `backend_execution_mismatch`
  - Exact error: both kerchunk and netcdf raised the same `temp_unique` multi-chunk `apply_ufunc` error during vertical processing

### `CMIP6.CMIP.MPI-M.MPI-ESM1-2-HR.piControl.r1i1p1f1.Amon.hur.gn.v20190710`

Source paths:

- Kerchunk JSON: `/global/cfs/projectdirs/m4931/kerchunk/hur/piControl/mon/CMIP6.CMIP.MPI-M.MPI-ESM1-2-HR.piControl.r1i1p1f1.Amon.hur.gn.v20190710.kerchunk.json`
- NetCDF source dir: `/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/CMIP/MPI-M/MPI-ESM1-2-HR/piControl/r1i1p1f1/Amon/hur/gn/v20190710`
- Example NetCDF files: `hur_Amon_MPI-ESM1-2-HR_piControl_r1i1p1f1_gn_185001-185412.nc`, `hur_Amon_MPI-ESM1-2-HR_piControl_r1i1p1f1_gn_185501-185912.nc`

- `vertical`
  - Failure category: `backend_execution_mismatch`
  - Exact error: both kerchunk and netcdf raised the same `temp_unique` multi-chunk `apply_ufunc` error during vertical processing

### `CMIP6.CMIP.MPI-M.MPI-ESM1-2-HR.piControl.r1i1p1f1.Amon.hus.gn.v20190710`

Source paths:

- Kerchunk JSON: `/global/cfs/projectdirs/m4931/kerchunk/hus/piControl/mon/CMIP6.CMIP.MPI-M.MPI-ESM1-2-HR.piControl.r1i1p1f1.Amon.hus.gn.v20190710.kerchunk.json`
- NetCDF source dir: `/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/CMIP/MPI-M/MPI-ESM1-2-HR/piControl/r1i1p1f1/Amon/hus/gn/v20190710`
- Example NetCDF files: `hus_Amon_MPI-ESM1-2-HR_piControl_r1i1p1f1_gn_185001-185412.nc`, `hus_Amon_MPI-ESM1-2-HR_piControl_r1i1p1f1_gn_185501-185912.nc`

- `vertical`
  - Failure category: `backend_execution_mismatch`
  - Exact error: both kerchunk and netcdf raised the same `temp_unique` multi-chunk `apply_ufunc` error during vertical processing
