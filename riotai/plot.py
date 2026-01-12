import os
import numpy as np
import json
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# -------------------------------------------------------------------
# Load data
# -------------------------------------------------------------------

# TODO: Update timestamp based on the file you want to plot.
TIMESTAMP = "20260112_114706"
BASE_FILEPATH = (
    f"riotai/results/{TIMESTAMP}/kerchunk_vs_netcdf_freq_avg_speed_{TIMESTAMP}"
)
os.makedirs(f"riotai/results/{TIMESTAMP}", exist_ok=True)

with open(f"{BASE_FILEPATH}.json") as f:
    data = json.load(f)

freq_order = {
    "CFsubhr": 1,  # sub-hourly
    "AERhr": 2,  # hourly
    "day": 3,  # daily
    "ImonAnt": 4,  # monthly (Antarctic)
    "ImonGre": 5,  # monthly (Greenland)
    "Amon": 6,  # monthly
}

frequencies = sorted(data.keys(), key=lambda f: freq_order.get(f, 999))

kerchunk_medians = [data[f]["kerchunk_median"] for f in frequencies]
netcdf_medians = [data[f]["netcdf_median"] for f in frequencies]
ns = [data[f]["n"] for f in frequencies]

x = np.arange(len(frequencies))
width = 0.35

# -------------------------------------------------------------------
# Plot
# -------------------------------------------------------------------

fig, ax1 = plt.subplots(figsize=(max(8, len(frequencies) * 1.2), 5))

# Kerchunk bars (left y-axis)
bars1 = ax1.bar(
    x - width / 2,
    kerchunk_medians,
    width,
    label="Kerchunk (median)",
    color="tab:blue",
)
ax1.set_ylabel("Kerchunk Median Time (seconds)", color="tab:blue")
ax1.tick_params(axis="y", labelcolor="tab:blue")

# NetCDF bars (right y-axis)
ax2 = ax1.twinx()
bars2 = ax2.bar(
    x + width / 2,
    netcdf_medians,
    width,
    label="NetCDF (median)",
    color="tab:orange",
)
ax2.set_ylabel("NetCDF Median Time (seconds)", color="tab:orange")
ax2.tick_params(axis="y", labelcolor="tab:orange")

# -------------------------------------------------------------------
# Log scale + formatting
# -------------------------------------------------------------------

ax1.set_yscale("log")
ax2.set_yscale("log")

ax1.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2g"))
ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2g"))

# Light grid (single axis)
ax1.grid(True, axis="y", which="major", linestyle=":", alpha=0.4)

# -------------------------------------------------------------------
# Add log-scale headroom for annotations
# -------------------------------------------------------------------


def add_log_headroom(ax, values, factor=1.6):
    ymin, ymax = ax.get_ylim()
    ax.set_ylim(ymin, max(ymax, max(values)) * factor)


add_log_headroom(ax1, kerchunk_medians)
add_log_headroom(ax2, netcdf_medians)

# -------------------------------------------------------------------
# Annotations (slightly tighter offset)
# -------------------------------------------------------------------

for bar, n, median in zip(bars1, ns, kerchunk_medians):
    ax1.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() * 1.04,
        f"{median:.2g}\nn={n}",
        ha="center",
        va="bottom",
        fontsize=9,
        color="tab:blue",
    )

for bar, n, median in zip(bars2, ns, netcdf_medians):
    ax2.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() * 1.04,
        f"{median:.2g}\nn={n}",
        ha="center",
        va="bottom",
        fontsize=9,
        color="tab:orange",
    )

# -------------------------------------------------------------------
# Frequency grouping cue (hourly/daily vs monthly)
# -------------------------------------------------------------------

ax1.axvline(2.5, color="gray", linestyle=":", alpha=0.3)

# -------------------------------------------------------------------
# Labels and title
# -------------------------------------------------------------------

ax1.set_xlabel("Frequency")
ax1.set_title(
    "Median read times (log scale): Kerchunk-based access vs native NetCDF by frequency"
)

ax1.set_xticks(x)
ax1.set_xticklabels(frequencies, rotation=30, ha="right")

fig.tight_layout()
plt.subplots_adjust(bottom=0.15)
plt.show()

BASERESULTS_PATH = "riotai/json_to_netcdf_maps/kerchunk_vs_netcdf_freq_avg_speed_"

fig.savefig(f"{BASE_FILEPATH}.png", dpi=150)
