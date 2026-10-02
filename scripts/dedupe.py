"""Overture 内の同一店の重複レコードをまとめる（保守的な簡易版）。

同じ店とみなす条件（すべて満たすとき）:
  - 距離 50m 以内
  - 店名の中核部分（NFKC・空白記号除去・末尾の「〇〇店」「本店」などを除いたもの）が一致するか、
    一方が他方を含む（短い方が3文字以上）
  - ジャンルが同じか、一方が判定不能

表記の違う重複（「Lali Guras」と「ラリグラス」など）はまとめられない。
JFF との名寄せはこれとは別に、実データを見てから作る（CLAUDE.md 参照）。
"""
import math
import re
import unicodedata
from collections import defaultdict

MAX_DIST_M = 50
CELL_DEG = 0.0005  # 約50m
_SUFFIX = re.compile(r"(亀戸|錦糸町|西大島|大島)?(駅前|駅|北口|南口|東口|西口)?(本店|支店|分店|店)$")
_STRIP = re.compile(r"[\s・\-‐－()（）【】「」&＆'’.,、。!！]")


def core_name(name):
    n = unicodedata.normalize("NFKC", name or "").lower()
    n = _STRIP.sub("", n)
    stripped = _SUFFIX.sub("", n)
    return stripped if len(stripped) >= 2 else n


def _dist_m(a, b):
    dy = (a[0] - b[0]) * 111320
    dx = (a[1] - b[1]) * 111320 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def _names_match(a, b):
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 3 and short in long_


def cluster(records, unresolved_genre):
    """records: [(lat, lng, name, genre)]。返り値: 各レコードの代表インデックスのリスト。"""
    parent = list(range(len(records)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cores = [core_name(r[2]) for r in records]
    grid = defaultdict(list)
    for i, (lat, lng, _, _) in enumerate(records):
        grid[(int(lat / CELL_DEG), int(lng / CELL_DEG))].append(i)
    for (cy, cx), members in grid.items():
        neighbors = [j for dy in (-1, 0, 1) for dx in (-1, 0, 1) for j in grid.get((cy + dy, cx + dx), [])]
        for i in members:
            for j in neighbors:
                if j <= i or not cores[i] or not cores[j]:
                    continue
                gi, gj = records[i][3], records[j][3]
                if gi != gj and unresolved_genre not in (gi, gj):
                    continue
                if not _names_match(cores[i], cores[j]):
                    continue
                if _dist_m(records[i], records[j]) <= MAX_DIST_M:
                    parent[find(i)] = find(j)
    return [find(i) for i in range(len(records))]


def dedupe_genres(records, unresolved_genre):
    """重複をまとめた後の (代表インデックス, ジャンル) の一覧。ジャンルは判定できた方を採る。"""
    roots = cluster(records, unresolved_genre)
    best = {}
    for i, root in enumerate(roots):
        g = records[i][3]
        if root not in best or best[root] == unresolved_genre:
            best[root] = g
    return best, roots
