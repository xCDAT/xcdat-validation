# %%
import glob
import os

import xarray as xr

from riotai.benchmark import benchmark_frequency
from riotai.utils import load_or_build_mappings

# %%
# ----------------------------------------------------------
# Paths and constants
# ----------------------------------------------------------
# Root directory containing kerchunk reference JSON files for testing.
ROOT_DIR = "/global/cfs/projectdirs/m4931/sasha-tmp/kerchunk"
# Absolute paths to all kerchunk JSON reference files.
JSON_PATHS = glob.glob(os.path.join(ROOT_DIR, "**", "*.json"), recursive=True)
# Path to store JSON→NetCDF mapping files.
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "json_to_netcdf_maps")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Path to the mapping and error files.
MAPPING_PATH = os.path.join(OUTPUT_DIR, "json_to_netcdf.json")
ERROR_PATH = os.path.join(OUTPUT_DIR, "json_to_netcdf_errors.json")

# ----------------------------------------------------------
# Prerequisite Mapping -- Load or build JSON → NetCDF mappings
# Frequencies: ['Amon', 'day', 'ImonAnt', 'AERhr', 'CFsubhr', 'ImonGre']
# ----------------------------------------------------------
freq_to_json_to_netcdf, errors = load_or_build_mappings(
    MAPPING_PATH, ERROR_PATH, JSON_PATHS
)

# %%
# ----------------------------------------------------------
# Calculate average I/O speed per frequency
# Notes:
#   - For frequencies where the available number of datasets was smaller than
#     the target sample size, all datasets were benchmarked.
# ----------------------------------------------------------
frequencies = freq_to_json_to_netcdf.keys()

freq_avg_speed = {}

for freq in frequencies:
    result = benchmark_frequency(freq, freq_to_json_to_netcdf)

    if result is None:
        print(f"  * No datasets found for {freq}, skipping.")
        continue

    freq_avg_speed[freq] = result
    print(
        f"{freq} (n={result['n']}): "
        f"kerchunk={result['kerchunk_median']:.4f}s, "
        f"netcdf={result['netcdf_median']:.4f}s"
    )


# %%
# First, check the metadata (dims, coords, atrs, variables)
print("\n=== Metadata comparison ===")

sizes_identical = ds_kc.sizes == ds_nc.sizes
print(f"Dimensions identical: {sizes_identical}")
if not sizes_identical:
    print("  Kerchunk sizes:", ds_kc.sizes)
    print("  NetCDF  sizes:", ds_nc.sizes)

vars_identical = set(ds_kc.data_vars) == set(ds_nc.data_vars)
print(f"Data variables identical: {vars_identical}")
if not vars_identical:
    print("  Only in kerchunk:", set(ds_kc.data_vars) - set(ds_nc.data_vars))
    print("  Only in netcdf :", set(ds_nc.data_vars) - set(ds_kc.data_vars))

coords_identical = set(ds_kc.coords.keys()) == set(ds_nc.coords.keys())
print(f"Coordinates identical: {coords_identical}")
if not coords_identical:
    print("  Only in kerchunk:", set(ds_kc.coords.keys()) - set(ds_nc.coords.keys()))
    print("  Only in netcdf :", set(ds_nc.coords.keys()) - set(ds_kc.coords.keys()))

if sizes_identical and vars_identical and coords_identical:
    print("=> RESULT: Metadata is IDENTICAL.\n")
else:
    print("=> RESULT: Metadata is NOT IDENTICAL.\n")

# %%
# Note: Attributes often differ (Kerchunk strips some file-level metadata),
# so compare cautiously.
# Optional: check variable attrs
print("\n=== Attributes comparison ===")

any_attr_diffs = False

for v in ds_kc.data_vars:
    kc_attrs = ds_kc[v].attrs
    nc_attrs = ds_nc[v].attrs

    if kc_attrs == nc_attrs:
        continue

    any_attr_diffs = True
    print(f"\n--- Variable attrs differ for {v!r} ---")
    kc_keys = set(kc_attrs.keys())
    nc_keys = set(nc_attrs.keys())

    only_kc = kc_keys - nc_keys
    only_nc = nc_keys - kc_keys
    both = kc_keys & nc_keys

    if only_kc:
        print("  Only in kerchunk:")
        for k in sorted(only_kc):
            print(f"    {k!r}: {kc_attrs[k]!r}")

    if only_nc:
        print("  Only in netcdf:")
        for k in sorted(only_nc):
            print(f"    {k!r}: {nc_attrs[k]!r}")

    diffs = []
    for k in sorted(both):
        if kc_attrs[k] != nc_attrs[k]:
            diffs.append(k)

    if diffs:
        print("  Different values:")
        for k in diffs:
            print(f"    {k!r}: kerchunk={kc_attrs[k]!r}, netcdf={nc_attrs[k]!r}")

if not any_attr_diffs:
    print("=> RESULT: All variable attributes are IDENTICAL.\n")
else:
    print(
        "\n=> RESULT: Variable attributes are NOT IDENTICAL (see differences above).\n"
    )

# %%
print("\n=== Chunk size comparison ===")


def summarize_chunks(ds):
    summary = {}
    for name, var in ds.data_vars.items():
        if hasattr(var.data, "chunks") and var.data.chunks is not None:
            # Dask-backed: chunks is a tuple of tuples
            summary[name] = tuple(tuple(c) for c in var.data.chunks)
        else:
            summary[name] = None
    return summary


kc_chunks = summarize_chunks(ds_kc)
nc_chunks = summarize_chunks(ds_nc)

all_vars = sorted(set(kc_chunks) | set(nc_chunks))

for v in all_vars:
    kc = kc_chunks.get(v)
    nc = nc_chunks.get(v)
    print(f"\nVariable: {v}")
    print(f"  kerchunk chunks: {kc}")
    print(f"  netcdf  chunks: {nc}")
    if kc == nc:
        print("  -> Chunking identical")
    else:
        print("  -> Chunking differs")

# %% Compare variable values (does not load everything into memory)
for v in ds_kc.data_vars:
    xr.testing.assert_allclose(ds_kc[v], ds_nc[v])

# %%
# results = {"identical": [], "not_identical": []}

# for json_file, netcdf_files in json_to_netcdf.items():
#     print(f"Kerchunk JSON: {json_file}")
#     ds_json = xc.open_dataset(json_file, engine="kerchunk")
#     ds_nc = xc.open_mfdataset(netcdf_files)

#     try:
#         xr.testing.assert_identical(ds_json, ds_nc)
#     except AssertionError as e:
#         print(f"Datasets not identical for {json_file}: {e}")
#         results["not_identical"].append(json_file)
#     else:
#         print(f"Datasets identical for {json_file}")
#         results["identical"].append(json_file)


# %%
