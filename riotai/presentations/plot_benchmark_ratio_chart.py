"""Create the presentation-friendly benchmark ratio chart.

The chart uses per-dataset ``kerchunk time / NetCDF time`` ratios and plots
their median in each file-count bin.  Temporal and spatial timings include
both graph construction and computation.

The default display excludes the seven ECMWF HighResMIP datasets discussed
separately in the presentation, matching the displayed count of 73 datasets.
It writes separate workflow-operation and complete-pipeline plots by default; use
``--layout combined`` to recreate a two-panel version.

Example
-------
python riotai/presentations/plot_benchmark_ratio_chart.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter, LogLocator


PRESENTATIONS_DIR = Path(__file__).resolve().parent
IMAGES_DIR = PRESENTATIONS_DIR / "images"
RESULTS_DIR = (
    PRESENTATIONS_DIR.parent
    / "results"
    / "20260422-steve-file-count-crossover-upscale"
)
DEFAULT_INPUT = RESULTS_DIR / "final_combined.csv"
DEFAULT_OUTPUT = IMAGES_DIR / "benchmark_ratios_by_file_count.png"

NFILES_BIN_ORDER = (
    "25-49",
    "50-99",
    "100-149",
    "150-199",
    "200-299",
    "300-499",
    "500-749",
    "750-1000",
)
HIGHLIGHT_BIN = "150-199"

# These datasets are covered separately in the presentation.  Keeping the
# exclusion explicit makes the displayed count (73 of 80 rows) reproducible.
DISPLAY_EXCLUSION_PATTERN = r"\.HighResMIP\.ECMWF\."
EXPECTED_EXCLUDED_COUNT = 7
EXPECTED_DISPLAYED_COUNT = 73

TIMING_PAIRS = {
    "Open": ("open_kerchunk", "open_netcdf"),
    "Load": ("load_kerchunk", "load_netcdf"),
    "Temporal": ("temporal_total_kerchunk", "temporal_total_netcdf"),
    "Spatial": ("spatial_total_kerchunk", "spatial_total_netcdf"),
    "Open + Load": ("open_load_kerchunk", "open_load_netcdf"),
    "Open + Temporal": ("open_temporal_kerchunk", "open_temporal_netcdf"),
    "Open + Spatial": ("open_spatial_kerchunk", "open_spatial_netcdf"),
}

COLORS = {
    "Open": "#0072B2",
    "Load": "#D55E00",
    "Temporal": "#009E73",
    "Spatial": "#CC79A7",
    "Open + Load": "#E69F00",
    "Open + Temporal": "#009E73",
    "Open + Spatial": "#56B4E9",
}
MARKERS = ("o", "s", "^", "D")

COMPONENT_SERIES = (
    ("Open", "Open"),
    ("Load", "Load"),
    ("Temporal", "Temporal (build + compute)"),
    ("Spatial", "Spatial (build + compute)"),
)
PIPELINE_SERIES = (
    ("Open + Load", "Open + Load"),
    ("Open + Temporal", "Open + Temporal"),
    ("Open + Spatial", "Open + Spatial"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Benchmark CSV (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=(
            "Output image, or filename base for separate plots "
            f"(default: {DEFAULT_OUTPUT})"
        ),
    )
    parser.add_argument(
        "--layout",
        choices=("separate", "combined", "all"),
        default="separate",
        help="Write separate plots, combined plot, or both (default: separate)",
    )
    parser.add_argument(
        "--include-excluded",
        action="store_true",
        help="Include the seven ECMWF HighResMIP datasets covered elsewhere.",
    )
    parser.add_argument("--dpi", type=int, default=240, help="Output DPI (default: 240)")
    return parser.parse_args()


def prepare_ratios(
    frame: pd.DataFrame, *, include_excluded: bool = False
) -> tuple[pd.DataFrame, int]:
    """Filter displayed rows and add operation and complete-pipeline ratios."""
    required = {
        "dataset_id",
        "nfiles_bin",
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
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"Missing required CSV columns: {', '.join(missing)}")

    displayed = frame.loc[frame["status"].eq("ok")].copy() if "status" in frame else frame.copy()
    excluded_count = 0
    if not include_excluded:
        excluded = displayed["dataset_id"].str.contains(
            DISPLAY_EXCLUSION_PATTERN, regex=True, na=False
        )
        excluded_count = int(excluded.sum())
        displayed = displayed.loc[~excluded].copy()
        if excluded_count != EXPECTED_EXCLUDED_COUNT:
            raise ValueError(
                "Displayed-count exclusion selected "
                f"{excluded_count} rows; expected {EXPECTED_EXCLUDED_COUNT}."
            )
        if len(displayed) != EXPECTED_DISPLAYED_COUNT:
            raise ValueError(
                f"Found {len(displayed)} displayed rows; expected "
                f"{EXPECTED_DISPLAYED_COUNT}."
            )

    displayed["temporal_total_kerchunk"] = (
        displayed["temporal_build_kerchunk"]
        + displayed["temporal_compute_kerchunk"]
    )
    displayed["temporal_total_netcdf"] = (
        displayed["temporal_build_netcdf"] + displayed["temporal_compute_netcdf"]
    )
    displayed["spatial_total_kerchunk"] = (
        displayed["spatial_build_kerchunk"] + displayed["spatial_compute_kerchunk"]
    )
    displayed["spatial_total_netcdf"] = (
        displayed["spatial_build_netcdf"] + displayed["spatial_compute_netcdf"]
    )

    for suffix in ("load", "temporal", "spatial"):
        displayed[f"open_{suffix}_kerchunk"] = (
            displayed["open_kerchunk"] + displayed[f"{suffix}_total_kerchunk"]
            if suffix != "load"
            else displayed["open_kerchunk"] + displayed["load_kerchunk"]
        )
        displayed[f"open_{suffix}_netcdf"] = (
            displayed["open_netcdf"] + displayed[f"{suffix}_total_netcdf"]
            if suffix != "load"
            else displayed["open_netcdf"] + displayed["load_netcdf"]
        )

    for label, (kerchunk_column, netcdf_column) in TIMING_PAIRS.items():
        ratio_column = f"{label.lower().replace(' + ', '_')}_ratio"
        numerator = displayed[kerchunk_column]
        denominator = displayed[netcdf_column]
        if (numerator <= 0).any() or (denominator <= 0).any():
            raise ValueError(f"{label} includes a non-positive timing value")
        displayed[ratio_column] = numerator / denominator

    return displayed, excluded_count


def bin_medians(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Return median ratios and displayed row counts in presentation order."""
    unknown_bins = sorted(set(frame["nfiles_bin"].dropna()) - set(NFILES_BIN_ORDER))
    if unknown_bins:
        raise ValueError(f"Unexpected file-count bins: {', '.join(unknown_bins)}")

    ratio_columns = [
        f"{label.lower().replace(' + ', '_')}_ratio" for label in TIMING_PAIRS
    ]
    medians = frame.groupby("nfiles_bin")[ratio_columns].median().reindex(NFILES_BIN_ORDER)
    counts = frame.groupby("nfiles_bin").size().reindex(NFILES_BIN_ORDER, fill_value=0)
    if medians.isna().any().any():
        raise ValueError("At least one file-count bin has no usable timing ratios")
    return medians, counts


def _ratio_tick(value: float, _position: float) -> str:
    return f"{value:g}×"


def _plot_limits(medians: pd.DataFrame) -> tuple[float, float]:
    all_values = medians.to_numpy().ravel()
    lower = 10 ** np.floor(np.log10(all_values.min()))
    upper = 10 ** np.ceil(np.log10(all_values.max()))
    return min(lower, 0.1), max(upper, 10.0)


def _count_note(counts: pd.Series) -> str:
    common_count = int(counts.mode().iloc[0])
    exceptions = [
        f"{bin_name.replace('-', '–')} (n={int(count)})"
        for bin_name, count in counts.items()
        if int(count) != common_count
    ]
    note = f"Displayed datasets · n={common_count} per bin"
    return f"{note} except {', '.join(exceptions)}" if exceptions else note


def _style_axis(
    ax: plt.Axes,
    medians: pd.DataFrame,
    series: tuple[tuple[str, str], ...],
    *,
    lower: float,
    upper: float,
    annotate_crossover: bool,
) -> None:
    x = np.arange(len(NFILES_BIN_ORDER))
    highlight_index = NFILES_BIN_ORDER.index(HIGHLIGHT_BIN)

    ax.set_yscale("log")
    ax.set_ylim(lower, upper)
    ax.axhspan(lower, 1, color="#D9F0F7", alpha=0.72, zorder=0)
    ax.axhspan(1, upper, color="#FCE3D7", alpha=0.64, zorder=0)
    ax.axvspan(
        highlight_index - 0.5,
        highlight_index + 0.5,
        facecolor="none",
        edgecolor="#C99A00",
        linewidth=2.5,
        zorder=2,
    )
    ax.axhline(1, color="#222222", linestyle="--", linewidth=1.6, zorder=2)
    ax.text(
        highlight_index,
        0.97,
        "150–199 focus bin",
        transform=ax.get_xaxis_transform(),
        ha="center",
        va="top",
        color="#725B00",
        fontsize=10,
        fontweight="bold",
    )

    for line_index, (label, display_label) in enumerate(series):
        column = f"{label.lower().replace(' + ', '_')}_ratio"
        ax.plot(
            x,
            medians[column],
            color=COLORS[label],
            marker=MARKERS[line_index],
            markersize=8,
            linewidth=2.7,
            label=display_label,
            zorder=3,
        )

    tick_labels = [label.replace("-", "–") for label in NFILES_BIN_ORDER]
    ax.set_xticks(x, tick_labels, rotation=28, ha="right")
    ax.set_xlabel("Files per dataset", fontsize=13)
    ax.set_ylabel("Median kerchunk time / NetCDF time", fontsize=13)
    ax.grid(axis="x", visible=False)
    ax.grid(axis="y", which="major", color="#AAAAAA", alpha=0.35)
    ax.yaxis.set_major_locator(LogLocator(base=10))
    ax.yaxis.set_major_formatter(FuncFormatter(_ratio_tick))
    ax.legend(loc="lower right", frameon=True, framealpha=0.95, fontsize=10)
    ax.text(
        0.02,
        0.04,
        "Kerchunk faster",
        transform=ax.transAxes,
        color="#176B87",
        fontsize=10,
        fontweight="bold",
    )
    ax.text(
        0.02,
        0.95,
        "NetCDF faster",
        transform=ax.transAxes,
        color="#A3461D",
        fontsize=10,
        fontweight="bold",
        va="top",
    )
    if annotate_crossover:
        ax.annotate(
            "Operation crossover begins",
            xy=(highlight_index, 0.72),
            xytext=(highlight_index + 0.65, 0.18),
            arrowprops={"arrowstyle": "->", "color": "#725B00", "linewidth": 1.5},
            color="#725B00",
            fontsize=10,
            fontweight="bold",
        )


def _save_figure(fig: plt.Figure, output: Path, *, dpi: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def draw_single_chart(
    medians: pd.DataFrame,
    counts: pd.Series,
    output: Path,
    *,
    series: tuple[tuple[str, str], ...],
    title: str,
    annotate_crossover: bool,
    dpi: int,
) -> None:
    """Draw one projection-friendly chart."""
    lower, upper = _plot_limits(medians)
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(11.5, 6.5))
    _style_axis(
        ax,
        medians,
        series,
        lower=lower,
        upper=upper,
        annotate_crossover=annotate_crossover,
    )
    fig.suptitle(title, fontsize=21, fontweight="bold")
    fig.text(
        0.5,
        0.925,
        "Below 1× means kerchunk is faster",
        ha="center",
        fontsize=13,
    )
    fig.text(0.5, 0.012, _count_note(counts), ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.04, 1, 0.9))
    _save_figure(fig, output, dpi=dpi)


def draw_combined_chart(
    medians: pd.DataFrame, counts: pd.Series, output: Path, *, dpi: int
) -> None:
    """Draw optional two-panel chart."""
    lower, upper = _plot_limits(medians)

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(1, 2, figsize=(15.5, 6.8), sharey=True)
    for panel_index, (ax, series, title) in enumerate(
        zip(
            axes,
            (COMPONENT_SERIES, PIPELINE_SERIES),
            ("Workflow operations", "Complete pipelines"),
            strict=True,
        )
    ):
        _style_axis(
            ax,
            medians,
            series,
            lower=lower,
            upper=upper,
            annotate_crossover=panel_index == 0,
        )
        ax.set_title(title, fontsize=17, fontweight="bold", pad=12)
        if panel_index == 1:
            ax.set_ylabel("")

    fig.suptitle("Workflow timing ratio by file count", fontsize=21, fontweight="bold")
    fig.text(0.5, 0.925, "Below 1× means kerchunk is faster", ha="center", fontsize=13)
    fig.text(0.5, 0.01, _count_note(counts), ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.04, 1, 0.9), w_pad=2.5)
    _save_figure(fig, output, dpi=dpi)


def _separate_output(output: Path, suffix: str) -> Path:
    return output.with_name(f"{output.stem}_{suffix}{output.suffix}")


def main() -> None:
    args = parse_args()
    frame = pd.read_csv(args.input)
    displayed, excluded_count = prepare_ratios(
        frame, include_excluded=args.include_excluded
    )
    medians, counts = bin_medians(displayed)
    outputs: list[Path] = []
    if args.layout in {"separate", "all"}:
        components_output = _separate_output(args.output, "components")
        pipelines_output = _separate_output(args.output, "pipelines")
        draw_single_chart(
            medians,
            counts,
            components_output,
            series=COMPONENT_SERIES,
            title="Workflow operation timing ratios by file count",
            annotate_crossover=True,
            dpi=args.dpi,
        )
        draw_single_chart(
            medians,
            counts,
            pipelines_output,
            series=PIPELINE_SERIES,
            title="Complete-pipeline timing ratios by file count",
            annotate_crossover=False,
            dpi=args.dpi,
        )
        outputs.extend((components_output, pipelines_output))
    if args.layout in {"combined", "all"}:
        draw_combined_chart(medians, counts, args.output, dpi=args.dpi)
        outputs.append(args.output)

    print(
        f"Wrote {', '.join(str(path) for path in outputs)} from "
        f"{len(displayed)} displayed rows ({excluded_count} excluded)."
    )


if __name__ == "__main__":
    main()
