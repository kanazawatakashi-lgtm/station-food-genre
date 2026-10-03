"""ジャンル判定のルール（暫定）。

上から順に照合し、最初に当たったものを採る。料理名のように具体的なものを先に、
「居酒屋」「ダイニング」のような業態語を後に置く（「海鮮居酒屋」は海鮮、「沖縄居酒屋」は沖縄料理）。
店名は NFKC 正規化・小文字化してから照合する。

ジャンル体系は試作用。亀戸の結果を見て統合・分割する。
"""

# (ジャンル, 正規表現) のリスト。チェーン名もここに入れる（店名に含まれていれば当たる）。
NAME_RULES = [
    # 「ダイニングバー」は料理の種類にかかわらずバー（ユーザー指定、2026-10-03）。料理名のルールより先に置く
    ("バー", r"ダイニング\s*[&＆・]?\s*バー|dining\s*[&＆・]?\s*bar|diningbar"),
    # 麺
    ("ラーメン", r"大勝軒|つじ田|舎鈴|どさん子|壱角家|来々軒|tenkaippin|博多風龍|ippudo|ichiran|afuri|ラーメン|らーめん|らあめん|拉麺|中華そば|中華ソバ|中華蕎麦|つけ麺|担々麺|担担麺|タンメン|麺屋|麺や|家系|二郎|ramen|天下一品|花月嵐|一蘭|一風堂|ちゃんぽん|リンガーハット|ごってり"),
    ("お好み焼き・もんじゃ・たこ焼き", r"gindako|okonomiyaki|monja|やきそば|焼きそば|焼そば"),
    ("そば・うどん", r"長寿庵|松月庵|砂場|更科|更級|尾張屋|大むら|やぶ|藪|増田屋|巴屋|小松庵|吉祥庵|辰巳庵|宝盛庵|小進庵|松竹庵|田毎|杵屋|さぬきや|そじ坊|角萬|箱根そば|小諸そば|そば|蕎麦|soba|うどん|饂飩|udon|丸亀製麺|はなまる|香川一福|満留賀|いろり庵|富士そば|ゆで太郎"),
    # 和食の専門店
    ("すし", r"sushiro|kura sushi|hama sushi|uobei|sushizanmai|寿司|寿し|鮨|すし|sushi|スシロー"),
    ("天ぷら・天丼", r"天一|ハゲ天|tempura|天ぷら|天麩羅|天婦羅|天丼|てんや|tenya"),
    ("串かつ・串揚げ", r"串家物語|串かつ|串カツ|串揚|串あげ|でんがな"),
    ("とんかつ・揚げ物", r"松のや|松乃家|和幸|とんき|とん八|牛かつ|gyukatsu|勝牛|katsugyu|からやま|がブリチキン|まい泉|katsuya|とんかつ|トンカツ|豚カツ|かつや|さぼてん|からあげ|唐揚|から揚"),
    ("うなぎ", r"うな鐵|宮川本廛|unagi|うなぎ|鰻"),
    ("焼き鳥・やきとん", r"とりや\s*八兵衛|焼鳥|焼き鳥|やきとり|やき鳥|鳥貴族|torikizoku|やきとん|もつ焼|串焼"),
    ("焼肉・ホルモン", r"jojoen|gyu-kaku|gyukaku|gyushige|金剛園|牛たん|牛タン|yakiniku|すたみな太郎|stamina taro|焼肉|やきにく|ホルモン|牛角|牛繁|焼肉きんぐ|叙々苑|ジンギスカン|gyusei"),
    ("鍋・しゃぶしゃぶ", r"今半|赤から|shabu|しゃぶ|すき焼|すきやき|ちゃんこ|もつ鍋|鍋|温野菜"),
    ("お好み焼き・もんじゃ・たこ焼き", r"お好み焼|もんじゃ|たこ焼|粉もん|銀だこ"),
    ("牛丼・丼", r"sukiya|yoshinoya|すためし|gyudon|牛丼|すき家|松屋|matsuya|吉野家|なか卯|すた丼|豚丼|帯広|丼"),
    ("沖縄・郷土料理", r"沖縄|沖繩|おきなわ|琉|泡盛|那覇|奄美"),
    ("海鮮・魚料理", r"海鮮|海産|鮮魚|(?<!金)魚|まぐろ|マグロ|浜焼|磯|牡蠣|かき小屋|さかな|炉端"),
    # 中華・アジア
    ("中華", r"鼎泰豊|din tai fung|麻辣湯|麻辣烫|gyoza|餃子|gyoza no ohsho|中華|chinese|チャイニーズ|中国料理|飯店|餃子|ぎょうざ|焼売|シュウマイ|麻婆|四川|上海|台湾|香港|点心|日高屋|バーミヤン|王将|焼烤|菜館|酒家"),
    ("韓国料理", r"韓国|korean|サムギョプサル|タッカルビ|ビビンバ|チーズタッカ"),
    ("タイ料理", r"thai|タイ料理|タイ食堂|タイ居酒屋|イサーン|プアンタイ|チャーンタイ|チャンタイ"),
    ("ベトナム料理", r"ベトナム|vietnam|フォー(?!ト)|バインミー"),
    ("インド・ネパール料理", r"インド|ネパール|india|nepal|ナマステ|タンドール"),
    ("その他アジア料理", r"アジアン|asian|ミャンマー|myanmar|フィリピン|filipin|pinoy|インドネシア|bali|シンガポール|マレーシア"),
    ("定食・食堂", r"ootoya|おぼんdeごはん|定食|食堂|大戸屋|やよい軒|ごはん処|おむすび|おにぎり|家庭料理"),
    ("和食・割烹", r"升本|割烹|料亭|懐石|会席|和食|washoku|ふぐ|河豚|御膳|小料理|和処|和旬"),
    # 洋
    ("イタリアン", r"イタリア|italian|trattoria|トラットリア|ピッツァ|ピザ|pizza|パスタ|pasta|サイゼリヤ|オステリア|osteria|リストランテ"),
    ("フレンチ・ビストロ", r"フレンチ|french|ビストロ|bistro|ブラッスリー|brasserie"),
    ("その他各国料理", r"スペイン|パエリア|メキシ|mexic|ブラジル|ドイツ|トルコ|ケバブ|ロシア|ギリシャ|アフリカ"),
    ("ステーキ・ハンバーグ", r"ステーキ|steak|ハンバーグ|ペッパーランチ"),
    ("ハンバーガー・ファストフード", r"サブウェイ|subway|wendy|ゼッテリア|クア・アイナ|kua aina|taco bell|tgi friday|mos burger|lotteria|ファーストキッチン|first kitchen|マクドナルド|mcdonald|モスバーガー|ロッテリア|バーガー|burger|ケンタッキー|kfc|フレッシュネス"),
    ("カレー", r"カレー|curry|coco壱|ココイチ|cocoichibanya|coco ichibanya"),
    ("ファミリーレストラン", r"denny|jonathan|gusto|saizeriya|royal host|bamiyan|デニーズ|ガスト|ジョナサン|ロイヤルホスト|ココス|ジョイフル"),
    ("洋食", r"キッチン南海|soup stock|スープストック|洋食|グリル|オムライス|シズラー|レストラン"),
    ("惣菜・弁当", r"キッチンオリジン|オリジン弁当|ほっともっと|ほっかほっか亭"),
    # 喫茶・甘味・パン
    ("パン", r"(?<!ャ)パン(?!ダ)|ベーカリー|bakery|bread|ブーランジェリー"),
    ("スイーツ・和菓子", r"とらや|両口屋是清|文明堂|口福堂|日本橋屋長兵衛|ずんだ茶寮|minamoto kitchoan|ladurée|pierre herm|スイーツ|ケーキ|洋菓子|和菓子|甘味|パフェ|クレープ|ドーナツ|アイス|ジェラート|タピオカ|大福|団子|だんご|あんみつ|船橋屋|三原堂|餡舎"),
    ("カフェ・喫茶", r"doutor|tully|excelsior|komeda|veloce|st\.? marc|renoir|blue bottle|カフェ|cafe|café|珈琲|コーヒー|coffee|喫茶|スターバックス|starbucks|ドトール|タリーズ|ベローチェ|プロント|pronto|コメダ|エクセルシオール|サンマルク|ルノアール"),
    # 酒
    ("バー", r"(?<![a-z])hub(?![a-z])|英国風パブ|british pub|irish pub|アイリッシュ|ビアバー|beer bar"),
    ("スナック・パブ", r"スナック|snack|ラウンジ|lounge|パブ(?!リ)"),
    ("居酒屋", r"はなの舞|うおや一丁|や台ずし|笑笑|千年の宴|山内農場|月の雫|金の蔵|東方見聞録|さくら水産|つぼ八|村さ来|てけてけ|鳥良|築地日本海|しるべ蔵|塚田農場|九州熱中屋|権八|izakaya|居酒屋|いざかや|酒場|立呑|立ち呑|立飲|呑み|呑飲|酒処|大衆|和民|養老乃瀧|白木屋|魚民|八剣伝|屋台屋|庄や|土間土間|晩杯屋|かんぱい家|目利きの銀次|磯丸|鳥メロ|串屋横丁|ちょいのみ|くいもの"),
    ("バー", r"ダイニング|dining|バル(?!ーン)|(?<![a-z])bar(?![a-z])|バー(?!ガ|ベ|ミ|ジ)|ダーツ|darts|ワイン|wine|whisk|ウイスキー"),
]

# 店名で決まらなかったときに使う Overture の taxonomy.primary の対応。
# japanese_restaurant / restaurant / asian_restaurant / diner などの粗い分類は載せない（判定不能扱い）。
OVERTURE_MAP = {
    "ramen_restaurant": "ラーメン",
    "sushi_restaurant": "すし",
    "chinese_restaurant": "中華",
    "taiwanese_restaurant": "中華",
    "korean_restaurant": "韓国料理",
    "thai_restaurant": "タイ料理",
    "vietnamese_restaurant": "ベトナム料理",
    "indian_restaurant": "インド・ネパール料理",
    "filipino_restaurant": "その他アジア料理",
    "singaporean_restaurant": "その他アジア料理",
    "italian_restaurant": "イタリアン",
    "pizza_restaurant": "イタリアン",
    "french_restaurant": "フレンチ・ビストロ",
    "spanish_restaurant": "その他各国料理",
    "mexican_restaurant": "その他各国料理",
    "fish_and_chips_restaurant": "その他各国料理",
    "soul_food": "その他各国料理",
    "steakhouse": "ステーキ・ハンバーグ",
    "burger_restaurant": "ハンバーガー・ファストフード",
    "seafood_restaurant": "海鮮・魚料理",
    "barbecue_restaurant": "焼肉・ホルモン",  # 日本では焼肉店がほとんど。焼き鳥が混じる可能性あり
    "chicken_restaurant": "とんかつ・揚げ物",
    "cafe": "カフェ・喫茶",
    "coffee_shop": "カフェ・喫茶",
    "tea_room": "カフェ・喫茶",
    "bubble_tea_shop": "スイーツ・和菓子",
    "smoothie_juice_bar": "カフェ・喫茶",
    "milk_bar": "カフェ・喫茶",
    "bakery": "パン",
    "sandwich_shop": "パン",
    "dessert_shop": "スイーツ・和菓子",
    "donut_shop": "スイーツ・和菓子",
    "ice_cream_shop": "スイーツ・和菓子",
    "chocolatier": "スイーツ・和菓子",
    "sake_bar": "居酒屋",
    # bar / pub / lounge は載せない。Overture の bar には居酒屋チェーン（はなの舞・うおや一丁など）が多く混じるため、
    # 店名ルールで決まらなければ Claude の店名判定に回す（2026-10-03）
    "cocktail_bar": "バー",
    "wine_bar": "バー",
    "whiskey_bar": "バー",
    "beer_bar": "バー",
    "champagne_bar": "バー",
    "sports_bar": "バー",
    "hookah_bar": "バー",
    "delicatessen": "惣菜・弁当",
    "salad_bar": "洋食",
    "dim_sum_restaurant": "中華",
    "cantonese_restaurant": "中華",
    "szechuan_restaurant": "中華",
    "bagel_shop": "パン",
    "pancake_house": "カフェ・喫茶",
    "gastropub": "バー",
    "brewery": "バー",
    "beer_garden": "バー",
    "tapas_bar": "その他各国料理",
    "gay_bar": "バー",
    "german_restaurant": "その他各国料理",
    "hawaiian_restaurant": "その他各国料理",
    "european_restaurant": "その他各国料理",
    "american_restaurant": "洋食",
    "bistro": "フレンチ・ビストロ",
    "soup_restaurant": "洋食",
}

# 飲食店ではないもの（物販・ネットカフェなど）。集計から外す。
NOT_RESTAURANT = {"candy_store", "internet_cafe"}
NOT_RESTAURANT_NAME = (
    r"自遊空間|まちおか|成城石井|smoking lounge"
    # Overture の cafe/bar/thai_restaurant などに紛れ込んでいる飲食店以外
    r"|閉店|エステ|陶芸|ランドリー|コピーショップ|マッサージ|整体|快活club|ネットカフェ|ネットルーム|漫画喫茶|まんが喫茶|マンガ喫茶"
    r"|ビッグエコー|カラオケ館|まねきねこ|ジャンカラ|カラオケの鉄人|elektro-shop"
    r"|ビル$|^[^\d]{0,4}\d+(-\d+)+$"  # 建物名だけ・住所だけのレコード
)
