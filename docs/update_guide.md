# データ更新の手順（飲食出店ナビ・東京23区版）

定期的に新しくするデータ、取得先、取り込みの手順、push の手順をまとめる（2026-10-05 作成）。
コマンドはリポジトリのルートで実行する（`python scripts/○○.py` の形なら、scripts の中の部品は自動で読み込まれる。
`python -c` で部品を直接使うときだけ `PYTHONPATH=scripts` を付ける）。

## 1. 更新するデータの一覧

| # | データ | 画面での使い道 | 公表の頻度 | 次の更新の目安 | 取得する人 |
|---|---|---|---|---|---|
| A | Overture Maps Places（店舗） | 店の数・ジャンル・地点分析の店の一覧 | 毎月（新しいリリース） | **半年ごと**に取り直す（disclosures.md の方針）。次は 2027年春 | Claude（この作業環境から取れる） |
| B | 国土数値情報 S12 駅別乗降客数 | 乗降客数・駅の位置 | 年1回 | 新しい版（S12-26）が出たら | ユーザー（ダウンロードして push） |
| C | 国土数値情報 N02 鉄道 | 地図の線路・路線名 | 年1回 | 新線の開業・路線名の変更があったら（毎年でなくてよい） | ユーザー |
| D | 国土数値情報 N03 行政区域（東京都） | 23区の境界・店の区の割り当て | 年1回（1月1日時点） | 区の境界が変わったときだけ（23区はほぼ変わらない） | ユーザー |
| E | 位置参照情報 街区レベル（東京都） | 地点分析の住所検索 | 年1回 | 年1回 | ユーザー |
| F | 国勢調査 地域メッシュ統計（250m） | 住んでいる人・年齢構成 | 5年ごと | 2025年調査のメッシュ統計の公表後（2027年ごろの見込み） | ユーザー |
| G | 経済センサス‐活動調査（市区町村別の事業所数、地域メッシュ統計 500m） | 平均比の補正・働いている人 | 5年ごと | 2026年調査の公表後（2027〜2028年ごろの見込み） | ユーザー |
| H | ライセンス文・Foursquare の NOTICE | 別ページ（留意点・出典）のライセンス文 | 不定期 | A を取り直すたびに確認 | ユーザー（Foursquare のページを開いて確認） |

「次の更新の目安」の F・G の時期は見込み。e-Stat の公表予定で確かめる。

国土交通省（nlftp.mlit.go.jp）と e-Stat はこの作業環境から開けないので、B〜H はユーザーがダウンロードして push する。
Overture（A）は Amazon S3 の公開バケットから取るので、この作業環境から取れる。

## 2. push の手順（ユーザーがダウンロードしたファイルを入れるとき）

PowerShell での例。`<リポジトリ>` は手元の station-food-genre のフォルダ。

```powershell
cd <リポジトリ>
git pull                                   # 先に最新にする
# ダウンロードした zip を展開し、決まった場所にコピーする（場所は 3. の各項目）
Copy-Item "$HOME\Downloads\S12-26_GML\S12-26_NumberOfPassengers.geojson" data\s12\
git add data\s12
git commit -m "S12-26（駅別乗降客数）を追加"
git push
```

- 1つのファイルが 100MB を超えると GitHub に push できない。超える場合は、必要な都道府県・範囲だけのファイルを選ぶ（N02 の線路は全国で約 14MB、位置参照情報の東京都は約 29MB なので問題ない）
- push したら Claude に「○○を push した」と伝える。取り込み・画面の作り直し・公開は Claude が行う
- API キーはチャットにも git にも入れない（店名の AI 判定は手元の PowerShell で環境変数に入れて実行する。4. を参照）

## 3. データごとの取得先と取り込み方

### A. Overture Maps Places（店舗）— Claude が実行

1. 最新のリリースを確かめる
   ```
   PYTHONPATH=scripts python3 -c "from fetch_overture import s3fs; import pyarrow.fs as f; print(sorted(i.base_name for i in s3fs().get_file_info(f.FileSelector('overturemaps-us-west-2/release/')))[-3:])"
   ```
   （2026-10-05 時点で 2026-09-23.1 まで出ている。今の画面は 2026-08-19.0）
2. `scripts/fetch_overture.py` の `RELEASE` を新しいリリースに書き換える
3. 取得と判定
   ```
   python scripts/fetch_overture_area.py tokyo23   # 23区の飲食 POI（数分）。区の境界は N03 から作る
   python scripts/classify_area.py tokyo23         # 店名ルールで判定し、判定できない店名の一覧を作る
   ```
4. 新しく増えた「判定できない店名」を AI（Claude）で判定する — **ユーザーが手元で実行**（4. を参照）。
   すでに判定済みの店名（`data/areas/tokyo23_claude.csv`）は送らないので、送るのは増えた分だけ
5. 判定結果を push してもらったら、反映して集計し直す
   ```
   python scripts/classify_area.py tokyo23
   python scripts/census.py tokyo23
   python scripts/station_table.py tokyo23 --stations data/stations.csv --radius 250 --quiet
   python scripts/station_table.py tokyo23 --stations data/stations.csv --radius 500 --quiet
   python scripts/station_table.py tokyo23 --stations data/stations.csv --radius 1000 --quiet
   python scripts/build_app.py
   ```
6. 文面を直す（6. のチェックリスト）。特に Overture の版・加工日・Foursquare の NOTICE の末尾の「Notice of changes」の日付と版

`data/areas/` の大きなファイル（tokyo23_food.parquet など）は git に入れていない。新しい作業環境では 3. の手順で作り直す。

### B. S12 駅別乗降客数 — ユーザーがダウンロード

- 取得先: 国土数値情報ダウンロードサイト https://nlftp.mlit.go.jp/ksj/ →「交通」→「駅別乗降客数」→ 最新の版（全国）
  （今使っている S12-25 の案内: https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-S12-2024.html）
- **データページの利用条件が「公共データ利用規約（第1.0版）」になっているか確かめる**（古い版は非商用。新しい版も念のため確認）
- 置き場所: zip の中の `S12-XX_NumberOfPassengers.geojson` を `data/s12/` に
- 取り込み（Claude）:
  ```
  python scripts/s12_stations.py data/s12/S12-XX_NumberOfPassengers.geojson --inspect   # 最新年の乗降客数の列を探す
  python scripts/s12_stations.py data/s12/S12-XX_NumberOfPassengers.geojson --passengers S12_0NN
  ```
  列の番号は版ごとに変わる（S12-25 では 2024年が S12_061。1年4列ずつ増える）。そのあと A の 5. の
  `station_table.py`（3つの半径）と `build_app.py`、人口・従業者の集計（F・G の取り込みコマンド）もやり直す（駅の位置や数が変わるため）
- 文面: 出典・disclosures.md の「S12-25（2024年の値）」を新しい版と年に

### C. N02 鉄道 — ユーザーがダウンロード

- 取得先: https://nlftp.mlit.go.jp/ksj/ →「交通」→「鉄道」→ 最新の版（全国）
- 置き場所: `N02-XX_RailroadSection.geojson` を `data/ksj/` に
- 取り込み（Claude）: `scripts/ksj.py` の `N02 = ...` のファイル名を書き換えて `python scripts/build_app.py`。
  新しい路線・事業者があれば `ksj.py` の `OPERATOR_SHORT`・`LINE_ALIAS`（路線名の短縮・通称）を足す

### D. N03 行政区域（東京都）— ユーザーがダウンロード

- 取得先: https://nlftp.mlit.go.jp/ksj/ →「政策区域」→「行政区域」→ 最新の年 → 東京都
- 置き場所: `N03-YYYYMMDD_13.geojson` を `data/ksj/` に
- 取り込み（Claude）: `scripts/ksj.py` の `N03 = ...` を書き換えて `python scripts/ksj.py tokyo23`（店の区を付け直す）、
  そのあと A の 5. を `classify_area.py` から

### E. 位置参照情報 街区レベル（東京都）— ユーザーがダウンロード

- 取得先: https://nlftp.mlit.go.jp/isj/ → 最新の年 →「街区レベル」→ 東京都
- 置き場所: zip の中の CSV を `data/isj/13_YYYY.csv` の名前で（YYYY は年。`build_app.py` はいちばん新しい年のファイルを使う）
- 取り込み（Claude）: `python scripts/build_app.py`
- 文面: 出典・disclosures.md の「街区レベル位置参照情報（2025年）」の年

### F. 国勢調査 地域メッシュ統計 — ユーザーがダウンロード

- 取得先: e-Stat https://www.e-stat.go.jp/ →「地図」（統計GIS）→「統計データダウンロード」→「国勢調査」→ 新しい年 →
  「5次メッシュ（250mメッシュ）」→「人口及び世帯」と「５歳階級別人口」（どちらも JGD2011）→ 1次メッシュ **5339**
- 置き場所: zip の中の `.txt` を `data/mesh/` に
- 取り込み（Claude）: 表の番号・項目名が変わるので、まず `python scripts/mesh_stats.py data/mesh/<新しいファイル>.txt --inspect`
  で項目名を確かめ、README の人口のコマンドの `--cols` を合わせて実行。そのあと `python scripts/build_app.py`
- 文面: 出典・disclosures.md の「令和2年国勢調査」「2020年」

### G. 経済センサス‐活動調査 — ユーザーがダウンロード

2つのファイルを使う。

1. **市区町村別・産業小分類別の事業所数**（平均比の補正に使う。今は「令和3年 第9-1A表」`data/census/b1_009_1a.xlsx`）
   - 取得先: e-Stat →「経済センサス‐活動調査」→ 新しい年 → 確報の「事業所に関する集計」の、
     産業小分類別・市区町村別の事業所数の表（Excel）
   - 置き場所: `data/census/` に。`scripts/census.py` の `CENSUS_XLSX` と、表の行・列の読み取り位置（`load_census`）を新しい表に合わせる
   - 取り込み（Claude）: `python scripts/census.py tokyo23` → A の 5. の `station_table.py` から
2. **地域メッシュ統計（500m）の従業者数**（働いている人）
   - 取得先: F と同じ e-Stat の画面で「経済センサス‐活動調査」→ 新しい年 → 4次メッシュ（500m）→ 1次メッシュ 5339
   - 取り込み（Claude）: `--inspect` で列コードを確かめ、README の従業者のコマンドの `--cols`（産業大分類 G・I・J・K・L・R、
     M 宿泊・飲食サービス）を合わせて実行
- 文面: 出典・disclosures.md・留意点の「令和3年」「2021年」と、補正の説明の数字（渋谷区のバー・居酒屋の例）

### H. ライセンス文・NOTICE — ユーザーが確認

- Foursquare OS Places Notice: https://opensource.foursquare.com/places-notice-txt/ を開き、`docs/license_texts/Foursquare-NOTICE.txt`
  の上の部分（「Notice of changes」より前）と同じか確かめる。違えば貼ってもらい差し替える
- Overture のライセンス（https://docs.overturemaps.org/attribution/）で Places のライセンスが変わっていないか確かめる
- 国土数値情報・e-Stat・位置参照情報の利用条件が変わっていないか、新しい版のページで確かめる（`docs/licenses.md`）

## 4. 店名の AI 判定（ユーザーが手元で実行）

Overture を取り直すと、判定できない店名が新しく増える。Claude の Message Batches API で判定する。

```powershell
cd <リポジトリ>
git pull
$env:ANTHROPIC_API_KEY = "<自分の API キー>"     # チャットや git には書かない
python scripts\classify_area_with_claude.py tokyo23 --dry-run   # 送る店名の数とリクエストの数を確認
python scripts\classify_area_with_claude.py tokyo23 submit      # 送信（結果はたいてい1時間以内）
python scripts\classify_area_with_claude.py tokyo23 collect     # 結果を取り込む。「まだ処理中」なら時間をおいて再実行
git add data\areas\tokyo23_claude.csv
git commit -m "新しい店名の AI 判定結果を追加"
git push
```

2026-10 の初回は 32,196 種類の店名を判定した。半年ごとの更新で増えるのは、その一部（新しい店名だけ）。

## 5. 公開

`python scripts/build_app.py` で `docs/app.html` を作り直したら、Claude が画面を確認して（全駅 × 全半径 × 全ジャンルで画面を作り、
エラーや「NaN」「undefined」の表示がないか、店が0軒の円・住む人がほとんどいない円で表示が崩れないかを確かめる）
公開ページ（https://claude.ai/artifact/LWtYAoxwNX1yRruwZFWMDF）を同じ URL で更新し（`docs/notes.html` と `docs/about.html` も `notes.html`・`about.html` として一緒に載せる）、コミットして push する。

## 6. 更新したら直す文面（チェックリスト）

- [ ] 別ページの出典（`scripts/notes_template.html` の「出典」）: データの版・年、加工日
- [ ] 別ページの留意点（`scripts/notes_template.html`）: 判定率（`classify_area.py` の出力と、`build_app.py` 後の中分類・大分類の割合）、補正の例の数字
- [ ] `docs/license_texts/Foursquare-NOTICE.txt` の末尾「Notice of changes」の日付と Overture のリリース
- [ ] `docs/disclosures.md` の 1.（出典）と 2.（データの時点）
- [ ] `docs/licenses.md`（利用条件を確かめた日）
- [ ] `CLAUDE.md`（何をいつ更新したか）
