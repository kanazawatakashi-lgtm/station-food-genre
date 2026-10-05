"""比較対象（東京23区）の Overture 飲食 POI を、区の境界で切り出して取得する。

  python scripts/fetch_overture_area.py tokyo23

1. 23区の境界を国土数値情報 N03 から作る（ksj.load_wards。data/ksj/ に N03 の GeoJSON が必要）
2. 23区全体を囲む範囲の places を取り、飲食系（taxonomy.hierarchy[1]=food_and_drink など）に絞る
3. 点が境界の内側にあるものだけ残し、区名（英語名）を付ける

出力: data/areas/tokyo23_wards.parquet（区の境界。geometry は WKB）
      data/areas/tokyo23_food.parquet（飲食 POI。ward 列付き）
HTTPS_PROXY が設定されていればそれを経由する。shapely が必要。
取得する Overture のリリースは fetch_overture.py の RELEASE。

以前は区の境界を Overture divisions（OpenStreetMap 由来、ODbL）から取っていたが、商用で使いやすい
国土数値情報に置き換えた（2026-10-04）。このスクリプトも N03 を使うので、取得後に ksj.py を実行し直す必要はない。
"""
import os
import sys

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq
from shapely.geometry import Point
from shapely.strtree import STRtree

from fetch_overture import BASE, RELEASE, s3fs

COLS = ["id", "names", "categories", "taxonomy", "basic_category", "confidence", "addresses", "bbox"]


def fetch_wards():
    """{区の英語名: 境界}（国土数値情報 N03）。"""
    from census import WARD_EN
    from ksj import load_wards
    return {WARD_EN[n]: g for n, g in load_wards().items()}


def main(name):
    if name != "tokyo23":
        raise SystemExit("今は tokyo23 だけ対応")
    fs = s3fs()
    wards = fetch_wards()
    os.makedirs("data/areas", exist_ok=True)
    pq.write_table(pa.table({"ward": list(wards), "geometry": [w.wkb for w in wards.values()]}),
                   "data/areas/tokyo23_wards.parquet")

    minx = min(w.bounds[0] for w in wards.values())
    miny = min(w.bounds[1] for w in wards.values())
    maxx = max(w.bounds[2] for w in wards.values())
    maxy = max(w.bounds[3] for w in wards.values())
    f = ((pc.field("bbox", "xmin") >= minx) & (pc.field("bbox", "xmax") <= maxx)
         & (pc.field("bbox", "ymin") >= miny) & (pc.field("bbox", "ymax") <= maxy))
    t = ds.dataset(BASE, filesystem=fs, format="parquet").to_table(columns=COLS, filter=f)
    print(f"範囲内 全POI {t.num_rows}")
    h1 = pc.list_element(pc.struct_field(t["taxonomy"], "hierarchy"), 0)
    keep = pc.or_(pc.equal(h1, "food_and_drink"),
                  pc.and_(pc.is_null(h1), pc.is_in(t["basic_category"], value_set=pa.array(["restaurant", "bar"]))))
    t = t.filter(pc.fill_null(keep, False))

    names = list(wards)
    tree = STRtree(list(wards.values()))
    ward_col = []
    for bb in t["bbox"].to_pylist():
        p = Point((bb["xmin"] + bb["xmax"]) / 2, (bb["ymin"] + bb["ymax"]) / 2)
        hit = tree.query(p, predicate="within")
        ward_col.append(names[hit[0]] if len(hit) else None)
    t = t.append_column("ward", pa.array(ward_col, pa.string()))
    t = t.filter(pc.is_valid(t["ward"]))
    out = f"data/areas/{name}_food.parquet"
    pq.write_table(t, out)
    print(f"23区内の飲食 {t.num_rows} -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
