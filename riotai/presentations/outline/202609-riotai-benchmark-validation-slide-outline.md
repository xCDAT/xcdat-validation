# RIOTAI Benchmarking and Validation Slide Outline

**Recommended length:** Four slides, about seven minutes.

**Count scope:** Performance and API counts exclude datasets covered in another
section. Metadata results retain all 30 tested datasets, with 21 in-scope
comparisons.

## Slide 1 — Benchmark design: matched xCDAT workflows on the same CMIP datasets

**Time:** 1–1.25 minutes

### Put on the slide

Use one compact setup matrix:

| Design element | Benchmark setup |
| --- | --- |
| Comparison | Same datasets through kerchunk references and source NetCDF |
| Sample | Amon; `time[:240]`; 73 displayed datasets across eight `25–1000` file-count bins |
| Platform | NERSC Perlmutter CPU; near-compute storage |
| Execution | Dask threaded scheduler; 8 workers; source chunks preserved; no rechunking |
| Workloads | Open, load, annual temporal mean, and spatial average |
| Timing | 3 runs per backend; discard warmup; report median of remaining runs |

Small footer:

> BLAS/OpenMP limited to one thread. Ten datasets were initially sampled per
> bin; displayed counts exclude datasets covered elsewhere.

### Visual to use

Place a small paired-input schematic above the matrix:

```text
Kerchunk references ─┐
                     ├──► same xCDAT workflows ───► wall time
Source NetCDF files ─┘
```

Use backend colors only on the two input boxes; keep the setup matrix neutral.

Related source assets:

- [Benchmark implementation](../results/20260422-steve-file-count-crossover-upscale/head_to_head.py)
- [Benchmark data](../results/20260422-steve-file-count-crossover-upscale/final_combined.csv)

### Takeaway

> This is a paired, storage-layout-faithful, single-node comparison.

## Slide 2 — Kerchunk’s open-time advantage drives end-to-end wins

**Time:** 2.5 minutes

### Put on the slide

- **Open:** kerchunk won `73/73` cases, with about a 110-fold median advantage.
- **Compute:** results were mixed; temporal and spatial bin medians favored
  kerchunk from `150–199` files onward.
- **End to end:** kerchunk won `69/73` cases for each tested monthly pipeline.

### Visual to use

Create one two-panel ratio chart:

1. **Components:** open, load, temporal, and spatial by file-count bin.
2. **Complete pipelines:** open + load, open + temporal, and open + spatial by
   file-count bin.

Use `kerchunk time / NetCDF time` on a log scale. Mark `1` as equal performance,
shade the faster-backend regions, and highlight `150–199`.

Related source assets:

- [Component bin-median figure](../results/20260422-steve-file-count-crossover-upscale/final_timing_by_bin.png)
- [Pipeline bin-median figure](../results/20260422-steve-file-count-crossover-upscale/final_total_timing_by_bin.png)
- [Benchmark data](../results/20260422-steve-file-count-crossover-upscale/final_combined.csv)

Redraw from the CSV using the displayed-count exclusions. Existing figures are too crowded for projection.

### Say, but do not show

File count is not the only driver—variable, grid, data shape, and chunking also
matter.

### Takeaway

> NetCDF can win compute while kerchunk still wins the complete workflow.

## Slide 3 — Tested outputs show no systematic backend regression

**Time:** 2 minutes

### Put on the slide

- **Metadata/CF:** `21/21` in-scope comparisons passed.
- **xCDAT API outputs:** `44/44` completed, applicable comparisons passed.
- **CF-axis detection failures:** `0`.

Small footer:

> 30 metadata datasets tested; nine separately handled reference/input,
> expected-metadata, or run-completion conditions. Results apply to the tested
> sample and operations.

### Visual to use

Use two large result cards, not a failure table:

| Metadata and CF | xCDAT API outputs |
| --- | --- |
| **21/21 passed** | **44/44 passed** |
| 30 datasets tested | 13 datasets, four operations |
| 0 CF-axis failures | Completed applicable comparisons |

Add a thin checkmark bar beneath both cards. Avoid dataset names and issue
breakdowns; those belong to the separate section.

Related source assets:

- [Metadata/CF validation summary](../results/20260605-metadata-cf-validation/20260605_144947_summary.md)
- [API-output validation summary](../results/20260702-api-output-comparison/run_3bins_5datasets_summary.md)

### Say, but do not show

Five API operations were not applicable because no vertical axis existed.
Three vertical operations encountered the same execution error through both
backends and are outside the `44/44` denominator.

### Takeaway

> No broad systematic kerchunk-versus-NetCDF regression appeared in the tested
> sample.

## Slide 4 — Choose by workflow shape, not backend reputation

**Time:** 1–1.25 minutes

### Put on the slide

Use a decision flow instead of bullets:

```text
Is open/metadata cost material?
        │
    Yes ├──► Start with kerchunk
        │
        No
        ▼
Already open + compute-dominated + lower file count?
        │
    Yes ├──► Start with NetCDF
        │
        No
        ▼
Full pipeline or roughly 150+ files?
            └──► Test kerchunk first
```

Footer:

> Benchmark representative cases for each new archive and environment; file
> count is a secondary signal.

### Visual to use

Render the decision flow as three large colored nodes:

- kerchunk: metadata/open path
- NetCDF: already-open lower-count compute path
- benchmark: large or unfamiliar workflow path

No separate chart needed. Keep the flow centered and use the same backend
colors as Slide 2.

### Takeaway

> Backend choice is a workflow decision, not a universal property.

## Optional Q&A backup — Daily cross-check and caveats

Use the [daily pipeline bin-median figure](../results/20260522-steve-file-count-crossover-upscale-daily/final_total_timing_by_bin.png).

Only show these callouts:

- open: kerchunk won `32/32`
- open + load: `28/32`
- open + temporal: `20/32`
- open + spatial: `21/32`

Speaker-note caveats: Perlmutter and near-compute storage only; no rechunking;
dataset properties vary within bins; monthly `50–99` bin retains only three
datasets after displayed-count exclusions.

## Source reports

- [Overall summary](../results/20260702-overall-summary.md)
- [Monthly crossover summary](../results/20260422-steve-file-count-crossover-upscale/summary.md)
- [Daily crossover summary](../results/20260522-steve-file-count-crossover-upscale-daily/summary.md)
- [Metadata/CF validation summary](../results/20260605-metadata-cf-validation/20260605_144947_summary.md)
- [API-output validation summary](../results/20260702-api-output-comparison/run_3bins_5datasets_summary.md)
