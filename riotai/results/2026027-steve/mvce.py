#%%
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


#%%
def _plot_results(df: pd.DataFrame, freq: str) -> None:
    df["temporal_total_kerchunk"] = (
        df["temporal_build_kerchunk"] + df["temporal_compute_kerchunk"]
    )
    df["temporal_total_netcdf"] = (
        df["temporal_build_netcdf"] + df["temporal_compute_netcdf"]
    )
    df["spatial_total_kerchunk"] = (
        df["spatial_build_kerchunk"] + df["spatial_compute_kerchunk"]
    )
    df["spatial_total_netcdf"] = (
        df["spatial_build_netcdf"] + df["spatial_compute_netcdf"]
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
        x = df[kcol]
        y = df[ncol]
        mv = max(float(np.nanmax(x)), float(np.nanmax(y)), 1.0)
        plt.scatter(x, y)
        plt.plot([0, mv], [0, mv], "k:")
        plt.title(title)
        plt.xlim(0, mv)
        plt.ylim(0, mv)

    plt.suptitle(f"Frequency: {freq}")
    plt.tight_layout()
    plt.savefig(os.path.join(ROOT_DIR, f"{_TS}_benchmark_{freq}.png"), dpi=300)
    plt.close()


#%%
df = pd.read_csv("riotai/results/2026027-steve/20260302_122701_benchmark.csv")

# %%
