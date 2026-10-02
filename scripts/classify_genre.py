"""店名ルール・Overture の細分類・Claude の店名判定を合わせてジャンルを決める。

  python scripts/classify_genre.py kameido

入力: data/<station>/overture_food.csv
      data/<station>/osm_genre.csv（任意）apply_osm.py の出力。OSM のタグから取ったジャンル
      data/<station>/genre_claude.csv（任意）ルールで決まらなかった店を Claude が店名から
        判定した結果。列は id, name, genre, confidence(高/中/低), reason
出力: data/<station>/genre.csv   1店1行。genre / method / matched を追加
      標準出力に判定率とジャンル別件数

method:
  name      店名の正規表現（チェーン名を含む）で決まった
  overture  Overture の細分類で決まった
  osm       OpenStreetMap の cuisine などのタグで決まった（人が付けたタグなので Claude 判定より先に使う）
  claude    Claude が店名から判定した（確信度 高・中のみ採用）
  excluded  飲食店ではない、または位置情報の誤りとして集計から外す
  unresolved  決まらなかった。集計では「その他飲食（判定不能）」になる

確信度「低」の Claude 判定は採用せず unresolved のまま残す（genre_claude.csv には残る）。
"""
import csv
import os
import re
import sys
import unicodedata
from collections import Counter

from genre_rules import NAME_RULES, NOT_RESTAURANT, NOT_RESTAURANT_NAME, OVERTURE_MAP

COMPILED = [(g, re.compile(p)) for g, p in NAME_RULES]
NOT_REST_RE = re.compile(NOT_RESTAURANT_NAME)
UNRESOLVED_GENRE = "その他飲食（判定不能）"
ACCEPTED_CONFIDENCE = {"高", "中"}


def normalize(name):
    return unicodedata.normalize("NFKC", name or "").lower()


def classify(name, category):
    n = normalize(name)
    if category in NOT_RESTAURANT or NOT_REST_RE.search(n):
        return "対象外", "excluded", category or ""
    for genre, rx in COMPILED:
        m = rx.search(n)
        if m:
            return genre, "name", m.group(0)
    if category in OVERTURE_MAP:
        return OVERTURE_MAP[category], "overture", category
    return UNRESOLVED_GENRE, "unresolved", category or ""


def load_osm(key):
    path = f"data/{key}/osm_genre.csv"
    if not os.path.exists(path):
        return {}
    return {r["id"]: r for r in csv.DictReader(open(path, encoding="utf-8")) if r["osm_genre"]}


def load_claude(key):
    path = f"data/{key}/genre_claude.csv"
    if not os.path.exists(path):
        return {}
    return {r["id"]: r for r in csv.DictReader(open(path, encoding="utf-8"))}


def main(key):
    src = f"data/{key}/overture_food.csv"
    out = f"data/{key}/genre.csv"
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    claude = load_claude(key)
    osm = load_osm(key)
    checked = agreed = 0
    disagreements = []
    for r in rows:
        r["genre"], r["method"], r["matched"] = classify(r["name"], r["category"])
        o = osm.get(r["id"])
        if o and r["method"] in ("name", "overture"):
            checked += 1
            if o["osm_genre"] == r["genre"]:
                agreed += 1
            else:
                disagreements.append(f'{r["name"]}: 判定 {r["genre"]} / OSM {o["osm_genre"]}')
        if r["method"] == "unresolved" and o:
            r["genre"], r["method"], r["matched"] = o["osm_genre"], "osm", f'{o["osm_id"]} {o["osm_tags"]}'
            continue
        c = claude.get(r["id"])
        if r["method"] == "unresolved" and c:
            if c["genre"] == "対象外":
                r["genre"], r["method"], r["matched"] = "対象外", "excluded", c["reason"]
            elif c["genre"] != "不明" and c["confidence"] in ACCEPTED_CONFIDENCE:
                r["genre"], r["method"], r["matched"] = c["genre"], "claude", f'{c["confidence"]}: {c["reason"]}'
    fields = ["id", "name", "category", "alternates", "genre", "method", "matched",
              "lat", "lng", "dist_m", "confidence", "address", "datasets", "licenses"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    methods = Counter(r["method"] for r in rows)
    target = len(rows) - methods["excluded"]
    resolved = target - methods["unresolved"]
    print(f"{len(rows)} 件（対象外 {methods['excluded']}）→ 対象 {target} 件")
    print(f"  店名ルール {methods['name']} / Overture {methods['overture']} / OSM {methods['osm']} / Claude {methods['claude']} / 判定不能 {methods['unresolved']}")
    print(f"  判定率 {resolved / target:.1%}")
    if checked:
        print(f"  OSM との照合: ルールで決まった {checked} 件中 {agreed} 件一致（{agreed / checked:.0%}）")
        with open(f"data/{key}/osm_disagreements.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(disagreements) + "\n")
    print(f"-> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
