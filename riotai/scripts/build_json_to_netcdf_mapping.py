"""Incrementally update the json_to_netcdf mapping from kerchunk JSON references.

This script is meant to be run directly in a Python session or as a plain
script. It reuses the helper functions in ``riotai.mapping`` and, by default,
skips JSON references that are already present in the existing mapping file.

Usage:
salloc --nodes 1 --qos interactive --time 02:00:00 --constraint cpu --account=e3sm
conda env create -f riotai/test_stable_min.yml
conda activate xcdat_test_stable_min
python riotai/scripts/build_json_to_netcdf_mapping.py
"""

from __future__ import annotations

import glob
import logging
from pathlib import Path
import sys

import orjson

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from riotai.mapping import (
        _get_netcdf_paths_by_json,
        _group_json_files_by_frequency,
        _write_mappings_to_disk,
    )
except ModuleNotFoundError as exc:
    if exc.name == "riotai":
        raise
    raise ModuleNotFoundError(
        "Failed to import riotai.mapping dependencies. "
        f"Missing module: {exc.name}. "
        "Run this script in the environment that has riotai's dependencies installed."
    ) from exc


ROOT_DATA_DIR = Path("/global/cfs/projectdirs/m4931/kerchunk")
MAPPING_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "json_to_netcdf_maps"
MAPPING_PATH = MAPPING_OUTPUT_DIR / "json_to_netcdf.json"
ERROR_PATH = MAPPING_OUTPUT_DIR / "json_to_netcdf_errors.json"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def find_json_paths(root_data_dir: Path = ROOT_DATA_DIR) -> list[str]:
    """Collect all kerchunk JSON files under the configured root."""
    pattern = str(root_data_dir / "**" / "*.json")
    return sorted(glob.glob(pattern, recursive=True))


def _load_existing_json(path: Path) -> dict:
    if not path.exists():
        return {}

    try:
        with path.open("rb") as f:
            return orjson.loads(f.read())
    except (OSError, orjson.JSONDecodeError):
        logger.warning("Ignoring unreadable JSON file at %s", path)
        return {}


def _count_netcdf_paths(freq_to_json_to_netcdf: dict[str, dict[str, list[str]]]) -> int:
    return sum(
        len(netcdf_paths)
        for json_to_netcdf in freq_to_json_to_netcdf.values()
        for netcdf_paths in json_to_netcdf.values()
    )


def rebuild_mappings(
    root_data_dir: Path = ROOT_DATA_DIR,
    mapping_path: Path = MAPPING_PATH,
    error_path: Path = ERROR_PATH,
    skip_existing: bool = True,
) -> tuple[dict[str, dict[str, list[str]]], dict[str, str]]:
    """Update and overwrite the json_to_netcdf mapping files."""
    json_paths = find_json_paths(root_data_dir)
    logger.info(
        "Discovered %d kerchunk JSON files under %s", len(json_paths), root_data_dir
    )

    freq_to_jsons = _group_json_files_by_frequency(json_paths)
    logger.info("Grouped JSON files into %d frequencies", len(freq_to_jsons))

    existing_mapping = _load_existing_json(mapping_path)
    existing_errors = _load_existing_json(error_path)

    freq_to_json_to_netcdf: dict[str, dict[str, list[str]]] = {
        frequency: dict(json_to_netcdf)
        for frequency, json_to_netcdf in existing_mapping.items()
    }
    errors: dict[str, str] = dict(existing_errors)

    existing_json_paths = {
        json_path
        for json_to_netcdf in freq_to_json_to_netcdf.values()
        for json_path in json_to_netcdf
    }
    known_error_paths = set(errors)
    known_json_paths = existing_json_paths | known_error_paths

    logger.info(
        "Loaded existing cache | frequencies=%d | mapped_jsons=%d | errored_jsons=%d",
        len(freq_to_json_to_netcdf),
        len(existing_json_paths),
        len(known_error_paths),
    )

    for index, (frequency, frequency_json_paths) in enumerate(
        freq_to_jsons.items(), start=1
    ):
        if skip_existing:
            pending_json_paths = [
                path for path in frequency_json_paths if path not in known_json_paths
            ]
        else:
            pending_json_paths = frequency_json_paths

        logger.info(
            "%d/%d -- Updating frequency '%s' | total=%d | pending=%d",
            index,
            len(freq_to_jsons),
            frequency,
            len(frequency_json_paths),
            len(pending_json_paths),
        )

        if not pending_json_paths:
            freq_to_json_to_netcdf.setdefault(frequency, {})
            continue

        frequency_mapping, frequency_errors = _get_netcdf_paths_by_json(
            pending_json_paths
        )
        freq_to_json_to_netcdf.setdefault(frequency, {}).update(frequency_mapping)
        errors.update(frequency_errors)
        existing_json_paths.update(frequency_mapping)
        known_json_paths.update(frequency_mapping)
        known_json_paths.update(frequency_errors)

    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    _write_mappings_to_disk(
        freq_to_json_to_netcdf,
        errors,
        str(mapping_path),
        str(error_path),
    )

    total_jsons = sum(
        len(json_to_netcdf) for json_to_netcdf in freq_to_json_to_netcdf.values()
    )
    total_netcdfs = _count_netcdf_paths(freq_to_json_to_netcdf)
    logger.info("Wrote mapping file to %s", mapping_path)
    logger.info("Wrote error file to %s", error_path)
    logger.info(
        "Summary | frequencies=%d | jsons=%d | netcdf_paths=%d | errors=%d | skip_existing=%s",
        len(freq_to_json_to_netcdf),
        total_jsons,
        total_netcdfs,
        len(errors),
        skip_existing,
    )

    return freq_to_json_to_netcdf, errors


def main() -> tuple[dict[str, dict[str, list[str]]], dict[str, str]]:
    return rebuild_mappings()


if __name__ == "__main__":
    main()
