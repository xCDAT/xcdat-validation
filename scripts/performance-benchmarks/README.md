# Performance Benchmark

A performance benchmarking script that captures and compares the API runtimes of xCDAT against CDAT.

## Overview

This performance benchmark uses multi-file time series datasets of varying sizes. The
default number of samples taken for each API runtime is 5 and the minimum value is
recorded. Runtimes only include computation, excluding I/O. xCDAT can operate in serial
or parallel, while CDAT can only operate in serial. **Currently, it only compares the
runtimes for global spatial averaging.**

## Prerequisites

1. `conda`/`mamba` to create the test environment that includes xCDAT and CDAT.
2. To get the input datasets, either:

   1. Be an internal user at LLNL to access the LLNL Climate Program filesystem
      with direct access to the LLNL ESGF node (internal user)
   2. Download the datasets from ESGF using the provided wget scripts. Instructions
      are provided below.
      - It is recommended that you run this script in `tmux` or another persistent
        terminal in case there is an issue with downloading at any point.

## How to use it

1. Create the conda/mamba environment.

   ```bash
   mamba env create -f conda-env/test_stable.yml
   mamba activate xcdat_test_stable
   ```

2. (REQUIRED for external users) Download the datasets from ESGF online using wget
   and HTTP. The files will be stored in the sub-directories of the `input-dataset`
   directory.

   ```bash
     python scripts/performance-benchmarks/1_esgf_download_datasets.py
   ```

3. (REQUIRED for external users) Create the XML files that link multi-file datasets
   together, which will be opened by `cdms2` in step 4.

   ```bash
    python scripts/performance-benchmarks/2_create_cdms2_xmls.py
   ```

4. Run the performance benchmarking script.

   ```bash
    python scripts/performance-benchmarks/3_perf_benchmark.py
   ```

5. Run the plotting scripts. Make sure to update the `ROOT_DIR` directory to
   the directory storing the output CSV files with the runtimes.

   ```bash
    python scripts/performance-benchmarks/4_plot_spatial_avg_times.py
   ```

### Misc. Info

#### Specifications for original machine for performance benchmarks for JOSS paper (Dec/2023)

- OS: RHEL 7
- Memory: 1,000 GiB
- CPU: Intel(R) Xeon(r) CPU E7-8890v4 @ 2.20GHz

#### How xCDAT is configured for parallelism

- Uses Dask Distributed local sechduler with multiprocessing
  - Docs: https://docs.dask.org/en/stable/scheduling.html#dask-distributed-local
  - Number of workers based on logical cores (num_workers=None), no memory limit
- Datasets are chunked on the "time" axis using Dask's auto chunking option.
- Datasets are opened in parallel using the `parallel=True` which uses
  `dask.delayed`.
- For temporal averaging APIs, the underlying Xarray `groupby()` call uses the
  `flox` package is used for map-reduce grouping, instead of Xarray's native
  grouping logic. Xarray's native grouping logic is much slower because it
  runs serially. More info can be found here: https://xarray.dev/blog/flox.

### Links to Datasets on ESGF (MetaGrid)

- 7 GB: https://esgf-node.ornl.gov/search?project=CMIP6&resultType=originals+only&activeFacets=%7B%22activity_id%22%3A%22CMIP%22%2C%22institution_id%22%3A%22NCAR%22%2C%22source_id%22%3A%22CESM2%22%2C%22experiment_id%22%3A%22historical%22%2C%22variant_label%22%3A%22r1i1p1f1%22%2C%22grid_label%22%3A%22gn%22%2C%22frequency%22%3A%22day%22%2C%22variable_id%22%3A%22tas%22%7D

- 12 GB: # https://esgf-node.ornl.gov/search?project=CMIP6&activeFacets=%7B%22variable_id%22%3A%22tas%22%2C%22source_id%22%3A%22MRI-ESM2-0%22%2C%22frequency%22%3A%223hrPt%22%2C%22table_id%22%3A%223hr%22%2C%22variant_label%22%3A%22r1i1p1f1%22%2C%22institution_id%22%3A%22MRI%22%2C%22grid_label%22%3A%22gn%22%2C%22activity_id%22%3A%22CMIP%22%2C%22experiment_id%22%3A%22amip%22%7D

- 22 GB: https://esgf-node.ornl.gov/search?project=CMIP6&activeFacets=%7B%22activity_id%22%3A%22CMIP%22%2C%22institution_id%22%3A%22MOHC%22%2C%22source_id%22%3A%22UKESM1-0-LL%22%2C%22variant_label%22%3A%22r5i1p1f3%22%2C%22grid_label%22%3A%22gn%22%2C%22frequency%22%3A%22day%22%2C%22variable_id%22%3A%22ta%22%2C%22table_id%22%3A%22day%22%7D

- 50 GB: https://esgf-node.ornl.gov/search?project=CMIP6&activeFacets=%7B%22activity_id%22%3A%22CMIP%22%2C%22institution_id%22%3A%22NCAR%22%2C%22source_id%22%3A%22CESM2%22%2C%22experiment_id%22%3A%22historical%22%2C%22grid_label%22%3A%22gn%22%2C%22table_id%22%3A%22day%22%2C%22variable_id%22%3A%22ta%22%2C%22variant_label%22%3A%22r1i1p1f1%22%7D

- 105 GB: https://esgf-node.ornl.gov/search?project=CMIP6&activeFacets=%7B%22activity_id%22%3A%22CMIP%22%2C%22source_id%22%3A%22HadGEM3-GC31-MM%22%2C%22institution_id%22%3A%22MOHC%22%2C%22experiment_id%22%3A%22historical%22%2C%22variant_label%22%3A%22r2i1p1f3%22%2C%22variable_id%22%3A%22ta%22%2C%22table_id%22%3A%22day%22%7D
