# CLAUDE.md

駅圏（半径1km）の飲食店をジャンル別に数え、駅ごとの過不足を比べるための作業リポジトリ。
背景と決定事項の原本は `docs/HANDOFF.md`（2026-10-02 の claude.ai での相談）。

## 決定済み

- 半径 1km、隣駅と重なる店は両方に数える
- ジャンルはできるだけ細かく。最終体系は試作の結果を見て決める
- 試作は JR 亀戸駅だけ。精度を確認してから広げる
- 指標は特化係数（LQ）と乗降客1万人あたり店舗数。件数そのままでは比べない

## 進み具合（亀戸）

| 手順 | 状態 |
|---|---|
| 1. 駅の座標 | 済。35.697306, 139.826583（`scripts/common.py`）。Wikipedia/MapFan の値で、Overture の「JR 亀戸駅」POI と約10mで一致。S12 との照合はまだ |
| 2. Overture 抽出 | 済。`data/kameido/overture_food.csv`、937件 |
| 3. OpenPOI 取得と名寄せ | **次はここ。ローカルで実行する**（下記） |
| 4. ジャンル判定 | 未着手 |
| 5. 件数・構成比・LQ の表 | 未着手 |

## 手順3をローカルで実行する

クラウド環境（claude.ai、Claude Code on the web）からは `api.openpoiapi.com`、
国土数値情報（nlftp.mlit.go.jp）、DuckDB の拡張配布サイトに接続できない。
Overture の S3 は接続できた。

```
pip install -r requirements.txt
python scripts/fetch_openpoi.py kameido
```

`fetch_openpoi.py` は実 API で一度も動かしていない。偽の API（名前順に 200 件で切る、
同一地点に 50 件を含む 5,000 件）を相手にした試験では取り漏れゼロだった。最初の実行で確認すること:

- 初回に `data/openpoi_openapi.json` に API 定義を保存する。レスポンスの形
  （POI 配列のキー名、`id` の有無、`lat`/`lng` の名前）が `extract_items()` と
  `record_key()` の想定どおりか、これで確かめる
- `bbox` パラメータだけで `q` を省いて全件が返るか
- `openpoi_tiles.csv` に `saturated` の葉が残っていないか

### 名寄せ（手順3の後半）

実データを見てから書く。方針案:

1. OpenPOI からは `source = jff` だけを使う。`overture` 由来のものは手順2の
   Overture 抽出と同じ店なので使わない（OpenPOI の方がカテゴリが粗い）
2. JFF の中の重複をまとめる。許可1件＝1レコードなので、同じ店が業種違いで
   複数ある。住所が同じで名前が近いものを1店にする
3. JFF と Overture を突き合わせる。距離（JFF の `level` が 8 なら街区精度なので
   数十m のずれはありうる）と、正規化した店名（NFKC、空白除去、「亀戸店」
   「株式会社」などを落とす）の近さで判定する
4. 判定が微妙な組は別ファイルに出して目で確認する。名寄せの精度が誤差の主因になる
5. JFF は食品営業許可なので、飲食店以外（食肉販売、菓子製造など）も入っている。
   `licenses` の業種で飲食店営業・喫茶店営業に絞る

## 分かったこと（手順2）

- Overture の分類列は `taxonomy.primary` と `taxonomy.hierarchy` を使う。
  `hierarchy[1] = 'food_and_drink'` で飲食に絞れる。`categories.primary` と
  `basic_category` も残っている
- **細分類は思ったほど細かくない。** 937件のうち `japanese_restaurant` が289件。
  `ramen_restaurant` は8件だけで、実態よりかなり少ないはず。`categories.alternate`
  も `noodles_restaurant` 程度。店名判定は JFF だけでなく Overture の大半にも必要
- Overture の中にも同一店の重複がある（「ラリグラス…」と「Lali Guras…」など）
- confidence が 0.5 未満の店が111件。閉店済みが混じっている可能性がある
- 出典ライセンスは CSV の `licenses` 列に残してある

## ジャンルが分からない店の補完（検討中）

名前と座標で外部の店舗データベースを引けば技術的には補えるが、**主要な商用 API は
どれも規約で取得データの保存や二次利用を制限している**（2026-10-02 時点、検索結果の
要約による確認。規約本文での最終確認は利用者が行う）:

- ホットペッパーグルメ API（リクルートWEBサービス）：取得情報を自分のデータベースに
  複製保存すること、許諾された用途以外のためにまとめることを禁止。キャッシュは
  24時間以内に更新する。ジャンルも十数種類と粗い
- Yahoo! ローカルサーチ API（YOLP）：常に最新を取得すること、別途承認がない限り
  キャッシュを含めて意図的に保存しないこと
- Google Places：place_id 以外の保存は原則不可。Google のデータをもとに別のデータを作ることも禁止
- 食べログ：API なし。スクレイピングは規約で禁止

どれも「店ごとのジャンル表を作って集計する」使い方とぶつかる。使うなら提供元に
個別に許可を取る。保存してよいデータ（Overture、JFF、OSM の cuisine タグ）と、
店名からの判定（キーワード、チェーン辞書、Claude による判定）で埋めるのが基本方針。

## 守ること

- 推定と実測を混ぜない。判定率・照合率は必ず出す
- 出典表示のため、保存するレコードには `licenses` / `attributions` を残す
