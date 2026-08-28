# Presentation-aligned remote Kerchunk benchmark

`head_to_head.py` preserves the 2026-04-22 presentation workload: its `Amon`
prepared-dataset selection, file-count bins, ranks, fixed 240-timestep slice,
and open/load/temporal/spatial diagnostics. It supports two explicit modes:
`--mode remote` maps inventory JSON paths to public ORNL URLs and measures only
remote Kerchunk I/O; `--mode local` runs the original local Kerchunk-versus-
NetCDF comparison on Perlmutter.

Run this from the external machine whose user experience you want to measure.
The repository's `riotai/json_to_netcdf_maps/prepared_datasets_Amon.csv` is a
local selection manifest only. It does not cause local data reads.

## macOS setup

```bash
git clone --branch kerchunk https://github.com/xCDAT/xcdat-validation.git
cd xcdat-validation

conda env create -f riotai/test_stable_min.yml -n xcdat-remote
conda activate xcdat-remote
```

## Smoke test

```bash
SCRIPT="$PWD/riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py"
OUT="$PWD/remote_0422_smoke.csv"

python "$SCRIPT" \
  --mode remote \
  --target-frequency Amon \
  --bins 25-49 \
  --datasets-per-bin 1 \
  --ntests 1 \
  --cache-mode uncontrolled \
  --out-csv "$OUT" \
  --skip-plot
```

## Full benchmark

Use one resumable output file. `warm` discards the first iteration and reports
the median of the remaining iterations; it does not guarantee a globally cold
HTTP cache.

```bash
OUT="$PWD/remote_0422_upscale.csv"

python "$SCRIPT" \
  --mode remote \
  --target-frequency Amon \
  --bins 25-49,50-99,100-149 \
  --cache-mode warm \
  --out-csv "$OUT" --resume-csv "$OUT" --skip-plot

python "$SCRIPT" \
  --mode remote \
  --target-frequency Amon \
  --bins 150-199,200-299 \
  --cache-mode warm \
  --out-csv "$OUT" --resume-csv "$OUT" --skip-plot

python "$SCRIPT" \
  --mode remote \
  --target-frequency Amon \
  --bins 300-499,500-749,750-1000 \
  --cache-mode warm \
  --out-csv "$OUT" --resume-csv "$OUT" --skip-plot
```

Remote Kerchunk references are usable only while their embedded HTTP(S) data
URLs remain live. A `ReferenceNotReachable` or HTTP 404 means the published
reference needs repair or regeneration; the benchmark does not fall back to
local data.

## Regular local Kerchunk-versus-NetCDF benchmark

Use `--mode local` for the regular local comparison. It opens local NetCDF
files and produces Kerchunk-to-NetCDF ratios. Run it only on Perlmutter:

```bash
conda activate xcdat_test_stable_min
python riotai/scripts/prepare_datasets.py --target-frequency Amon

salloc --nodes 1 --qos interactive --constraint cpu --time 02:00:00 --account m4581

python riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py \
  --mode local \
  --target-frequency Amon \
  --bins 25-49,50-99,100-149 \
  --out-csv run_25_149.csv \
  --resume-csv run_25_149.csv \
  --skip-plot
```

The local benchmark reads both the Kerchunk references and matching
NetCDF files from Perlmutter storage, then reports direct backend comparisons
and timing ratios. Do not run it on a Mac.
