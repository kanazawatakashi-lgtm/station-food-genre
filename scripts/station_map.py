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


import re

RAIL_CLASSES = {"standard_gauge", "narrow_gauge", "light_rail", "monorail", "tram", "subway"}
RAIL_SKIP_FLAGS = {"is_disused", "is_abandoned"}

# 英語などで入っている路線名と、同じ路線の表記ゆれを日本語の名前にそろえる
RAIL_NAME = {
    "Keihin Kyuuko Line": "京浜急行電鉄本線", "Keikyū-Hauptlinie": "京浜急行電鉄本線", "京浜急行線": "京浜急行電鉄本線",
    "Keio New Line": "京王新線", "Keio Railway Keio Line": "京王電鉄京王線", "Línea Keio Inokashira": "京王電鉄井の頭線",
    "Keisei Main Line": "京成電鉄本線", "Linea Keisei principale": "京成電鉄本線", "京成本線": "京成電鉄本線",
    "京成金町線": "京成電鉄金町線", "Línea Hokuso": "北総線",
    "Línea Verde del Metro Municipal de Yokohama": "横浜市営地下鉄グリーンライン",
    "Línea de servicio rápida Joban": "常磐快速線", "Nambu Line": "JR南武線", "Odawara-Linie": "小田急電鉄小田原線",
    "小田急電鉄 小田原線": "小田急電鉄小田原線", "Sōtetsu-Tokyu Verbindungsbahn": "相鉄・東急直通線",
    "Tobu Isesaki Sen": "東武伊勢崎線", "伊勢崎線": "東武伊勢崎線", "とうぶだいしせん": "東武大師線", "東武鉄道大師線": "東武大師線",
    "Toei Asakusa Line": "都営地下鉄浅草線", "都営浅草線": "都営地下鉄浅草線",
    "Toei Mita Line": "都営地下鉄三田線", "都営三田線": "都営地下鉄三田線",
    "Tokyo Metro Chiyoda Line": "東京メトロ千代田線", "Tokyo Metro Marunouchi Line": "東京メトロ丸ノ内線",
    "Tokyo Metro Yurakucho Line": "東京メトロ有楽町線", "Tokyo Monorail": "東京モノレール",
    "Tōhoku-Hauptlinie": "JR東北本線", "東北本線": "JR東北本線", "Yamanote-Linie": "山手線",
    "せいぶいけぶくろせん": "西武池袋線", "西武鉄道新宿線": "西武新宿線",
    "東急電鉄世田谷線": "東急世田谷線", "東京急行電鉄世田谷線": "東急世田谷線",
    "京浜急行電鉄連続立体交差事業": "京浜急行電鉄本線", "北総鉄道": "北総線",
}
# 車両基地の線・遊園地の乗り物・廃線跡・計画線など、路線として描かないもの
RAIL_DROP = re.compile(r"番線$|引上|機待|機留|機回|機走|機関区|仕業|仕訳|検修|修繕|洗浄|留置|着発|到着|出発|収納|材料線|車両所|車輪"
                       r"|通路線|特入線|月検査|亘り|^センター線$|^Y線$|^MC線$|旧線|跡$|廃線|延伸|中央新幹線|アクセス線|豆汽車"
                       r"|ミニトレイン|スカイサイクル|ディズニー|ウエスタン|Busy Buggies|ビジーバギー|さくらレール|あすかパーク"
                       r"|訓練線|専用線|引き込み線|白鬚線|川崎市電")
SUBWAY = re.compile(r"東京メトロ|都営地下鉄|横浜市営|地下鉄")
JR = re.compile(r"^JR|山手|京浜東北|常磐|中央|総武|東海道|東北|赤羽線|上野東京ライン|成田エクスプレス|新幹線|大崎支線|大汐線"
                r"|尻手短絡線|新金貨物線|越中島支線|北王子線|馬橋支線|北小金支線|貨物")


def rail_name(raw):
    n = raw.split(" (")[0].split(";")[0].strip()
    return RAIL_NAME.get(n, n)


def rail_kind(name):
    if SUBWAY.search(name):
        return "subway"
    if JR.search(name):
        return "jr"
    return "private"  # 私鉄のほか、都電・モノレール・ゆりかもめ・りんかい線なども含む


def line_path(coords):
    pts = [xy(x, y) for x, y in coords]
    return "M" + "L".join(f"{x},{y}" for x, y in pts)


def load_rails(area_geom):
    """JR・私鉄・地下鉄に分け、路線名ごとに線路をまとめて SVG パスにする。23区の外は少し余白を残して切る。
    名前のない線路は、60m 以内にある名前つきの線路と同じ路線とみなす（見つからなければ描かない）。"""
    import os
    from shapely.strtree import STRtree
    path = "data/areas/tokyo23_rail.parquet"
    if not os.path.exists(path):
        return []
    clip = area_geom.buffer(0.01)
    named, unnamed = [], []
    for r in pq.read_table(path).to_pylist():
        flags = {v for f in (r["rail_flags"] or []) for v in f["values"]}
        if r["class"] not in RAIL_CLASSES or flags & RAIL_SKIP_FLAGS:
            continue
        g = wkb.loads(r["geometry"]).intersection(clip)
        if g.is_empty:
            continue
        raw = (r["names"] or {}).get("primary") or ""
        if raw:
            name = rail_name(raw)
            if not RAIL_DROP.search(name):
                named.append((name, g))
        else:
            unnamed.append(g)
    tree = STRtree([g for _, g in named])
    near = 60 / 111000
    groups = defaultdict(list)
    for name, g in named:
        groups[name].append(g)
    for g in unnamed:
        hits = tree.query(g, predicate="dwithin", distance=near)
        if len(hits):
            best = min(hits, key=lambda i: named[i][1].distance(g))
            groups[named[best][0]].append(g)
    rails = []
    for name, gs in groups.items():
        d = []
        for g in gs:
            for line in ([g] if g.geom_type == "LineString" else [x for x in getattr(g, "geoms", []) if x.geom_type == "LineString"]):
                d.append(line_path(line.simplify(0.00015).coords))
        rails.append({"k": rail_kind(name), "n": name, "d": "".join(d)})
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
