import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import xcdat as xc


def main():
    script_dir = Path(__file__).resolve().parent

    df = load_results(
        "riotai/results/20260126_130127/kerchunk_vs_netcdf_raw_20260126_130127.csv",
        "riotai/json_to_netcdf_maps/json_to_netcdf.json",
    )

    cases = {
        "Amon_1_file": df[
            (df["frequency"] == "Amon") & (df["num_netcdf_files"] == 1)
        ].head(1),
        "Amon_many_files": df[
            (df["frequency"] == "Amon") & (df["num_netcdf_files"] >= 80)
        ].head(1),
        # "3hr_normal": df[
        #     (df["frequency"] == "3hr")
        #     & (df["timesteps"] > 100000)
        #     & (df["num_netcdf_files"] < 20)
        # ].head(1),
        # "3hr_time_last_outlier": df[
        #     (df["frequency"] == "3hr")
        #     & (df["timesteps"] > 500000)
        #     & (df["num_netcdf_files"] < 20)
        # ].head(1),
    }

    all_results = []

    for case_name, case_df in cases.items():
        if case_df.empty:
            continue

        row = case_df.iloc[0]
        variable = "tas" if row["frequency"] == "Amon" else "pr"

        full_metrics = benchmark_full_field_load(
            kerchunk_path=row["json"],
            netcdf_paths=row["netcdf_filepaths"],
            variable=variable,
            runs=5,
        )

        reduction_metrics = benchmark_reductions_separately(
            kerchunk_path=row["json"],
            netcdf_paths=row["netcdf_filepaths"],
            variable=variable,
            runs=5,
        )

        combined = {
            "case": case_name,
            "frequency": row["frequency"],
            "num_files": row["num_netcdf_files"],
            "timesteps": row["timesteps"],
            **full_metrics,
            **reduction_metrics,
        }

        all_results.append(combined)

    df_out = pd.DataFrame(all_results)

    output_path = script_dir / "kerchunk_vs_netcdf_aggregated_results.csv"
    df_out.to_csv(output_path, index=False)

    print("Saved results to:", output_path)


# ============================================================
# Data Loading Utilities
# ============================================================
def load_results(csv_path: str, json_map_path: str) -> pd.DataFrame:
    df_raw = pd.read_csv(csv_path)

    with open(json_map_path, "r") as f:
        json_netcdf_map = json.load(f)

    rows = []
    for freq, json_map in json_netcdf_map.items():
        for json_key, netcdf_filepaths in json_map.items():
            rows.append(
                {
                    "frequency": freq,
                    "json": json_key,
                    "netcdf_filepaths": netcdf_filepaths,
                }
            )

    df_json_netcdf = pd.DataFrame(rows)
    return df_raw.merge(df_json_netcdf, how="left", on=["frequency", "json"])


# ============================================================
# Benchmarks
# ============================================================
def benchmark_full_field_load(
    kerchunk_path,
    netcdf_paths,
    variable,
    runs=5,
    drop_first_run=True,
    use_xcdat=False,
):
    kc_open, kc_load, nc_open, nc_load = [], [], [], []

    for _ in range(runs):
        # Kerchunk
        t0 = time.perf_counter()
        ds = _open_kerchunk(kerchunk_path, use_xcdat)
        kc_open.append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        ds[variable].compute()
        kc_load.append(time.perf_counter() - t0)
        ds.close()

        # NetCDF
        t0 = time.perf_counter()
        ds = _open_netcdf(netcdf_paths, use_xcdat)
        nc_open.append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        ds[variable].compute()
        nc_load.append(time.perf_counter() - t0)
        ds.close()

    if drop_first_run:
        kc_open, kc_load = kc_open[1:], kc_load[1:]
        nc_open, nc_load = nc_open[1:], nc_load[1:]

    return {
        "kerchunk_open_median": float(np.median(kc_open)),
        "netcdf_open_median": float(np.median(nc_open)),
        "kerchunk_load_median": float(np.median(kc_load)),
        "netcdf_load_median": float(np.median(nc_load)),
    }


def benchmark_reductions_separately(
    kerchunk_path,
    netcdf_paths,
    variable,
    runs=5,
    drop_first_run=True,
):
    kc_annual, kc_spatial = [], []
    nc_annual, nc_spatial = [], []

    for _ in range(runs):
        # Kerchunk annual
        ds = _open_kerchunk(kerchunk_path, use_xcdat=True)
        ds = ds.bounds.add_missing_bounds()
        t0 = time.perf_counter()
        ds.temporal.group_average(variable, freq="year").compute()
        kc_annual.append(time.perf_counter() - t0)
        ds.close()

        # Kerchunk spatial
        ds = _open_kerchunk(kerchunk_path, use_xcdat=True)
        ds = ds.bounds.add_missing_bounds()
        t0 = time.perf_counter()
        ds.spatial.average(variable).compute()
        kc_spatial.append(time.perf_counter() - t0)
        ds.close()

        # NetCDF annual
        ds = _open_netcdf(netcdf_paths, use_xcdat=True)
        ds = ds.bounds.add_missing_bounds()
        t0 = time.perf_counter()
        ds.temporal.group_average(variable, freq="year").compute()
        nc_annual.append(time.perf_counter() - t0)
        ds.close()

        # NetCDF spatial
        ds = _open_netcdf(netcdf_paths, use_xcdat=True)
        ds = ds.bounds.add_missing_bounds()
        t0 = time.perf_counter()
        ds.spatial.average(variable).compute()
        nc_spatial.append(time.perf_counter() - t0)
        ds.close()

    if drop_first_run:
        kc_annual, kc_spatial = kc_annual[1:], kc_spatial[1:]
        nc_annual, nc_spatial = nc_annual[1:], nc_spatial[1:]

    return {
        "kerchunk_annual_median": float(np.median(kc_annual)),
        "netcdf_annual_median": float(np.median(nc_annual)),
        "kerchunk_spatial_median": float(np.median(kc_spatial)),
        "netcdf_spatial_median": float(np.median(nc_spatial)),
    }


# ============================================================
# Open Helpers
# ============================================================
def _open_kerchunk(path, use_xcdat=False):
    open_func = xc.open_dataset if use_xcdat else xr.open_dataset

    return open_func(path, engine="kerchunk", chunks={})


def _open_netcdf(paths, use_xcdat=False):
    if isinstance(paths, (list, tuple)) and len(paths) > 1:
        open_func = xc.open_mfdataset if use_xcdat else xr.open_mfdataset

        return open_func(paths, combine="by_coords", parallel=False, chunks={})
    else:
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        open_func = xc.open_dataset if use_xcdat else xr.open_dataset

        return open_func(path, chunks={})


if __name__ == "__main__":
    main()
