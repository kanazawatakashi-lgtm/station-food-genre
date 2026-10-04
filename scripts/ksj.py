"""国土数値情報（N02 鉄道、N03 行政区域）を読む部品。

  python scripts/ksj.py tokyo23    # 23区の境界を N03 から作り直し、店に区を付け直す

入力: data/ksj/N02-25_RailroadSection.geojson（鉄道。全国）
      data/ksj/N03-20260101_13.geojson（行政区域。東京都）
出力: data/areas/tokyo23_wards.parquet（区の境界。ward は英語名、geometry は WKB）
      data/areas/tokyo23_food.parquet の ward 列を N03 の境界で付け直す（境界の外の店は外す）

出典: 国土交通省「国土数値情報（鉄道データ・行政区域データ）」（公共データ利用規約 第1.0版）を加工して作成。
線路・区の境界は以前 Overture（OpenStreetMap 由来、ODbL）を使っていたが、全国で同じ形で取れ、
商用で使いやすい国土数値情報に置き換えた（2026-10-04、docs/licenses.md）。
"""
import json
import re
import sys
from collections import defaultdict

import pyarrow as pa
import pyarrow.parquet as pq
from shapely import wkb
from shapely.geometry import Point, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

N02 = "data/ksj/N02-25_RailroadSection.geojson"
N03 = "data/ksj/N03-20260101_13.geojson"

# 事業者名を短くする（路線名の頭に付ける）
OPERATOR_SHORT = {
    "東日本旅客鉄道": "JR", "東海旅客鉄道": "JR東海", "東京地下鉄": "東京メトロ", "京成電鉄": "京成", "京浜急行電鉄": "京急",
    "京王電鉄": "京王", "小田急電鉄": "小田急", "東急電鉄": "東急", "東武鉄道": "東武", "西武鉄道": "西武", "相模鉄道": "相鉄",
    "流鉄": "流鉄", "北総鉄道": "", "埼玉高速鉄道": "", "東京モノレール": "", "ゆりかもめ": "", "舞浜リゾートライン": "",
}
# 通称で呼ばれる路線
LINE_ALIAS = {
    ("東京臨海高速鉄道", "臨海副都心線"): "りんかい線",
    ("首都圏新都市鉄道", "常磐新線"): "つくばエクスプレス",
    ("ゆりかもめ", "東京臨海新交通臨海線"): "ゆりかもめ",
    ("東京都", "荒川線"): "都電荒川線",
    ("東京都", "日暮里・舎人ライナー"): "日暮里・舎人ライナー",
    ("横浜市", "3号線"): "横浜市営地下鉄ブルーライン",
    ("横浜市", "4号線"): "横浜市営地下鉄グリーンライン",
    ("東京モノレール", "東京モノレール羽田空港線"): "東京モノレール",
    ("東海旅客鉄道", "東海道新幹線"): "東海道新幹線",
    ("東日本旅客鉄道", "東北新幹線"): "東北新幹線",
}


def line_name(operator, line):
    """N02 の事業者名と路線名から、地図に出す路線名を作る（例: 東京地下鉄 + 3号線銀座線 → 東京メトロ銀座線）。"""
    if (operator, line) in LINE_ALIAS:
        return LINE_ALIAS[(operator, line)]
    line = re.sub(r"^\d+号線", "", line).replace("分岐線", "")
    if operator == "東京都":
        return "都営" + line
    short = OPERATOR_SHORT.get(operator, operator)
    if short and not line.startswith(short):
        return short + line
    return line


def line_kind(n02_002, operator, line):
    """jr / private / subway。N02_002 は事業者種別（1 新幹線、2 JR在来線、3 公営、4 民営、5 第三セクター）。"""
    if n02_002 in ("1", "2"):
        return "jr"
    if operator in ("東京地下鉄",) or (operator in ("東京都", "横浜市") and re.match(r"^\d+号線", line)):
        return "subway"
    return "private"


def load_rails(bbox):
    """bbox (minx, miny, maxx, maxy) にかかる線路を、路線ごとに [{"name", "kind", "operator", "lines": [LineString]}] で返す。"""
    from shapely.geometry import box
    b = box(*bbox)
    groups = defaultdict(lambda: {"lines": []})
    for f in json.load(open(N02, encoding="utf-8"))["features"]:
        p = f["properties"]
        g = shape(f["geometry"])
        if not g.intersects(b):
            continue
        name = line_name(p["N02_004"], p["N02_003"])
        r = groups[name]
        r["name"], r["operator"] = name, p["N02_004"]
        r["kind"] = line_kind(p["N02_002"], p["N02_004"], p["N02_003"])
        r["lines"].append(g)
    return list(groups.values())


def load_wards():
    """23区の境界 {区の日本語名: Polygon/MultiPolygon}。N03 は区ごとに島などで複数行になるのでまとめる。"""
    parts = defaultdict(list)
    for f in json.load(open(N03, encoding="utf-8"))["features"]:
        p = f["properties"]
        code = p.get("N03_007") or ""
        if code.startswith("131") and "101" <= code[2:] <= "123":
            parts[p["N03_004"]].append(shape(f["geometry"]))
    wards = {name: unary_union(gs) for name, gs in parts.items()}
    if len(wards) != 23:
        raise SystemExit(f"23区がそろわない: {len(wards)}")
    return wards


def main(area):
    if area != "tokyo23":
        raise SystemExit("今は tokyo23 だけ対応")
    from census import WARD_EN
    wards = load_wards()
    names = [WARD_EN[n] for n in wards]
    geoms = list(wards.values())
    pq.write_table(pa.table({"ward": names, "geometry": [g.wkb for g in geoms]}), "data/areas/tokyo23_wards.parquet")

    path = "data/areas/tokyo23_food.parquet"
    t = pq.read_table(path)
    tree = STRtree(geoms)
    ward_col, before = [], t["ward"].to_pylist()
    for bb in t["bbox"].to_pylist():
        p = Point((bb["xmin"] + bb["xmax"]) / 2, (bb["ymin"] + bb["ymax"]) / 2)
        hit = tree.query(p, predicate="within")
        ward_col.append(names[hit[0]] if len(hit) else None)
    changed = sum(1 for a, b in zip(before, ward_col) if a != b)
    t = t.set_column(t.schema.get_field_index("ward"), "ward", pa.array(ward_col, pa.string()))
    t = t.filter(pa.compute.is_valid(t["ward"]))
    pq.write_table(t, path)
    print(f"23区の境界を N03 で作り直した。店 {len(before)} 件のうち区が変わった {changed} 件"
          f"（境界の外になった {len(before) - t.num_rows} 件は外した）-> {path}")


if __name__ == "__main__":
    import pyarrow.compute  # noqa: F401
    main(sys.argv[1])
