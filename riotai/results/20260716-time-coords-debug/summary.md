# ECMWF Time Comparison

**Finding:** The Kerchunk JSON does not represent the complete NetCDF dataset, and its aggregated time coordinate is incorrect.

| Check                       |                 NetCDF |               Kerchunk |
| --------------------------- | ---------------------: | ---------------------: |
| Source files                |                     65 |                     50 |
| Time entries                |                    780 |                    618 |
| Unique months               |                    780 |                    420 |
| Time range                  | `1950-01` to `2014-12` | `1950-01` to `1984-12` |
| Duplicate month occurrences |                      0 |                    198 |
| Calendar                    |            `gregorian` |            `gregorian` |

All 50 Kerchunk source references point to the tested NetCDF directory, but the JSON omits 15 annual files. The omitted years are 1950, 1953, 1962, 1965, 1970, 1978, 1984, 1987, 1988, 1991, 1996, 1999, 2003, 2004, and 2007. The JSON references no files absent from the local directory.

The time lengths differ by 162. Kerchunk also has shifted or duplicated timestamps: it contains 198 duplicate month occurrences and no dates after `1984-12`, while NetCDF continues through `2014-12`. Both backends use the same calendar and time units, so calendar decoding does not explain the discrepancy.

Detailed results: [comparison metrics](comparison_summary.csv), [file differences](file_differences.csv), and [time differences](time_differences.csv).

## Minimal Reproduction

```python
from pathlib import Path

import xcdat as xc

nc_path = "/global/cfs/projectdirs/m4931/gsharing/css03_data/CMIP6/HighResMIP/ECMWF/ECMWF-IFS-HR/highresSST-present/r5i1p1f1/Amon/pr/gr/v20181119"
kc_path = "/global/cfs/projectdirs/m4931/kerchunk/pr/highresSST-present/mon/CMIP6.HighResMIP.ECMWF.ECMWF-IFS-HR.highresSST-present.r5i1p1f1.Amon.pr.gr.v20181119.kerchunk.json"

nc_files = sorted(Path(nc_path).glob("*.nc"))
ds_kc = xc.open_dataset(kc_path, engine="kerchunk", chunks={})
ds_nc = xc.open_mfdataset(
    [str(path) for path in nc_files], engine="netcdf4", chunks={}
)

print(ds_kc.time[2])
# 1950-02-15 12:00:00

print(ds_nc.time[2])
# 1950-03-16 12:00:00
```

At index 2, Kerchunk returns February while NetCDF returns March, showing that the aggregated sequence diverges near its start.

## Recommended Action

Regenerate the Kerchunk JSON from all 65 NetCDF files and validate that the resulting time coordinate contains 780 unique, ordered months from `1950-01` through `2014-12`.
