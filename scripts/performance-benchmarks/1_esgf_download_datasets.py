# %%
import glob
import os
import shutil
import stat
import subprocess

# Example: `/home/vo13/xCDAT/xcdat-validation/scripts/performance-benchmarks/`
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
# ROOT_DIR = "./scripts/performance-benchmarks/"
# Example: `/home/vo13/xCDAT/xcdat-validation/scripts/performance-benchmarks/input-datasets/7gb/7gb.sh`
WGET_FILEPATHS = glob.glob(os.path.join(ROOT_DIR, "**/**/*.sh"))


# %%
def _move_ncfiles_to_dir(dir: str):
    filepaths = glob.glob(os.path.join("./", "*.nc"))

    for file in filepaths:
        shutil.move(file, dir)


if __name__ == "__main__":
    for path in WGET_FILEPATHS[0:1]:

        # print(f"Running {path}")
        # st = os.stat(path)
        # os.chmod(path, st.st_mode | stat.S_IEXEC)

        # -s flag is required to bypass ESG credential check.
        # Related issue: https://github.com/esgf2-us/metagrid/issues/617
        # proc = subprocess.run([path, "-s"], capture_output=True)
        # output = proc.stdout.decode()
        # print(output)

        subprocess.call([path, "-s"])

        # Example:
        filename = path.split("/")[-1]
        # Example:
        file_dir = path.split(filename)[0]

        _move_ncfiles_to_dir(file_dir)

# %%
