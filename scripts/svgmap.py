"""地図の座標変換と、国土数値情報の路線を SVG パスにする処理（build_app.py が使う）。

経度・緯度を SVG 座標に直す（外部の地図タイルは使わない）。
"""
import math

LAT0 = 35.68
KX = math.cos(math.radians(LAT0))
SCALE = 2600  # 経度1度 → SVG 座標
MIN_LNG, MAX_LAT = 139.555, 35.825


def xy(lng, lat):
    return round((lng - MIN_LNG) * KX * SCALE, 1), round((MAX_LAT - lat) * SCALE, 1)


def ring_path(coords):
    pts = [xy(x, y) for x, y in coords]
    return "M" + "L".join(f"{x},{y}" for x, y in pts) + "Z"


def line_path(coords):
    pts = [xy(x, y) for x, y in coords]
    return "M" + "L".join(f"{x},{y}" for x, y in pts)


def _length_m(line):
    return sum(math.hypot((x2 - x1) * 111320 * KX, (y2 - y1) * 110950)
               for (x1, y1), (x2, y2) in zip(line.coords, list(line.coords)[1:]))


def load_rails(area_geom):
    """国土数値情報 N02 の路線を JR・私鉄・地下鉄に分けて SVG パスにする。23区の外は少し余白を残して切る。
    N02 は路線ごとに線が入っている（共用区間も路線ごとにある）ので、途切れを補う処理は要らない。"""
    from shapely.ops import linemerge
    from ksj import load_rails as ksj_rails
    clip = area_geom.buffer(0.01)
    rails = []
    for r in ksj_rails(clip.bounds):
        g = linemerge(r["lines"]).intersection(clip)
        d, anchors = [], []
        for line in ([g] if g.geom_type == "LineString" else [x for x in getattr(g, "geoms", []) if x.geom_type == "LineString"]):
            if line.is_empty:
                continue
            d.append(line_path(line.simplify(0.00015).coords))
            # 路線名を置く位置: 3km 以上の線に、おおむね 5km おきに
            km = _length_m(line) / 1000
            if km >= 3:
                n = max(1, round(km / 5))
                for j in range(n):
                    p = line.interpolate((j + 0.5) / n, normalized=True)
                    anchors.append(xy(p.x, p.y))
        if d:
            rails.append({"k": r["kind"], "n": r["name"], "d": "".join(d), "a": anchors})
    order = {"subway": 0, "private": 1, "jr": 2}
    rails.sort(key=lambda r: order[r["k"]])  # 地下鉄を下に
    return rails
