"""飲食出店ナビ・東京23区版（docs/app.html）を作る。店舗物件の仲介会社向け。

  python scripts/build_app.py

入力: data/areas/tokyo23_genre.parquet（classify_area.py）、data/census/weights_tokyo23.csv（census.py）
      data/stations.csv（s12_stations.py）、data/stations/tokyo23_r{250,500,1000}_stations.csv（station_table.py）
      data/stations/tokyo23_population.csv・tokyo23_workers.csv（mesh_stats.py、任意。あれば駅カードに人口・働く人の数を出す）
      国土数値情報 N02（線路）、data/areas/tokyo23_wards.parquet（区の境界。ksj.py が N03 から作る）
      docs/license_texts/*.txt（店舗データのライセンス文と Foursquare の NOTICE。出典欄から開く）
      data/isj/13_<年>.csv（位置参照情報 街区レベル、東京都。いちばん新しい年のものを使う。任意。あれば地点分析で住所から探せる）
出力: docs/app.html（データを埋め込んだ1ファイル。公開ページ用）

画面（タブ）:
- 各駅情報: 駅の特徴（規則で作る文章）、乗降客数、半径 250/500/1000m の店数・ジャンル構成・多い／少ないジャンル
  （平均比＝LQ、センサス補正後）、住んでいる人・働いている人
- 地点分析: 駅名・住所・座標・地図のクリックで地点を決め、半径 50/100/250m の店の一覧と分布を出す
- 比較: 最大5駅のジャンル別構成表を並べる（構成比・店数・平均比）
- ジャンル別: 中分類を選ぶと、そのジャンルが少ない（多い）駅を並べ、地図を平均比で塗る
- 乗降客数: 乗降客数の順位と、路線ごとの強調表示
"""
import csv
import json
import os
from collections import Counter

import pyarrow.parquet as pq
from shapely import wkb
from shapely.ops import unary_union

from census import WARD_EN, load_weights, weight_of
from genre_groups import GROUPS, MAJOR_ORDER, UNKNOWN, group_of
from svgmap import load_rails, ring_path, xy

RADII = (250, 500, 1000)
MID_ORDER = list(dict.fromkeys(mid for _, mid in GROUPS.values()))
MID_MAJOR = {mid: major for major, mid in GROUPS.values()}


def load_station_stats():
    """{駅キー: {半径: {"t": 店数, "tw": 補正後店数, "M": 大分類ごとの件数, "m": 中分類ごとの件数, "q": 中分類の LQ_w}}}"""
    out = {}
    for r in RADII:
        for row in csv.DictReader(open(f"data/stations/tokyo23_r{r}_stations.csv", encoding="utf-8-sig")):
            st = out.setdefault(row["station"], {}).setdefault(r, {
                "t": 0, "tw": 0.0, "M": [0] * len(MAJOR_ORDER), "m": [0] * len(MID_ORDER), "q": [None] * len(MID_ORDER),
                "u": 0, "e": int(row["near_edge"] or 0)})
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
    """駅 × 半径ごとの人口（mesh_stats.py の出力）。国勢調査の人口と経済センサスの従業者数を列としてつなぐ。"""
    out, cols = {}, []
    for path in ("data/stations/tokyo23_population.csv", "data/stations/tokyo23_workers.csv"):
        if not os.path.exists(path):
            continue
        rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
        these = [c for c in rows[0] if c not in ("station", "name", "radius")]
        for r in rows:
            cur = out.setdefault(r["station"], {}).setdefault(int(r["radius"]), [0] * len(cols))
            cur.extend(int(float(r[c] or 0)) for c in these)
        cols += these
        for st in out.values():  # この表に無い駅も列の数をそろえる
            for v in st.values():
                v.extend([0] * (len(cols) - len(v)))
    return out, cols  # out["_area"][0] は対象地域全体の合計


KANJI_DIGIT = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def kanji_num(t):
    """漢数字（二十三 など、99 まで）を数に。"""
    if "十" in t:
        a, _, b = t.partition("十")
        return (KANJI_DIGIT.get(a, 1) if a else 1) * 10 + (KANJI_DIGIT.get(b, 0) if b else 0)
    return KANJI_DIGIT.get(t, 0)


def load_addresses():
    """位置参照情報（街区レベル）から、23区の住所 → 緯度経度の索引を作る。
    {区: {町名: {丁目(0=丁目なし): [緯度, 経度, {街区符号: [緯度, 経度]}]}}}。緯度経度は (値-35)*1e5, (値-139)*1e5 の整数。
    丁目・町の位置は、含まれる街区の平均。"""
    import re
    import glob
    paths = sorted(glob.glob("data/isj/13_*.csv"))
    if not paths:
        return {}
    path = paths[-1]  # いちばん新しい年
    idx = {}
    pts = {}
    for r in csv.DictReader(open(path, encoding="cp932")):
        ward = r["市区町村名"]
        if ward not in WARD_EN or r["更新前履歴フラグ"] == "1":
            continue
        m = re.match(r"^(.*?)([〇一二三四五六七八九十]+)丁目$", r["大字・丁目名"])
        town, chome = (m.group(1), kanji_num(m.group(2))) if m else (r["大字・丁目名"], 0)
        key = (ward, town, chome, r["街区符号・地番"])
        if key in pts and r["代表フラグ"] != "1":
            continue
        pts[key] = (int(round((float(r["緯度"]) - 35) * 1e5)), int(round((float(r["経度"]) - 139) * 1e5)))
    groups = {}
    for (ward, town, chome, block), (la, lo) in pts.items():
        groups.setdefault((ward, town, chome), {})[block] = [la, lo]
    for (ward, town, chome), blocks in groups.items():
        la = round(sum(v[0] for v in blocks.values()) / len(blocks))
        lo = round(sum(v[1] for v in blocks.values()) / len(blocks))
        idx.setdefault(ward, {}).setdefault(town, {})[chome] = [la, lo, blocks]
    return idx


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
    raw_M = [0] * len(MAJOR_ORDER)  # 補正なしの件数（構成表で駅の構成比と並べる用）
    raw_m = [0] * len(MID_ORDER)
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
        raw_M[MAJOR_ORDER.index(major)] += 1
        if mid != UNKNOWN:
            base_m[MID_ORDER.index(mid)] += w
            raw_m[MID_ORDER.index(mid)] += 1
    # 23区全体の構成比（センサス補正後、分からない店を除いた分母）
    known_M = sum(v for k, v in zip(MAJOR_ORDER, base_M) if k != UNKNOWN)
    base = {"M": [round(v / known_M, 4) if k != UNKNOWN else None for k, v in zip(MAJOR_ORDER, base_M)],
            "m": [round(v / sum(base_m), 4) for v in base_m],
            "rawM": [round(v / sum(x for k, x in zip(MAJOR_ORDER, raw_M) if k != UNKNOWN), 4) if k != UNKNOWN else None
                     for k, v in zip(MAJOR_ORDER, raw_M)],
            "rawm": [round(v / sum(raw_m), 4) for v in raw_m]}

    stats = load_station_stats()
    pop, pop_cols = load_population()
    stations = []
    for r in csv.DictReader(open("data/stations.csv", encoding="utf-8")):
        if not r["passengers"] or r["key"] not in stats:
            continue
        x, y = xy(float(r["lng"]), float(r["lat"]))
        stations.append({"k": r["key"], "n": r["name"], "la": float(r["lat"]), "lo": float(r["lng"]), "x": x, "y": y,
                         "p": int(r["passengers"]), "o": r["operators"].replace("|", "・"),
                         "lines": [x for x in (r.get("lines") or "").split("|") if x],
                         "r": {str(k): v for k, v in stats[r["key"]].items()},
                         "pop": {str(k): v for k, v in pop.get(r["key"], {}).items()}})
    stations.sort(key=lambda s: -s["p"])
    # 同じ名前の別の駅（浅草・早稲田など）は、駅名に路線名を添えて区別する（ユーザー決定 2026-10-05。今後も同じ扱い）。
    # 路線が3つ以上なら、乗降客数の多い事業者の路線から2つと「など」
    dup = {n for n, c in Counter(s["n"] for s in stations).items() if c > 1}
    for s in stations:
        if s["n"] in dup:
            ls = s.pop("lines")
            s["n"] = f'{s["n"]}（{"・".join(ls[:2])}{"など" if len(ls) > 2 else ""}）' if ls else s["n"]
        else:
            s.pop("lines")

    w, h = xy(139.925, 35.515)
    from svgmap import MIN_LNG, MAX_LAT, SCALE, KX
    data = {"w": w, "h": h, "proj": {"lng0": MIN_LNG, "lat0": MAX_LAT, "s": SCALE, "kx": KX},
            "wards": wards, "rails": rails, "stations": stations,
            "majors": MAJOR_ORDER, "mids": MID_ORDER, "midMajor": [MAJOR_ORDER.index(MID_MAJOR[m]) for m in MID_ORDER],
            "fine": fine_names, "stores": S, "base": base, "popCols": pop_cols, "radii": list(RADII),
            "popArea": pop.get("_area", {}).get(0), "areaKm2": round(area_km2(area_geom), 1),
            "addr": load_addresses(),
            # 店舗データのライセンス文（CDLA-Permissive-2.0 は第2.1条、Apache-2.0 は第4条で、配るときに全文を添えることが条件）と、
            # Foursquare の NOTICE（全文を残すことが条件。末尾に変更の内容を書き足してある）
            "licenses": {n: open(f"docs/license_texts/{n}.txt", encoding="utf-8").read() for n in ("CDLA-Permissive-2.0", "Apache-2.0", "Foursquare-NOTICE")}}
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    html = open("scripts/app_template.html", encoding="utf-8").read().replace("__DATA__", blob)
    with open("docs/app.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"駅 {len(stations)}・店 {len(S['n'])}・路線 {len(rails)}・人口列 {len(pop_cols)} -> docs/app.html（{len(html) / 1e6:.1f} MB）")


if __name__ == "__main__":
    main()
