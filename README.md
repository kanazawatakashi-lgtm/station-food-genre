# station-food-genre

駅の半径1km圏の飲食店をジャンル別に集計し、駅ごとの過不足（特化係数・乗降客1万人あたり店舗数）を比べる。
試作は JR 亀戸駅。経緯と進み具合は `CLAUDE.md` と `docs/HANDOFF.md` を参照。

```
pip install -r requirements.txt
python scripts/fetch_overture.py kameido          # Overture 元データ（周辺の全 POI）
python scripts/extract_overture_food.py kameido   # 半径内の飲食系に絞って CSV
python scripts/fetch_openpoi.py kameido           # OpenPOI を bbox 再帰分割で全件取得
python scripts/fetch_osm.py kameido               # OSM の飲食店（ローカルで実行）
python scripts/apply_osm.py kameido               # OSM と突き合わせ
python scripts/classify_genre.py kameido          # ジャンル判定 → genre.csv
python scripts/fetch_overture_area.py tokyo23     # 比較対象（23区）
PYTHONPATH=scripts python scripts/genre_table.py kameido tokyo23   # 件数・構成比・特化係数
```

亀戸の第1版の結果は `docs/kameido_results.md`。

スクリプトはリポジトリのルートで実行する。

## 出典

- Overture Maps Foundation, Places（release 2026-08-19.0）。レコードごとのライセンスは `licenses` 列
- OpenPOI API（https://openpoiapi.com/）。レコードごとの `licenses` / `attributions` を保持
- © OpenStreetMap contributors（ODbL）。`apply_osm.py` を使った場合
