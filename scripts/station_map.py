"""23区の駅を地図に打ち、乗降客数を円の大きさで表す HTML を作る。

  python scripts/station_map.py

入力: data/stations.csv（s12_stations.py の出力）
      data/stations/tokyo23_r1000_lq_mid.csv（station_table.py の出力。1km 圏の店数を添える）
      data/areas/tokyo23_wards.parquet（区の境界）
      data/areas/tokyo23_rail.parquet（Overture transportation の線路。fetch_rail.py の出力、任意）
出力: docs/station_map.html  ブラウザで開くだけで見られる（外部の地図タイルは使わない）

円の面積を乗降客数に比例させる（半径は平方根）。
"""
import csv
import json
import math

import pyarrow.parquet as pq
from collections import defaultdict

from shapely import wkb
from shapely.ops import unary_union

from census import WARD_EN

LAT0 = 35.68
KX = math.cos(math.radians(LAT0))
SCALE = 2600  # 経度1度 → SVG 座標
MIN_LNG, MAX_LAT = 139.555, 35.825


def xy(lng, lat):
    return round((lng - MIN_LNG) * KX * SCALE, 1), round((MAX_LAT - lat) * SCALE, 1)


def ring_path(coords):
    pts = [xy(x, y) for x, y in coords]
    return "M" + "L".join(f"{x},{y}" for x, y in pts) + "Z"


RAIL_CLASSES = {"standard_gauge": "rail", "narrow_gauge": "rail", "light_rail": "rail", "monorail": "rail",
                "tram": "rail", "subway": "subway"}
RAIL_SKIP_FLAGS = {"is_disused", "is_abandoned"}


def line_path(coords):
    pts = [xy(x, y) for x, y in coords]
    return "M" + "L".join(f"{x},{y}" for x, y in pts)


def load_rails(area_geom):
    """路線名（なければ種別）ごとに線路をまとめて SVG パスにする。23区の外は少し余白を残して切る。"""
    import os
    path = "data/areas/tokyo23_rail.parquet"
    if not os.path.exists(path):
        return []
    clip = area_geom.buffer(0.01)
    groups = defaultdict(list)
    for r in pq.read_table(path).to_pylist():
        kind = RAIL_CLASSES.get(r["class"])
        flags = {v for f in (r["rail_flags"] or []) for v in f["values"]}
        if not kind or flags & RAIL_SKIP_FLAGS:
            continue
        g = wkb.loads(r["geometry"]).intersection(clip)
        if g.is_empty:
            continue
        name = ((r["names"] or {}).get("primary") or "").split(" (")[0]
        for line in ([g] if g.geom_type == "LineString" else [x for x in getattr(g, "geoms", []) if x.geom_type == "LineString"]):
            groups[(kind, name)].append(line_path(line.simplify(0.00015).coords))
    rails = [{"k": k, "n": n, "d": "".join(ds)} for (k, n), ds in groups.items()]
    rails.sort(key=lambda r: r["k"] != "subway")  # 地下鉄を下に
    return rails


def main():
    ja = {en: name for name, en in WARD_EN.items()}
    wards = []
    for r in pq.read_table("data/areas/tokyo23_wards.parquet").to_pylist():
        g = wkb.loads(r["geometry"]).simplify(0.0004, preserve_topology=True)
        polys = [g] if g.geom_type == "Polygon" else list(g.geoms)
        d = "".join(ring_path(p.exterior.coords) for p in polys)
        c = g.representative_point()
        wards.append({"name": ja.get(r["ward"], r["ward"]), "d": d, "c": xy(c.x, c.y)})

    area_geom = unary_union([wkb.loads(r["geometry"]) for r in pq.read_table("data/areas/tokyo23_wards.parquet").to_pylist()])
    rails = load_rails(area_geom)

    stores = {r["station"]: r for r in csv.DictReader(open("data/stations/tokyo23_r1000_lq_mid.csv", encoding="utf-8-sig"))}
    stations = []
    for r in csv.DictReader(open("data/stations.csv", encoding="utf-8")):
        if not r["passengers"]:
            continue
        x, y = xy(float(r["lng"]), float(r["lat"]))
        s = stores.get(r["key"], {})
        stations.append({"n": r["name"], "p": int(r["passengers"]), "x": x, "y": y,
                         "o": r["operators"].replace("|", "・"), "s": int(s.get("stores") or 0)})
    stations.sort(key=lambda s: -s["p"])

    w, h = xy(139.925, 35.515)
    data = json.dumps({"w": w, "h": h, "wards": wards, "rails": rails, "stations": stations}, ensure_ascii=False, separators=(",", ":"))
    html = open("scripts/station_map_template.html", encoding="utf-8").read().replace("__DATA__", data)
    with open("docs/station_map.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"{len(stations)} 駅・{len(rails)} 路線 -> docs/station_map.html（{len(html) / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
