"""Combine shard CSVs and generate final timing plot.

Usage examples
--------------
python combine_and_plot.py \
  --inputs shard_le_1020.csv shard_gt_1020.csv \
  --out-csv final_combined.csv \
  --out-plot final_timing_vs_nfiles.png
"""

from __future__ import annotations

import argparse
import logging
import os

import pandas as pd


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("combine_plot")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Combine two or more benchmark shard CSVs, deduplicate by key, "
            "write final CSV, and generate timing plot"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python combine_and_plot.py --inputs shard_le_1020.csv shard_gt_1020.csv "
            "--out-csv final_combined.csv --out-plot final_timing_vs_nfiles.png\n\n"
            "  python combine_and_plot.py --inputs runA.csv runB.csv runC.csv "
            "--out-csv final.csv --out-plot final.png --dedupe-key dataset_id"
        ),
    )
    parser.add_argument(
        "--inputs",
        nargs="+",
        required=True,
        help="Two or more input shard CSV paths",
    )
    parser.add_argument(
        "--out-csv",
        required=True,
        help="Output path for combined CSV",
    )
    parser.add_argument(
        "--out-plot",
        required=True,
        help="Output path for final timing plot",
    )
    parser.add_argument(
        "--dedupe-key",
        default="dataset_id",
        help="Column used for deduplication (default: dataset_id)",
    )

    args = parser.parse_args()

    if len(args.inputs) < 2:
        parser.error("--inputs requires at least 2 CSV files")

    missing = [p for p in args.inputs if not os.path.exists(p)]
    if missing:
        parser.error(f"Missing input CSV file(s): {', '.join(missing)}")

    return args


def _fmt_nfiles_label(n: float | int) -> str:
    n_int = int(n)
    if n_int >= 1000:
        return f"{n_int / 1000:.1f}k".replace(".0k", "k")
    return str(n_int)


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
    import matplotlib.pyplot as plt
    import numpy as np

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
        "netcdf_file_count",
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

    plt.figure(figsize=(9, 9))

    panels = [
        ("Open", "open_kerchunk", "open_netcdf"),
        ("Load", "load_kerchunk", "load_netcdf"),
        ("Temporal", "temporal_total_kerchunk", "temporal_total_netcdf"),
        ("Spatial", "spatial_total_kerchunk", "spatial_total_netcdf"),
    ]

    for i, (title, kcol, ncol) in enumerate(panels):
        plt.subplot(2, 2, i + 1)
        x = ok_df[kcol]
        y = ok_df[ncol]
        mv = max(float(np.nanmax(x)), float(np.nanmax(y)))
        if not np.isfinite(mv) or mv <= 0:
            mv = 1.0

        plt.scatter(x, y)
        offsets = [(4, 4), (4, -8), (-18, 4), (-18, -8)]
        for j, (xv, yv, nf) in enumerate(zip(x, y, ok_df["netcdf_file_count"])):
            dx, dy = offsets[j % len(offsets)]
            plt.annotate(
                _fmt_nfiles_label(nf),
                (xv, yv),
                xytext=(dx, dy),
                textcoords="offset points",
                fontsize=8,
                color="dimgray",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.7, pad=0.2),
            )

        plt.plot([0, mv], [0, mv], "k:")
        plt.title(title)
        plt.xlabel("Kerchunk [s]")
        plt.ylabel("NetCDF [s]")
        plt.xlim(0, mv)
        plt.ylim(0, mv)

    plt.suptitle("Frequency: Amon")
    plt.tight_layout()
    plt.savefig(out_plot, dpi=300)
    plt.close()
    logger.info("Timing plot saved to %s", out_plot)


def main() -> None:
    args = _parse_args()

    logger.info("Combining %d input CSVs", len(args.inputs))
    combined_df = _combine_csvs(args.inputs, args.dedupe_key)

    combined_df.to_csv(args.out_csv, index=False)
    logger.info("Combined CSV written to %s", args.out_csv)

    _plot_timing(combined_df, args.out_plot)


if __name__ == "__main__":
    main()
