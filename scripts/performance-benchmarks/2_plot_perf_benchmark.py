import time

import pandas as pd

# Output file configurations
# --------------------------
TIME_STR = time.strftime("%Y%m%d-%H%M%S")

# TODO: Update ROOT_DIR directory.
ROOT_DIR = "scripts/10-18-23-perf-metrics/"
XC_FILENAME = f"{ROOT_DIR}/{TIME_STR}-xcdat-runtimes"
CD_FILENAME = f"{ROOT_DIR}/{TIME_STR}-cdat-runtimes"

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
        fig.savefig(f"{XC_FILENAME}-{api}.png")


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

        fig.savefig(f"{CD_FILENAME}-{api}.png")


if __name__ == "__main__":
    # 1. Plot xCDAT runtimes
    df_xc = pd.read_csv(
        "/home/vo13/xCDAT/xcdat_test/scripts/10-18-23-perf-metrics/11-15-23-perf-metrics-spatial-avg/20231115-092731-xcdat-runtimes.csv"
    )
    _plot_xcdat_runtimes(df_xc)

    # 2. Plot CDAT runtimes
    # df_cdat = pd.read_csv("")
    # _plot_cdat_runtimes(df_cdat_times)
