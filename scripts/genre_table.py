"""駅のジャンル別件数・構成比と、比較対象に対する特化係数（LQ）を出す。

  python scripts/genre_table.py kameido tokyo23

入力: data/<station>/genre.csv（classify_genre.py の出力）
      data/areas/<area>_food.parquet（fetch_overture_area.py の出力）
出力: data/<station>/genre_table.csv

LQ の計算は駅側も比較対象側も「店名ルール＋Overture」だけで判定した結果を使う。
Claude の判定は比較対象側に無いので、混ぜると駅側だけ判定率が上がり比べられなくなる。
構成比の分母は判定できた店だけ（判定不能を除く）。判定率の差が LQ に効かないようにするため。
重複レコードは駅側・比較対象側とも dedupe.py の同じ条件でまとめてから数える（--no-dedupe で無効）。
"""
import csv
import sys
from collections import Counter

import pyarrow.parquet as pq

from classify_genre import UNRESOLVED_GENRE, classify
from dedupe import dedupe_genres

ORDER_EXCLUDE = {"対象外", UNRESOLVED_GENRE}


def count(records, dedupe):
    """records: [(lat, lng, name, genre)]。重複をまとめてジャンル別に数える。"""
    if not dedupe:
        return Counter(r[3] for r in records)
    best, _ = dedupe_genres(records, UNRESOLVED_GENRE)
    return Counter(best.values())


def area_records(area):
    t = pq.read_table(f"data/areas/{area}_food.parquet", columns=["names", "taxonomy", "bbox"]).to_pylist()
    out = []
    for r in t:
        name = (r["names"] or {}).get("primary") or ""
        cat = (r["taxonomy"] or {}).get("primary") or ""
        g = classify(name, cat)[0]
        if g != "対象外":
            b = r["bbox"]
            out.append(((b["ymin"] + b["ymax"]) / 2, (b["xmin"] + b["xmax"]) / 2, name, g))
    return out


def shares(counter):
    resolved = {g: n for g, n in counter.items() if g not in ORDER_EXCLUDE}
    total = sum(resolved.values())
    return {g: n / total for g, n in resolved.items()}, total


def main(key, area, dedupe=True):
    rows = [r for r in csv.DictReader(open(f"data/{key}/genre.csv", encoding="utf-8")) if r["method"] != "excluded"]
    pos = [(float(r["lat"]), float(r["lng"]), r["name"]) for r in rows]
    final = count([(*p, r["genre"]) for p, r in zip(pos, rows)], dedupe)
    rules_only = count([(*p, classify(r["name"], r["category"])[0]) for p, r in zip(pos, rows)], dedupe)
    rules_only.pop("対象外", None)
    area_recs = area_records(area)
    base = count(area_recs, dedupe)

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

    st_rate = st_total / sum(rules_only.values())
    base_rate = base_total / sum(base.values())
    print(f"{key}: 対象 {len(rows)} 件 → 重複除去後 {target} 件（最終判定率 {1 - final[UNRESOLVED_GENRE] / target:.1%}、ルールのみ {st_rate:.1%}）")
    print(f"{area}: 飲食 {len(area_recs)} 件 → 重複除去後 {sum(base.values())} 件（ルールのみ判定率 {base_rate:.1%}）")
    print(f"-> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], dedupe="--no-dedupe" not in sys.argv)
