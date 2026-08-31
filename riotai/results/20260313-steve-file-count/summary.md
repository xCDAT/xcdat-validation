# Benchmark overview (2026-03-13 file-count sweep)

This directory contains a storage-faithful, head-to-head comparison of kerchunk vs native NetCDF in xCDAT workflows, focused on scaling with NetCDF file count.

Key artifacts:

- `final_combined.csv`
- `final_timing_vs_nfiles.png`
- `head_to_head.py`

## Experiment setup

- Platform: Perlmutter CPU node; CMIP archive on NERSC near-compute storage.
- Scheduler: Dask threaded (`num_workers=8`), no distributed cluster.
- Thread controls: `OMP/MKL/OPENBLAS_NUM_THREADS=1`.
- Workload: fixed leading slice `time[:240]` (`FIXED_TIMESTEPS = 240`).
- Storage behavior: preserve on-disk chunking (`chunks={}`), no rechunking.
- NetCDF open mode: `join="exact"`.
- Repeats: `NTESTS = 3`; first iteration discarded (warmup), median of remaining runs reported.
- Dataset set: 15 Amon datasets from `DATASET_ENTRIES`, spanning `netcdf_file_count` from 1 to 2000 (run as two shards and combined).

## Timed phases

- Open
- Load
- Temporal (`group_average(..., freq="year")`): build + compute
- Spatial (`spatial.average(...)`): build + compute

## How to read the plot and CSV

- In `final_timing_vs_nfiles.png`, x-axis is Kerchunk time and y-axis is NetCDF time.
- Dashed diagonal is parity (`y=x`): points above mean NetCDF is slower; below mean Kerchunk is slower.
- Point labels are `netcdf_file_count` (`1k`, `1.3k`, `2k`, etc.).
- In `final_combined.csv`, ratio columns are `kerchunk / netcdf` and include:
- `open_ratio`
- `load_ratio`
- `temporal_compute_ratio` (compute only, not build+compute total)
- `spatial_compute_ratio` (compute only, not build+compute total)

## Results summary

- Overall completion: 15 rows total, 14 `ok`, 1 `failed`.
- Failed case: one dataset failed due mixed calendar types on `time` (`DatetimeProlepticGregorian` + `DatetimeGregorian`).

### Open
- Kerchunk is faster in 14/14 successful datasets.
- Median `open_ratio` is `0.0171`.
- At 2000 files: `open_kerchunk=0.509s` vs `open_netcdf=606.660s` (~1191x faster for kerchunk).

### Load
- NetCDF is usually faster or near parity.
- Kerchunk is faster in 2/14 cases (286 and 505 files).
- Median `load_ratio` is `1.329`.

### Temporal (build+compute total, as plotted)
- Small file counts are generally NetCDF-favored.
- Crossover begins around mid/high file counts; kerchunk dominates for the largest cases.
- At 2000 files: temporal total `6.664s` (kerchunk) vs `98.177s` (netcdf), ~14.7x kerchunk advantage.

### Spatial (build+compute total, as plotted)
- Similar crossover pattern, with an even larger high-file-count advantage for kerchunk.
- At 2000 files: spatial total `8.666s` (kerchunk) vs `273.685s` (netcdf), ~31.6x kerchunk advantage.

## Interpretation for this run

- Kerchunk provides a consistent and very large metadata/open advantage that grows with file count.
- For load, NetCDF remains competitive and often faster across much of the range.
- For temporal/spatial reductions, this run shows a file-count-dependent crossover: lower file-count datasets mostly favor NetCDF, while very high file-count datasets favor kerchunk strongly.

## xsearch file-count distribution

Follow-up work using the xsearch database shows that the archive is heavily concentrated in low-file-count datasets:

| nfiles_bucket | path_count | path_pct | total_nfiles | total_nfiles_pct |
|---------------|-----------:|---------:|-------------:|-----------------:|
| 0-49 | 1098125 | 94.82 | 4545050 | 38.66 |
| 50-99 | 42659 | 3.68 | 3358691 | 28.57 |
| 100-199 | 14153 | 1.22 | 2160707 | 18.38 |
| 200-499 | 1457 | 0.13 | 417244 | 3.55 |
| 500-999 | 1442 | 0.12 | 866977 | 7.37 |
| 1000+ | 315 | 0.03 | 407667 | 3.47 |

This suggests that NetCDF should likely remain the default overall for near-compute analysis without rechunking, with kerchunk used as a targeted optimization for highly fragmented datasets.

At the same time, archive prevalence is not the same as workload importance. A relatively small number of high-file-count datasets may still account for a disproportionate share of user pain, metadata overhead, or total files touched. That is visible in the table above: the `0-49` bucket contains 94.82% of paths but only 38.66% of total files.

## Caveats

- This is not a pure "nfiles-only" control experiment: datasets also differ by model, variable (`tas`/`pr`), grid, and physical size.
- Results are specific to this environment and workload design (`time[:240]`, local threaded scheduler, near-compute storage).
- `final_combined.csv` currently has a leading encoding artifact in the first header field (`¨dataset_id`), which may affect strict CSV parsers expecting `dataset_id`.
