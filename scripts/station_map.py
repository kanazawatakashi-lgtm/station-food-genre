"""23区の駅を地図に打ち、乗降客数を円の大きさで表す HTML を作る。

  python scripts/station_map.py

入力: data/stations.csv（s12_stations.py の出力）
      data/stations/tokyo23_r1000_lq_mid.csv（station_table.py の出力。1km 圏の店数を添える）
      data/areas/tokyo23_wards.parquet（区の境界）
      data/ksj/N02-25_RailroadSection.geojson（国土数値情報 鉄道。scripts/ksj.py で読む）
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


def line_path(coords):
    pts = [xy(x, y) for x, y in coords]
    return "M" + "L".join(f"{x},{y}" for x, y in pts)


def _length_m(line):
    return sum(math.hypot((x2 - x1) * 111320 * KX, (y2 - y1) * 110950)
               for (x1, y1), (x2, y2) in zip(line.coords, list(line.coords)[1:]))


def load_rails(area_geom):
    """国土数値情報 N02 の路線を JR・私鉄・地下鉄に分けて SVG パスにする。23区の外は少し余白を残して切る。
    N02 は路線ごとに線が入っている（共用区間も路線ごとにある）ので、途切れを補う処理は要らない。"""
    from shapely.ops import linemerge
    from ksj import load_rails as ksj_rails
    clip = area_geom.buffer(0.01)
    rails = []
    for r in ksj_rails(clip.bounds):
        g = linemerge(r["lines"]).intersection(clip)
        d, anchors = [], []
        for line in ([g] if g.geom_type == "LineString" else [x for x in getattr(g, "geoms", []) if x.geom_type == "LineString"]):
            if line.is_empty:
                continue
            d.append(line_path(line.simplify(0.00015).coords))
            # 路線名を置く位置: 3km 以上の線に、おおむね 5km おきに
            km = _length_m(line) / 1000
            if km >= 3:
                n = max(1, round(km / 5))
                for j in range(n):
                    p = line.interpolate((j + 0.5) / n, normalized=True)
                    anchors.append(xy(p.x, p.y))
        if d:
            rails.append({"k": r["kind"], "n": r["name"], "d": "".join(d), "a": anchors})
    order = {"subway": 0, "private": 1, "jr": 2}
    rails.sort(key=lambda r: order[r["k"]])  # 地下鉄を下に
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
