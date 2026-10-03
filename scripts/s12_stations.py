"""国土数値情報 S12（駅別乗降客数）から、23区内の駅一覧（station_table.py の --stations 用）を作る。

  python scripts/s12_stations.py S12-23_GML/S12-23_NumberOfPassengers.geojson --inspect   # 列と値を確認
  python scripts/s12_stations.py <geojson> --passengers S12_057 [--group S12_001g]

入力: S12 の GeoJSON（ユーザーがローカルで取得。https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-S12-2024.html 等）
      data/areas/tokyo23_wards.parquet（区の境界）
出力: data/stations.csv  列 key, name, lat, lng, passengers, operators, near_edge

S12 の列名（どの年の乗降客数が何番の列か）は版によって違うので、まず --inspect で確かめてから
--passengers に最新年の乗降客数の列を指定する。（このスクリプトは実データで未確認。2026-10-03）

まとめ方:
- 同じグループコード（乗換駅として同じ駅とみなされる単位）の駅を1駅にする
- 乗降客数は、事業者ごとに最大の値を取って合計する。S12 は同じ事業者の同じ駅を路線ごとに
  同じ数字で載せていることがあり、単純に足すと二重に数えるため
- 位置はグループ内の駅（線）の座標の平均
- 駅が23区内にあるものだけ残す。半径1km の円が23区の外にはみ出す駅は near_edge=1
  （外側の店はデータに無いので、店の数は少なめに出る。構成比・LQ への影響は小さい）
"""
import argparse
import csv
import json
from collections import Counter, defaultdict

import pyarrow.parquet as pq
from shapely import wkb
from shapely.geometry import Point
from shapely.ops import unary_union

from common import RADIUS_M


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
    # 1km を度に直した概算（緯度35.7度）。円がはみ出すかの目安にだけ使う
    inner = area.buffer(-RADIUS_M / 111320 / 0.81)

    groups = defaultdict(list)
    for f in feats:
        p = f["properties"]
        groups[p.get(args.group) or p.get(args.name)].append((p, coords(f["geometry"])))

    rows = []
    for g, members in groups.items():
        pts = [c for _, cs in members for c in cs]
        lng = sum(c[0] for c in pts) / len(pts)
        lat = sum(c[1] for c in pts) / len(pts)
        pt = Point(lng, lat)
        if not area.contains(pt):
            continue
        by_op = defaultdict(float)
        for p, _ in members:
            by_op[p.get(args.operator)] = max(by_op[p.get(args.operator)], num(p.get(args.passengers)))
        name = Counter(p.get(args.name) for p, _ in members).most_common(1)[0][0]
        rows.append({"key": str(g), "name": name, "lat": round(lat, 6), "lng": round(lng, 6),
                     "passengers": int(sum(by_op.values())) or "", "operators": "|".join(sorted(map(str, by_op))),
                     "near_edge": 0 if inner.contains(pt) else 1})

    rows.sort(key=lambda r: -(r["passengers"] or 0))
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"23区内 {len(rows)} 駅（乗降客数なし {sum(1 for r in rows if not r['passengers'])}、"
          f"円が23区の外にはみ出す {sum(r['near_edge'] for r in rows)}）")
    print("乗降客数の多い駅:", "、".join(f"{r['name']} {r['passengers']:,}" for r in rows[:5] if r["passengers"]))
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
