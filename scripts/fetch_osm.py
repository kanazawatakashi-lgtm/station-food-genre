"""OpenStreetMap から駅の半径圏の飲食店（料理ジャンルのタグ付き）を Overpass API で取る。

  python scripts/fetch_osm.py kameido

出力: data/<station>/osm_food.json（Overpass の返り値そのまま。ODbL、© OpenStreetMap contributors）

クラウド環境からは Overpass / Geofabrik / OSM API のどれにも接続できないため、ローカルで実行する。
標準ライブラリだけで動く。実 API では未実行。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from common import RADIUS_M, STATIONS

ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
AMENITIES = "restaurant|cafe|fast_food|bar|pub|food_court|ice_cream|biergarten"
UA = "station-food-genre/0.1 (research)"


def query(lat, lng, radius):
    # 半径を少し広げる（Overture と座標がずれている店を拾うため）。way は中心点を返す
    r = int(radius * 1.1)
    return f"""[out:json][timeout:120];
(
  nwr["amenity"~"^({AMENITIES})$"](around:{r},{lat},{lng});
  nwr["shop"~"^(bakery|confectionery|pastry|deli)$"](around:{r},{lat},{lng});
);
out center tags;"""


def main(key):
    st = STATIONS[key]
    q = query(st["lat"], st["lng"], RADIUS_M)
    data = urllib.parse.urlencode({"data": q}).encode()
    for url in ENDPOINTS:
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=180) as r:
                    resp = json.load(r)
                os.makedirs(f"data/{key}", exist_ok=True)
                out = f"data/{key}/osm_food.json"
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(resp, f, ensure_ascii=False, indent=0)
                els = resp.get("elements", [])
                with_cuisine = sum(1 for e in els if "cuisine" in e.get("tags", {}))
                print(f"{len(els)} 件（cuisine タグあり {with_cuisine}）-> {out}")
                return
            except (urllib.error.HTTPError, urllib.error.URLError) as e:
                print(f"  {url} 失敗: {e}。再試行", file=sys.stderr)
                time.sleep(5 * (attempt + 1))
    raise SystemExit("Overpass に接続できなかった")


if __name__ == "__main__":
    main(sys.argv[1])
