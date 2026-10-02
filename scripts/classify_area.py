"""23区の飲食 POI を一度に判定し、重複をまとめる（駅ごとの集計の元になる表）。

  python scripts/classify_area.py tokyo23

入力: data/areas/<area>_food.parquet（fetch_overture_area.py の出力）
      data/areas/<area>_claude.csv（任意）判定不能の店名を Claude が判定した結果。列は name, genre, confidence, reason。
        店名単位なので、同じ店名の店（チェーンなど）にはまとめて効く
出力: data/areas/<area>_genre.parquet  1店1行。id, name, ward, lat, lng, category, alternates, address,
        genre, method, cluster（重複をまとめた代表の行番号。cluster == 行番号の行だけ数えればよい）
      data/areas/<area>_unresolved_names.csv  判定不能の店名（重複なし）と件数・手がかり。Claude 判定に送る
"""
import csv
import os
import sys
import unicodedata
from collections import Counter, defaultdict

import pyarrow as pa
import pyarrow.parquet as pq

from classify_genre import ACCEPTED_CONFIDENCE, UNRESOLVED_GENRE, classify
from dedupe import cluster


def norm_name(n):
    return unicodedata.normalize("NFKC", n or "").strip()


def load_claude(area):
    path = f"data/areas/{area}_claude.csv"
    if not os.path.exists(path):
        return {}
    return {norm_name(r["name"]): r for r in csv.DictReader(open(path, encoding="utf-8"))}


def main(area):
    t = pq.read_table(f"data/areas/{area}_food.parquet").to_pylist()
    claude = load_claude(area)
    rows = []
    for r in t:
        name = (r["names"] or {}).get("primary") or ""
        cat = (r["taxonomy"] or {}).get("primary") or ""
        alts = "|".join(((r["categories"] or {}).get("alternate") or []))
        addr = ((r["addresses"] or [{}])[0] or {}).get("freeform") or ""
        b = r["bbox"]
        genre, method, _ = classify(name, cat)
        if method == "unresolved":
            c = claude.get(norm_name(name))
            if c and c["genre"] == "対象外":
                genre, method = "対象外", "excluded"
            elif c and c["genre"] not in ("不明", "") and c["confidence"] in ACCEPTED_CONFIDENCE:
                genre, method = c["genre"], "claude"
        rows.append({"id": r["id"], "name": name, "ward": r["ward"], "lat": (b["ymin"] + b["ymax"]) / 2,
                     "lng": (b["xmin"] + b["xmax"]) / 2, "category": cat, "alternates": alts, "address": addr,
                     "confidence": r["confidence"], "genre": genre, "method": method})

    keep = [i for i, r in enumerate(rows) if r["method"] != "excluded"]
    roots = cluster([(rows[i]["lat"], rows[i]["lng"], rows[i]["name"], rows[i]["genre"]) for i in keep], UNRESOLVED_GENRE)
    for r in rows:
        r["cluster"] = -1
    # 代表は判定できた行を優先する
    best = {}
    for k, root in zip(keep, roots):
        cur = best.get(root)
        if cur is None or (rows[cur]["genre"] == UNRESOLVED_GENRE and rows[k]["genre"] != UNRESOLVED_GENRE):
            best[root] = k
    for k, root in zip(keep, roots):
        rows[k]["cluster"] = best[root]

    out = f"data/areas/{area}_genre.parquet"
    pq.write_table(pa.Table.from_pylist(rows), out)

    reps = [r for i, r in enumerate(rows) if r["cluster"] == i]
    methods = Counter(r["method"] for r in reps)
    unresolved = [r for r in reps if r["genre"] == UNRESOLVED_GENRE]
    print(f"{len(rows)} 件 → 飲食店以外 {sum(1 for r in rows if r['method'] == 'excluded')} 件を除き、"
          f"重複をまとめて {len(reps)} 件")
    print(f"  店名ルール {methods['name']} / Overture {methods['overture']} / Claude {methods['claude']} / "
          f"判定不能 {methods['unresolved']}（判定率 {1 - len(unresolved) / len(reps):.1%}）")

    by_name = defaultdict(list)
    for r in unresolved:
        by_name[norm_name(r["name"])].append(r)
    path = f"data/areas/{area}_unresolved_names.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "count", "category", "alternates", "address_example"])
        for n, rs in sorted(by_name.items(), key=lambda x: -len(x[1])):
            w.writerow([n, len(rs), Counter(r["category"] for r in rs).most_common(1)[0][0],
                        Counter(r["alternates"] for r in rs).most_common(1)[0][0], rs[0]["address"]])
    print(f"  判定不能の店名（重複なし）{len(by_name)} 種類 -> {path}")
    print(f"-> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
