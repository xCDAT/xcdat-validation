#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --constraint=cpu
#SBATCH --qos=regular
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --account=m4581
#SBATCH --job-name=kerchunk-bench
#SBATCH --output=kerchunk-bench-%j.out
#SBATCH --signal=B:TERM@120

# Submit this file from the repository root. The submission helper supplies
# MODE, BINS, OUT_CSV, and CACHE_MODE through sbatch --export.
set -euo pipefail

: "${MODE:?Set MODE to local or remote}"
: "${BINS:?Set BINS to one or more file-count bins}"
: "${OUT_CSV:?Set OUT_CSV to an absolute output CSV path}"
: "${CACHE_MODE:=warm}"
: "${RETRY_COUNT:=0}"
: "${MAX_RETRIES:=2}"

if [[ "$MODE" != "local" && "$MODE" != "remote" ]]; then
    echo "MODE must be local or remote, got: $MODE" >&2
    exit 2
fi

BENCH_ROOT="${SLURM_SUBMIT_DIR:?Submit this job from the repository root}"
BENCH_SCRIPT="$BENCH_ROOT/riotai/results/20260422-steve-file-count-crossover-upscale/head_to_head.py"
SELF_SCRIPT="$(readlink -f "${BASH_SOURCE[0]}")"

resubmit() {
    local reason="$1"
    local next_retry=$((RETRY_COUNT + 1))

    if (( next_retry > MAX_RETRIES )); then
        echo "Not resubmitting after ${reason}: retry limit (${MAX_RETRIES}) reached." >&2
        return 0
    fi

    echo "Resubmitting after ${reason}; retry ${next_retry}/${MAX_RETRIES}." >&2
    sbatch --export="ALL,MODE=$MODE,BINS=$BINS,OUT_CSV=$OUT_CSV,CACHE_MODE=$CACHE_MODE,RETRY_COUNT=$next_retry,MAX_RETRIES=$MAX_RETRIES" "$SELF_SCRIPT"
}

on_timeout() {
    trap - TERM
    resubmit "Slurm timeout signal"
    exit 143
}

trap on_timeout TERM

cd "$BENCH_ROOT"
CONDA_BASE="$(conda info --base)"
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate xcdat_test_stable_min

echo "mode=$MODE bins=$BINS cache_mode=$CACHE_MODE retry=$RETRY_COUNT/$MAX_RETRIES"
echo "host=$(hostname) output=$OUT_CSV"

set +e
srun python "$BENCH_SCRIPT" \
    --mode "$MODE" \
    --target-frequency Amon \
    --bins "$BINS" \
    --cache-mode "$CACHE_MODE" \
    --out-csv "$OUT_CSV" \
    --resume-csv "$OUT_CSV" \
    --skip-plot
BENCH_EXIT=$?
set -e

if (( BENCH_EXIT != 0 )); then
    resubmit "benchmark exit code $BENCH_EXIT"
fi

exit "$BENCH_EXIT"
