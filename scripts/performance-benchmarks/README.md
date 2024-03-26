# Performance Benchmark

A performance benchmarking script that captures and compares the API runtimes of
xCDAT against CDAT.

## Overview

The performance benchmark uses multi-file time series datasets of varying sizes. The
default number of samples taken for each API runtime is 3 and the minimum value is
recorded. Runtimes only include computation, excluding I/O. xCDAT can operate
in serial or parallel, while CDAT can only operate in serial.

## Prerequisites

1. Have a `conda`/`mamba` to create the test environment which includes xCDAT and CDAT.
2. To get the input datasets, you must be on on the LLNL Climate Program filesystem
   with direct access to the LLNL ESGF node (internal user) OR download the datasets
   from ESGF online (external user).

## How to use it

1. Create the conda/mamba environment:

   ```bash
   mamba env create -f conda-env/test_stable.yml
   mamba activate xcdat_test_stable
   ```

2. (REQUIRED for external users) Download the datasets from ESGF online using wget
   and HTTP: The files will be downloaded to the `input-dataset` directory. It is
   recommended that you run this script in `tmux` or another persistent terminal in
   case there is an issue with downloading at any point.

   ```bash
     # -s is required to bypass credential requirements
     # Related issue: https://github.com/esgf2-us/metagrid/issues/617#issuecomment-1984677121
     python scripts/performance-benchmarks/1_esgf_download_datasets.py
   ```

3. (REQUIRED for external users) Create the XML files that link multi-file datasets
   together to open up with `cdms2`.

   ```bash
    python scripts/performance-benchmarks/2_create-cdms2-xmls.py
   ```

4. Run the performance benchmarking script:

   ```bash
    python 3_perf_benchmark.py
   ```

5. Run the plotting scripts. Make sure to update the `ROOT_DIR` directory to
   the directory storing the output CSV files with the runtimes.

   ```bash
    python 4_plot_perf_benchmark.py
   ```

## Specifications for original machine used to run this script (Dec/2023)

- OS: RHEL 7
- Memory: 1,000 GiB
- CPU: Intel(R) Xeon(r) CPU E7-8890v4 @ 2.20GHz

## How xCDAT is configured for parallelism

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
