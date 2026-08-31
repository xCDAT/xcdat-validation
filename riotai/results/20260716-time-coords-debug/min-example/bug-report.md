# Kerchunk reference has fewer and duplicated time entries than source NetCDF files

## Summary

This reproducible comparison finds different time-coordinate sequences when the
same HighResMIP precipitation collection is opened through an existing Kerchunk
reference and directly from its NetCDF files. The current evidence implicates
the generated Kerchunk reference artifact as incomplete; it is **not** proof of
an engine decoder bug.

## Reproducer

Run from this directory (or use equivalent absolute paths):

After updating `riotai/test_stable_min.yml`, install or recreate the
`xcdat_test_stable_min` environment before running this command. The current
environment must be recreated to obtain the newly required dependencies.

```bash
/global/homes/v/vo13/miniforge3/condabin/conda run --no-capture-output \
  -n xcdat_test_stable_min python mvce.py
```

The script uses hard-coded NERSC paths for the source NetCDF directory and
Kerchunk JSON. It compares four paths: xarray opening the Kerchunk JSON,
xarray opening the NetCDF collection, VirtualiZarr opening the same Kerchunk
JSON, and VirtualiZarr's HDFParser opening the NetCDF collection. It evaluates
only `time` and prints source count, coordinate endpoints, units/calendar,
monotonicity, duplicates, and pairwise sequence comparisons.

The required runtime packages are Python, xarray, kerchunk, netCDF4,
virtualizarr, obstore, and an ObjectStoreRegistry provider. VirtualiZarr 2.0
uses `virtualizarr.registry`; newer releases use `obspec-utils`.

Environment from the earlier two-backend attempted run:

| Package | Version |
| --- | --- |
| Python | 3.14.4 |
| xarray | 2026.4.0 |
| kerchunk | 0.2.10 |
| netCDF4 | 1.7.4 |

Neither VirtualiZarr path has been run in the supplied environment. It must
first be recreated after the YAML dependency change.

## Existing observations

- The source directory contains 65 NetCDF files, while the Kerchunk reference
  describes 50 sources.
- The direct NetCDF open has 780 time entries; the Kerchunk open has 618.
- Kerchunk has 420 unique months and 198 duplicate occurrences, covering
  1950-01 through 1984-12. The direct NetCDF open has 780 unique months through
  2014-12.
- Both report a `gregorian` calendar.
- The first mismatch is index 2: Kerchunk is `1950-02-15 12:00:00`, while
  netCDF4 is `1950-03-16 12:00:00`.

## Suggested next step

Regenerate the Kerchunk reference from all 65 source files, verify the source
list and concatenated time coordinate, then rerun this reproducer. If a newly
generated reference still differs from a direct NetCDF open, the resulting
minimal example would provide stronger evidence for an engine-level issue.
