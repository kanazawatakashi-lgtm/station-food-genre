"""OpenPOI の JFF（食品営業許可・届出）レコードを Overture の店と突き合わせる（名寄せ）。

  python scripts/merge_jff.py kameido

入力: data/<station>/openpoi_raw.jsonl（fetch_openpoi.py の出力）
      data/<station>/genre.csv（classify_genre.py の出力。Overture 側の店）
出力: data/<station>/jff_merge.csv  JFF 1レコード1行。status 列:
        matched   Overture の店と同じ店と判断（overture_id に対応先）
        added     Overture に無い飲食店として追加する
        dup       JFF 内の重複（同じ店の業種違い許可など。dup_of に代表レコード）
        nonfood   飲食店ではない許可（ホテル・学校・保育園・コンビニ・期間限定の催事など）。
                  Overture の店と一致しなかったものだけに掛ける
        uncertain 飲食店か分からない（カテゴリ unknown で店名からも飲食と言えない）。追加しない

JFF の判別: attributions に食品営業許可のデータ名を含むレコード。OpenPOI 側で Overture と統合済みの
レコード（source が overture でも JFF 由来を含むもの）も対象にする。

同じ店とみなす条件（どれか1つ）:
  - 700m 以内で、店名（地名・業態語を除く）が完全一致し4文字以上。どちらかの座標がずれている場合の救済
  - 30m 以内で、店名の一方が他方を含む（短い方2文字以上）か、共通部分が3文字以上（英字だけなら4文字以上）で
    短い方の半分以上
  - 80m 以内で店名の類似度 0.7 以上
  - 200m 以内で店名の類似度 0.9 以上
  店名は地名・建物名・業態語（居酒屋、バー、キッチンなど）を除いてから比べる。JFF の名前とカナ読み（ローマ字に直したものも）を Overture の名前と比べる。
"""
import csv
import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher

from classify_genre import classify
from common import haversine_m

JFF_MARK = ("食品", "営業許可")
NONFOOD_NAME = re.compile(
    r"ホテル|hotel|ホステル|hostel|旅館|学校|中学|小学|高校|大学|保育|幼稚園|こども園|キッズ|kids|学童|"
    r"デイサービス|介護|老人|ホーム|病院|クリニック|医院|スパ|温泉|サウナ|銭湯|"
    r"セブン|ファミリーマート|ローソン|ミニストップ|デイリーヤマザキ|まいばすけっと|コンビニ|"
    r"ドラッグ|薬局|薬ヒグチ|マツモトキヨシ|スーパー|イトーヨーカドー|ダイエー|"
    r"期間|催事|イベント|工業|製作所|シェアラウンジ|カプセル|シネマ|映画|フットサル|ジム|ボウリング"
)
NONFOOD_CATEGORY = {"grocery", "convenience_store"}
FAR_MATCH_M = 700  # 店名が完全一致（地名・業態語を除いて4文字以上）なら、この距離まで同じ店とみなす
FOOD_CATEGORY = {"restaurant", "bakery", "cafe", "bar_izakaya", "fast_food"}

# カタカナ→ローマ字（照合用の簡易版。拗音・促音・長音に対応）
_KANA = {
    "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o", "カ": "ka", "キ": "ki", "ク": "ku", "ケ": "ke", "コ": "ko",
    "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so", "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to",
    "ナ": "na", "ニ": "ni", "ヌ": "nu", "ネ": "ne", "ノ": "no", "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he", "ホ": "ho",
    "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo", "ヤ": "ya", "ユ": "yu", "ヨ": "yo",
    "ラ": "ra", "リ": "ri", "ル": "ru", "レ": "re", "ロ": "ro", "ワ": "wa", "ヲ": "o", "ン": "n",
    "ガ": "ga", "ギ": "gi", "グ": "gu", "ゲ": "ge", "ゴ": "go", "ザ": "za", "ジ": "ji", "ズ": "zu", "ゼ": "ze", "ゾ": "zo",
    "ダ": "da", "ヂ": "ji", "ヅ": "zu", "デ": "de", "ド": "do", "バ": "ba", "ビ": "bi", "ブ": "bu", "ベ": "be", "ボ": "bo",
    "パ": "pa", "ピ": "pi", "プ": "pu", "ペ": "pe", "ポ": "po", "ヴ": "vu",
    "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o",
}
_YOON = {"ャ": "ya", "ュ": "yu", "ョ": "yo"}


def kana_to_romaji(kana):
    k = unicodedata.normalize("NFKC", kana or "")
    out, i = [], 0
    while i < len(k):
        ch = k[i]
        nxt = k[i + 1] if i + 1 < len(k) else ""
        if ch == "ッ":
            if nxt in _KANA:
                out.append(_KANA[nxt][0])
            i += 1
            continue
        if ch == "ー":
            i += 1
            continue
        if ch in _KANA and nxt in _YOON:
            base = _KANA[ch]
            stem = {"shi": "sh", "chi": "ch", "ji": "j"}.get(base, base[:-1] + "y" if len(base) > 1 else base)
            out.append(stem + _YOON[nxt][1:] if stem.endswith(("sh", "ch", "j")) else stem + _YOON[nxt][1:])
            i += 2
            continue
        if ch in _KANA:
            out.append(_KANA[ch])
        i += 1
    return "".join(out)


def latin_only(name):
    n = unicodedata.normalize("NFKC", name or "").lower()
    return re.sub(r"[^a-z]", "", n)


# 照合の前に店名から外す語（地名・建物名・支店表記と、業態を表すだけの一般語）。
# これらが共通しているだけで同じ店と判断しないようにする
_LOC = (r"亀戸|錦糸町|西大島|大島|江東橋|天神前|天神|カメイドクロック|kameidoclock|アトレ|atre|parco|パルコ|"
        r"楽天地ビル|楽天地|北口|南口|東口|西口|駅前|kinshicho|kameido|本店|支店|分店|新館|地下")
_GENERIC = (r"居酒屋|酒場|スナック|snack|バー|bar|ラウンジ|lounge|パブ|pub|キッチン|kitchen|カフェ|cafe|café|"
            r"ダイニング|dining|食堂|レストラン|restaurant|和食|洋風|大衆|株式会社|有限会社|shop")
_PUNCT = re.compile(r"[\s・\-‐－()（）【】「」『』&＆'’.,、。!！■□◆★☆]")


def match_core(name):
    n = unicodedata.normalize("NFKC", name or "").lower()
    n = _PUNCT.sub("", n)
    n = re.sub(_LOC, "", n)
    n = re.sub(_GENERIC, "", n)
    return re.sub(r"店$", "", n)


def core_score(a, b):
    ca, cb = match_core(a), match_core(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    short, long_ = sorted((ca, cb), key=len)
    if len(short) >= 3 and short in long_:
        return 0.9
    return SequenceMatcher(None, ca, cb).ratio()


def is_jff(r):
    return any(any(m in a for m in JFF_MARK) for a in r.get("attributions", []))


def longest_common(a, b):
    m = SequenceMatcher(None, a, b).find_longest_match(0, len(a), 0, len(b))
    return m.size


def match_score(ov_name, jff_name, jff_kana, dist):
    """同じ店とみなせるなら (理由) を返す。だめなら None。"""
    s = max(core_score(ov_name, jff_name), core_score(ov_name, jff_kana) if jff_kana else 0)
    if s == 1.0 and len(match_core(ov_name)) >= 4:
        return "店名完全一致"
    if dist <= 200 and s >= 0.9:
        return f"類似度{s:.2f}"
    if dist <= 80 and s >= 0.7:
        return f"類似度{s:.2f}"
    if dist <= 30:
        a, b = match_core(ov_name), match_core(jff_name)
        if a and b:
            short, long_ = sorted((a, b), key=len)
            if len(short) >= 2 and short in long_:
                return "近接・包含"
            lc = longest_common(a, b)
            need = 4 if re.fullmatch(r"[a-z0-9]+", short) else 3
            if lc >= need and lc >= len(short) / 2:
                return "近接・共通部分"
        ro, rj = latin_only(match_core(ov_name)), kana_to_romaji(jff_kana)
        if len(ro) >= 4 and rj and (ro in rj or rj in ro or SequenceMatcher(None, ro, rj).ratio() >= 0.8):
            return "近接・ローマ字一致"
    return None


def main(key):
    raw = [json.loads(l) for l in open(f"data/{key}/openpoi_raw.jsonl", encoding="utf-8")]
    jff = [r for r in raw if is_jff(r) and r.get("lat") not in ("", None)]
    ov = [r for r in csv.DictReader(open(f"data/{key}/genre.csv", encoding="utf-8")) if r["method"] != "excluded"]

    out = []
    for i, r in enumerate(jff):
        lat, lng = float(r["lat"]), float(r["lng"])
        rec = {"jff_idx": i, "name": r["name"], "name_kana": r.get("name_kana", ""), "address": r.get("address", ""),
               "category": r.get("category", ""), "lat": lat, "lng": lng, "dist_m": r.get("_dist_m", ""),
               "status": "", "overture_id": "", "overture_name": "", "match_dist_m": "", "match_reason": "",
               "dup_of": "", "name_genre": "", "licenses": "|".join(r.get("licenses", [])),
               "attributions": "|".join(r.get("attributions", []))}
        g, m, _ = classify(re.sub(r"株式会社|有限会社", "", r["name"]), "")
        rec["name_genre"] = g if m == "name" else ""
        best = None
        for o in ov:
            d = haversine_m(lat, lng, float(o["lat"]), float(o["lng"]))
            if d > FAR_MATCH_M:
                continue
            reason = match_score(o["name"], r["name"], r.get("name_kana", ""), d)
            if reason and (best is None or d < best[0]):
                best = (d, o, reason)
        if best:
            d, o, reason = best
            rec.update(status="matched", overture_id=o["id"], overture_name=o["name"], match_dist_m=round(d), match_reason=reason)
        elif NONFOOD_NAME.search(unicodedata.normalize("NFKC", r["name"]).lower()) \
                or r.get("category") in NONFOOD_CATEGORY or g == "対象外":
            rec["status"] = "nonfood"
        elif r.get("category") in FOOD_CATEGORY or rec["name_genre"]:
            rec["status"] = "added"
        else:
            rec["status"] = "uncertain"
        out.append(rec)

    # JFF 内の重複（追加分どうし）: 30m 以内で店名の中核が一致・包含
    added = [x for x in out if x["status"] == "added"]
    for a_i, a in enumerate(added):
        for b in added[:a_i]:
            if b["status"] != "added":
                continue
            ca, cb = match_core(a["name"]), match_core(b["name"])
            short, long_ = sorted((ca, cb), key=len)
            if short and len(short) >= 2 and short in long_ and haversine_m(a["lat"], a["lng"], b["lat"], b["lng"]) <= 30:
                a["status"], a["dup_of"] = "dup", b["name"]
                break

    path = f"data/{key}/jff_merge.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    from collections import Counter
    c = Counter(x["status"] for x in out)
    print(f"JFF {len(out)} 件: 一致 {c['matched']} / 追加 {c['added']} / JFF内重複 {c['dup']} / "
          f"飲食店以外 {c['nonfood']} / 不確か {c['uncertain']} -> {path}")


if __name__ == "__main__":
    main(sys.argv[1])
