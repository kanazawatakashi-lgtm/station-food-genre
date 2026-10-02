"""駅定義と距離計算など、各スクリプト共通の部品。"""
import math

# 駅の座標。S12（国土数値情報 駅別乗降客数）で確認でき次第そちらに置き換える。
STATIONS = {
    # JR 亀戸駅。Wikipedia/MapFan の値。Overture の「JR 亀戸駅」POI と約10mで一致。
    "kameido": {"name": "亀戸", "lat": 35.697306, "lng": 139.826583},
}

RADIUS_M = 1000
EARTH_R = 6371000


def haversine_m(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def circle_bbox(lat, lng, radius_m, margin=1.05):
    """半径 radius_m の円を含む bbox (minLng, minLat, maxLng, maxLat)。"""
    dlat = radius_m * margin / 111320
    dlng = radius_m * margin / (111320 * math.cos(math.radians(lat)))
    return (lng - dlng, lat - dlat, lng + dlng, lat + dlat)
