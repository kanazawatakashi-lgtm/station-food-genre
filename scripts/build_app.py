"""出店エリア分析アプリ（docs/app.html）を作る。店舗物件の仲介会社向けの試作。

  python scripts/build_app.py

入力: data/areas/tokyo23_genre.parquet（classify_area.py）、data/census/weights_tokyo23.csv（census.py）
      data/stations.csv（s12_stations.py）、data/stations/tokyo23_r{300,500,1000}_stations.csv（station_table.py）
      data/stations/tokyo23_population.csv（mesh_stats.py、任意。あれば駅カードに人口を出す）
      国土数値情報 N02（線路）、data/areas/tokyo23_wards.parquet（区の境界）
出力: docs/app.html（データを埋め込んだ1ファイル。ブラウザで開くだけで動く）

画面:
- 駅カード: 乗降客数、半径 300/500/1000m の店数・ジャンル構成・多い／少ないジャンル（LQ、センサス補正後）、人口
- 比較: 最大5駅を並べる
- ジャンルで探す: 中分類を選ぶと、そのジャンルが少ない（多い）駅を並べ、地図を LQ で塗る
- 地点分析: 地図をクリック・座標の貼り付け・駅名で地点を決め、半径 50/100/300m の店の一覧と分布を出す
"""
import csv
import json
import os

import pyarrow.parquet as pq
from shapely import wkb
from shapely.ops import unary_union

from census import WARD_EN, load_weights, weight_of
from genre_groups import GROUPS, MAJOR_ORDER, UNKNOWN, group_of
from station_map import load_rails, ring_path, xy

RADII = (300, 500, 1000)
MID_ORDER = list(dict.fromkeys(mid for _, mid in GROUPS.values()))
MID_MAJOR = {mid: major for major, mid in GROUPS.values()}


def load_station_stats():
    """{駅キー: {半径: {"t": 店数, "tw": 補正後店数, "M": 大分類ごとの件数, "m": 中分類ごとの件数, "q": 中分類の LQ_w}}}"""
    out = {}
    for r in RADII:
        for row in csv.DictReader(open(f"data/stations/tokyo23_r{r}_stations.csv", encoding="utf-8-sig")):
            st = out.setdefault(row["station"], {}).setdefault(r, {
                "t": 0, "tw": 0.0, "M": [0] * len(MAJOR_ORDER), "m": [0] * len(MID_ORDER), "q": [None] * len(MID_ORDER),
                "u": 0})
            n = int(row["count"])
            if row["level"] == "major":
                st["M"][MAJOR_ORDER.index(row["major"])] = n
                st["t"] += n
                st["tw"] += float(row["count_w"] or 0)
            elif row["mid"] == UNKNOWN:
                st["u"] += n  # 中分類不明
            else:
                i = MID_ORDER.index(row["mid"])
                st["m"][i] = n
                st["q"][i] = round(float(row["LQ_w"]), 2) if row["LQ_w"] else None
    for st in out.values():
        for v in st.values():
            v["tw"] = round(v["tw"], 1)
    return out


def load_population():
    path = "data/stations/tokyo23_population.csv"
    if not os.path.exists(path):
        return {}, []
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    cols = [c for c in rows[0] if c not in ("station", "name", "radius")]
    out = {}
    for r in rows:
        out.setdefault(r["station"], {})[int(r["radius"])] = [int(float(r[c] or 0)) for c in cols]
    return out, cols  # out["_area"][0] は対象地域全体の合計


def area_km2(g):
    """経緯度のポリゴンの面積（km²、緯度35.7度での近似）。"""
    import math
    return g.area * 111.32 * 110.95 * math.cos(math.radians(35.7))


def main():
    ja = {en: name for name, en in WARD_EN.items()}
    ward_rows = pq.read_table("data/areas/tokyo23_wards.parquet").to_pylist()
    wards = []
    for r in ward_rows:
        g = wkb.loads(r["geometry"]).simplify(0.0003, preserve_topology=True)
        polys = [g] if g.geom_type == "Polygon" else list(g.geoms)
        c = g.representative_point()
        wards.append({"name": ja.get(r["ward"], r["ward"]), "d": "".join(ring_path(p.exterior.coords) for p in polys),
                      "c": xy(c.x, c.y)})
    area_geom = unary_union([wkb.loads(r["geometry"]) for r in ward_rows])
    rails = load_rails(area_geom)

    # 店（重複をまとめた代表の行）。列ごとの配列にして小さくする
    rows = pq.read_table("data/areas/tokyo23_genre.parquet").to_pylist()
    weights = load_weights("tokyo23")
    fine_names = []
    fine_idx = {}
    S = {"la": [], "lo": [], "n": [], "f": [], "M": [], "m": []}
    base_M = [0.0] * len(MAJOR_ORDER)
    base_m = [0.0] * len(MID_ORDER)
    for i, r in enumerate(rows):
        if r["cluster"] != i or r["genre"] == "対象外":
            continue
        major, mid = group_of(r["genre"], r["category"], r.get("low_genre", ""))
        fine = r["genre"] if r["genre"] in GROUPS else ""
        if fine not in fine_idx:
            fine_idx[fine] = len(fine_names)
            fine_names.append(fine)
        S["la"].append(round(r["lat"], 5))
        S["lo"].append(round(r["lng"], 5))
        S["n"].append(r["name"])
        S["f"].append(fine_idx[fine])
        S["M"].append(MAJOR_ORDER.index(major))
        S["m"].append(MID_ORDER.index(mid) if mid != UNKNOWN else -1)
        w = weight_of(weights, r["ward"], major, mid) if weights else 1
        base_M[MAJOR_ORDER.index(major)] += w
        if mid != UNKNOWN:
            base_m[MID_ORDER.index(mid)] += w
    # 23区全体の構成比（センサス補正後、分からない店を除いた分母）
    known_M = sum(v for k, v in zip(MAJOR_ORDER, base_M) if k != UNKNOWN)
    base = {"M": [round(v / known_M, 4) if k != UNKNOWN else None for k, v in zip(MAJOR_ORDER, base_M)],
            "m": [round(v / sum(base_m), 4) for v in base_m]}

    stats = load_station_stats()
    pop, pop_cols = load_population()
    stations = []
    for r in csv.DictReader(open("data/stations.csv", encoding="utf-8")):
        if not r["passengers"] or r["key"] not in stats:
            continue
        x, y = xy(float(r["lng"]), float(r["lat"]))
        stations.append({"k": r["key"], "n": r["name"], "la": float(r["lat"]), "lo": float(r["lng"]), "x": x, "y": y,
                         "p": int(r["passengers"]), "o": r["operators"].replace("|", "・"),
                         "r": {str(k): v for k, v in stats[r["key"]].items()},
                         "pop": {str(k): v for k, v in pop.get(r["key"], {}).items()}})
    stations.sort(key=lambda s: -s["p"])

    w, h = xy(139.925, 35.515)
    from station_map import MIN_LNG, MAX_LAT, SCALE, KX
    data = {"w": w, "h": h, "proj": {"lng0": MIN_LNG, "lat0": MAX_LAT, "s": SCALE, "kx": KX},
            "wards": wards, "rails": rails, "stations": stations,
            "majors": MAJOR_ORDER, "mids": MID_ORDER, "midMajor": [MAJOR_ORDER.index(MID_MAJOR[m]) for m in MID_ORDER],
            "fine": fine_names, "stores": S, "base": base, "popCols": pop_cols, "radii": list(RADII),
            "popArea": pop.get("_area", {}).get(0), "areaKm2": round(area_km2(area_geom), 1)}
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    html = open("scripts/app_template.html", encoding="utf-8").read().replace("__DATA__", blob)
    with open("docs/app.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"駅 {len(stations)}・店 {len(S['n'])}・路線 {len(rails)}・人口列 {len(pop_cols)} -> docs/app.html（{len(html) / 1e6:.1f} MB）")


if __name__ == "__main__":
    main()
