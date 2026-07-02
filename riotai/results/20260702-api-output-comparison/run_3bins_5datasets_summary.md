# Backend API Output Comparison Summary

This compares backend API outputs for the same selected CMIP datasets processed through `kerchunk` versus source `netcdf` inputs across `temporal`, `spatial`, `horizontal`, and `vertical` operations.

## Overall Summary

Takeaway: most datasets compare cleanly, and the remaining issues are concentrated in a small number of ECMWF time-axis mismatches plus a shared vertical chunking failure.

- `44/60` rows passed all checks.
- `6` validation failures are concentrated in `2` HighResMIP ECMWF datasets and affect `horizontal`, `spatial`, and `temporal`.
- The ECMWF failures point to a kerchunk time-axis mismatch or truncation pattern: first-timestep disagreement (`1950-01-16 12:00:00` vs `1951-01-16 12:00:00`) and `temporal` outputs with `13` kerchunk years vs `20` NetCDF years.
- `4` execution errors are all `vertical` and share the same dask chunking failure on `temp_unique`.
- `6` rows were skipped because `vertical` was not applicable due to `missing_vertical_axis`.

## Run Configuration

- target_frequency: `Amon`
- bins: `25-49,50-99,100-149`
- min_files: `None`
- max_files: `None`
- datasets_per_bin: `5`
- fixed_timesteps: `240`
- rtol: `1e-06`
- atol: `1e-08`
- operations: `temporal,spatial,horizontal,vertical`
- out_csv: `/global/u2/v/vo13/xCDAT/xcdat-validation/riotai/results/20260702-api-output-comparison/run_3bins_5datasets.csv`
- resume_csv: `/global/u2/v/vo13/xCDAT/xcdat-validation/riotai/results/20260702-api-output-comparison/run_3bins_5datasets.csv`
- summary_md: `/global/u2/v/vo13/xCDAT/xcdat-validation/riotai/results/20260702-api-output-comparison/run_3bins_5datasets_summary.md`
- resume_summary_md: `None`

## Operation Configuration

- temporal: `{"freq": "year"}`
- spatial: `{"axis": ["X", "Y"], "weights": "generate"}`
- horizontal: `{"method": "bilinear", "target_grid": {"lat_name": "lat", "lat_start": -88, "lat_step": 4, "lat_stop": 88, "lon_name": "lon", "lon_start": 2, "lon_step": 4, "lon_stop": 358}, "tool": "xesmf"}`
- vertical: `{"method": "log", "target_plevs_pa": [100000, 92500, 85000, 75000, 70000, 60000, 50000, 40000, 30000, 25000, 20000, 15000, 10000, 7000, 5000, 3000, 1000, 500, 300, 100], "tool": "xgcm"}`

- Total rows: 60
- Passed all checks: 44
- Failed validation checks: 6
- Execution errors: 4
- Skipped rows: 6

## Pass/Fail by Operation

| operation  | total | passed | failed_checks | errors | skipped |
| ---------- | ----: | -----: | ------------: | -----: | ------: |
| temporal   |    15 |     13 |             2 |      0 |       0 |
| spatial    |    15 |     13 |             2 |      0 |       0 |
| horizontal |    15 |     13 |             2 |      0 |       0 |
| vertical   |    15 |      5 |             0 |      4 |       6 |

## Common Skip Reasons

| operation_and_reason            | count | example_dataset_ids                                                                                                                                                                                                                                                                                                                                                                                  |
| ------------------------------- | ----: | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| vertical::missing_vertical_axis |     6 | CMIP6.CMIP.MOHC.HadGEM3-GC31-MM.piControl.r1i1p1f1.Amon.huss.gn.kerchunk.json, CMIP6.CMIP.MOHC.HadGEM3-GC31-MM.piControl.r1i1p1f1.Amon.pr.gn.v20190920, CMIP6.CMIP.MPI-M.MPI-ESM1-2-LR.esm-piControl.r1i1p1f1.Amon.pr.gn.v20190815, CMIP6.CMIP.NCC.NorESM2-LM.abrupt-4xCO2.r1i1p1f1.Amon.huss.gn.kerchunk.json, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119 |

## Common Failure Categories

| failure_category            | count | example_rows                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| --------------------------- | ----: | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| operation_not_applicable    |     6 | CMIP6.CMIP.MOHC.HadGEM3-GC31-MM.piControl.r1i1p1f1.Amon.huss.gn.kerchunk.json::vertical, CMIP6.CMIP.MOHC.HadGEM3-GC31-MM.piControl.r1i1p1f1.Amon.pr.gn.v20190920::vertical, CMIP6.CMIP.MPI-M.MPI-ESM1-2-LR.esm-piControl.r1i1p1f1.Amon.pr.gn.v20190815::vertical, CMIP6.CMIP.NCC.NorESM2-LM.abrupt-4xCO2.r1i1p1f1.Amon.huss.gn.kerchunk.json::vertical, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119::vertical                                   |
| coordinate_mismatch         |     6 | CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119::horizontal, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119::spatial, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119::temporal, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json::horizontal, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json::spatial |
| data_mismatch               |     6 | CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119::horizontal, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119::spatial, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119::temporal, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json::horizontal, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json::spatial |
| backend_execution_mismatch  |     4 | CMIP6.CMIP.FIO-QLNM.FIO-ESM-2-0.piControl.r1i1p1f1.Amon.hus.gn.kerchunk.json::vertical, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json::vertical, CMIP6.CMIP.MPI-M.MPI-ESM1-2-HR.piControl.r1i1p1f1.Amon.hur.gn.v20190710::vertical, CMIP6.CMIP.MPI-M.MPI-ESM1-2-HR.piControl.r1i1p1f1.Amon.hus.gn.v20190710::vertical                                                                                                                                 |
| metadata_structure_mismatch |     2 | CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119::temporal, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json::temporal                                                                                                                                                                                                                                                                                               |

## Key Findings

- Validation failures are isolated to 2 HighResMIP ECMWF datasets and affect `horizontal`, `spatial`, and `temporal`.
- Execution errors are isolated to `vertical` and all 4 failing rows share the same dask `temp_unique` chunking error.
- Skips are all expected `vertical` cases with `missing_vertical_axis`.

## Validation Problem Datasets

### `CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119`

- Operations: `horizontal`, `spatial`, `temporal`
- Likely root cause: kerchunk time-axis mismatch or truncation, not a fully missing time coordinate
- Evidence:
  - `horizontal` and `spatial` disagree on the first time value: kerchunk `1950-01-16 12:00:00` vs netcdf `1951-01-16 12:00:00`
  - `temporal` shape differs: kerchunk `[13, 361, 720]` vs netcdf `[20, 361, 720]`
  - Largest data mismatch: `horizontal max_abs_diff=0.0006744196289218962`, `max_rel_diff=454259.0625`
- Kerchunk JSON: `/global/cfs/projectdirs/m4931/kerchunk/pr/highresSST-present/mon/CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119.kerchunk.json`
- NetCDF source dir: `/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/HighResMIP/ECMWF/ECMWF-IFS-HR/highresSST-present/r5i1p1f1/Amon/pr/gr/v20181119`

### `CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json`

- Operations: `horizontal`, `spatial`, `temporal`, `vertical`
- Likely root cause for validation failures: kerchunk time-axis mismatch or truncation
- Evidence:
  - `horizontal` and `spatial` disagree on the first time value: kerchunk `1950-01-16 12:00:00` vs netcdf `1951-01-16 12:00:00`
  - `temporal` shape differs: kerchunk `[13, 19, 361, 720]` vs netcdf `[20, 19, 361, 720]`
  - Largest data mismatch: `horizontal max_abs_diff=0.015414523892104626`, `max_rel_diff=32.17081832885742`
  - `vertical` also fails with the shared `temp_unique` chunking error listed below
- Kerchunk JSON: `/global/cfs/projectdirs/m4931/kerchunk/hus/hist-1950/mon/CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json`
- NetCDF source dir: `/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/HighResMIP/ECMWF/ECMWF-IFS-HR/hist-1950/r1i1p1f1/Amon/hus/gr/v20170915`

## Vertical Execution Errors

Shared error across all 4 failing datasets:

- `error_type=operation_failed_both_backends`
- `kerchunk` and `netcdf` both fail with `vertical_operation_failed: dimension temp_unique on 0th function argument to apply_ufunc with dask='parallelized' consists of multiple chunks, but is also a core dimension`
- Suggested fix from the error text: rechunk `temp_unique` to a single chunk or pass `allow_rechunk=True` in `dask_gufunc_kwargs`

Affected datasets:

- `CMIP6.CMIP.FIO-QLNM.FIO-ESM-2-0.piControl.r1i1p1f1.Amon.hus.gn.kerchunk.json`
  - Kerchunk: `/global/cfs/projectdirs/m4931/kerchunk/hus/piControl/mon/CMIP6.CMIP.FIO-QLNM.FIO-ESM-2-0.piControl.r1i1p1f1.Amon.hus.gn.kerchunk.json`
  - NetCDF dir: `/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/CMIP/FIO-QLNM/FIO-ESM-2-0/piControl/r1i1p1f1/Amon/hus/gn/v20201016`
- `CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json`
  - Kerchunk: `/global/cfs/projectdirs/m4931/kerchunk/hus/hist-1950/mon/CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json`
  - NetCDF dir: `/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/HighResMIP/ECMWF/ECMWF-IFS-HR/hist-1950/r1i1p1f1/Amon/hus/gr/v20170915`
- `CMIP6.CMIP.MPI-M.MPI-ESM1-2-HR.piControl.r1i1p1f1.Amon.hur.gn.v20190710`
  - Kerchunk: `/global/cfs/projectdirs/m4931/kerchunk/hur/piControl/mon/CMIP6.CMIP.MPI-M.MPI-ESM1-2-HR.piControl.r1i1p1f1.Amon.hur.gn.v20190710.kerchunk.json`
  - NetCDF dir: `/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/CMIP/MPI-M/MPI-ESM1-2-HR/piControl/r1i1p1f1/Amon/hur/gn/v20190710`
- `CMIP6.CMIP.MPI-M.MPI-ESM1-2-HR.piControl.r1i1p1f1.Amon.hus.gn.v20190710`
  - Kerchunk: `/global/cfs/projectdirs/m4931/kerchunk/hus/piControl/mon/CMIP6.CMIP.MPI-M.MPI-ESM1-2-HR.piControl.r1i1p1f1.Amon.hus.gn.v20190710.kerchunk.json`
  - NetCDF dir: `/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/CMIP/MPI-M/MPI-ESM1-2-HR/piControl/r1i1p1f1/Amon/hus/gn/v20190710`
