"""駅のジャンル別件数・構成比と、比較対象に対する特化係数（LQ）を出す。

  python scripts/genre_table.py kameido tokyo23

入力: data/<station>/genre.csv（classify_genre.py の出力）
      data/areas/<area>_food.parquet（fetch_overture_area.py の出力）
出力: data/<station>/genre_table.csv

LQ の計算は駅側も比較対象側も「店名ルール＋Overture」だけで判定した結果を使う。
Claude の判定は比較対象側に無いので、混ぜると駅側だけ判定率が上がり比べられなくなる。
構成比の分母は判定できた店だけ（判定不能を除く）。判定率の差が LQ に効かないようにするため。
"""
import csv
import sys
from collections import Counter

import pyarrow.parquet as pq

from classify_genre import UNRESOLVED_GENRE, classify

ORDER_EXCLUDE = {"対象外", UNRESOLVED_GENRE}


def area_counts(area):
    t = pq.read_table(f"data/areas/{area}_food.parquet", columns=["names", "taxonomy"]).to_pylist()
    c = Counter()
    for r in t:
        name = (r["names"] or {}).get("primary") or ""
        cat = (r["taxonomy"] or {}).get("primary") or ""
        c[classify(name, cat)[0]] += 1
    return c


def shares(counter):
    resolved = {g: n for g, n in counter.items() if g not in ORDER_EXCLUDE}
    total = sum(resolved.values())
    return {g: n / total for g, n in resolved.items()}, total


def main(key, area):
    rows = list(csv.DictReader(open(f"data/{key}/genre.csv", encoding="utf-8")))
    final = Counter(r["genre"] for r in rows if r["method"] != "excluded")
    rules_only = Counter(classify(r["name"], r["category"])[0] for r in rows)
    base = area_counts(area)

    st_share, st_total = shares(rules_only)
    base_share, base_total = shares(base)
    target = sum(final.values())

    genres = sorted({g for g in final if g not in ORDER_EXCLUDE} | set(base_share), key=lambda g: -final.get(g, 0))
    out = f"data/{key}/genre_table.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["genre", "count", "share", "count_rules_only", "share_rules_only",
                    f"{area}_count", f"{area}_share", "LQ"])
        for g in genres:
            lq = st_share.get(g, 0) / base_share[g] if base_share.get(g) else None
            w.writerow([g, final.get(g, 0), round(final.get(g, 0) / target, 4),
                        rules_only.get(g, 0), round(st_share.get(g, 0), 4),
                        base.get(g, 0), round(base_share.get(g, 0), 4),
                        round(lq, 2) if lq is not None else ""])
        w.writerow([UNRESOLVED_GENRE, final.get(UNRESOLVED_GENRE, 0), round(final.get(UNRESOLVED_GENRE, 0) / target, 4),
                    rules_only.get(UNRESOLVED_GENRE, 0), "", base.get(UNRESOLVED_GENRE, 0), "", ""])

    st_rate = st_total / (sum(rules_only.values()) - rules_only["対象外"])
    base_rate = base_total / (sum(base.values()) - base["対象外"])
    print(f"{key}: 対象 {target} 件（最終判定率 {1 - final[UNRESOLVED_GENRE] / target:.1%}、ルールのみ {st_rate:.1%}）")
    print(f"{area}: 飲食 {sum(base.values())} 件（ルールのみ判定率 {base_rate:.1%}）")
    print(f"-> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
