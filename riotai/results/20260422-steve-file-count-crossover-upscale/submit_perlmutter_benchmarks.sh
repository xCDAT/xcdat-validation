#!/usr/bin/env bash
# Submit presentation-aligned Perlmutter-to-ORNL remote benchmark shards.
# The existing final_combined.csv is the local baseline and is not rerun here.
# Run from the repository root with: bash path/to/this/script
# Set MAX_RETRIES before submitting to override the default of two retries.
set -euo pipefail

BENCH_ROOT="$(pwd)"
JOB_SCRIPT="$BENCH_ROOT/riotai/results/20260422-steve-file-count-crossover-upscale/run_perlmutter_benchmark.sbatch"
RESULT_DIR="$BENCH_ROOT/riotai/results/20260422-steve-file-count-crossover-upscale"

BENCH_BINS=(
    '25-49,50-99,100-149'
    '150-199,200-299'
    '300-499'
    '500-749'
    '750-1000'
)
BENCH_TIMES=('02:00:00' '03:00:00' '04:00:00' '04:00:00' '04:00:00')

for BENCH_INDEX in "${!BENCH_BINS[@]}"; do
    BENCH_BINS_VALUE="${BENCH_BINS[$BENCH_INDEX]}"
    BENCH_TIME="${BENCH_TIMES[$BENCH_INDEX]}"
    BENCH_TAG="${BENCH_BINS_VALUE//,/_}"
    sbatch --time="$BENCH_TIME" --export="ALL,MODE=remote,BINS=$BENCH_BINS_VALUE,CACHE_MODE=warm,RETRY_COUNT=0,MAX_RETRIES=${MAX_RETRIES:-2},OUT_CSV=$RESULT_DIR/remote_perlmutter_to_ornl_${BENCH_TAG}.csv" "$JOB_SCRIPT"
done
