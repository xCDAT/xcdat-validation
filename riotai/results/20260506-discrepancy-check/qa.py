"""Ad hoc kerchunk vs NetCDF timing check for a small set of xCDAT workloads.

This script is a reduced, single-run benchmark derived from
`riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py`.
It compares matching kerchunk and NetCDF inputs while preserving on-disk
chunking, and times four phases under xCDAT:

1. Open
2. Load of a fixed leading time slice
3. Temporal annual average
4. Spatial average

Results are printed during execution and summarized to `qa_results.csv` in the
same directory as this script.

Usage:
salloc --nodes 1 --qos interactive --constraint cpu --time 02:00:00 --account m4581
conda activate xcdat_test_stable_min
python riotai/results/20260506-discrepancy-check/qa.py
"""

import csv
import gc
from pathlib import Path
import random
import time

import fsspec
from tqdm import tqdm
import xarray as xr
import xcdat as xc

ROOT_DIR = Path(__file__).resolve().parent
OUT_CSV = ROOT_DIR / "qa_results.csv"

DATASETS = [
    {
        "netcdf_dir": Path(
            "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/CMIP/MPI-M/MPI-ESM1-2-LR/esm-piControl/r1i1p1f1/Amon/ta/gn/v20190815"
        ),
        "kerchunk_path": "/global/cfs/projectdirs/m4931/kerchunk/ta/esm-piControl/mon/CMIP6.CMIP.MPI-M.MPI-ESM1-2-LR.esm-piControl.r1i1p1f1.Amon.ta.gn.v20190815.kerchunk.json",
    },
]

N = 10
FIXED_TIMESTEPS = 240
BACKENDS = ["kerchunk", "netcdf"]


def benchmark(datasets=DATASETS, out_csv=OUT_CSV, iterations=N):
    result_rows = []

    for dataset in tqdm(datasets, desc="Datasets", unit="dataset"):
        kerchunk_path = dataset["kerchunk_path"]
        netcdf_dir = dataset["netcdf_dir"]
        metrics = _create_metrics()
        var_id = _infer_var_id(kerchunk_path)
        netcdf_files = _get_netcdf_files(netcdf_dir)

        _log("")
        _log(f"Starting dataset: {Path(kerchunk_path).name}")
        _log(f"  variable: {var_id}")
        _log(f"  netcdf dir: {netcdf_dir}")
        _log(f"  netcdf file count: {len(netcdf_files)}")
        _log(f"  iterations: {iterations} | fixed timesteps: {FIXED_TIMESTEPS}")

        for iteration in range(iterations):
            backend_order = list(BACKENDS)
            random.shuffle(backend_order)
            _log(
                f"Iteration {iteration + 1}/{iterations} backend order: {', '.join(backend_order)}"
            )

            for backend in backend_order:
                open_time = _time_open(
                    backend,
                    kerchunk_path,
                    netcdf_files,
                )
                load_time = _time_load(
                    backend,
                    kerchunk_path,
                    netcdf_files,
                    var_id,
                )
                temporal_build, temporal_compute, temporal_graph_tasks = _time_temporal(
                    backend,
                    kerchunk_path,
                    netcdf_files,
                    var_id,
                )
                spatial_build, spatial_compute = _time_spatial(
                    backend,
                    kerchunk_path,
                    netcdf_files,
                    var_id,
                )

                metrics[backend]["open"].append(open_time)
                metrics[backend]["load"].append(load_time)
                metrics[backend]["temporal_build"].append(temporal_build)
                metrics[backend]["temporal_compute"].append(temporal_compute)
                metrics[backend]["temporal_graph_tasks"].append(temporal_graph_tasks)
                metrics[backend]["spatial_build"].append(spatial_build)
                metrics[backend]["spatial_compute"].append(spatial_compute)

                _log(
                    "  "
                    f"{backend}: open={open_time:.3f}s, "
                    f"load={load_time:.3f}s, "
                    f"temporal build={temporal_build:.3f}s, "
                    f"temporal compute={temporal_compute:.3f}s, "
                    f"graph tasks={_format_graph_tasks(temporal_graph_tasks)}, "
                    f"spatial build={spatial_build:.3f}s, "
                    f"spatial compute={spatial_compute:.3f}s"
                )

        _print_dataset_results(dataset, var_id, netcdf_files, metrics)
        result_rows.append(_build_result_row(dataset, var_id, netcdf_files, metrics))

    _write_results_csv(result_rows, out_csv)
    return result_rows


def main():
    benchmark()


def _log(message):
    tqdm.write(message)


def _print_dataset_results(dataset, var_id, netcdf_files, metrics):
    kerchunk_path = dataset["kerchunk_path"]
    netcdf_dir = dataset["netcdf_dir"]

    print(f"dataset_id: {Path(kerchunk_path).name.removesuffix('.kerchunk.json')}")
    print(f"variable: {var_id}")
    print(f"netcdf dir: {netcdf_dir}")
    print(f"netcdf files: {len(netcdf_files)}")

    for backend, values in metrics.items():
        open_load_total = _average_total(values, "open", "load")
        open_temporal_total = _average_total(
            values, "open", "temporal_build", "temporal_compute"
        )
        open_spatial_total = _average_total(
            values, "open", "spatial_build", "spatial_compute"
        )

        print(backend)
        print(f"  open: avg={_average(values['open']):.6f}s")
        print(f"  load: avg={_average(values['load']):.6f}s")
        print(f"  temporal build: avg={_average(values['temporal_build']):.6f}s")
        print(f"  temporal compute: avg={_average(values['temporal_compute']):.6f}s")
        print(f"  temporal graph tasks: {values['temporal_graph_tasks']}")
        print(f"  spatial build: avg={_average(values['spatial_build']):.6f}s")
        print(f"  spatial compute: avg={_average(values['spatial_compute']):.6f}s")
        print(f"  total open+load: avg={open_load_total:.6f}s")
        print(f"  total open+temporal: avg={open_temporal_total:.6f}s")
        print(f"  total open+spatial: avg={open_spatial_total:.6f}s")
        print(f"  open samples: {values['open']}")
        print(f"  load samples: {values['load']}")
        print(f"  temporal build samples: {values['temporal_build']}")
        print(f"  temporal compute samples: {values['temporal_compute']}")
        print(f"  spatial build samples: {values['spatial_build']}")
        print(f"  spatial compute samples: {values['spatial_compute']}")

    print("kerchunk/netcdf ratios")
    print(
        f"  open: {_ratio(_average(metrics['kerchunk']['open']), _average(metrics['netcdf']['open'])):.3f}"
    )
    print(
        f"  load: {_ratio(_average(metrics['kerchunk']['load']), _average(metrics['netcdf']['load'])):.3f}"
    )
    print(
        "  temporal build: "
        f"{_ratio(_average(metrics['kerchunk']['temporal_build']), _average(metrics['netcdf']['temporal_build'])):.3f}"
    )
    print(
        "  temporal compute: "
        f"{_ratio(_average(metrics['kerchunk']['temporal_compute']), _average(metrics['netcdf']['temporal_compute'])):.3f}"
    )
    print(
        "  spatial build: "
        f"{_ratio(_average(metrics['kerchunk']['spatial_build']), _average(metrics['netcdf']['spatial_build'])):.3f}"
    )
    print(
        "  spatial compute: "
        f"{_ratio(_average(metrics['kerchunk']['spatial_compute']), _average(metrics['netcdf']['spatial_compute'])):.3f}"
    )
    print(
        "  total open+load: "
        f"{_ratio(_average_total(metrics['kerchunk'], 'open', 'load'), _average_total(metrics['netcdf'], 'open', 'load')):.3f}"
    )
    print(
        "  total open+temporal: "
        f"{_ratio(_average_total(metrics['kerchunk'], 'open', 'temporal_build', 'temporal_compute'), _average_total(metrics['netcdf'], 'open', 'temporal_build', 'temporal_compute')):.3f}"
    )
    print(
        "  total open+spatial: "
        f"{_ratio(_average_total(metrics['kerchunk'], 'open', 'spatial_build', 'spatial_compute'), _average_total(metrics['netcdf'], 'open', 'spatial_build', 'spatial_compute')):.3f}"
    )


def _build_result_row(dataset, var_id, netcdf_files, metrics):
    kerchunk_path = dataset["kerchunk_path"]
    row = {
        "dataset_id": Path(kerchunk_path).name.removesuffix(".kerchunk.json"),
        "variable": var_id,
        "netcdf_dir": str(dataset["netcdf_dir"]),
        "netcdf_file_count": len(netcdf_files),
        "kerchunk_path": kerchunk_path,
    }

    for backend in BACKENDS:
        row[f"open_{backend}"] = _average(metrics[backend]["open"])
        row[f"load_{backend}"] = _average(metrics[backend]["load"])
        row[f"temporal_build_{backend}"] = _average(metrics[backend]["temporal_build"])
        row[f"temporal_compute_{backend}"] = _average(
            metrics[backend]["temporal_compute"]
        )
        row[f"temporal_graph_tasks_{backend}"] = _summarize_graph_tasks(
            metrics[backend]["temporal_graph_tasks"]
        )
        row[f"spatial_build_{backend}"] = _average(metrics[backend]["spatial_build"])
        row[f"spatial_compute_{backend}"] = _average(
            metrics[backend]["spatial_compute"]
        )
        row[f"total_open_load_{backend}"] = _average_total(
            metrics[backend], "open", "load"
        )
        row[f"total_open_temporal_{backend}"] = _average_total(
            metrics[backend], "open", "temporal_build", "temporal_compute"
        )
        row[f"total_open_spatial_{backend}"] = _average_total(
            metrics[backend], "open", "spatial_build", "spatial_compute"
        )

    row["open_ratio_kerchunk_to_netcdf"] = _ratio(
        row["open_kerchunk"],
        row["open_netcdf"],
    )
    row["load_ratio_kerchunk_to_netcdf"] = _ratio(
        row["load_kerchunk"],
        row["load_netcdf"],
    )
    row["temporal_build_ratio_kerchunk_to_netcdf"] = _ratio(
        row["temporal_build_kerchunk"],
        row["temporal_build_netcdf"],
    )
    row["temporal_compute_ratio_kerchunk_to_netcdf"] = _ratio(
        row["temporal_compute_kerchunk"],
        row["temporal_compute_netcdf"],
    )
    row["spatial_build_ratio_kerchunk_to_netcdf"] = _ratio(
        row["spatial_build_kerchunk"],
        row["spatial_build_netcdf"],
    )
    row["spatial_compute_ratio_kerchunk_to_netcdf"] = _ratio(
        row["spatial_compute_kerchunk"],
        row["spatial_compute_netcdf"],
    )
    row["total_open_load_ratio_kerchunk_to_netcdf"] = _ratio(
        row["total_open_load_kerchunk"],
        row["total_open_load_netcdf"],
    )
    row["total_open_temporal_ratio_kerchunk_to_netcdf"] = _ratio(
        row["total_open_temporal_kerchunk"],
        row["total_open_temporal_netcdf"],
    )
    row["total_open_spatial_ratio_kerchunk_to_netcdf"] = _ratio(
        row["total_open_spatial_kerchunk"],
        row["total_open_spatial_netcdf"],
    )

    return row


def _write_results_csv(result_rows, out_csv):
    if not result_rows:
        _log(f"No results to write to {out_csv}")
        return

    fieldnames = list(result_rows[0].keys())
    with out_csv.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(result_rows)

    _log(f"Wrote CSV results to {out_csv}")


def _create_metrics():
    return {
        backend: {
            "open": [],
            "load": [],
            "temporal_build": [],
            "temporal_compute": [],
            "temporal_graph_tasks": [],
            "spatial_build": [],
            "spatial_compute": [],
        }
        for backend in BACKENDS
    }


def _time_open(backend, kerchunk_path, netcdf_files):
    _reset_caches()

    with xr.set_options(file_cache_maxsize=1):
        start = time.perf_counter()
        ds = _open_dataset(backend, kerchunk_path, netcdf_files)
        open_time = time.perf_counter() - start
        ds.close()

    return open_time


def _time_load(backend, kerchunk_path, netcdf_files, var_id):
    _reset_caches()

    with xr.set_options(file_cache_maxsize=1):
        ds = _open_dataset(backend, kerchunk_path, netcdf_files)
        ds = _apply_fixed_time_slice(ds, var_id)

        try:
            start = time.perf_counter()
            ds[var_id].compute()
            load_time = time.perf_counter() - start
        finally:
            ds.close()

    return load_time


def _time_temporal(backend, kerchunk_path, netcdf_files, var_id):
    _reset_caches()

    with xr.set_options(file_cache_maxsize=1):
        ds = _prepare_dataset(backend, kerchunk_path, netcdf_files, var_id)

        try:
            start = time.perf_counter()
            expr = ds.temporal.group_average(var_id, freq="year")
            build_time = time.perf_counter() - start

            try:
                graph_tasks = len(expr.data.__dask_graph__())
            except Exception:
                graph_tasks = None

            start = time.perf_counter()
            expr.compute()
            compute_time = time.perf_counter() - start
        finally:
            ds.close()

    return build_time, compute_time, graph_tasks


def _time_spatial(backend, kerchunk_path, netcdf_files, var_id):
    _reset_caches()

    with xr.set_options(file_cache_maxsize=1):
        ds = _prepare_dataset(backend, kerchunk_path, netcdf_files, var_id)

        try:
            start = time.perf_counter()
            expr = ds.spatial.average(var_id)
            build_time = time.perf_counter() - start

            start = time.perf_counter()
            expr.compute()
            compute_time = time.perf_counter() - start
        finally:
            ds.close()

    return build_time, compute_time


def _prepare_dataset(backend, kerchunk_path, netcdf_files, var_id):
    ds = _open_dataset(backend, kerchunk_path, netcdf_files)
    ds = _apply_fixed_time_slice(ds, var_id)
    return ds.bounds.add_missing_bounds()


def _open_dataset(backend, kerchunk_path, netcdf_files):
    if backend == "kerchunk":
        return xc.open_dataset(kerchunk_path, engine="kerchunk", chunks={})

    return xc.open_mfdataset(netcdf_files, chunks={}, join="exact")


def _apply_fixed_time_slice(ds, var_id):
    if "time" in ds[var_id].dims:
        time_len = ds[var_id].sizes["time"]
        return ds.isel(time=slice(0, min(FIXED_TIMESTEPS, time_len)))
    return ds


def _infer_var_id(dataset_path):
    parts = Path(dataset_path).name.split(".")
    return parts[7] if len(parts) > 7 else "ta"


def _get_netcdf_files(netcdf_dir):
    netcdf_files = tuple(sorted(str(path) for path in netcdf_dir.glob("*.nc")))
    if not netcdf_files:
        raise ValueError(f"No NetCDF files found in {netcdf_dir}")
    return netcdf_files


def _reset_caches():
    fsspec.AbstractFileSystem.clear_instance_cache()
    gc.collect()


def _average(values):
    return sum(values) / len(values)


def _average_total(metrics, *metric_names):
    return sum(_average(metrics[metric_name]) for metric_name in metric_names)


def _ratio(numerator, denominator):
    if denominator == 0:
        return None
    return numerator / denominator


def _format_graph_tasks(graph_tasks):
    if graph_tasks is None:
        return "n/a"
    return str(graph_tasks)


def _summarize_graph_tasks(values):
    valid_values = [value for value in values if value is not None]
    if not valid_values:
        return None
    return int(round(sum(valid_values) / len(valid_values)))


if __name__ == "__main__":
    main()
