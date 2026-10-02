"""OSM の飲食店を Overture のレコードと突き合わせ、OSM のタグからジャンルを付ける。

  python scripts/apply_osm.py kameido

入力: data/<station>/overture_food.csv、data/<station>/osm_food.json（fetch_osm.py の出力）
出力: data/<station>/osm_genre.csv   列: id(Overture), name, osm_id, osm_name, dist_m, name_score, osm_genre, osm_tags
      classify_genre.py がこれを読み、ルールで決まらなかった店に使う（Claude 判定より優先）

突き合わせの条件: 距離 80m 以内で、店名が一致・包含、または類似度 0.6 以上。
OSM 側は name / name:ja / name:en / alt_name / brand / brand:ja を候補にする。
1つの Overture レコードに複数の OSM が当たったら、店名の近さ→距離の順で1つ選ぶ。

OSM は ODbL。このファイルから作るデータを公開するときは出典表示（© OpenStreetMap contributors）と
ODbL の条件に従う。
"""
import csv
import json
import sys
from difflib import SequenceMatcher

from common import haversine_m
from dedupe import core_name

MAX_DIST_M = 80
MIN_SIM = 0.6
NAME_KEYS = ["name", "name:ja", "name:en", "alt_name", "brand", "brand:ja", "official_name"]

# OSM の cuisine（; 区切りの先頭から順に見る）→ ジャンル。japanese や regional のような粗い値は載せない
CUISINE_MAP = {
    "ramen": "ラーメン", "noodle": "ラーメン", "chinese_noodle": "ラーメン", "tsukemen": "ラーメン",
    "soba": "そば・うどん", "udon": "そば・うどん",
    "sushi": "すし", "kaiten_sushi": "すし",
    "tempura": "天ぷら・天丼", "tendon": "天ぷら・天丼",
    "kushikatsu": "串かつ・串揚げ", "kushiage": "串かつ・串揚げ",
    "tonkatsu": "とんかつ・揚げ物", "karaage": "とんかつ・揚げ物", "fried_chicken": "とんかつ・揚げ物",
    "unagi": "うなぎ", "eel": "うなぎ",
    "yakitori": "焼き鳥・やきとん", "yakiton": "焼き鳥・やきとん", "motsuyaki": "焼き鳥・やきとん",
    "yakiniku": "焼肉・ホルモン", "horumon": "焼肉・ホルモン", "korean_barbecue": "焼肉・ホルモン", "barbecue": "焼肉・ホルモン",
    "shabu-shabu": "鍋・しゃぶしゃぶ", "shabu_shabu": "鍋・しゃぶしゃぶ", "sukiyaki": "鍋・しゃぶしゃぶ",
    "hot_pot": "鍋・しゃぶしゃぶ", "nabe": "鍋・しゃぶしゃぶ", "chanko": "鍋・しゃぶしゃぶ", "motsunabe": "鍋・しゃぶしゃぶ",
    "okonomiyaki": "お好み焼き・もんじゃ・たこ焼き", "monjayaki": "お好み焼き・もんじゃ・たこ焼き",
    "takoyaki": "お好み焼き・もんじゃ・たこ焼き", "yakisoba": "お好み焼き・もんじゃ・たこ焼き",
    "gyudon": "牛丼・丼", "donburi": "牛丼・丼", "beef_bowl": "牛丼・丼",
    "okinawan": "沖縄・郷土料理",
    "seafood": "海鮮・魚料理", "fish": "海鮮・魚料理",
    "teishoku": "定食・食堂", "onigiri": "定食・食堂",
    "kaiseki": "和食・割烹", "kappo": "和食・割烹", "fugu": "和食・割烹",
    "chinese": "中華", "dumpling": "中華", "gyoza": "中華", "dim_sum": "中華", "szechuan": "中華", "sichuan": "中華",
    "cantonese": "中華", "taiwanese": "中華", "shanghai": "中華",
    "korean": "韓国料理",
    "thai": "タイ料理", "vietnamese": "ベトナム料理",
    "indian": "インド・ネパール料理", "nepalese": "インド・ネパール料理", "nepali": "インド・ネパール料理",
    "sri_lankan": "その他アジア料理", "filipino": "その他アジア料理", "indonesian": "その他アジア料理",
    "malaysian": "その他アジア料理", "singaporean": "その他アジア料理", "burmese": "その他アジア料理", "asian": "その他アジア料理",
    "italian": "イタリアン", "pizza": "イタリアン", "pasta": "イタリアン",
    "french": "フレンチ・ビストロ",
    "spanish": "その他各国料理", "mexican": "その他各国料理", "brazilian": "その他各国料理", "german": "その他各国料理",
    "turkish": "その他各国料理", "kebab": "その他各国料理", "russian": "その他各国料理", "greek": "その他各国料理",
    "steak_house": "ステーキ・ハンバーグ", "hamburg_steak": "ステーキ・ハンバーグ",
    "burger": "ハンバーガー・ファストフード", "sandwich": "パン",
    "curry": "カレー", "japanese_curry": "カレー",
    "western": "洋食", "yoshoku": "洋食",
    "coffee_shop": "カフェ・喫茶", "tea": "カフェ・喫茶",
    "cake": "スイーツ・和菓子", "dessert": "スイーツ・和菓子", "ice_cream": "スイーツ・和菓子", "donut": "スイーツ・和菓子",
    "crepe": "スイーツ・和菓子", "wagashi": "スイーツ・和菓子", "bubble_tea": "スイーツ・和菓子",
    "izakaya": "居酒屋",
}
# cuisine が無いか粗いときに使う amenity / shop
AMENITY_MAP = {"cafe": "カフェ・喫茶", "ice_cream": "スイーツ・和菓子", "bar": "バー"}
SHOP_MAP = {"bakery": "パン", "confectionery": "スイーツ・和菓子", "pastry": "スイーツ・和菓子", "deli": "惣菜・弁当"}


def osm_genre(tags):
    for c in (tags.get("cuisine") or "").lower().replace(" ", "").split(";"):
        if c in CUISINE_MAP:
            return CUISINE_MAP[c]
    if tags.get("amenity") in AMENITY_MAP:
        return AMENITY_MAP[tags["amenity"]]
    if tags.get("shop") in SHOP_MAP:
        return SHOP_MAP[tags["shop"]]
    return ""


def name_score(a, b):
    ca, cb = core_name(a), core_name(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    short, long_ = sorted((ca, cb), key=len)
    if len(short) >= 3 and short in long_:
        return 0.9
    return SequenceMatcher(None, ca, cb).ratio()


def osm_points(key):
    data = json.load(open(f"data/{key}/osm_food.json", encoding="utf-8"))
    out = []
    for e in data.get("elements", []):
        tags = e.get("tags", {})
        lat = e.get("lat", (e.get("center") or {}).get("lat"))
        lng = e.get("lon", (e.get("center") or {}).get("lon"))
        names = [tags[k] for k in NAME_KEYS if tags.get(k)]
        if lat is None or not names:
            continue
        out.append({"osm_id": f'{e["type"]}/{e["id"]}', "lat": lat, "lng": lng, "names": names,
                    "genre": osm_genre(tags), "tags": tags})
    return out


def main(key):
    rows = list(csv.DictReader(open(f"data/{key}/overture_food.csv", encoding="utf-8")))
    osm = osm_points(key)
    out = []
    for r in rows:
        lat, lng = float(r["lat"]), float(r["lng"])
        best = None
        for o in osm:
            d = haversine_m(lat, lng, o["lat"], o["lng"])
            if d > MAX_DIST_M:
                continue
            s = max(name_score(r["name"], n) for n in o["names"])
            if s < MIN_SIM:
                continue
            cand = (s, -d, o)
            if best is None or cand[:2] > best[:2]:
                best = cand
        if best:
            s, nd, o = best
            keep = {k: v for k, v in o["tags"].items() if k in ("amenity", "shop", "cuisine", "name")}
            out.append({"id": r["id"], "name": r["name"], "osm_id": o["osm_id"], "osm_name": o["names"][0],
                        "dist_m": round(-nd), "name_score": round(s, 2), "osm_genre": o["genre"],
                        "osm_tags": json.dumps(keep, ensure_ascii=False)})
    path = f"data/{key}/osm_genre.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "name", "osm_id", "osm_name", "dist_m", "name_score", "osm_genre", "osm_tags"])
        w.writeheader()
        w.writerows(out)
    with_genre = sum(1 for o in out if o["osm_genre"])
    print(f"OSM {len(osm)} 件（名前あり）。Overture {len(rows)} 件のうち {len(out)} 件が OSM と一致、"
          f"うちジャンルが取れたもの {with_genre} 件 -> {path}")


if __name__ == "__main__":
    main(sys.argv[1])
