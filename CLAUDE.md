# CLAUDE.md

駅圏（半径1km）の飲食店をジャンル別に数え、駅ごとの過不足を比べるための作業リポジトリ。
アプリの名前は「飲食出店ナビ・東京23区版」（ユーザー決定 2026-10-05。旧称「駅まわり出店ナビ」。サブタイトルは付けない）。
背景と決定事項の原本は `docs/HANDOFF.md`（2026-10-02 の claude.ai での相談）。

## 決定済み

- 半径 1km、隣駅と重なる店は両方に数える
- ジャンルはできるだけ細かく。最終体系は試作の結果を見て決める
- 試作は JR 亀戸駅だけ。精度を確認してから広げる
- 指標は特化係数（LQ）と乗降客1万人あたり店舗数。件数そのままでは比べない

**多くの駅に広げるときのやり方は `docs/method.md` にまとめた（23区全域を一度に判定して駅ごとに切り出す）。進み具合も同じファイルの末尾。**

23区全域の流れ: `fetch_overture_area.py tokyo23` → `classify_area.py tokyo23` → `classify_area_with_claude.py tokyo23 submit/collect`（ローカル）→ `classify_area.py tokyo23`（反映）。
`data/areas/` は大きいので git 管理外。ただし `tokyo23_unresolved_names.csv` と `tokyo23_claude.csv` はローカルとの受け渡しのため管理する。

## 進み具合（亀戸）

| 手順 | 状態 |
|---|---|
| 1. 駅の座標 | 済。35.697306, 139.826583（`scripts/common.py`）。Wikipedia/MapFan の値で、Overture の「JR 亀戸駅」POI と約10mで一致。S12 との照合はまだ |
| 2. Overture 抽出 | 済。`data/kameido/overture_food.csv`、937件 |
| 3. OpenPOI 取得と名寄せ | 済。JFF から 95 件追加（`scripts/merge_jff.py`、`data/kameido/jff_merge.csv`） |
| 4. ジャンル判定 | 済（判定率 86.2%、重複除去後 996 件） |
| 5. 件数・構成比・LQ の表 | 済。`docs/kameido_results.md`。LQ は Overture の店だけで計算 |

### パイプライン

```
python scripts/fetch_overture.py kameido            # Overture から周辺の全 POI
python scripts/extract_overture_food.py kameido     # 1km 圏の飲食 → overture_food.csv
python scripts/fetch_openpoi.py kameido             # OpenPOI（JFF を含む）。ローカルのみ
python scripts/merge_jff.py kameido                 # JFF と Overture の名寄せ → jff_merge.csv
python scripts/fetch_osm.py kameido                 # OSM（Overpass）。ローカルのみ
python scripts/apply_osm.py kameido                 # OSM と Overture を突き合わせ → osm_genre.csv
python scripts/classify_genre.py kameido            # ルール＋Overture＋OSM＋genre_claude.csv → genre.csv
python scripts/classify_with_claude.py kameido      # 判定不能の店を Claude API で判定（要 ANTHROPIC_API_KEY）
python scripts/classify_genre.py kameido            # 反映
python scripts/fetch_overture_area.py tokyo23       # 比較対象（23区 bbox）。data/areas/ は git 管理外
PYTHONPATH=scripts python scripts/genre_table.py kameido tokyo23   # 件数・構成比・LQ
```

### ジャンル判定の仕組み

1. 店名の正規表現（`scripts/genre_rules.py` の `NAME_RULES`、チェーン名を含む）。上から順に最初に当たったもの。
   料理名を先、「居酒屋」「ダイニング」などの業態語を後に置く
2. Overture の `taxonomy.primary` が細分類なら `OVERTURE_MAP` で対応付け。`japanese_restaurant` などの粗い分類は使わない
3. それでも決まらない店は OSM のタグ（`cuisine` など）を使う（`apply_osm.py`。80m 以内・店名一致の OSM 要素）。
   人が付けたタグなので Claude 判定より優先。ルールで決まった店とも照合し、一致率と不一致一覧
   （`osm_disagreements.txt`）を出す
4. それでも決まらない店は Claude が店名から判定（`data/<駅>/genre_claude.csv`）。確信度「高」「中」だけ採用、
   「低」と「不明」は判定不能のまま。外部サイトは調べない
5. 飲食店でないもの（ネットカフェ、コインランドリー、地名や住所だけのレコードなど）は `NOT_RESTAURANT*` で除外

**亀戸の `genre_claude.csv` は API ではなく、作業セッション中の Claude（API キーが無かった）が同じ基準で
手で判定したもの。** `classify_with_claude.py` は実 API で未実行。

### 分かったこと（手順4・5）

- 店名ルールと Overture 料理系細分類の両方がある168件で一致 88%。不一致の多くは Overture 側の誤り
- Overture の cafe / coffee_shop / bar には飲食店以外がかなり混じる（23区の cafe 系サンプルにエステ、陶芸教室など）
- Overture 内の同一店重複: `scripts/dedupe.py`（50m 以内・店名の中核一致／包含・同ジャンル）で亀戸9組、23区1.3%をまとめる。表記違い・距離の離れた重複は残る
- 居酒屋とバーの境界は分類方法でかなり動く。酒場系をまとめた LQ は 1.04 で、内訳の比較はまだ信頼できない
- LQ は駅側・比較側とも同じ方法（ルール＋Overture）で計算する。Claude 判定を駅側だけに入れると比べられない

### 23区の判定結果から駅を切り出す（2026-10-03、Claude 判定待ちで準備済み）

```
python scripts/classify_area.py tokyo23            # 23区を判定（tokyo23_claude.csv があれば反映）
python scripts/census.py tokyo23                   # センサス補正の重み → data/census/weights_tokyo23.csv
python scripts/station_table.py tokyo23            # 亀戸（common.py）
python scripts/s12_stations.py <S12.geojson> --inspect                 # S12 の列を確認（ローカルで取得）
python scripts/s12_stations.py <S12.geojson> --passengers <列名>       # → data/stations.csv
python scripts/station_table.py tokyo23 --stations data/stations.csv [--radius 500]  # 23区の全駅。半径は任意（既定 1000m）
```

- 駅の集計は亀戸専用のパイプライン（JFF・OSM 込み）ではなく、23区の判定結果（Overture のみ）から切り出す。
  駅と比較対象が同じ方法になり、LQ に方法の差が入らない
- `_w` の列はセンサス補正後。乗降客1万人あたり店舗数は補正後の件数で出す
- S12-25 は `data/s12/`（ユーザーが取得）。2024年の乗降客数は `S12_061`:
  `python scripts/s12_stations.py data/s12/S12-25_NumberOfPassengers.geojson --passengers S12_061`。
  別の版を使うときは `--inspect` で列を確認する
- Claude 判定は高・中を採用。「低」は大分類だけに使い中分類は不明（ユーザー決定 2026-10-04）。中分類不明の扱いは今後検討
- 円が重なる駅どうしで同じ店を重ねて数えてよい（ユーザー確認 2026-10-04）。乗降客1万人あたり店舗数は、
  そのため小さい駅ほど大きく出る（docs/method.md「23区の全駅」）
- 出力は半径ごとに `data/stations/tokyo23_r<半径>_*.csv`。円が23区の外にはみ出すか（near_edge）も半径ごとに判定

### 次にやること

- OSM（ローカル）: `fetch_osm.py` → `apply_osm.py` → `classify_genre.py` → `genre_table.py`。
  クラウド環境からは Overpass・Geofabrik・OSM API・BigQuery のどれにも届かず、AWS の osm-pds（planet の ORC、
  129GB）は読めるが stripe が全球にまたがっていて範囲を絞れないため断念した。スクリプトは偽データで試験済み、実データは未実行。
  実行後に確認すること: 判定不能 116 件のうち何件埋まったか、ルール判定との一致率、`osm_disagreements.txt` の中身。
  OSM は ODbL。OSM 由来のジャンルを含むデータを公開するときは出典表示と ODbL の条件に従う
- JFF の分かったこと: 亀戸 1km 圏で 313 件しかなく、全許可の一部（電子申請分と江東区の一覧）。Overture に無い飲食店を
  95 件足せたが、OSM にあって Overture に無い店はほとんど拾えなかった。店の網羅にはまだ穴がある
- Windows でスクリプトを動かすときの注意: ファイルを開くときは必ず encoding="utf-8" を付ける（付けないと cp932 になり、
  絵文字などで書き込みが止まる。fetch_openpoi.py で実際に起きた）。PowerShell では `PYTHONPATH=scripts` の書き方は使えない
- （済）手順3（ローカル）: OpenPOI 取得 → JFF の飲食店営業・喫茶店営業に絞る → Overture 内重複と JFF の名寄せ
- 名寄せ後に genre_table を作り直す。重複除去は比較対象（23区）側にも同じ方法で掛ける
- 乗降客1万人あたり店舗数: S12 の取得が必要（この環境からは nlftp.mlit.go.jp に届かない）
- 近隣駅（錦糸町・平井・大島など）との比較。駅の座標は S12 から取る

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

## サービス化（2026-10-04〜）

- 対象: 店舗物件の仲介会社（飲食店を出したい人向け）。駅ごとのジャンル構成（300/500/1000m）、複数駅の比較、
  乗降客数と飲食の特色を見せる。無料・有料で分ける
- **23区でうまくいけば他の地域にも広げる**（ユーザー方針 2026-10-04）。そのため全国で同じ形で取れるデータだけを使う。
  乗降客数は国土数値情報 S12 を使う（東京都統計年鑑など都内だけのデータは使わない）。線路・境界も国土数値情報 N02・N03（全国）に置き換える
- **LQ の基準は対象地域**（ユーザー決定 2026-10-04）。23区なら23区全体、他の地域ならその地域全体と比べる
- 地域を広げるときに直す所: `fetch_overture_area.py`（tokyo23 だけ）、`census.py` の WARD_EN（23区の名前）、
  `s12_stations.py` の範囲（23区の境界）、比較対象を「23区」から地域ごとに変えること
- ライセンス: `docs/licenses.md`。S12-25（乗降客数）は公共データ利用規約 第1.0版で商用可（ユーザー確認）。古い版は非商用なので使わない。
  線路・区の境界（Overture、ODbL）は国土数値情報 N02・N03 に置き換える
- **サービスに載せる注記（出典表示、データの時点、数字の限界）は `docs/disclosures.md` に作業のたびに足す**（ユーザーの指示。最後にまとめて載せる）
- **アプリ（飲食出店ナビ・東京23区版）**: `python scripts/build_app.py` → `docs/app.html`（データ埋め込みの1ファイル、約6.6MB）。
  駅カード（300/500/1000m）、比較（5駅）、ジャンルで探す（LQ で地図を塗る）、地点分析（50/100/300m の店一覧）。
  公開先 https://claude.ai/artifact/LWtYAoxwNX1yRruwZFWMDF 。人口は取り込み済み（国勢調査2020 250mメッシュ、`data/mesh/`、`mesh_stats.py` の --cols は README 参照）。働く人の数も取り込み済み（経済センサス2021 500mメッシュ、T001147022＝全産業の従業者数。001〜021 は事業所数で項目名が重複するので列コードで指定する）。住所検索も対応済み（位置参照情報 街区レベル `data/isj/`、build_app.py の load_addresses と app の geocode()）。地価は見送り（ユーザー判断 2026-10-05）
- 線路・区の境界は国土数値情報 N02・N03 に置き換え済み（`scripts/ksj.py`）。Overture の rail/divisions はもう使わない
- 駐車料金は無料で商用に使えるデータがない。地価も見送り（`docs/parking_research.md`）
- 駅カードの「駅の特徴」は `app_template.html` の describe() が規則で作る文章（街の性格＝人口密度と店の密度の23区比、住民＝年齢・単身・外国人の23区比、飲食＝まとまりの LQ と上位/下位ジャンル）。AI の生成文ではない
- 地図の駅名: 拡大の度合いに応じた乗降客数以上の駅だけ、乗降客数の多い順に重ならないように出す（全体表示は100万人以上。ユーザー指示 2026-10-05）
- 画面では LQ を「平均比」と呼び、「1.3倍」のように倍を付ける（ユーザー決定 2026-10-05）。見出しの「?」に定義と例だけを出す（注意書きは入れない）
- 「オフィス・商業系」の働く人＝経済センサス大分類 Ｇ情報通信＋Ｉ卸売小売＋Ｊ金融保険＋Ｋ不動産＋Ｌ専門サービス＋Ｒその他サービス（ユーザー決定 2026-10-05）。Ｎ生活関連・Ｐ医療福祉は住宅地にも多く、オフィス街との差が消えるので入れない
- 駅カードに「ジャンル別構成表」ボタン（全中分類の店数・構成比・23区の構成比・平均比）。比較タブはジャンル別構成表の比較だけ（構成比／店数／平均比の切り替え、ユーザー指示 2026-10-05）
- 印刷は見送り（ユーザー指示）。公開ページの枠の中では window.print() が動かないので、やるなら自分の PC で開く版を別に出す必要がある

## 2026-10-05 の見直し（一区切り）

- サイトとコードを見直して直した: 駅の特徴の飲食まとまり判定（補正前と補正後を混ぜていて平均比が約0.7倍に小さく出ていた）、
  端の駅の判定（区の境界の川・堀の穴を端とみなしていた）、乗降客数タブの選択表示、23区平均の大分類の棒（補正前にそろえた）、
  初期表示の駅を駅名で指定、位置参照情報はいちばん新しい年のファイルを使う、`fetch_overture_area.py` は区の境界を
  N03 から作る（以前は Overture divisions で上書きしていた）、不要になった半径 300m の表を削除
- データの定期更新の手順: `docs/update_guide.md`。ほかの地域で作る手順: `docs/new_area_guide.md`
- Overture は 2026-09-23.1 まで出ている（画面は 2026-08-19.0）。半年ごとに取り直す方針なので、次は 2027年春の見込み
- 同じ名前の別の駅（23区では浅草・早稲田）は、駅名に路線名を添えて区別する（ユーザー決定 2026-10-05。**今後も、ほかの地域でも同じ扱い**）。
  `s12_stations.py` が駅ごとの路線名（`lines` 列）を出し、`build_app.py` が同名の駅だけ「浅草（つくばエクスプレス）」の形にする。
  路線が3つ以上なら乗降客数の多い事業者の路線から2つと「など」。「○○駅」と書く所は「浅草駅（つくばエクスプレス）」

## 2026-10-05 の2回目の見直し

- 円の中に飲食店が0軒の半径（辰巳・舎人公園の250m、昭和島の250m・500m）はデータが作られず、その駅で半径を切り替えたときと、
  ジャンル別タブを250mにしたときに画面が止まっていた。`build_app.py` で0店の値を入れる
- 住む人が500人未満の円は「働く人 ÷ 住む人」が数万倍になり、数人の住民の割合で文章を作っていた。「—」と注意を出し、文章では触れない
- 平均比の「?」の例の「23区全体では居酒屋が7%」は実際の値と合わなかったので、「仮に10%とする」例にした
- 1人世帯の割合の分母を世帯総数から一般世帯数に直した（人口の集計に「一般世帯数」の列を追加）
- 各駅情報の「中分類まで分からない店は構成比の分母から除いている」は大分類の棒の下にあって誤解を招いたので、大分類・中分類それぞれの分母を書いた
- 地点分析の店の探し方を、範囲の広さに応じて調べる格子の数を決める形にした（無作為の200地点で全件の数え上げと一致）
- 確かめる手順: 全駅 × 全半径 × 全ジャンルで画面を作って、エラーと NaN・undefined の表示がないかを見る（`docs/update_guide.md` の 5.）
- 駅の特徴の文章を作り直した（ユーザー指示 2026-10-05）: 乗降客数の多さは書かない、昼と夜の需要を分けて書く（夜は居酒屋・バーの数の密度から）、
  少ないジャンルは書かない。空港など特殊な駅は `data/station_notes.csv` の手書きの説明（一般的な情報による）を出す。規則は disclosures.md の 7.
- 駅の特徴の文章は、画面で選んだ半径に関わらず250m圏の数字で作る（ユーザー決定 2026-10-05。`DESC_RADIUS`）
- 画面の見出し「駅の特徴」を「駅周辺の特徴」に変更（ユーザー指示 2026-10-05。特殊な駅は「駅周辺の特徴（一般的な情報による）」）
- 留意点・出典・ライセンス文は別ページ（`docs/notes.html`、文面は `scripts/notes_template.html`）にし、地図のページのフッターにリンクを置く（ユーザー指示 2026-10-06）。公開ページには `notes.html` として一緒に載せる

## 2026-10-08 の構成変更（ユーザー指示）

- タブ: 地点分析・各駅分析（旧「各駅情報」）・駅比較（旧「比較」）・ジャンル別・乗降客数。最初は地点分析。タブを上に置き、各ページの中に地図（PC で幅 2/5）
- 各駅分析の範囲は 0〜250m・250〜500m・500〜1000m のドーナツ型を複数選べる（`RINGS`・`ringStats()`）。平均比は画面側で補正後の中分類ごとの店数（`w`）から計算
  （`build_app.py` は `q` を出さず `w` を出す。23区の補正後の割合 `base.m` は小数6桁。集計表の LQ_w との差は 0.0003 以内）。店が0軒の中分類は 0倍
- 地点分析の指定は住所と座標だけ（駅名は外した）
- 駅の円の大きさを乗降客数に合わせるのは乗降客数タブだけ（`stR()`）
