# Presentation-aligned remote Kerchunk benchmark

`head_to_head.py` preserves the 2026-04-22 presentation workload: its `Amon`
prepared-dataset selection, file-count bins, ranks, fixed 240-timestep slice,
and open/load/temporal/spatial diagnostics. It supports two explicit modes:
`--mode remote` maps inventory JSON paths to public ORNL URLs and measures only
remote Kerchunk I/O; `--mode local` runs the original local Kerchunk-versus-
NetCDF comparison on Perlmutter.

Run remote mode from the client path you want to characterize. A Perlmutter
batch job is a valid **Perlmutter-to-ORNL** measurement; a Mac run represents
that external-client path instead.

The repository's `riotai/json_to_netcdf_maps/prepared_datasets_Amon.csv` is a
local selection manifest only. It does not cause local data reads.

## Quick start: run both benchmarks on Perlmutter

From the repository root, prepare the local manifest and submit all six shards
(three remote Perlmutter-to-ORNL shards and three local comparison shards):

```bash
conda activate xcdat_test_stable_min
python riotai/scripts/prepare_datasets.py --target-frequency Amon

bash riotai/results/20260422-steve-file-count-crossover-upscale/submit_perlmutter_benchmarks.sh
```

Check submitted jobs with:

```bash
squeue -u "$USER"
```

The CSVs are written in this directory as `remote_perlmutter_to_ornl_*.csv`
and `local_*.csv`. Each job checkpoints after each dataset. If a job times out
or exits nonzero, it resubmits the same shard and resumes its CSV, up to two
retries by default. Set `MAX_RETRIES=3` before the submission command to use a
different retry limit. Change the account or time limit in
`run_perlmutter_benchmark.sbatch` when necessary.

## macOS setup

```bash
git clone --branch kerchunk https://github.com/xCDAT/xcdat-validation.git
cd xcdat-validation

conda env create -f riotai/test_stable_min.yml -n xcdat_test_stable_min
conda activate xcdat_test_stable_min
```

## Remote benchmark

Use `--mode remote` for the remote Kerchunk-only benchmark. It fetches the
Kerchunk JSON and its embedded byte-range data targets over HTTP(S); it does
not open local NetCDF files or produce Kerchunk-to-NetCDF ratios. Run it from
your Mac, another external client, or a Perlmutter batch job.

### Smoke test

```bash
python riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py \
  --mode remote \
  --target-frequency Amon \
  --bins 25-49 \
  --datasets-per-bin 1 \
  --ntests 1 \
  --cache-mode uncontrolled \
  --out-csv remote_0422_smoke.csv \
  --skip-plot
```

### Full benchmark

Use one resumable output file. `warm` discards the first iteration and reports
the median of the remaining iterations; it does not guarantee a globally cold
HTTP cache.

```bash
python riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py \
  --mode remote \
  --target-frequency Amon \
  --bins 25-49,50-99,100-149 \
  --cache-mode warm \
  --out-csv remote_0422_upscale.csv \
  --resume-csv remote_0422_upscale.csv --skip-plot

python riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py \
  --mode remote \
  --target-frequency Amon \
  --bins 150-199,200-299 \
  --cache-mode warm \
  --out-csv remote_0422_upscale.csv \
  --resume-csv remote_0422_upscale.csv --skip-plot

python riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py \
  --mode remote \
  --target-frequency Amon \
  --bins 300-499,500-749,750-1000 \
  --cache-mode warm \
  --out-csv remote_0422_upscale.csv \
  --resume-csv remote_0422_upscale.csv --skip-plot
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

## Perlmutter batch jobs

Submit from the repository root after preparing the local manifest:

```bash
conda activate xcdat_test_stable_min
python riotai/scripts/prepare_datasets.py --target-frequency Amon

bash riotai/results/20260422-steve-file-count-crossover-upscale/submit_perlmutter_benchmarks.sh
```

The helper submits three remote jobs and three local jobs, one per bin shard.
Remote results are labeled as Perlmutter-to-ORNL measurements. Each job uses
the same resumable CSV after a timeout or nonzero benchmark exit, and resubmits
itself up to two times. Override that limit when submitting, for example:

```bash
MAX_RETRIES=3 bash riotai/results/20260422-steve-file-count-crossover-upscale/submit_perlmutter_benchmarks.sh
```

After the retry limit is reached, the job stops and leaves its CSV intact for
manual inspection or a later resume. Edit the account and time settings in
`run_perlmutter_benchmark.sbatch` if needed.
