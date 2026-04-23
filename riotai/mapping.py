# %%
import logging
import os

import orjson
from tqdm import tqdm
import re
from collections import defaultdict

logger = logging.getLogger(__name__)

VERSION_PATTERN = re.compile(r"v\d+$")


def load_or_build_mappings(
    mapping_path: str, error_path: str, json_paths: list[str]
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Load cached JSON→NetCDF mappings if available, otherwise build them.

    Parameters
    ----------
    mapping_path : str
        Path to the JSON→NetCDF mapping file.
    error_path : str
        Path to the error file.
    json_paths : list of str
        Paths to kerchunk JSON reference files.

    Returns
    -------
    freq_to_json_to_netcdf : dict of str to dict of str to list of str
        Mapping from frequency to JSON file paths to lists of NetCDF file paths.
    errors : dict of str to str
        Mapping from JSON file paths to error messages.
    """
    try:
        with open(mapping_path, "rb") as f:
            freq_to_json_to_netcdf = orjson.loads(f.read())

        with open(error_path, "rb") as f:
            errors = orjson.loads(f.read())
    except (FileNotFoundError, orjson.JSONDecodeError, OSError):
        freq_to_jsons = _group_json_files_by_frequency(json_paths)
        freq_to_json_to_netcdf = {freq: {} for freq in freq_to_jsons}

        for index, (freq, jsons) in enumerate(freq_to_jsons.items()):
            logger.info(
                f"{index+1}/{len(freq_to_jsons)} -- Processing frequency '{freq}' with {len(jsons)} JSON files..."
            )
            freq_to_json_to_netcdf[freq], errors = _get_netcdf_paths_by_json(jsons)

        _write_mappings_to_disk(
            freq_to_json_to_netcdf, errors, mapping_path, error_path
        )
    else:
        logger.info(
            "Loaded cached JSON→NetCDF mappings from disk.\n"
            f"  * Mappings: {mapping_path}\n"
            f"  * Errors:   {error_path}"
        )

    total_json_files = sum(
        len(json_to_netcdf) for json_to_netcdf in freq_to_json_to_netcdf.values()
    )
    total_netcdf_files = sum(
        len(nc_files)
        for json_to_netcdf in freq_to_json_to_netcdf.values()
        for nc_files in json_to_netcdf.values()
    )
    logger.info("\n=== Summary ===")
    logger.info(f"* Total JSON files processed: {total_json_files}")
    logger.info(f"* Total NetCDF files found:   {total_netcdf_files}")
    logger.info(
        f"* Frequencies ({len(freq_to_json_to_netcdf)}): {list(freq_to_json_to_netcdf.keys())}"
    )
    for freq, json_to_netcdf in freq_to_json_to_netcdf.items():
        json_count = len(json_to_netcdf)
        netcdf_count = sum(len(nc_files) for nc_files in json_to_netcdf.values())
        logger.info(f"  - {freq}: {json_count} JSON files, {netcdf_count} NetCDF files")
    logger.info(f"* JSON files with errors:     {len(errors)}")

    return freq_to_json_to_netcdf, errors


def _group_json_files_by_frequency(json_paths: list[str]) -> dict[str, list[str]]:
    """Group kerchunk JSON files by frequency based on filename pattern.

    For example: CMIP6.ScenarioMIP.EC-Earth-Consortium.EC-Earth3.ssp119.r150i1p1f1.Amon.tas.gr.v20200412.kerchunk.json --> freq is 'Amon'.

    Parameters
    ----------
    json_paths : list of str
        Paths to kerchunk JSON reference files.

    Returns
    -------
    dict of str to list of str
        Mapping from frequency to list of JSON file paths.
    """
    freq_to_jsons = defaultdict(list)

    for path in json_paths:
        freq = _extract_frequency_from_json_path(path)
        if freq is not None:
            freq_to_jsons[freq].append(path)

    return freq_to_jsons


def _extract_frequency_from_json_path(path: str) -> str | None:
    """Extract the CMIP frequency token from a kerchunk JSON filename.

    We see multiple filename variants in the archive, including:
    - ``...Amon.tas.gn.v20200412.kerchunk.json``
    - ``...Amon.tas.gnkerchunk.json``
    - ``...Amon.tas.grkerchunk.json``

    All of them share the same tail structure:
    ``<freq>.<variable>.<grid>[.<version>]kerchunk.json``.
    """
    fname = os.path.basename(path)
    suffix = "kerchunk.json"

    if not fname.endswith(suffix):
        return None

    tail = fname[: -len(suffix)].rstrip(".")
    parts = tail.split(".")

    if len(parts) < 3:
        return None

    if VERSION_PATTERN.fullmatch(parts[-1]):
        if len(parts) < 4:
            return None
        return parts[-4]

    return parts[-3]


def _get_netcdf_paths_by_json(
    json_paths: list[str],
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """
    Get NetCDF file paths for each kerchunk JSON reference file.

    Parameters
    ----------
    json_paths : list of str
        Paths to kerchunk JSON reference files.

    Returns
    -------
    json_to_netcdf : dict of str to list of str
        Mapping from JSON file paths to lists of NetCDF file paths.
    errors : dict of str to str
        Mapping from JSON file paths to error messages.
    """
    json_to_netcdf = {}
    errors = {}

    for json_path in tqdm(json_paths, desc="* Processing kerchunk JSONs"):
        try:
            with open(json_path, "rb") as f:
                refs = orjson.loads(f.read())

            # 1. MultiZarrToZarr sources (fastest)
            mz_sources = refs.get("meta", {}).get("sources")
            if mz_sources:
                json_to_netcdf[json_path] = sorted(set(mz_sources))
                continue

            # 2. Fallback: extract from refs
            sources = _extract_sources_from_refs(refs)
            json_to_netcdf[json_path] = sorted(sources)

        except (PermissionError, OSError) as e:
            errors[json_path] = str(e)
        except Exception as e:
            errors[json_path] = f"{type(e).__name__}: {e}"

    return json_to_netcdf, errors


def _extract_sources_from_refs(refs: dict) -> set[str]:
    """Extract unique source file paths from kerchunk refs dictionary.

    Parameters
    ----------
    refs : dict
        The kerchunk references dictionary.

    Returns
    -------
    set of str
        Unique source file paths extracted from the refs.
    """
    sources = set()

    for v in refs.get("refs", {}).values():
        if isinstance(v, list) and v:  # non-empty list
            sources.add(v[0])

    return sources


def _write_mappings_to_disk(
    freq_to_json_to_netcdf: dict[str, dict[str, list[str]]],
    errors: dict[str, str],
    mapping_path: str,
    error_path: str,
) -> None:
    """Write mappings to disk for reuse.

    Parameters
    ----------
    freq_to_json_to_netcdf : dict of str to dict of str to list of
        Mapping from frequency to JSON file paths to lists of NetCDF file paths.
    errors : dict of str to str
        Mapping from JSON file paths to error messages.
    mapping_path : str
        Path to save the JSON→NetCDF mapping file.
    error_path : str
        Path to save the error file.

    Returns
    -------
    None
    """
    with open(mapping_path, "wb") as f:
        f.write(orjson.dumps(freq_to_json_to_netcdf, option=orjson.OPT_INDENT_2))

    with open(error_path, "wb") as f:
        f.write(orjson.dumps(errors, option=orjson.OPT_INDENT_2))
