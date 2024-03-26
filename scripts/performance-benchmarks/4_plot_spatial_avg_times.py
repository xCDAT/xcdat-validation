# %%
import os
import time

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# %% Get the CSV data into DataFrames.
# TODO: Update ROOT_PATH, XCDAT_CSV_PATH, and CDAT_CSV_PATH
ROOT_PATH = "./scripts/performance-benchmarks/joss-paper-results-spatial-avg/"
XCDAT_CSV_PATH = os.path.join(ROOT_PATH, "20240102-135850-xcdat-runtimes.csv")
CDAT_CSV_PATH = os.path.join(ROOT_PATH, "20240102-135850-cdat-runtimes.csv")

df_xcdat = pd.read_csv(XCDAT_CSV_PATH)
df_cdat = pd.read_csv(CDAT_CSV_PATH)

# %% Get x / y series.
bar_width = 0.25
y_cdat = df_cdat["serial_runtime"].values
x_cdat = np.arange(len(y_cdat))
y_xcdats = df_xcdat["runtime_serial"].values
x_xcdats = x_cdat + bar_width
y_xcdatp = df_xcdat["runtime_parallel"].values
x_xcdatp = x_xcdats + bar_width

# %% Plot the data.
# Set up the bar plot objects.
plt.bar(
    x_cdat, y_cdat, width=bar_width, facecolor="firebrick", edgecolor=None, label="CDAT"
)
plt.bar(
    x_xcdats,
    y_xcdats,
    width=bar_width,
    facecolor="darkseagreen",
    edgecolor=None,
    label="xCDAT Serial",
)
plt.bar(
    x_xcdatp,
    y_xcdatp,
    width=bar_width,
    facecolor="rebeccapurple",
    edgecolor=None,
    label="xCDAT Parallel",
)
# Add plot labels.
plt.legend(loc="upper left", frameon=False)
plt.title("Spatial Average Runtime Comparison")
plt.ylabel("Runtime [s]")
plt.xlabel("Filesize [GB]")
plt.xticks(x_xcdats, labels=df_cdat["gb"])

# Update the spines.
ax = plt.gca()

# Move left and bottom spines outward by 10 points.
ax.spines.left.set_position(("outward", 10))

# Hide the right and top spines.
ax.spines.right.set_visible(False)
ax.spines.top.set_visible(False)

# Only show ticks on the left and bottom spines.
ax.yaxis.set_ticks_position("left")
ax.xaxis.set_ticks_position("bottom")

# The base bar label configuration passed to axis containers to add
# the floating point labels above the bars.
BAR_LABEL_CONFIG = {
    "label_type": "edge",
    "padding": 2,
    "fontsize": 10,
}
for cont in ax.containers:
    labels = ["{:10.0f}".format(v) if v > 0.00 else "" for v in cont.datavalues]
    ax.bar_label(cont, **BAR_LABEL_CONFIG, labels=labels)

# %% Save the figure
TIME_STR = time.strftime("%Y%m%d-%H%M%S")
png_path = os.path.join(ROOT_PATH, f"{TIME_STR}-spatial-avg-runtimes.png")

plt.savefig(png_path)
plt.show()
