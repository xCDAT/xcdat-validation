"""Combine shard CSVs and generate final timing plots.

Usage examples
--------------
python riotai/results/20260522-steve-file-count-crossover-upscale-daily/combine_and_plot.py

python riotai/results/20260522-steve-file-count-crossover-upscale-daily/combine_and_plot.py \
    --inputs run_25_149.csv run_150_299.csv run_300_499.csv run_500_749.csv run_750_1000.csv

python riotai/results/20260522-steve-file-count-crossover-upscale-daily/combine_and_plot.py \
    --out-csv custom_combined.csv \
    --out-plot custom_timing_vs_nfiles.png \
    --out-bin-plot custom_timing_by_bin.png \
    --out-total-plot custom_total_timing_vs_nfiles.png \
    --out-total-bin-plot custom_total_timing_by_bin.png
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("combine_plot")

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_GLOB = "run_*.csv"
DEFAULT_OUT_CSV = ROOT_DIR / "final_combined.csv"
DEFAULT_OUT_PLOT = ROOT_DIR / "final_timing_vs_nfiles.png"
DEFAULT_OUT_BIN_PLOT = ROOT_DIR / "final_timing_by_bin.png"
DEFAULT_OUT_TOTAL_PLOT = ROOT_DIR / "final_total_timing_vs_nfiles.png"
DEFAULT_OUT_TOTAL_BIN_PLOT = ROOT_DIR / "final_total_timing_by_bin.png"

NFILES_BIN_ORDER: tuple[str, ...] = (
    "25-49",
    "50-99",
    "100-149",
    "150-199",
    "200-299",
    "300-499",
    "500-749",
    "750-1000",
)


def _resolve_local_path(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if path.is_absolute():
        return path
    return ROOT_DIR / path


def _run_csv_sort_key(path: Path) -> tuple[int, str]:
    nums = [int(token) for token in re.findall(r"\d+", path.stem)]
    first_num = nums[0] if nums else 10**9
    return (first_num, path.name)


def _default_input_paths() -> list[Path]:
    return sorted(ROOT_DIR.glob(DEFAULT_INPUT_GLOB), key=_run_csv_sort_key)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Combine benchmark shard CSVs, deduplicate by key, "
            "write final CSV, and generate dataset/bin timing plots"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python riotai/results/20260522-steve-file-count-crossover-upscale-daily/combine_and_plot.py\n"
            "    Auto-discovers run_*.csv in the script directory and writes:\n"
            f"      {DEFAULT_OUT_CSV.name}\n"
            f"      {DEFAULT_OUT_PLOT.name}\n"
            f"      {DEFAULT_OUT_BIN_PLOT.name}\n"
            f"      {DEFAULT_OUT_TOTAL_PLOT.name}\n"
            f"      {DEFAULT_OUT_TOTAL_BIN_PLOT.name}\n\n"
            "  python riotai/results/20260522-steve-file-count-crossover-upscale-daily/combine_and_plot.py "
            "--inputs run_25_149.csv run_150_299.csv"
        ),
    )
    parser.add_argument(
        "--inputs",
        nargs="+",
        default=None,
        help=(
            "Input shard CSV paths relative to the script directory unless absolute. "
            f"Defaults to all {DEFAULT_INPUT_GLOB} files in the script directory."
        ),
    )
    parser.add_argument(
        "--out-csv",
        default=str(DEFAULT_OUT_CSV),
        help=(
            "Output path for combined CSV relative to the script directory unless absolute "
            f"(default: {DEFAULT_OUT_CSV.name})"
        ),
    )
    parser.add_argument(
        "--out-plot",
        default=str(DEFAULT_OUT_PLOT),
        help=(
            "Output path for final per-dataset timing plot relative to the script directory unless absolute "
            f"(default: {DEFAULT_OUT_PLOT.name})"
        ),
    )
    parser.add_argument(
        "--out-bin-plot",
        default=str(DEFAULT_OUT_BIN_PLOT),
        help=(
            "Output path for per-bin median timing plot relative to the script directory unless absolute "
            f"(default: {DEFAULT_OUT_BIN_PLOT.name})"
        ),
    )
    parser.add_argument(
        "--out-total-plot",
        default=str(DEFAULT_OUT_TOTAL_PLOT),
        help=(
            "Output path for the total-time timing plot relative to the script directory unless absolute "
            f"(default: {DEFAULT_OUT_TOTAL_PLOT.name})"
        ),
    )
    parser.add_argument(
        "--out-total-bin-plot",
        default=str(DEFAULT_OUT_TOTAL_BIN_PLOT),
        help=(
            "Output path for the total-time per-bin median plot relative to the script directory unless absolute "
            f"(default: {DEFAULT_OUT_TOTAL_BIN_PLOT.name})"
        ),
    )
    parser.add_argument(
        "--dedupe-key",
        default="dataset_id",
        help="Column used for deduplication (default: dataset_id)",
    )

    args = parser.parse_args()

    input_paths = [_resolve_local_path(path_str) for path_str in args.inputs or []]
    if not input_paths:
        input_paths = _default_input_paths()

    if len(input_paths) < 2:
        parser.error(
            "Need at least 2 input CSV files. Pass --inputs explicitly or ensure "
            f"at least two {DEFAULT_INPUT_GLOB} files exist in {ROOT_DIR}"
        )

    missing = [str(path) for path in input_paths if not path.exists()]
    if missing:
        parser.error(f"Missing input CSV file(s): {', '.join(missing)}")

    args.inputs = [str(path) for path in input_paths]
    args.out_csv = str(_resolve_local_path(args.out_csv))
    args.out_plot = str(_resolve_local_path(args.out_plot))
    args.out_bin_plot = str(_resolve_local_path(args.out_bin_plot))
    args.out_total_plot = str(_resolve_local_path(args.out_total_plot))
    args.out_total_bin_plot = str(_resolve_local_path(args.out_total_bin_plot))

    return args


def _prepare_plot_frame(df: pd.DataFrame) -> pd.DataFrame:
    ok_df = df[df["status"] == "ok"].copy() if "status" in df.columns else df.copy()
    if ok_df.empty:
        raise ValueError("No rows with status == 'ok'; cannot generate timing plot")

    required = [
        "open_kerchunk",
        "open_netcdf",
        "load_kerchunk",
        "load_netcdf",
        "temporal_build_kerchunk",
        "temporal_build_netcdf",
        "temporal_compute_kerchunk",
        "temporal_compute_netcdf",
        "spatial_build_kerchunk",
        "spatial_build_netcdf",
        "spatial_compute_kerchunk",
        "spatial_compute_netcdf",
    ]
    missing = [col for col in required if col not in ok_df.columns]
    if missing:
        raise ValueError(
            f"Missing required timing columns for plotting: {', '.join(missing)}"
        )

    ok_df["temporal_total_kerchunk"] = (
        ok_df["temporal_build_kerchunk"] + ok_df["temporal_compute_kerchunk"]
    )
    ok_df["temporal_total_netcdf"] = (
        ok_df["temporal_build_netcdf"] + ok_df["temporal_compute_netcdf"]
    )
    ok_df["spatial_total_kerchunk"] = (
        ok_df["spatial_build_kerchunk"] + ok_df["spatial_compute_kerchunk"]
    )
    ok_df["spatial_total_netcdf"] = (
        ok_df["spatial_build_netcdf"] + ok_df["spatial_compute_netcdf"]
    )
    ok_df["open_load_kerchunk"] = ok_df["open_kerchunk"] + ok_df["load_kerchunk"]
    ok_df["open_load_netcdf"] = ok_df["open_netcdf"] + ok_df["load_netcdf"]
    ok_df["open_temporal_kerchunk"] = (
        ok_df["open_kerchunk"] + ok_df["temporal_total_kerchunk"]
    )
    ok_df["open_temporal_netcdf"] = (
        ok_df["open_netcdf"] + ok_df["temporal_total_netcdf"]
    )
    ok_df["open_spatial_kerchunk"] = (
        ok_df["open_kerchunk"] + ok_df["spatial_total_kerchunk"]
    )
    ok_df["open_spatial_netcdf"] = (
        ok_df["open_netcdf"] + ok_df["spatial_total_netcdf"]
    )
    return ok_df


def _timing_panel_specs() -> list[tuple[str, str, str]]:
    return [
        ("Open", "open_kerchunk", "open_netcdf"),
        ("Load", "load_kerchunk", "load_netcdf"),
        ("Temporal", "temporal_total_kerchunk", "temporal_total_netcdf"),
        ("Spatial", "spatial_total_kerchunk", "spatial_total_netcdf"),
    ]


def _total_panel_specs() -> list[tuple[str, str, str]]:
    return [
        ("Open + Load", "open_load_kerchunk", "open_load_netcdf"),
        ("Open + Temporal", "open_temporal_kerchunk", "open_temporal_netcdf"),
        ("Open + Spatial", "open_spatial_kerchunk", "open_spatial_netcdf"),
    ]


def _bin_color_map() -> dict[str, tuple[float, float, float, float]]:
    import matplotlib.pyplot as plt

    cmap = plt.get_cmap("tab10")
    return {label: cmap(index % cmap.N) for index, label in enumerate(NFILES_BIN_ORDER)}


def _axis_limits(x: pd.Series, y: pd.Series, log_scale: bool) -> tuple[float, float]:
    import numpy as np

    x_vals = np.asarray(x, dtype=float)
    y_vals = np.asarray(y, dtype=float)
    all_vals = np.concatenate([x_vals, y_vals])
    finite_vals = all_vals[np.isfinite(all_vals)]
    if finite_vals.size == 0:
        return (1e-3, 1.0) if log_scale else (0.0, 1.0)

    upper = float(np.nanmax(finite_vals))
    if not np.isfinite(upper) or upper <= 0:
        upper = 1.0

    if not log_scale:
        return (0.0, upper)

    positive_vals = finite_vals[finite_vals > 0]
    if positive_vals.size == 0:
        return (1e-3, upper)

    lower = float(np.nanmin(positive_vals))
    lower *= 0.8
    if lower <= 0:
        lower = float(np.nanmin(positive_vals))
    upper *= 1.05
    return (lower, upper)


def _plot_scatter_panels(
    df: pd.DataFrame,
    out_plot: str,
    title: str,
    panel_specs: list[tuple[str, str, str]],
    labels: list[str] | None = None,
    *,
    label_points: bool = True,
    color_by_bin: bool = False,
    show_legend: bool = True,
    legend_outside: bool = False,
    log_scale: bool = False,
    marker_size: float = 40,
    marker_alpha: float = 0.85,
) -> None:
    import matplotlib.pyplot as plt

    panel_count = len(panel_specs)
    if panel_count <= 3:
        nrows, ncols = 1, panel_count
        figsize = (5.25 * panel_count, 5.0)
    else:
        nrows, ncols = 2, 2
        figsize = (11.5, 9)

    fig = plt.figure(figsize=figsize)
    color_map = _bin_color_map()
    legend_handles: dict[str, object] = {}

    for i, (panel_title, kcol, ncol) in enumerate(panel_specs):
        ax = plt.subplot(nrows, ncols, i + 1)
        x = df[kcol]
        y = df[ncol]
        lower, upper = _axis_limits(x, y, log_scale)

        if color_by_bin and "nfiles_bin" in df.columns:
            for bin_label in NFILES_BIN_ORDER:
                bin_df = df[df["nfiles_bin"] == bin_label]
                if bin_df.empty:
                    continue
                handle = ax.scatter(
                    bin_df[kcol],
                    bin_df[ncol],
                    s=marker_size,
                    alpha=marker_alpha,
                    color=color_map[bin_label],
                    edgecolors="white",
                    linewidths=0.5,
                )
                if show_legend and bin_label not in legend_handles:
                    legend_handles[bin_label] = handle

            other_df = df[~df["nfiles_bin"].isin(NFILES_BIN_ORDER)]
            if not other_df.empty:
                handle = ax.scatter(
                    other_df[kcol],
                    other_df[ncol],
                    s=marker_size,
                    alpha=marker_alpha,
                    color="0.5",
                    edgecolors="white",
                    linewidths=0.5,
                )
                if show_legend and "other" not in legend_handles:
                    legend_handles["other"] = handle
        else:
            ax.scatter(
                x,
                y,
                s=marker_size,
                alpha=marker_alpha,
                edgecolors="white",
                linewidths=0.5,
            )

        if label_points and labels is not None:
            offsets = [(4, 4), (4, -8), (-18, 4), (-18, -8)]
            for j, (xv, yv, label) in enumerate(zip(x, y, labels)):
                dx, dy = offsets[j % len(offsets)]
                ax.annotate(
                    label,
                    (xv, yv),
                    xytext=(dx, dy),
                    textcoords="offset points",
                    fontsize=8,
                    color="dimgray",
                    bbox=dict(facecolor="white", edgecolor="none", alpha=0.7, pad=0.2),
                )

        ax.plot([lower, upper], [lower, upper], "k:")
        if log_scale:
            ax.set_xscale("log")
            ax.set_yscale("log")
        ax.set_title(panel_title)
        ax.set_xlabel("Kerchunk [s]")
        ax.set_ylabel("NetCDF [s]")
        ax.set_xlim(lower, upper)
        ax.set_ylim(lower, upper)

    fig.suptitle(title)
    if show_legend and legend_handles:
        if legend_outside:
            fig.legend(
                legend_handles.values(),
                legend_handles.keys(),
                title="nfiles_bin",
                fontsize=8,
                title_fontsize=9,
                loc="center left",
                bbox_to_anchor=(0.87, 0.5),
                frameon=False,
            )
            fig.tight_layout(rect=[0, 0, 0.82, 0.97])
        else:
            fig.legend(
                legend_handles.values(),
                legend_handles.keys(),
                title="nfiles_bin",
                fontsize=8,
                title_fontsize=9,
                loc="upper right",
            )
            fig.tight_layout(rect=[0, 0, 1, 0.97])
    else:
        fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(out_plot, dpi=300)
    plt.close(fig)
    logger.info("Timing plot saved to %s", out_plot)


def _combine_csvs(input_paths: list[str], dedupe_key: str) -> pd.DataFrame:
    import numpy as np
    import pandas as pd

    frames: list[pd.DataFrame] = []
    for input_order, csv_path in enumerate(input_paths):
        df = pd.read_csv(csv_path)
        df["__input_order"] = input_order
        df["__row_order"] = np.arange(len(df), dtype=int)
        frames.append(df)

    combined = pd.concat(frames, ignore_index=True, sort=False)

    if dedupe_key not in combined.columns:
        raise ValueError(f"Deduplication key '{dedupe_key}' not found in inputs")

    combined = combined.sort_values(["__input_order", "__row_order"])
    combined = combined.drop_duplicates(subset=[dedupe_key], keep="last")

    if "netcdf_file_count" in combined.columns:
        combined["__nfiles_sort"] = pd.to_numeric(
            combined["netcdf_file_count"], errors="coerce"
        )
        sort_cols = ["__nfiles_sort"]
        if dedupe_key in combined.columns:
            sort_cols.append(dedupe_key)
        combined = combined.sort_values(sort_cols, na_position="last")
        combined = combined.drop(columns=["__nfiles_sort"])

    combined = combined.drop(columns=["__input_order", "__row_order"])
    return combined.reset_index(drop=True)


def _plot_timing(df: pd.DataFrame, out_plot: str) -> None:
    ok_df = _prepare_plot_frame(df)
    if "netcdf_file_count" not in ok_df.columns:
        raise ValueError(
            "Missing required timing column for plotting: netcdf_file_count"
        )

    _plot_scatter_panels(
        ok_df,
        out_plot,
        "Frequency: Amon | Raw Datasets Colored by nfiles_bin (log scale)",
        _timing_panel_specs(),
        labels=None,
        label_points=False,
        color_by_bin=True,
        show_legend=True,
        legend_outside=True,
        log_scale=True,
        marker_size=45,
        marker_alpha=0.75,
    )


def _plot_total_timing(df: pd.DataFrame, out_plot: str) -> None:
    ok_df = _prepare_plot_frame(df)
    if "netcdf_file_count" not in ok_df.columns:
        raise ValueError(
            "Missing required timing column for plotting: netcdf_file_count"
        )

    _plot_scatter_panels(
        ok_df,
        out_plot,
        "Frequency: Amon | Total Pipeline Time Colored by nfiles_bin (log scale)",
        _total_panel_specs(),
        labels=None,
        label_points=False,
        color_by_bin=True,
        show_legend=True,
        legend_outside=True,
        log_scale=True,
        marker_size=45,
        marker_alpha=0.75,
    )


def _build_bin_summary(
    df: pd.DataFrame, agg_cols: list[str] | None = None
) -> pd.DataFrame:
    ok_df = _prepare_plot_frame(df)
    if "nfiles_bin" not in ok_df.columns:
        raise ValueError("Combined CSV does not include nfiles_bin")

    ok_df = ok_df.dropna(subset=["nfiles_bin"]).copy()
    if ok_df.empty:
        raise ValueError("No successful rows with nfiles_bin; cannot generate bin plot")

    if agg_cols is None:
        agg_cols = [
            "open_kerchunk",
            "open_netcdf",
            "load_kerchunk",
            "load_netcdf",
            "temporal_total_kerchunk",
            "temporal_total_netcdf",
            "spatial_total_kerchunk",
            "spatial_total_netcdf",
        ]
    grouped = (
        ok_df.groupby("nfiles_bin", dropna=False)[agg_cols]
        .median(numeric_only=True)
        .reset_index()
    )
    counts = ok_df.groupby("nfiles_bin", dropna=False).size().rename("n_datasets")
    grouped = grouped.merge(counts, on="nfiles_bin", how="left")

    bin_order = {label: i for i, label in enumerate(NFILES_BIN_ORDER)}
    grouped["__bin_order"] = grouped["nfiles_bin"].map(bin_order).fillna(len(bin_order))
    grouped = grouped.sort_values(["__bin_order", "nfiles_bin"]).drop(
        columns=["__bin_order"]
    )
    return grouped.reset_index(drop=True)


def _plot_timing_by_bin(df: pd.DataFrame, out_plot: str) -> None:
    bin_df = _build_bin_summary(df)
    labels = [
        f"{bin_label} (n={int(n_datasets)})"
        for bin_label, n_datasets in zip(bin_df["nfiles_bin"], bin_df["n_datasets"])
    ]
    _plot_scatter_panels(
        bin_df,
        out_plot,
        "Frequency: Amon | Bin Median",
        _timing_panel_specs(),
        labels=labels,
        label_points=True,
        color_by_bin=True,
        show_legend=False,
        legend_outside=False,
        log_scale=False,
        marker_size=70,
        marker_alpha=0.95,
    )


def _plot_total_timing_by_bin(df: pd.DataFrame, out_plot: str) -> None:
    bin_df = _build_bin_summary(
        df,
        agg_cols=[
            "open_load_kerchunk",
            "open_load_netcdf",
            "open_temporal_kerchunk",
            "open_temporal_netcdf",
            "open_spatial_kerchunk",
            "open_spatial_netcdf",
        ],
    )
    labels = [
        f"{bin_label} (n={int(n_datasets)})"
        for bin_label, n_datasets in zip(bin_df["nfiles_bin"], bin_df["n_datasets"])
    ]
    _plot_scatter_panels(
        bin_df,
        out_plot,
        "Frequency: Amon | Total Pipeline Bin Median",
        _total_panel_specs(),
        labels=labels,
        label_points=True,
        color_by_bin=True,
        show_legend=False,
        legend_outside=False,
        log_scale=False,
        marker_size=70,
        marker_alpha=0.95,
    )


def main() -> None:
    args = _parse_args()

    logger.info("Combining %d input CSVs", len(args.inputs))
    logger.info("Input CSVs: %s", ", ".join(args.inputs))
    combined_df = _combine_csvs(args.inputs, args.dedupe_key)

    Path(args.out_csv).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_plot).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_bin_plot).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_total_plot).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_total_bin_plot).parent.mkdir(parents=True, exist_ok=True)

    combined_df.to_csv(args.out_csv, index=False)
    logger.info("Combined CSV written to %s", args.out_csv)

    _plot_timing(combined_df, args.out_plot)
    _plot_total_timing(combined_df, args.out_total_plot)
    if args.out_bin_plot:
        try:
            _plot_timing_by_bin(combined_df, args.out_bin_plot)
        except ValueError as e:
            logger.warning("Skipping bin timing plot: %s", e)
    if args.out_total_bin_plot:
        try:
            _plot_total_timing_by_bin(combined_df, args.out_total_bin_plot)
        except ValueError as e:
            logger.warning("Skipping total bin timing plot: %s", e)


if __name__ == "__main__":
    main()
