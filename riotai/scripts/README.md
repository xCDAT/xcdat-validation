# riotai/scripts

These scripts build the input artifacts used by the kerchunk vs NetCDF benchmarking workflow.
Run them from the repository root so the relative paths in the scripts resolve as expected.

## Prerequisites

- Create the minimal benchmark environment:

```bash
conda env create -f riotai/test_stable_min.yml
conda activate xcdat_test_stable_min
```

- On HPC systems, the mapping and validation steps are typically run inside an interactive CPU allocation.
- The scripts assume access to the kerchunk JSON archive rooted at `/global/cfs/projectdirs/m4931/kerchunk`.

## Script Order

Run the scripts in this order:

1. `build_json_to_netcdf_mapping.py`
2. `json_to_netcdf_table.py`
3. `prepare_datasets.py`

Each step depends on artifacts produced by the previous one.

## Scripts

### `build_json_to_netcdf_mapping.py`

Purpose:

- Scans the kerchunk archive for `*.json` files.
- Groups files by CMIP frequency.
- Extracts the source NetCDF paths referenced by each kerchunk JSON.
- Writes the cached mapping and any extraction errors.

Outputs:

- `riotai/json_to_netcdf_maps/json_to_netcdf.json`
- `riotai/json_to_netcdf_maps/json_to_netcdf_errors.json`

Notes:

- This script is incremental by default and skips JSON files already present in the cache.
- If the run is interrupted, rerun the same command to continue updating the cache.

Run:

```bash
python riotai/scripts/build_json_to_netcdf_mapping.py
```

### `json_to_netcdf_table.py`

Purpose:

- Flattens the nested frequency-to-JSON mapping into a tabular dataset.
- Derives the variable name from each kerchunk filename.
- Records one row per kerchunk JSON with frequency, variable, file list, and file count.

Output:

- `riotai/json_to_netcdf_maps/json_to_netcdf_table.csv`

Notes:

- CSV is the default output format because it is easy to inspect and reuse.
- This step should be rerun after rebuilding the mapping if you want the table to reflect new or changed entries.

Run:

```bash
python riotai/scripts/json_to_netcdf_table.py
```

### `prepare_datasets.py`

Purpose:

- Filters the flat dataset table by frequency and optional file-count bounds.
- Assigns each dataset to a file-count bin.
- Validates that the kerchunk JSON exists, the NetCDF files exist, and the NetCDF collection can be opened with `xcdat.open_mfdataset()`.
- Writes the curated dataset list consumed by the benchmarking scripts.

Default output:

- `riotai/json_to_netcdf_maps/prepared_datasets_<frequency>.csv`

Notes:

- This is the step that determines which datasets are eligible for later benchmark runs.
- `--replace-bin` can be used to refresh only specific bins in an existing prepared CSV.
- `--datasets-per-bin` overrides the default target count for all selected bins.

Common run:

```bash
python riotai/scripts/prepare_datasets.py --target-frequency Amon
```

Useful variants:

```bash
python riotai/scripts/prepare_datasets.py \
  --target-frequency Amon \
  --bins 25-49,50-99,100-149

python riotai/scripts/prepare_datasets.py \
  --target-frequency Amon \
  --replace-bin 300-499

python riotai/scripts/prepare_datasets.py \
  --target-frequency Amon \
  --datasets-per-bin 10

python riotai/scripts/prepare_datasets.py \
  --target-frequency Amon \
  --replace-bin 100-149 \
  --exclude-dataset-pattern 'CMIP6\\..*\\.EC-Earth-Consortium\\..*\\.Amon\\.'
```

## Typical End-to-End Run

```bash
python riotai/scripts/build_json_to_netcdf_mapping.py
python riotai/scripts/json_to_netcdf_table.py
python riotai/scripts/prepare_datasets.py --target-frequency Amon
```

After these steps complete, the benchmark scripts in `riotai/results/...` can use the prepared dataset CSV directly.
