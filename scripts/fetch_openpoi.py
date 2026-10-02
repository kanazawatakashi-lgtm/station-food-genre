"""OpenPOI API から駅の半径圏の POI を全件取得する（bbox 再帰4分割）。

  python scripts/fetch_openpoi.py kameido

/v1/search は 1 回 200 件までで、ページ送りがない。200 件に達した bbox は
4 分割して取り直し、全ての葉が 200 件未満になるまで続ける。
カテゴリでは絞らない（約55%が unknown のため）。飲食かどうかは後段で判定する。

出力:
  data/<station>/openpoi_raw.jsonl   半径内の全レコード（licenses/attributions を含む API の返り値そのまま）
  data/<station>/openpoi_tiles.csv   取得した葉 bbox と件数（取り漏れ確認用）
  data/openpoi_openapi.json          初回だけ保存する API 定義

標準ライブラリだけで動く。この作業はクラウド環境からは api.openpoiapi.com に
接続できないため、ローカルで実行する前提で書いている（未実行・未検証）。
"""
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from common import RADIUS_M, STATIONS, circle_bbox, haversine_m

BASE_URL = "https://api.openpoiapi.com"
LIMIT = 200
MIN_SPAN_DEG = 0.00005   # 約5m。これより細かく割っても 200 件なら打ち切って警告
REQ_INTERVAL = 0.1       # 10 req/s。API 全体の上限 200 req/s を大きく下回る
UA = "station-food-genre/0.1 (research; contact via GitHub)"


def get_json(path, params=None, retries=5):
    url = BASE_URL + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                wait = 2 ** i
                print(f"  HTTP {e.code}, {wait}s 後に再試行", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError:
            time.sleep(2 ** i)
    raise RuntimeError(f"failed: {url}")


def extract_items(resp):
    """レスポンスから POI 配列を取り出す。形は API 定義で要確認なので、よくある形を順に試す。"""
    if isinstance(resp, list):
        return resp
    for k in ("results", "items", "data", "pois", "features"):
        v = resp.get(k)
        if isinstance(v, list):
            return v
    raise ValueError(f"POI 配列が見つからない。キー: {list(resp)}")


def record_key(p):
    if p.get("id") is not None:
        return str(p["id"])
    return f'{p.get("source")}|{p.get("name")}|{p.get("lat")}|{p.get("lng")}|{p.get("address")}'


def fetch_bbox(bbox, depth, out, tiles, stats):
    minx, miny, maxx, maxy = bbox
    resp = get_json("/v1/search", {"bbox": f"{minx:.6f},{miny:.6f},{maxx:.6f},{maxy:.6f}", "limit": LIMIT})
    time.sleep(REQ_INTERVAL)
    stats["requests"] += 1
    items = extract_items(resp)
    if len(items) >= LIMIT:
        if (maxx - minx) < MIN_SPAN_DEG and (maxy - miny) < MIN_SPAN_DEG:
            print(f"  警告: 約5m四方で {len(items)} 件。取り漏れの可能性 {bbox}", file=sys.stderr)
            tiles.append((*bbox, depth, len(items), "saturated"))
        else:
            mx, my = (minx + maxx) / 2, (miny + maxy) / 2
            for sub in ((minx, miny, mx, my), (mx, miny, maxx, my), (minx, my, mx, maxy), (mx, my, maxx, maxy)):
                fetch_bbox(sub, depth + 1, out, tiles, stats)
            return
    else:
        tiles.append((*bbox, depth, len(items), "ok"))
    for p in items:
        out.setdefault(record_key(p), p)  # 境界上の重複を除く


def main(key):
    st = STATIONS[key]
    os.makedirs(f"data/{key}", exist_ok=True)

    spec_path = "data/openpoi_openapi.json"
    if not os.path.exists(spec_path):
        with open(spec_path, "w", encoding="utf-8") as f:
            json.dump(get_json("/openapi.json"), f, ensure_ascii=False, indent=1)
        print(f"API 定義を保存: {spec_path}")

    out, tiles, stats = {}, [], {"requests": 0}
    fetch_bbox(circle_bbox(st["lat"], st["lng"], RADIUS_M), 0, out, tiles, stats)

    first = next(iter(out.values()), None)
    if first is not None and ("lat" not in first or "lng" not in first):
        raise ValueError(f"lat/lng が無い。キー: {list(first)}")

    kept = []
    for p in out.values():
        d = haversine_m(st["lat"], st["lng"], float(p["lat"]), float(p["lng"]))
        if d <= RADIUS_M:
            p["_dist_m"] = round(d)
            kept.append(p)

    with open(f"data/{key}/openpoi_raw.jsonl", "w", encoding="utf-8") as f:
        for p in kept:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with open(f"data/{key}/openpoi_tiles.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["minLng", "minLat", "maxLng", "maxLat", "depth", "count", "status"])
        w.writerows(tiles)

    by_src = {}
    for p in kept:
        by_src[p.get("source")] = by_src.get(p.get("source"), 0) + 1
    print(f"requests={stats['requests']} tiles={len(tiles)} bbox内={len(out)} 半径内={len(kept)} source別={by_src}")
    sat = sum(1 for t in tiles if t[-1] == "saturated")
    if sat:
        print(f"警告: 上限に達したままの葉が {sat} 個ある（openpoi_tiles.csv を確認）")


if __name__ == "__main__":
    main(sys.argv[1])
