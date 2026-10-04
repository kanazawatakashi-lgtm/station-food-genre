"""23区の駅を地図に打ち、乗降客数を円の大きさで表す HTML を作る。

  python scripts/station_map.py

入力: data/stations.csv（s12_stations.py の出力）
      data/stations/tokyo23_r1000_lq_mid.csv（station_table.py の出力。1km 圏の店数を添える）
      data/areas/tokyo23_wards.parquet（区の境界）
出力: docs/station_map.html  ブラウザで開くだけで見られる（外部の地図タイルは使わない）

円の面積を乗降客数に比例させる（半径は平方根）。
"""
import csv
import json
import math

import pyarrow.parquet as pq
from shapely import wkb

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


def main():
    ja = {en: name for name, en in WARD_EN.items()}
    wards = []
    for r in pq.read_table("data/areas/tokyo23_wards.parquet").to_pylist():
        g = wkb.loads(r["geometry"]).simplify(0.0004, preserve_topology=True)
        polys = [g] if g.geom_type == "Polygon" else list(g.geoms)
        d = "".join(ring_path(p.exterior.coords) for p in polys)
        c = g.representative_point()
        wards.append({"name": ja.get(r["ward"], r["ward"]), "d": d, "c": xy(c.x, c.y)})

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
    data = json.dumps({"w": w, "h": h, "wards": wards, "stations": stations}, ensure_ascii=False, separators=(",", ":"))
    html = open("scripts/station_map_template.html", encoding="utf-8").read().replace("__DATA__", data)
    with open("docs/station_map.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"{len(stations)} 駅 -> docs/station_map.html（{len(html) / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
