"""比較対象（東京23区など）の範囲の Overture 飲食 POI をまとめて取得する。

  python scripts/fetch_overture_area.py tokyo23

bbox で取ってから、住所の区名ではなく bbox で絞る（23区の境界ポリゴンは持っていないため、
多摩地域の東端や千葉・埼玉・川崎の一部が混じる）。比較対象としての粗い基準値として使う。
出力: data/areas/<name>_food.parquet（飲食系のみ、列は extract_overture_food.py と同じ考え方）
"""
import os
import sys

import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from fetch_overture import BASE, s3fs

AREAS = {
    # 東京23区をおおむね覆う bbox (minLng, minLat, maxLng, maxLat)
    "tokyo23": (139.56, 35.52, 139.92, 35.82),
}
COLS = ["id", "names", "categories", "taxonomy", "basic_category", "confidence", "addresses", "bbox"]


def main(name):
    minx, miny, maxx, maxy = AREAS[name]
    f = ((pc.field("bbox", "xmin") >= minx) & (pc.field("bbox", "xmax") <= maxx)
         & (pc.field("bbox", "ymin") >= miny) & (pc.field("bbox", "ymax") <= maxy))
    t = ds.dataset(BASE, filesystem=s3fs(), format="parquet").to_table(columns=COLS, filter=f)
    print(f"bbox 内 全POI {t.num_rows}")
    h1 = pc.list_element(pc.struct_field(t["taxonomy"], "hierarchy"), 0)
    basic = t["basic_category"]
    keep = pc.or_(pc.equal(h1, "food_and_drink"),
                  pc.and_(pc.is_null(h1), pc.is_in(basic, value_set=__import__("pyarrow").array(["restaurant", "bar"]))))
    t = t.filter(pc.fill_null(keep, False))
    os.makedirs("data/areas", exist_ok=True)
    out = f"data/areas/{name}_food.parquet"
    pq.write_table(t, out)
    print(f"飲食 {t.num_rows} -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
