# Performance Benchmark

A performance benchmark that captures and compares the API runtimes of xCDAT against
CDAT.

## Overview

This performance benchmark uses multi-file time series datasets with varying sizes. The
default number of samples taken for each API runtime is 5 and the minimum value is
recorded. Runtimes only include computation, excluding I/O. xCDAT can operate in serial
or parallel, while CDAT can only operate in serial. **Currently, it only compares the
runtimes for global spatial averaging.**

## Prerequisites

1. Use a `linux-64` or `osx-64` based machine (CDAT does not support `osx-arm64` or `win-64`).
2. `conda`/`mamba` to create the test environment that includes xCDAT and CDAT.
3. To get the input datasets, either:

   1. Be an internal user at LLNL to access the LLNL Climate Program filesystem
      with direct access to the LLNL ESGF node
   2. Download the datasets from ESGF using either (1) `1_esgf_download_datasets.py` or
      (2) the ESGF2 Globus Endpoint links. Instructions are provided below.
      - If you run (1) `1_esgf_download_datasets.py`, it is recommended to do so in
        `tmux` or another persistent terminal in case there is an issue with downloading at any point.
      - Downloading via (2) the ESGF Globus Endpoint is significantly faster than (1),
        which uses wget/HTTP. However, you need to do some extra work with choosing the
        correct directory to store each multi-file dataset.

## How to use it

1. Create the conda/mamba environment.

   ```bash
   mamba env create -f conda-env/test_stable.yml
   mamba activate xcdat_test_stable
   ```

2. (REQUIRED for external users) Download the datasets from ESGF.

   You can either download files via (1) `1_esgf_download_datasets.py` (wget/HTTP) or
   (2) **ESGF2 Globus endpoint**. If you download the datasets using (2), make sure they
   are organized correctly by file size `scripts/performance-benchmarks/input-dataset`.
   Links to Globus are located in the "Links to Datasets on ESGF" section below.

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

### Links to Datasets on ESGF

#### 7 GB

- MetaGrid: https://aims2.llnl.gov/search?project=CMIP6&activeFacets=%7B%22activity_id%22%3A%22CMIP%22%2C%22institution_id%22%3A%22NCAR%22%2C%22source_id%22%3A%22CESM2%22%2C%22experiment_id%22%3A%22historical%22%2C%22variant_label%22%3A%22r1i1p1f1%22%2C%22grid_label%22%3A%22gn%22%2C%22frequency%22%3A%22day%22%2C%22variable_id%22%3A%22tas%22%2C%22dataNode%22%3A%5B%22aims3.llnl.gov%22%2C%22esgf-data1.llnl.gov%22%2C%22esgf-data2.llnl.gov%22%5D%7D

- Globus: https://app.globus.org/file-manager?origin_id=1889ea03-25ad-4f9f-8110-1ce8833a9d7e&origin_path=%2Fcss03_data%2FCMIP6%2FCMIP%2FNCAR%2FCESM2%2Fhistorical%2Fr1i1p1f1%2Fday%2Ftas%2Fgn%2Fv20190308%2F

#### 12 GB

- MetaGrid: https://aims2.llnl.gov/search?project=CMIP6&activeFacets=%7B%22variable_id%22%3A%22tas%22%2C%22source_id%22%3A%22MRI-ESM2-0%22%2C%22frequency%22%3A%223hrPt%22%2C%22table_id%22%3A%223hr%22%2C%22variant_label%22%3A%22r1i1p1f1%22%2C%22institution_id%22%3A%22MRI%22%2C%22grid_label%22%3A%22gn%22%2C%22activity_id%22%3A%22CMIP%22%2C%22experiment_id%22%3A%22amip%22%2C%22dataNode%22%3A%5B%22aims3.llnl.gov%22%2C%22esgf-data1.llnl.gov%22%2C%22esgf-data2.llnl.gov%22%5D%7D

- Globus: https://app.globus.org/file-manager?origin_id=1889ea03-25ad-4f9f-8110-1ce8833a9d7e&origin_path=%2Fcss03_data%2FCMIP6%2FCMIP%2FMRI%2FMRI-ESM2-0%2Famip%2Fr1i1p1f1%2F3hr%2Ftas%2Fgn%2Fv20190829%2F

#### 22 GB

- MetaGrid: https://aims2.llnl.gov/search?project=CMIP6&activeFacets=%7B%22activity_id%22%3A%22CMIP%22%2C%22institution_id%22%3A%22MOHC%22%2C%22source_id%22%3A%22UKESM1-0-LL%22%2C%22variant_label%22%3A%22r5i1p1f3%22%2C%22grid_label%22%3A%22gn%22%2C%22frequency%22%3A%22day%22%2C%22variable_id%22%3A%22ta%22%2C%22table_id%22%3A%22day%22%2C%22dataNode%22%3A%5B%22aims3.llnl.gov%22%2C%22esgf-data1.llnl.gov%22%2C%22esgf-data2.llnl.gov%22%5D%7D

- Globus: https://app.globus.org/file-manager?origin_id=1889ea03-25ad-4f9f-8110-1ce8833a9d7e&origin_path=%2Fcss03_data%2FCMIP6%2FCMIP%2FMOHC%2FUKESM1-0-LL%2Fhistorical%2Fr5i1p1f3%2Fday%2Fta%2Fgn%2Fv20191115%2F

#### 50 GB

- MetaGrid: https://aims2.llnl.gov/search?project=CMIP6&activeFacets=%7B%22activity_id%22%3A%22CMIP%22%2C%22institution_id%22%3A%22NCAR%22%2C%22source_id%22%3A%22CESM2%22%2C%22experiment_id%22%3A%22historical%22%2C%22grid_label%22%3A%22gn%22%2C%22table_id%22%3A%22day%22%2C%22variable_id%22%3A%22ta%22%2C%22variant_label%22%3A%22r1i1p1f1%22%2C%22dataNode%22%3A%5B%22aims3.llnl.gov%22%2C%22esgf-data1.llnl.gov%22%2C%22esgf-data2.llnl.gov%22%5D%7D

- Globus: https://app.globus.org/file-manager?origin_id=1889ea03-25ad-4f9f-8110-1ce8833a9d7e&origin_path=%2Fcss03_data%2FCMIP6%2FCMIP%2FNCAR%2FCESM2%2Fhistorical%2Fr1i1p1f1%2Fday%2Fta%2Fgn%2Fv20190308%2F

#### 105 GB

- MetaGrid: https://aims2.llnl.gov/search?project=CMIP6&activeFacets=%7B%22activity_id%22%3A%22CMIP%22%2C%22source_id%22%3A%22HadGEM3-GC31-MM%22%2C%22institution_id%22%3A%22MOHC%22%2C%22experiment_id%22%3A%22historical%22%2C%22variant_label%22%3A%22r2i1p1f3%22%2C%22variable_id%22%3A%22ta%22%2C%22table_id%22%3A%22day%22%2C%22dataNode%22%3A%5B%22aims3.llnl.gov%22%2C%22esgf-data1.llnl.gov%22%2C%22esgf-data2.llnl.gov%22%5D%7D

- Globus: https://app.globus.org/file-manager?origin_id=1889ea03-25ad-4f9f-8110-1ce8833a9d7e&origin_path=%2Fcss03_data%2FCMIP6%2FCMIP%2FMOHC%2FHadGEM3-GC31-MM%2Fhistorical%2Fr2i1p1f3%2Fday%2Fta%2Fgn%2Fv20191218%2F

### Misc. Info

#### Specifications for original machine for performance benchmarks for JOSS paper (Dec/2023)

- OS: RHEL 7
- Memory: 1,000 GiB
- CPU: Intel(R) Xeon(r) CPU E7-8890v4 @ 2.20GHz

#### How xCDAT is configured for parallelism

- Uses Dask Distributed local scheduler with multiprocessing
  - Docs: https://docs.dask.org/en/stable/scheduling.html#dask-distributed-local
  - Number of workers based on logical cores (num_workers=None), no memory limit
- Datasets are chunked on the "time" axis using Dask's auto chunking option.
- Datasets are opened in parallel using the `parallel=True` which uses
  `dask.delayed`.
- For temporal averaging APIs, the underlying Xarray `groupby()` call uses the
  `flox` package is used for map-reduce grouping, instead of Xarray's native
  grouping logic. Xarray's native grouping logic is much slower because it
  runs serially. More info can be found here: https://xarray.dev/blog/flox.
