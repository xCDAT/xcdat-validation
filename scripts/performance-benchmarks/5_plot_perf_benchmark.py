import os
import time

import pandas as pd

# Input CSV file configurations
# -----------------------------
# TODO: Update ROOT_DIR, XC_CSV_FILENAME, and CD_CSV_FILENAME
ROOT_DIR = "./scripts/performance-benchmarks/joss-paper-results-spatial-avg/"
XC_CSV_FILENAME = os.path.join(ROOT_DIR, "20240102-135850-xcdat-runtimes.csv")
CD_CSV_FILENAME = os.path.join(ROOT_DIR, "20240102-135850-cdat-runtimes.csv")

# Output plot configurations
# --------------------------
TIME_STR = time.strftime("%Y%m%d-%H%M%S")
XC_PLOT_FILEPATH = f"{ROOT_DIR}/{TIME_STR}-xcdat-runtimes"
CD_PLOT_FILENAME = f"{ROOT_DIR}/{TIME_STR}-cdat-runtimes"

# Plot configs
# -------------------
# The base plot configuration passed to Panda's DataFrame plotting API.
PLOT_CONFIG: pd.DataFrame.plot.__init__ = {
    "kind": "bar",
    "legend": True,
    "rot": 0,
    "x": "gb",
    "xlabel": "File Size (GB)",
    "ylabel": "Runtime (secs)",
    "figsize": (6, 4),
}
# The base bar label configuration passed to axis containers to add
# the floating point labels above the bars.
BAR_LABEL_CONFIG = {
    "fmt": "{:10.2f}",
    "label_type": "edge",
    "padding": 3,
    "fontsize": 8,
}


def main():
    # 1. Plot xCDAT runtimes
    df_xc = pd.read_csv(XC_CSV_FILENAME)
    _plot_xcdat_runtimes(df_xc)

    # 2. Plot CDAT runtimes
    df_cdat = pd.read_csv(CD_CSV_FILENAME)
    _plot_cdat_runtimes(df_cdat)


def _plot_xcdat_runtimes(df_xcdat: pd.DataFrame):
    apis = df_xcdat.api.unique()

    for api in apis:
        ax = df_xcdat.plot(**PLOT_CONFIG)

        for cont in ax.containers:
            labels = ["{:10.2f}".format(v) if v > 0.00 else "" for v in cont.datavalues]
            ax.bar_label(cont, **BAR_LABEL_CONFIG, labels=labels)

        ax.margins(y=0.1)
        ax.legend(
            ["Serial", "Parallel"],
            fontsize=10,
            loc="upper center",
            ncol=2,
        )

        fig = ax.get_figure()

        api_title = api.title().replace("_", " ")
        fig.suptitle(f"xCDAT {api_title} Runtime")
        fig.tight_layout()
        fig.savefig(f"{XC_PLOT_FILEPATH}-{api}.png")


def _plot_cdat_runtimes(df_cdat: pd.DataFrame):
    apis = df_cdat.api.unique()

    for api in apis:
        ax = df_cdat.plot(**PLOT_CONFIG)

        for cont in ax.containers:
            ax.bar_label(cont, **BAR_LABEL_CONFIG)

        ax.margins(y=0.1)
        ax.legend(["Serial"], fontsize="medium", loc="upper center", ncol=1)

        fig = ax.get_figure()

        api_title = api.title().replace("_", " ")
        fig.suptitle(f"CDAT {api_title} Runtime")
        fig.tight_layout()

        fig.savefig(f"{CD_PLOT_FILENAME}-{api}.png")


if __name__ == "__main__":
    main()
