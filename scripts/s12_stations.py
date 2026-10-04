"""国土数値情報 S12（駅別乗降客数）から、23区内の駅一覧（station_table.py の --stations 用）を作る。

  python scripts/s12_stations.py S12-23_GML/S12-23_NumberOfPassengers.geojson --inspect   # 列と値を確認
  python scripts/s12_stations.py <geojson> --passengers S12_057 [--group S12_001g]

入力: S12 の GeoJSON（ユーザーがローカルで取得。https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-S12-2024.html 等）
      data/areas/tokyo23_wards.parquet（区の境界）
出力: data/stations.csv  列 key, name, lat, lng, passengers, operators

S12 の列名（どの年の乗降客数が何番の列か）は版によって違うので、まず --inspect で確かめてから
--passengers に最新年の乗降客数の列を指定する。
S12-25（2026-10-04 取得）は S12_006 から1年4列（重複コード・データ有無・備考・乗降客数）で 2011〜2024 年。
2024 年の乗降客数は S12_061。重複コード 2 の行（別路線として重ねて載せた行）は乗降客数が 0 になっている。

まとめ方:
- 同じグループコード（乗換駅として同じ駅とみなされる単位）の駅を1駅にする。グループコードが違っても、
  同じ駅名で中心が MERGE_M 以内なら1駅にする（S12 では東京駅の京葉線などが別グループになっている）
- 乗降客数は、事業者ごとに最大の値を取って合計する。S12 は同じ事業者の同じ駅を路線ごとに
  同じ数字で載せていることがあり、単純に足すと二重に数えるため
- 位置はグループ内の駅（線）の座標の平均
- 駅が23区内にあるものだけ残す。円が23区の外にはみ出すか（near_edge）は半径によるので station_table.py で判定する
"""
import argparse
import csv
import json
from collections import Counter, defaultdict

import pyarrow.parquet as pq
from shapely import wkb
from shapely.geometry import Point
from shapely.ops import unary_union

from common import haversine_m

MERGE_M = 500


def coords(geom):
    t = geom["type"]
    if t == "Point":
        return [geom["coordinates"]]
    if t == "LineString":
        return geom["coordinates"]
    if t == "MultiLineString":
        return [c for line in geom["coordinates"] for c in line]
    raise ValueError(t)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("geojson")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--passengers")
    ap.add_argument("--group", default="S12_001g")
    ap.add_argument("--name", default="S12_001")
    ap.add_argument("--operator", default="S12_002")
    ap.add_argument("--out", default="data/stations.csv")
    args = ap.parse_args()

    feats = json.load(open(args.geojson, encoding="utf-8"))["features"]
    if args.inspect or not args.passengers:
        print(f"{len(feats)} 件。最初の駅の属性:")
        for k, v in feats[0]["properties"].items():
            print(f"  {k}: {v}")
        shinjuku = [f["properties"] for f in feats if f["properties"].get(args.name) == "新宿"][:3]
        print("新宿駅の行（乗降客数の列を見分ける手がかり）:")
        for p in shinjuku:
            print("  ", p)
        return

    wards = pq.read_table("data/areas/tokyo23_wards.parquet").to_pylist()
    area = unary_union([wkb.loads(w["geometry"]) for w in wards])

    groups = defaultdict(list)
    for f in feats:
        p = f["properties"]
        groups[p.get(args.group) or p.get(args.name)].append((p, coords(f["geometry"])))

    def center(members):
        pts = [c for _, cs in members for c in cs]
        return sum(c[1] for c in pts) / len(pts), sum(c[0] for c in pts) / len(pts)

    def main_name(members):
        return Counter(p.get(args.name) for p, _ in members).most_common(1)[0][0]

    # 同じ駅名で近いグループをまとめる（駅名ごとに比べる）
    by_name = defaultdict(list)
    for g, members in groups.items():
        by_name[main_name(members)].append(g)
    for gs in by_name.values():
        for i, a in enumerate(gs):
            if a not in groups:
                continue
            for b in gs[i + 1:]:
                if b in groups and haversine_m(*center(groups[a]), *center(groups[b])) <= MERGE_M:
                    groups[a] += groups.pop(b)

    rows = []
    for g, members in groups.items():
        lat, lng = center(members)
        pt = Point(lng, lat)
        if not area.contains(pt):
            continue
        by_op = defaultdict(float)
        for p, _ in members:
            by_op[p.get(args.operator)] = max(by_op[p.get(args.operator)], num(p.get(args.passengers)))
        name = main_name(members)
        rows.append({"key": str(g), "name": name, "lat": round(lat, 6), "lng": round(lng, 6),
                     "passengers": int(sum(by_op.values())) or "", "operators": "|".join(sorted(map(str, by_op)))})

    rows.sort(key=lambda r: -(r["passengers"] or 0))
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"23区内 {len(rows)} 駅（乗降客数なし {sum(1 for r in rows if not r['passengers'])}）")
    print("乗降客数の多い駅:", "、".join(f"{r['name']} {r['passengers']:,}" for r in rows[:5] if r["passengers"]))
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
