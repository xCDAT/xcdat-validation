import glob
import os
import shutil
import subprocess

# Example: `/home/vo13/xCDAT/xcdat-validation/scripts/performance-benchmarks/`
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Example: `/home/vo13/xCDAT/xcdat-validation/scripts/performance-benchmarks/input-datasets/7gb/7gb.sh`
WGET_FILEPATHS = glob.glob(os.path.join(ROOT_DIR, "**/**/*.sh"))


def main():
    for path in WGET_FILEPATHS:
        # -s flag is required to bypass ESG credential check.
        # Related issue: https://github.com/esgf2-us/metagrid/issues/617
        subprocess.call([path, "-s"])

        filename = path.split("/")[-1]
        filedir = path.split(filename)[0]

        _move_ncfiles_to_dir(filedir)


def _move_ncfiles_to_dir(dir: str):
    """Move the nc files to the sub-directories by file size.

    The wget scripts download the data to the root of the repo. After iteration,
    this function moves those files to the correct sub-directory by file size.

    Parameters
    ----------
    dir : str
        The sub-directory for the respective iteration, by file size.
    """
    filepaths = glob.glob(os.path.join("./", "*.nc"))

    for file in filepaths:
        shutil.move(file, dir)


if __name__ == "__main__":
    main()
