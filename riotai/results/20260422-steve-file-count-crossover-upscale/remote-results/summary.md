# Remote Kerchunk results summary

These five `remote_perlmutter_to_ornl_*.csv` shards contain 50 datasets: **36
successful (72%)** and **14 failed (28%)**. All successful rows used the
`warm` cache mode and fetched their Kerchunk JSON from ORNL.

## Successful timings

Median Kerchunk timings in seconds, computed from successful rows only:

| File-count bin | Successful | Open | Load | Temporal compute | Spatial compute |
| --- | ---: | ---: | ---: | ---: | ---: |
| 25-49 | 10 | 1.633 | 2.972 | 4.217 | 4.447 |
| 150-199 | 10 | 1.948 | 2.884 | 3.556 | 4.023 |
| 300-499 | 4 | 1.717 | 27.892 | 28.843 | 28.697 |
| 500-749 | 10 | 1.463 | 3.228 | 3.866 | 4.609 |
| 750-1000 | 2 | 0.996 | 9.005 | 9.967 | 9.518 |

The 300-499 and 750-1000 medians have small successful samples because six
and eight rows, respectively, failed before timing. These results therefore
should not be treated as complete bin-level comparisons.

Only two dataset IDs overlap `../20260416-steve-file-count-crossover/final_combined.csv`, so this 50-dataset upscale run cannot be directly compared to
that 21-dataset benchmark as a whole.

## Failures

Every failure is `ReferenceNotReachable` while resolving the `lat/0`
reference. This confirms that the remote Kerchunk JSON was reachable, but its
embedded source NetCDF URL under ORNL's `/thredds/fileServer/css03_data/` path
was unavailable to the client. The exception alone cannot distinguish a missing
object from an access-policy failure.
The common error form is:

```text
ReferenceNotReachable: Reference "lat/0" failed to fetch target [ORNL source URL]
```

| Dataset | Files | Unreachable ORNL source path |
| --- | ---: | --- |
| `CMIP6.HighResMIP.CMCC.CMCC-CM2-HR4.highres-future.r1i1p1f1.Amon.hus.gn.v20190509` | 432 | <https://esgf-node.ornl.gov/thredds/fileServer/css03_data/CMIP6/HighResMIP/CMCC/CMCC-CM2-HR4/highres-future/r1i1p1f1/Amon/hus/gn/v20190509/hus_Amon_CMCC-CM2-HR4_highres-future_r1i1p1f1_gn_204406-204406.nc> |
| `CMIP6.HighResMIP.CMCC.CMCC-CM2-HR4.highres-future.r1i1p1f1.Amon.huss.gn.v20190509` | 432 | <https://esgf-node.ornl.gov/thredds/fileServer/css03_data/CMIP6/HighResMIP/CMCC/CMCC-CM2-HR4/highres-future/r1i1p1f1/Amon/huss/gn/v20190509/huss_Amon_CMCC-CM2-HR4_highres-future_r1i1p1f1_gn_203906-203906.nc> |
| `CMIP6.HighResMIP.CMCC.CMCC-CM2-HR4.highres-future.r1i1p1f1.Amon.pr.gn.v20190509` | 432 | <https://esgf-node.ornl.gov/thredds/fileServer/css03_data/CMIP6/HighResMIP/CMCC/CMCC-CM2-HR4/highres-future/r1i1p1f1/Amon/pr/gn/v20190509/pr_Amon_CMCC-CM2-HR4_highres-future_r1i1p1f1_gn_204310-204310.nc> |
| `CMIP6.HighResMIP.CMCC.CMCC-CM2-VHR4.highres-future.r1i1p1f1.Amon.hus.gn.v20190509` | 432 | <https://esgf-node.ornl.gov/thredds/fileServer/css03_data/CMIP6/HighResMIP/CMCC/CMCC-CM2-VHR4/highres-future/r1i1p1f1/Amon/hus/gn/v20190509/hus_Amon_CMCC-CM2-VHR4_highres-future_r1i1p1f1_gn_204504-204504.nc> |
| `CMIP6.HighResMIP.CMCC.CMCC-CM2-VHR4.highres-future.r1i1p1f1.Amon.huss.gn.v20190509` | 432 | <https://esgf-node.ornl.gov/thredds/fileServer/css03_data/CMIP6/HighResMIP/CMCC/CMCC-CM2-VHR4/highres-future/r1i1p1f1/Amon/huss/gn/v20190509/huss_Amon_CMCC-CM2-VHR4_highres-future_r1i1p1f1_gn_201507-201507.nc> |
| `CMIP6.HighResMIP.CMCC.CMCC-CM2-VHR4.highres-future.r1i1p1f1.Amon.pr.gn.v20190509` | 432 | <https://esgf-node.ornl.gov/thredds/fileServer/css03_data/CMIP6/HighResMIP/CMCC/CMCC-CM2-VHR4/highres-future/r1i1p1f1/Amon/pr/gn/v20190509/pr_Amon_CMCC-CM2-VHR4_highres-future_r1i1p1f1_gn_204409-204409.nc> |
| `CMIP6.HighResMIP.CMCC.CMCC-CM2-HR4.hist-1950.r1i1p1f1.Amon.hus.gn.v20190105` | 780 | <https://esgf-node.ornl.gov/thredds/fileServer/css03_data/CMIP6/HighResMIP/CMCC/CMCC-CM2-HR4/hist-1950/r1i1p1f1/Amon/hus/gn/v20190105/hus_Amon_CMCC-CM2-HR4_hist-1950_r1i1p1f1_gn_196906-196906.nc> |
| `CMIP6.HighResMIP.CMCC.CMCC-CM2-HR4.hist-1950.r1i1p1f1.Amon.huss.gn.v20190105` | 780 | <https://esgf-node.ornl.gov/thredds/fileServer/css03_data/CMIP6/HighResMIP/CMCC/CMCC-CM2-HR4/hist-1950/r1i1p1f1/Amon/huss/gn/v20190105/huss_Amon_CMCC-CM2-HR4_hist-1950_r1i1p1f1_gn_198909-198909.nc> |
| `CMIP6.HighResMIP.CMCC.CMCC-CM2-HR4.hist-1950.r1i1p1f1.Amon.psl.gn.v20190105` | 780 | <https://esgf-node.ornl.gov/thredds/fileServer/css03_data/CMIP6/HighResMIP/CMCC/CMCC-CM2-HR4/hist-1950/r1i1p1f1/Amon/psl/gn/v20190105/psl_Amon_CMCC-CM2-HR4_hist-1950_r1i1p1f1_gn_201303-201303.nc> |
| `CMIP6.HighResMIP.CMCC.CMCC-CM2-HR4.hist-1950.r1i1p1f1.Amon.ua.gn.kerchunk.json` | 780 | <https://esgf-node.ornl.gov/thredds/fileServer/css03_data/CMIP6/HighResMIP/CMCC/CMCC-CM2-HR4/hist-1950/r1i1p1f1/Amon/ua/gn/v20190105/ua_Amon_CMCC-CM2-HR4_hist-1950_r1i1p1f1_gn_198411-198411.nc> |
| `CMIP6.HighResMIP.CMCC.CMCC-CM2-HR4.hist-1950.r1i1p1f1.Amon.ua.gn.v20190105` | 780 | <https://esgf-node.ornl.gov/thredds/fileServer/css03_data/CMIP6/HighResMIP/CMCC/CMCC-CM2-HR4/hist-1950/r1i1p1f1/Amon/ua/gn/v20190105/ua_Amon_CMCC-CM2-HR4_hist-1950_r1i1p1f1_gn_198411-198411.nc> |
| `CMIP6.HighResMIP.CMCC.CMCC-CM2-VHR4.hist-1950.r1i1p1f1.Amon.hus.gn.v20180705` | 780 | <https://esgf-node.ornl.gov/thredds/fileServer/css03_data/CMIP6/HighResMIP/CMCC/CMCC-CM2-VHR4/hist-1950/r1i1p1f1/Amon/hus/gn/v20180705/hus_Amon_CMCC-CM2-VHR4_hist-1950_r1i1p1f1_gn_196106-196106.nc> |
| `CMIP6.HighResMIP.CMCC.CMCC-CM2-VHR4.hist-1950.r1i1p1f1.Amon.huss.gn.v20180705` | 780 | <https://esgf-node.ornl.gov/thredds/fileServer/css03_data/CMIP6/HighResMIP/CMCC/CMCC-CM2-VHR4/hist-1950/r1i1p1f1/Amon/huss/gn/v20180705/huss_Amon_CMCC-CM2-VHR4_hist-1950_r1i1p1f1_gn_199207-199207.nc> |
| `CMIP6.HighResMIP.CMCC.CMCC-CM2-VHR4.hist-1950.r1i1p1f1.Amon.psl.gn.v20180705` | 780 | <https://esgf-node.ornl.gov/thredds/fileServer/css03_data/CMIP6/HighResMIP/CMCC/CMCC-CM2-VHR4/hist-1950/r1i1p1f1/Amon/psl/gn/v20180705/psl_Amon_CMCC-CM2-VHR4_hist-1950_r1i1p1f1_gn_198606-198606.nc> |
