#!/usr/bin/env bash
# Submit presentation-aligned local and Perlmutter-to-ORNL remote benchmark
# shards. Run from the repository root with: bash path/to/this/script
# Set MAX_RETRIES before submitting to override the default of two retries.
set -euo pipefail

BENCH_ROOT="$(pwd)"
JOB_SCRIPT="$BENCH_ROOT/riotai/results/20260422-steve-file-count-crossover-upscale/run_perlmutter_benchmark.sbatch"
RESULT_DIR="$BENCH_ROOT/riotai/results/20260422-steve-file-count-crossover-upscale"

for BENCH_BINS in '25-49,50-99,100-149' '150-199,200-299' '300-499,500-749,750-1000'; do
    BENCH_TAG="${BENCH_BINS//,/_}"
    sbatch --export="ALL,MODE=remote,BINS=$BENCH_BINS,CACHE_MODE=warm,RETRY_COUNT=0,MAX_RETRIES=${MAX_RETRIES:-2},OUT_CSV=$RESULT_DIR/remote_perlmutter_to_ornl_${BENCH_TAG}.csv" "$JOB_SCRIPT"
    sbatch --export="ALL,MODE=local,BINS=$BENCH_BINS,CACHE_MODE=warm,RETRY_COUNT=0,MAX_RETRIES=${MAX_RETRIES:-2},OUT_CSV=$RESULT_DIR/local_${BENCH_TAG}.csv" "$JOB_SCRIPT"
done
