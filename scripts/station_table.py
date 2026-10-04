"""駅から半径1kmの店を23区の判定結果から切り出し、ジャンル別の件数・構成比・特化係数（LQ）を出す。

  python scripts/station_table.py tokyo23                         # common.py の STATIONS（今は亀戸だけ）
  python scripts/station_table.py tokyo23 --stations data/stations.csv   # 駅一覧（S12 から作る予定）

入力: data/areas/<area>_genre.parquet（classify_area.py の出力。重複をまとめた代表の行だけ数える）
      data/census/weights_<area>.csv（census.py の出力、任意。あればセンサス補正した列も出す）
      --stations の CSV: 列 key, name, lat, lng, passengers（passengers は1日平均乗降客数、空欄可）
出力: data/stations/<area>_stations.csv  駅 × 大分類／中分類 の縦長の表
      data/stations/<area>_lq_mid.csv    駅ごとの店数（補正前・後）・乗降客1万人あたり店舗数と、中分類の LQ（センサス補正あり）の
                                         横長の表。駅どうしの比較用。near_edge=1 は円が23区の外にはみ出す駅（外側の店はデータに無い）

数え方:
- 円が重なる駅どうしは、同じ店をそれぞれの駅で数える
- 比較対象（23区全体）も駅側と同じ表・同じ判定・同じ重複まとめなので、方法の違いが LQ に入らない
- 構成比の分母は、大分類なら大分類が分かる店、中分類なら中分類が分かる店だけ。判定率の差が LQ に効かないようにするため
- センサス補正（_w の列）は、店1件を区×センサス小分類の重み件として数える（census.py）。
  乗降客1万人あたり店舗数は補正後の件数で出す（Overture の件数は都心ほど多めに出るため）
"""
import argparse
import csv
import os
from collections import defaultdict

import numpy as np
import pyarrow.parquet as pq

from census import load_weights, weight_of
from common import EARTH_R, RADIUS_M, STATIONS
from genre_groups import GROUPS, MAJOR_ORDER, UNKNOWN, group_of

MID_ORDER = list(dict.fromkeys(mid for _, mid in GROUPS.values()))


def load_stores(area):
    rows = pq.read_table(f"data/areas/{area}_genre.parquet").to_pylist()
    reps = [r for i, r in enumerate(rows) if r["cluster"] == i and r["genre"] != "対象外"]
    weights = load_weights(area)
    stores = []
    for r in reps:
        major, mid = group_of(r["genre"], r["category"])
        w = weight_of(weights, r["ward"], major, mid) if weights else None
        stores.append((major, mid, w))
    lat = np.array([r["lat"] for r in reps])
    lng = np.array([r["lng"] for r in reps])
    return stores, lat, lng, weights is not None


def load_stations(path):
    if not path:
        return [{"key": k, "name": s["name"], "lat": s["lat"], "lng": s["lng"], "passengers": None, "near_edge": ""}
                for k, s in STATIONS.items()]
    out = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        out.append({"key": r["key"], "name": r["name"], "lat": float(r["lat"]), "lng": float(r["lng"]),
                    "passengers": float(r["passengers"]) if r.get("passengers") else None,
                    "near_edge": r.get("near_edge", "")})
    return out


def within(lat, lng, s_lat, s_lng, radius):
    p1, p2 = np.radians(s_lat), np.radians(lat)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lng - s_lng) / 2) ** 2
    return np.nonzero(2 * EARTH_R * np.arcsin(np.sqrt(a)) <= radius)[0]


def tally(stores, idx, weighted):
    """{(level, major, mid): 件数}。level は major / mid。weighted なら重みの合計。"""
    c = defaultdict(float)
    for i in idx:
        major, mid, w = stores[i]
        n = w if weighted else 1
        c[("major", major, "")] += n
        c[("mid", major, mid)] += n
    return c


def shares(c):
    known = {"major": sum(n for (lv, mj, _), n in c.items() if lv == "major" and mj != UNKNOWN),
             "mid": sum(n for (lv, _, md), n in c.items() if lv == "mid" and md != UNKNOWN)}
    return {k: n / known[k[0]] for k, n in c.items()
            if known[k[0]] and (k[1] if k[0] == "major" else k[2]) != UNKNOWN}


def keys_in_order(c):
    out = [("major", mj, "") for mj in MAJOR_ORDER if ("major", mj, "") in c]
    for mj in MAJOR_ORDER:
        mids = [k for k in c if k[0] == "mid" and k[1] == mj]
        out += sorted(mids, key=lambda k: MID_ORDER.index(k[2]) if k[2] in MID_ORDER else len(MID_ORDER))
    return out


def r4(x):
    return round(x, 4) if x is not None else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("area")
    ap.add_argument("--stations")
    ap.add_argument("--radius", type=float, default=RADIUS_M)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    stores, lat, lng, has_w = load_stores(args.area)
    everyone = range(len(stores))
    base = tally(stores, everyone, False)
    base_s = shares(base)
    base_w = tally(stores, everyone, True) if has_w else {}
    base_ws = shares(base_w) if has_w else {}
    if not has_w:
        print(f"data/census/weights_{args.area}.csv が無いのでセンサス補正なしで出す（python scripts/census.py {args.area}）")

    os.makedirs("data/stations", exist_ok=True)
    out = f"data/stations/{args.area}_stations.csv"
    wide, names, totals = {}, {}, {}
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["station", "name", "passengers", "near_edge", "level", "major", "mid",
                    "count", "share", "base_share", "LQ",
                    "count_w", "share_w", "base_share_w", "LQ_w", "per_10k_passengers_w"])
        for st in load_stations(args.stations):
            idx = within(lat, lng, st["lat"], st["lng"], args.radius)
            c = tally(stores, idx, False)
            s = shares(c)
            cw = tally(stores, idx, True) if has_w else {}
            sw = shares(cw) if has_w else {}
            wide[st["key"]] = {}
            for k in keys_in_order(c):
                lq = s[k] / base_s[k] if k in s and base_s.get(k) else None
                lqw = sw[k] / base_ws[k] if k in sw and base_ws.get(k) else None
                per = cw.get(k, 0) / st["passengers"] * 10000 if has_w and st["passengers"] else None
                w.writerow([st["key"], st["name"], int(st["passengers"]) if st["passengers"] else "", st["near_edge"], k[0], k[1], k[2],
                            int(c[k]), r4(s.get(k)), r4(base_s.get(k)), r4(lq),
                            r4(cw.get(k)) if has_w else "", r4(sw.get(k)), r4(base_ws.get(k)), r4(lqw), r4(per)])
                if k[0] == "mid" and k[2] != UNKNOWN:
                    wide[st["key"]][k[2]] = lqw if has_w else lq
            total = len(idx)
            tw = sum(n for (lv, _, _), n in cw.items() if lv == "major") if has_w else None
            per = tw / st["passengers"] * 10000 if tw is not None and st["passengers"] else None
            names[st["key"]] = st["name"]
            totals[st["key"]] = [int(st["passengers"]) if st["passengers"] else "", st["near_edge"], total, r4(tw), r4(per)]
            unk = c.get(("major", UNKNOWN, ""), 0)
            unk_mid = sum(n for (lv, _, md), n in c.items() if lv == "mid" and md == UNKNOWN)
            if not args.quiet:
                print(f"{st['name']}: 半径{args.radius:.0f}m に {total} 店（大分類不明 {unk / total:.1%}、中分類不明 {unk_mid / total:.1%}）")

    out_wide = f"data/stations/{args.area}_lq_mid.csv"
    with open(out_wide, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["station", "name", "passengers", "near_edge", "stores", "stores_w", "per_10k_passengers_w"] + MID_ORDER)
        for key, row in wide.items():
            w.writerow([key, names[key], *totals[key]] + [r4(row.get(m)) for m in MID_ORDER])
    print(f"-> {out}\n-> {out_wide}")


if __name__ == "__main__":
    main()
