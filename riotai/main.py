"""
Benchmark Kerchunk vs NetCDF dataset open performance.

This script measures xarray dataset open times using Kerchunk JSON references
versus raw NetCDF file collections for CMIP / E3SM-style datasets.

Datasets are deterministically sampled per frequency and benchmarked in
parallel using multiprocessing.

Parallelism
-----------
* Multiprocessing via ``ProcessPoolExecutor`` with the ``spawn`` start method
* For each frequency, up to 4 datasets are benchmarked concurrently;
    frequencies are handled one after another serially.
* Serial warm-up performed in the parent process
* Results aggregated in the parent process
* Parallelism controlled by ``max_workers`` (by defualt 4)

All execution and file I/O are guarded by ``if __name__ == "__main__"`` to
ensure correctness under multiprocessing.
"""

import datetime
import glob
import multiprocessing as mp
import os
import random

from riotai.benchmark import benchmark_all_frequencies
from riotai.utils import load_or_build_mappings

# %%
# ----------------------------------------------------------
# Data paths
# ----------------------------------------------------------
# Root directory containing kerchunk reference JSON files for testing.
ROOT_DATA_DIR = "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk"
JSON_PATHS = glob.glob(os.path.join(ROOT_DATA_DIR, "**", "*.json"), recursive=True)

# ----------------------------------------------------------
# Mapping paths
# ----------------------------------------------------------
# Path to store JSON→NetCDF mapping files.
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), f"results/{TIMESTAMP}")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Path to the mapping and error files.
MAPPING_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "json_to_netcdf_maps")
MAPPING_PATH = os.path.join(MAPPING_OUTPUT_DIR, "json_to_netcdf.json")
ERROR_PATH = os.path.join(MAPPING_OUTPUT_DIR, "json_to_netcdf_errors.json")

# %%
# ----------------------------------------------------------
# Calculate average I/O speed per frequency
# Notes:
#   - For frequencies where the available number of datasets was smaller than
#     the target sample size, all datasets were benchmarked.
# ----------------------------------------------------------

# NOTE: Comment out temporarily to only benchmark "Amon" for testing.
# for freq in frequencies:

# %%
if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    freq_json_netcdf_map, errors_map = load_or_build_mappings(
        MAPPING_PATH, ERROR_PATH, JSON_PATHS
    )

    df_raw, df_agg = benchmark_all_frequencies(
        freq_json_netcdf_map,
        sample_size=5,
        warmup=True,
        rng=random.Random(42),
    )

    # freq_avg_speed_path = os.path.join(
    #     OUTPUT_DIR, f"kerchunk_vs_netcdf_freq_avg_speed_{TIMESTAMP}.json"
    # )
    # with open(freq_avg_speed_path, "w") as f:
    #     json.dump(df_agg.to_dict(orient="records"), f, indent=2)

# %%
