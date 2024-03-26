# %%
import glob
import os
import stat
import subprocess
import sys
from typing import List

from cdms2 import cdscan

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(ROOT_DIR, "input-datasets")


def main():
    for input_path, dir_names, _ in os.walk(INPUT_DIR):
        for dir_name in dir_names:
            dir_path = os.path.abspath(os.path.join(input_path, dir_name))

            _set_cdscan_args(dir_path, dir_name)
            cdscan.main(sys.argv)


def _set_cdscan_args(dir_path: str, dir_name: str) -> List[str]:
    """Set the cdscan args through sys.argv.

    Parameters
    ----------
    dir_path : str
        The absolute directory path containing the input datasets for the
        specified file size (e.g., "/input-datasets/7gb/")
    dir_name : str
        The name of the directory (e.g., "7gb")

    Returns
    -------
    List[str]
        The sys.argv arguments that will be passed to cdscan.
    """
    # Get the cdscan args.
    xml_filepath = _create_xml_file(dir_path, dir_name)
    nc_glob = glob.glob(os.path.join(dir_path, "*.nc"))
    cdscan_args = ["-x", xml_filepath] + nc_glob

    # Save the original args and append the cdscan args.
    # We use this method instead of `sys.argv.extend()` because we want to reset
    # sys.argv after each iteration of `os.walk`.
    og_args = sys.argv
    sys.argv = og_args + cdscan_args


def _create_xml_file(dir_path: str, dir_name: str) -> str:
    """Create an empty XML file to pass to cdscan.

    Parameters
    ----------
    dir_path : str
        The absolute directory path containing the input datasets for the
        specified file size (e.g., "/input-datasets/7gb/")
    dir_name : str
        The name of the directory (e.g., "7gb")

    Returns
    -------
    str
        The path to the XML file.
    """
    xml_filepath = os.path.join(dir_path, f"{dir_name}.xml")

    with open(xml_filepath, "w") as file:
        pass

    return xml_filepath


if __name__ == "__main__":
    main()
