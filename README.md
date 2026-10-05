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
python scripts/classify_area.py tokyo23     # 23区を判定
python scripts/census.py tokyo23            # 経済センサスで補正する重み
python scripts/station_table.py tokyo23 [--stations data/stations.csv]   # 駅ごとの表
python scripts/ksj.py tokyo23               # 区の境界を国土数値情報 N03 で作り直す
python scripts/mesh_stats.py data/mesh/tblT001142Q5339.txt data/mesh/tblT001196Q5339.txt --cols "人口=人口（総数）,世帯数=世帯総数,0〜14歳=０～１４歳人口　総数,15〜19歳=１５～１９歳人口　総数,20〜34歳=２０～２４歳人口　総数+２５～２９歳人口　総数+３０～３４歳人口　総数,35〜49歳=３５～３９歳人口　総数+４０～４４歳人口　総数+４５～４９歳人口　総数,50〜64歳=５０～５４歳人口　総数+５５～５９歳人口　総数+６０～６４歳人口　総数,65歳以上=６５歳以上人口　総数,1人世帯=１人世帯数　一般世帯数,外国人=外国人人口　総数"   # 駅ごとの人口
python scripts/mesh_stats.py data/mesh/tblT001147H5339.txt --cols "従業者=T001147022,オフィス・商業系従業者=T001147030+T001147032+T001147033+T001147034+T001147035+T001147041,飲食サービス従業者=T001147036,事業所=T001147001" --out data/stations/tokyo23_workers.csv   # 駅ごとの従業者数
python scripts/build_app.py                 # 出店エリア分析アプリ → docs/app.html
```

亀戸の第1版の結果は `docs/kameido_results.md`。

スクリプトはリポジトリのルートで実行する。

## 出典

- Overture Maps Foundation, Places（release 2026-08-19.0）。レコードごとのライセンスは `licenses` 列
- OpenPOI API（https://openpoiapi.com/）。レコードごとの `licenses` / `attributions` を保持
- © OpenStreetMap contributors（ODbL）。`apply_osm.py` を使った場合
- 総務省・経済産業省「令和3年経済センサス‐活動調査」（e-Stat）。`data/census/`
- 「国土数値情報（駅別乗降客数データ）」（国土交通省）S12-25 を加工して作成。`data/s12/`、`data/stations.csv`
- 総務省統計局「令和2年国勢調査 地域メッシュ統計」（e-Stat）を加工して作成。`data/mesh/`、`data/stations/tokyo23_population.csv`
- 総務省・経済産業省「令和3年経済センサス‐活動調査 地域メッシュ統計」（e-Stat）を加工して作成。`data/mesh/`、`data/stations/tokyo23_workers.csv`
