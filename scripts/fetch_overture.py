"""Overture Maps Places から駅周辺の全 POI を取得し parquet に保存する。

  python scripts/fetch_overture.py kameido

出力: data/<station>/overture_raw.parquet（半径の 1.5 倍四方、全カテゴリ）
HTTPS_PROXY が設定されていればそれを経由する。
"""
import os
import sys
from urllib.parse import urlparse

import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.fs as fs
import pyarrow.parquet as pq

from common import RADIUS_M, STATIONS, circle_bbox

RELEASE = "2026-08-19.0"  # OpenPOI が使っているリリースに合わせる
BASE = f"overturemaps-us-west-2/release/{RELEASE}/theme=places/type=place"
COLS = ["id", "names", "categories", "basic_category", "taxonomy", "confidence",
        "operating_status", "addresses", "sources", "brand", "bbox"]


def s3fs():
    kw = {"anonymous": True, "region": "us-west-2"}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        u = urlparse(proxy)
        kw["proxy_options"] = {"scheme": u.scheme, "host": u.hostname, "port": u.port}
    return fs.S3FileSystem(**kw)


def main(key):
    st = STATIONS[key]
    minx, miny, maxx, maxy = circle_bbox(st["lat"], st["lng"], RADIUS_M, margin=1.5)
    f = ((pc.field("bbox", "xmin") >= minx) & (pc.field("bbox", "xmax") <= maxx)
         & (pc.field("bbox", "ymin") >= miny) & (pc.field("bbox", "ymax") <= maxy))
    t = ds.dataset(BASE, filesystem=s3fs(), format="parquet").to_table(columns=COLS, filter=f)
    out = f"data/{key}/overture_raw.parquet"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    pq.write_table(t, out)
    print(f"{t.num_rows} rows -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
