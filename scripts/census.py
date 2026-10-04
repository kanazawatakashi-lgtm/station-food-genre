"""経済センサス2021 で区ごとの店数を補正する重み（センサス補正）。

  python scripts/census.py tokyo23

入力: data/census/b1_009_1a.xlsx（第9-1A表 産業小分類別事業所数、市区町村）
      data/areas/<area>_genre.parquet（classify_area.py の出力）
出力: data/census/weights_<area>.csv  区 × センサス小分類ごとの重み

Overture の件数は区によってセンサスの 1.2〜2.6 倍、ジャンルによっても 0.5〜2.5 倍とずれる
（docs/method.md「経済センサスとの比較」）。店1件を「重み」件として数え直し、区×小分類の合計を
センサスの事業所数に合わせる。区単位の補正なので、駅単位の偏りまでは消せない。

重みの決め方:
- 中分類が分かる店: 重み = センサスの件数 ÷ Overture の推定件数（区 × 小分類）。
  推定件数は、中分類不明の店が分かっている店と同じ割合で各小分類に散らばっているとみなして、
  分かっている店の件数を（飲食店全体 ÷ 中分類が分かる店）倍したもの
- 中分類不明の店: その区の飲食店全体の重み（センサス 761〜769 の合計 ÷ Overture の飲食店全体）
- パン・スイーツ・惣菜（センサスでは小売業などに入る）: 比べる相手がないので、その区の飲食店全体の重みを使う
"""
import csv
import sys
from collections import Counter, defaultdict

import pyarrow.parquet as pq

from genre_groups import UNKNOWN, group_of

CENSUS_XLSX = "data/census/b1_009_1a.xlsx"

CODES = {
    "761": "食堂・レストラン",
    "762": "専門料理店",
    "763": "そば・うどん店",
    "764": "すし店",
    "765": "酒場・ビヤホール",
    "766": "バー・キャバレー・ナイトクラブ",
    "767": "喫茶店",
    "769": "その他の飲食店",
}

# 中分類 → センサス小分類。ここに無い和食・中華・アジア・洋食の中分類は 762 専門料理店
MID_TO_CODE = {
    "そば・うどん": "763",
    "すし": "764",
    "居酒屋": "765",
    "焼き鳥・やきとん": "765",
    "バー": "766",
    "スナック・パブ": "766",
    "カフェ・喫茶": "767",
    "定食・丼": "761",
    "洋食": "761",
    "ファミレス": "761",
    "ハンバーガー・ファストフード": "769",
    "お好み焼き・もんじゃ": "769",
}
RETAIL_MIDS = {"パン", "スイーツ・和菓子", "惣菜・弁当"}
SPECIALTY_MAJORS = {"和食", "中華・アジア", "洋食"}

WARD_EN = {
    "千代田区": "Chiyoda", "中央区": "Chuo", "港区": "Minato", "新宿区": "Shinjuku", "文京区": "Bunkyo",
    "台東区": "Taito", "墨田区": "Sumida", "江東区": "Koto", "品川区": "Shinagawa", "目黒区": "Meguro",
    "大田区": "Ota", "世田谷区": "Setagaya", "渋谷区": "Shibuya", "中野区": "Nakano", "杉並区": "Suginami",
    "豊島区": "Toshima", "北区": "Kita", "荒川区": "Arakawa", "板橋区": "Itabashi", "練馬区": "Nerima",
    "足立区": "Adachi", "葛飾区": "Katsushika", "江戸川区": "Edogawa",
}

ALL = "all"      # 区の飲食店全体の重み（中分類不明・パンなどに使う）
RETAIL = "retail"


def census_code(major, mid):
    """(大分類, 中分類) → センサス小分類コード。不明は UNKNOWN、パンなどは RETAIL。"""
    if mid in MID_TO_CODE:
        return MID_TO_CODE[mid]
    if mid in RETAIL_MIDS:
        return RETAIL
    if major in SPECIALTY_MAJORS and mid != UNKNOWN:
        return "762"
    return UNKNOWN


def load_census():
    """{区の英語名: {小分類コード: 事業所数}}（23区）。"""
    import openpyxl
    ws = openpyxl.load_workbook(CENSUS_XLSX, read_only=True).worksheets[0]
    out = {}
    cols = {}
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 5:
            cols = {str(h)[:3]: j for j, h in enumerate(row) if h and str(h)[:3] in CODES and str(h)[3] == "_"}
        if i >= 9 and row[1] and str(row[1]).startswith("131"):
            name = str(row[1]).split("_", 1)[1]
            if name in WARD_EN:
                out[WARD_EN[name]] = {k: (int(row[j]) if isinstance(row[j], (int, float)) else 0) for k, j in cols.items()}
    if len(out) != 23 or len(cols) != len(CODES):
        raise RuntimeError(f"センサス表の読み取りに失敗（区 {len(out)}、小分類 {len(cols)}）")
    return out


def representatives(area):
    rows = pq.read_table(f"data/areas/{area}_genre.parquet").to_pylist()
    return [r for i, r in enumerate(rows) if r["cluster"] == i]


def compute_weights(area):
    """{(区, コード): 重み} と集計表（出力用の行）を返す。コードは CODES のキーと ALL。"""
    census = load_census()
    counts = defaultdict(Counter)
    for r in representatives(area):
        counts[r["ward"]][census_code(*group_of(r["genre"], r["category"], r.get("low_genre", "")))] += 1

    weights, table = {}, []
    for ward, cen in sorted(census.items()):
        c = counts[ward]
        known = sum(c[k] for k in CODES)
        food = known + c[UNKNOWN]
        scale = food / known if known else 0
        cen_total = sum(cen.values())
        weights[(ward, ALL)] = cen_total / food if food else 0
        table.append([ward, ALL, "飲食店全体（中分類不明・パンなどに使う）", cen_total, food, "", round(weights[(ward, ALL)], 4)])
        for k, label in CODES.items():
            est = c[k] * scale
            # Overture に1件も無い小分類は重みを決められないので全体の重みで代用
            weights[(ward, k)] = cen[k] / est if est else weights[(ward, ALL)]
            table.append([ward, k, label, cen[k], c[k], round(est, 1), round(weights[(ward, k)], 4)])
    return weights, table


def weight_of(weights, ward, major, mid):
    code = census_code(major, mid)
    if code in (UNKNOWN, RETAIL):
        code = ALL
    return weights.get((ward, code), 1.0)


def load_weights(area):
    """census.py で書き出した重みを読む。無ければ None。"""
    import os
    path = f"data/census/weights_{area}.csv"
    if not os.path.exists(path):
        return None
    return {(r["ward"], r["code"]): float(r["weight"]) for r in csv.DictReader(open(path, encoding="utf-8"))}


def main(area):
    weights, table = compute_weights(area)
    out = f"data/census/weights_{area}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ward", "code", "census_category", "census_count", "overture_count", "overture_estimated", "weight"])
        w.writerows(table)
    alls = sorted(((weights[(wd, ALL)], wd) for wd, k in weights if k == ALL))
    print(f"飲食店全体の重み: 最小 {alls[0][1]} {alls[0][0]:.2f} 〜 最大 {alls[-1][1]} {alls[-1][0]:.2f}")
    for k, label in CODES.items():
        vals = [weights[(wd, k)] for wd, kk in weights if kk == k]
        print(f"  {k} {label}: {min(vals):.2f}〜{max(vals):.2f}")
    print(f"-> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
