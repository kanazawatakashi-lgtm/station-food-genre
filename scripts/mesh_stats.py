"""地域メッシュ統計（国勢調査・経済センサスなど、e-Stat の「地域メッシュ統計」CSV）を、駅から半径 R の円で集計する。

  python scripts/mesh_stats.py --inspect data/mesh/tblT001141H5339.txt            # 列名と項目名を表示
  python scripts/mesh_stats.py data/mesh/*.txt --cols "人口=人口（総数）,0-14歳=..." --out data/stations/tokyo23_population.csv

入力: e-Stat 統計GIS の地域メッシュ統計 CSV（1次メッシュごとのファイル。1行目が列コード、2行目が項目名、
      KEY_CODE 列がメッシュコード。秘匿値は "*"、該当なしは "-"）。複数ファイルを渡すとまとめて読む
      data/stations.csv（s12_stations.py の出力）
出力: 駅 × 半径（300/500/1000m）ごとの合計（--out の CSV）

--cols は「出力の列名=元の項目名」をカンマ区切りで並べる（「+」でつなぐと合計）。項目名は --inspect で確認する。

集計の仕方: メッシュの中に人口が均等に散らばっているとみなし、円と重なる面積の割合をかけて足す
（メッシュを 10×10 の点に分け、円に入る点の割合で近似）。250m メッシュなら 300m の円でもおおむね正しい。
秘匿値（"*"）は 0 として扱う（少人数のメッシュなので影響は小さい）。

出典の書き方: 総務省統計局「令和2年国勢調査 地域メッシュ統計」（e-Stat）を加工して作成。
"""
import argparse
import csv
import glob
import math
from collections import defaultdict

from common import haversine_m

RADII = (300, 500, 1000)


def mesh_bounds(code):
    """メッシュコード → (min_lat, min_lng, dlat, dlng)。1次〜6次（4〜11桁）に対応。"""
    c = str(code)
    lat = int(c[0:2]) / 1.5
    lng = int(c[2:4]) + 100
    dlat, dlng = 2 / 3, 1.0
    if len(c) >= 6:  # 2次
        dlat, dlng = dlat / 8, dlng / 8
        lat += int(c[4]) * dlat
        lng += int(c[5]) * dlng
    if len(c) >= 8:  # 3次（約1km）
        dlat, dlng = dlat / 10, dlng / 10
        lat += int(c[6]) * dlat
        lng += int(c[7]) * dlng
    for d in c[8:]:  # 4次（500m）・5次（250m）・6次（125m）: 1=南西 2=南東 3=北西 4=北東
        dlat, dlng = dlat / 2, dlng / 2
        q = int(d) - 1
        lat += (q // 2) * dlat
        lng += (q % 2) * dlng
    return lat, lng, dlat, dlng


def read_mesh_csv(paths):
    """{メッシュコード: {項目名: 値}} と、列コード→項目名の対応を返す。"""
    rows, labels = {}, {}
    for path in paths:
        for enc in ("utf-8-sig", "cp932"):
            try:
                lines = list(csv.reader(open(path, encoding=enc)))
                break
            except UnicodeDecodeError:
                continue
        head, names = lines[0], lines[1]
        labels.update(dict(zip(head, names)))
        for r in lines[2:]:
            if not r or not r[0].strip():
                continue
            rec = dict(zip(head, r))
            code = rec.get("KEY_CODE", "").strip()
            if code.isdigit():
                rows.setdefault(code, {}).update({labels[k]: v for k, v in rec.items() if k in labels})
    return rows, labels


def num(v):
    v = (v or "").strip()
    try:
        return float(v)
    except ValueError:
        return 0.0  # "*"（秘匿）や "-"（該当なし）


def coverage(code, lat, lng, radius, n=10):
    """メッシュのうち、駅から radius 以内にある面積の割合（n×n 点で近似）。"""
    mlat, mlng, dlat, dlng = mesh_bounds(code)
    inside = 0
    for i in range(n):
        for j in range(n):
            if haversine_m(lat, lng, mlat + (i + 0.5) * dlat / n, mlng + (j + 0.5) * dlng / n) <= radius:
                inside += 1
    return inside / (n * n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--cols", default="")
    ap.add_argument("--stations", default="data/stations.csv")
    ap.add_argument("--out", default="data/stations/tokyo23_population.csv")
    args = ap.parse_args()
    paths = [p for f in args.files for p in glob.glob(f)]
    rows, labels = read_mesh_csv(paths)
    if args.inspect or not args.cols:
        print(f"{len(paths)} ファイル、メッシュ {len(rows)} 個（例: {next(iter(rows), '')}）")
        for k, v in labels.items():
            print(f"  {k}: {v}")
        return

    # 「出力名=項目名」。項目名は全角空白を除いて完全一致を優先し、なければ部分一致。「+」でつなぐと足し合わせる
    norm = lambda t: t.replace("\u3000", "").strip()
    labs = list(dict.fromkeys(labels.values()))
    cols = []
    for part in args.cols.split(","):
        out, src = part.split("=", 1)
        srcs = []
        for one in src.split("+"):
            hits = [lab for lab in labs if norm(lab) == norm(one)] or [lab for lab in labs if norm(one) in norm(lab)]
            if not hits:
                raise SystemExit(f"項目が見つからない: {one}")
            srcs.append(hits[0])
        cols.append((out.strip(), srcs))
        print(f"  {out.strip()} ← {' + '.join(norm(x) for x in srcs)}")

    # メッシュの中心で大まかに絞ってから面積の割合を計算する
    centers = {}
    for code in rows:
        mlat, mlng, dlat, dlng = mesh_bounds(code)
        centers[code] = (mlat + dlat / 2, mlng + dlng / 2, max(dlat * 111000, dlng * 90000))
    stations = list(csv.DictReader(open(args.stations, encoding="utf-8")))
    out_rows = []
    for st in stations:
        lat, lng = float(st["lat"]), float(st["lng"])
        for radius in RADII:
            tot = defaultdict(float)
            for code, (clat, clng, size) in centers.items():
                if haversine_m(lat, lng, clat, clng) > radius + size:
                    continue
                f = coverage(code, lat, lng, radius)
                if f:
                    for out, srcs in cols:
                        tot[out] += sum(num(rows[code].get(x)) for x in srcs) * f
            out_rows.append({"station": st["key"], "name": st["name"], "radius": radius,
                             **{out: round(tot[out]) for out, _ in cols}})
    # 比較対象の地域全体（23区）の合計も1行加える（station="_area"、radius=0）。メッシュの中心が区の中にあるものを足す
    import os
    if os.path.exists("data/areas/tokyo23_wards.parquet"):
        import pyarrow.parquet as pq
        from shapely import wkb
        from shapely.geometry import Point
        from shapely.ops import unary_union
        from shapely.prepared import prep
        area = prep(unary_union([wkb.loads(r["geometry"]) for r in pq.read_table("data/areas/tokyo23_wards.parquet").to_pylist()]))
        tot = defaultdict(float)
        for code, (clat, clng, _) in centers.items():
            if area.contains(Point(clng, clat)):
                for out, srcs in cols:
                    tot[out] += sum(num(rows[code].get(x)) for x in srcs)
        out_rows.append({"station": "_area", "name": "対象地域全体", "radius": 0, **{out: round(tot[out]) for out, _ in cols}})
    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)
    print(f"{len(stations)} 駅 × {len(RADII)} 半径 -> {args.out}")


if __name__ == "__main__":
    main()
