# Backend API Output Comparison Summary

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

| operation | total | passed | failed_checks | errors | skipped |
| --- | ---: | ---: | ---: | ---: | ---: |
| temporal | 15 | 13 | 2 | 0 | 0 |
| spatial | 15 | 13 | 2 | 0 | 0 |
| horizontal | 15 | 13 | 2 | 0 | 0 |
| vertical | 15 | 5 | 0 | 4 | 6 |

## Common Skip Reasons

| operation_and_reason | count | example_dataset_ids |
| --- | ---: | --- |
| vertical::missing_vertical_axis | 6 | CMIP6.CMIP.MOHC.HadGEM3-GC31-MM.piControl.r1i1p1f1.Amon.huss.gn.kerchunk.json, CMIP6.CMIP.MOHC.HadGEM3-GC31-MM.piControl.r1i1p1f1.Amon.pr.gn.v20190920, CMIP6.CMIP.MPI-M.MPI-ESM1-2-LR.esm-piControl.r1i1p1f1.Amon.pr.gn.v20190815, CMIP6.CMIP.NCC.NorESM2-LM.abrupt-4xCO2.r1i1p1f1.Amon.huss.gn.kerchunk.json, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119 |

## Common Failure Categories

| failure_category | count | example_rows |
| --- | ---: | --- |
| operation_not_applicable | 6 | CMIP6.CMIP.MOHC.HadGEM3-GC31-MM.piControl.r1i1p1f1.Amon.huss.gn.kerchunk.json::vertical, CMIP6.CMIP.MOHC.HadGEM3-GC31-MM.piControl.r1i1p1f1.Amon.pr.gn.v20190920::vertical, CMIP6.CMIP.MPI-M.MPI-ESM1-2-LR.esm-piControl.r1i1p1f1.Amon.pr.gn.v20190815::vertical, CMIP6.CMIP.NCC.NorESM2-LM.abrupt-4xCO2.r1i1p1f1.Amon.huss.gn.kerchunk.json::vertical, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119::vertical |
| coordinate_mismatch | 6 | CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119::horizontal, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119::spatial, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119::temporal, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json::horizontal, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json::spatial |
| data_mismatch | 6 | CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119::horizontal, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119::spatial, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119::temporal, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json::horizontal, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json::spatial |
| backend_execution_mismatch | 4 | CMIP6.CMIP.FIO-QLNM.FIO-ESM-2-0.piControl.r1i1p1f1.Amon.hus.gn.kerchunk.json::vertical, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json::vertical, CMIP6.CMIP.MPI-M.MPI-ESM1-2-HR.piControl.r1i1p1f1.Amon.hur.gn.v20190710::vertical, CMIP6.CMIP.MPI-M.MPI-ESM1-2-HR.piControl.r1i1p1f1.Amon.hus.gn.v20190710::vertical |
| metadata_structure_mismatch | 2 | CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119::temporal, CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json::temporal |

## Worst Rows by Max Absolute Difference

| operation | dataset_id | value |
| --- | --- | ---: |
| horizontal | CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json | 0.0154145238921046 |
| spatial | CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json | 0.00087849692355 |
| horizontal | CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119 | 0.0006744196289218 |
| spatial | CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119 | 2.5335769050407314e-06 |
| horizontal | CMIP6.CMIP.MIROC.MIROC6.abrupt-4xCO2.r1i1p1f1.Amon.ta.gn.v20190705 | 0.0 |
| spatial | CMIP6.CMIP.MIROC.MIROC6.abrupt-4xCO2.r1i1p1f1.Amon.ta.gn.v20190705 | 0.0 |
| temporal | CMIP6.CMIP.MIROC.MIROC6.abrupt-4xCO2.r1i1p1f1.Amon.ta.gn.v20190705 | 0.0 |
| vertical | CMIP6.CMIP.MIROC.MIROC6.abrupt-4xCO2.r1i1p1f1.Amon.ta.gn.v20190705 | 0.0 |
| spatial | CMIP6.CMIP.MOHC.HadGEM3-GC31-MM.piControl.r1i1p1f1.Amon.pr.gn.v20190920 | 0.0 |
| temporal | CMIP6.CMIP.MOHC.HadGEM3-GC31-MM.piControl.r1i1p1f1.Amon.pr.gn.v20190920 | 0.0 |

## Worst Rows by Max Relative Difference

| operation | dataset_id | value |
| --- | --- | ---: |
| horizontal | CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119 | 454259.0625 |
| horizontal | CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json | 32.17081832885742 |
| spatial | CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.hist-1950.r1i1p1f1.Amon.hus.gr.kerchunk.json | 0.3080181100053374 |
| spatial | CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119 | 0.0749420825783765 |
| horizontal | CMIP6.CMIP.MIROC.MIROC6.abrupt-4xCO2.r1i1p1f1.Amon.ta.gn.v20190705 | 0.0 |
| spatial | CMIP6.CMIP.MIROC.MIROC6.abrupt-4xCO2.r1i1p1f1.Amon.ta.gn.v20190705 | 0.0 |
| temporal | CMIP6.CMIP.MIROC.MIROC6.abrupt-4xCO2.r1i1p1f1.Amon.ta.gn.v20190705 | 0.0 |
| vertical | CMIP6.CMIP.MIROC.MIROC6.abrupt-4xCO2.r1i1p1f1.Amon.ta.gn.v20190705 | 0.0 |
| spatial | CMIP6.CMIP.MOHC.HadGEM3-GC31-MM.piControl.r1i1p1f1.Amon.pr.gn.v20190920 | 0.0 |
| temporal | CMIP6.CMIP.MOHC.HadGEM3-GC31-MM.piControl.r1i1p1f1.Amon.pr.gn.v20190920 | 0.0 |

