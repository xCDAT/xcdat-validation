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

NERSC Compute Node
--------------------
Request a compute node with the following command:

```bash
salloc --nodes 1 --qos interactive --time 01:00:00 --constraint cpu --account=e3sm
```
"""

import datetime
import glob
import logging
import multiprocessing as mp
import os
import sys

from riotai.benchmark import benchmark_all_frequencies
from riotai.mapping import load_or_build_mappings

# Root directory containing kerchunk reference JSON files for testing.
ROOT_DATA_DIR = "/global/cfs/projectdirs/m4931/kerchunk"
JSON_PATHS = glob.glob(os.path.join(ROOT_DATA_DIR, "**", "*.json"), recursive=True)

# Path to store JSON→NetCDF mapping files.
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), f"results/{TIMESTAMP}")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Path to the mapping and error files.
MAPPING_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "json_to_netcdf_maps")
MAPPING_PATH = os.path.join(MAPPING_OUTPUT_DIR, "json_to_netcdf.json")
ERROR_PATH = os.path.join(MAPPING_OUTPUT_DIR, "json_to_netcdf_errors.json")


if __name__ == "__main__":
    log_path = os.path.join(OUTPUT_DIR, f"console_log_{TIMESTAMP}.txt")

    # Remove all handlers associated with the root logger
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger()

    mp.set_start_method("spawn", force=True)
    freq_json_netcdf_map, errors_map = load_or_build_mappings(
        MAPPING_PATH, ERROR_PATH, JSON_PATHS
    )

    df_raw, df_agg = benchmark_all_frequencies(
        freq_json_netcdf_map, sample_size=40, warmup=True, freqs=["Amon"]
    )

    df_raw.to_csv(
        os.path.join(OUTPUT_DIR, f"kerchunk_vs_netcdf_raw_{TIMESTAMP}.csv"), index=False
    )
    df_agg.to_csv(
        os.path.join(OUTPUT_DIR, f"kerchunk_vs_netcdf_agg_{TIMESTAMP}.csv"), index=False
    )
    logger.info("\nBenchmarking complete.")
    logger.info(f"Detailed results have been saved in:\n  {OUTPUT_DIR}\n")
