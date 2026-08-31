"""Merge remote benchmark shards with the existing local final_combined.csv.

The local baseline is never modified. The output contains local columns with a
``_local`` suffix, remote columns with a ``_remote`` suffix, and remote/local
ratios for shared Kerchunk timing metrics.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_BASELINE = ROOT_DIR / "final_combined.csv"
DEFAULT_REMOTE_GLOB = "remote_perlmutter_to_ornl_*.csv"
DEFAULT_OUT = ROOT_DIR / "final_combined_with_remote.csv"


def _resolve(path: str) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else ROOT_DIR / candidate


def _read_csv(path: Path, label: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{label} CSV does not exist: {path}")
    frame = pd.read_csv(path)
    if "dataset_id" not in frame:
        raise ValueError(f"{label} CSV has no dataset_id column: {path}")
    return frame


def _remote_shards(paths: list[Path]) -> pd.DataFrame:
    if not paths:
        raise FileNotFoundError(
            f"No remote shards matched {DEFAULT_REMOTE_GLOB!r} in {ROOT_DIR}"
        )
    frames = [_read_csv(path, "Remote shard") for path in paths]
    remote = pd.concat(frames, ignore_index=True, sort=False)
    remote = remote.drop_duplicates(subset=["dataset_id"], keep="last")
    if "status" in remote:
        remote = remote[remote["status"] == "ok"].copy()
    return remote


def _add_timing_ratios(combined: pd.DataFrame) -> None:
    for metric in (
        "open_kerchunk",
        "load_kerchunk",
        "temporal_build_kerchunk",
        "temporal_compute_kerchunk",
        "spatial_build_kerchunk",
        "spatial_compute_kerchunk",
    ):
        local = f"{metric}_local"
        remote = f"{metric}_remote"
        if local not in combined or remote not in combined:
            continue
        denominator = pd.to_numeric(combined[local], errors="coerce")
        numerator = pd.to_numeric(combined[remote], errors="coerce")
        combined[f"{metric}_remote_to_local_ratio"] = numerator.div(
            denominator.where(denominator != 0)
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge remote Kerchunk shards with the local final_combined baseline."
    )
    parser.add_argument("--baseline-csv", default=str(DEFAULT_BASELINE))
    parser.add_argument(
        "--remote-inputs",
        nargs="+",
        default=None,
        help=(
            "Remote shard CSVs. Defaults to "
            f"{DEFAULT_REMOTE_GLOB} in this script directory."
        ),
    )
    parser.add_argument("--out-csv", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    baseline = _read_csv(_resolve(args.baseline_csv), "Baseline")
    remote_paths = (
        [_resolve(path) for path in args.remote_inputs]
        if args.remote_inputs is not None
        else sorted(ROOT_DIR.glob(DEFAULT_REMOTE_GLOB))
    )
    remote = _remote_shards(remote_paths)

    combined = baseline.merge(
        remote,
        on="dataset_id",
        how="left",
        suffixes=("_local", "_remote"),
        validate="one_to_one",
    )
    _add_timing_ratios(combined)

    out_path = _resolve(args.out_csv)
    combined.to_csv(out_path, index=False)
    print(f"Wrote {len(combined)} baseline rows to {out_path}")
    print(f"Remote successful rows merged: {len(remote)}")
    print(f"Baseline rows without remote result: {combined['status_remote'].isna().sum()}")


if __name__ == "__main__":
    main()
