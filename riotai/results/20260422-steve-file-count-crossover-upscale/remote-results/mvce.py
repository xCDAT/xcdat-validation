"""Reproduce an ORNL remote Kerchunk reference failure.

The Kerchunk JSON is reachable. Opening it fails only when the ``lat/0``
reference requests its embedded NetCDF source at ORNL's ``css03_data`` path.
The resulting exception proves that source URL is unavailable to this client;
it does not distinguish a missing object from an access-policy failure.

Run with:
    conda run -n xcdat_test_stable_min python mvce.py
"""

import xcdat as xc


KERCHUNK_JSON = (
    "https://esgf-node.ornl.gov/thredds/fileServer/user_pub_work/kerchunk/"
    "hus/highres-future/mon/"
    "CMIP6.HighResMIP.CMCC.CMCC-CM2-HR4.highres-future.r1i1p1f1.Amon."
    "hus.gn.v20190509.kerchunk.json"
)


ds = xc.open_dataset(KERCHUNK_JSON, engine="kerchunk", chunks={})
