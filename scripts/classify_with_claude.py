"""ルールで決まらなかった店のジャンルを、Claude API に店名から判定させる。

  python scripts/classify_with_claude.py kameido            # 実行（ANTHROPIC_API_KEY が必要）
  python scripts/classify_with_claude.py kameido --dry-run  # 送るプロンプトを表示するだけ

入力: data/<station>/genre.csv（classify_genre.py の出力。method=unresolved の行が対象）
出力: data/<station>/genre_claude.csv に追記（既に判定済みの id は送らない）
その後 classify_genre.py を再実行すると最終ジャンルに反映される。

外部サイトは検索しない。店名・Overture の分類・住所だけから判断させる
（店舗データベースの規約問題を避けるため。CLAUDE.md 参照）。

亀戸の genre_claude.csv はこのスクリプトではなく、作業セッション中の Claude が
同じ基準で手で判定したもの。このスクリプトは実 API で未実行。
"""
import argparse
import csv
import json
import os
import sys

from genre_rules import NAME_RULES, OVERTURE_MAP

BATCH = 50
GENRES = list(dict.fromkeys([g for g, _ in NAME_RULES] + list(OVERTURE_MAP.values())))
LABELS = GENRES + ["不明", "対象外"]

SYSTEM = f"""あなたは日本の飲食店の店名からジャンルを判定する担当です。

各店について、次のジャンル一覧から1つ選んでください:
{"、".join(GENRES)}

選べないときの扱い:
- 店名・分類・住所からジャンルが読み取れない店は「不明」にする。推測で埋めない
- 地名だけのレコード、フードコート・横丁などの区画全体、飲食店でない施設、
  住所が明らかに別の場所を指すレコードは「対象外」にする

確信度:
- 高: 店名にジャンルが明記されている、よく知られたチェーン、または同じリスト内に
  同じ店の別表記レコードがあって中身が分かる
- 中: 日本の店名の慣習や Overture の分類からほぼ判断できる
- 低: 可能性はあるが外れることも多い

Overture の分類（category / alternates）は機械的に付いたもので誤りが多い。参考にとどめる。
外部の情報は調べない。与えた情報と一般知識だけで判断する。
reason は日本語30字以内で、判断の根拠を書く。"""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "genre": {"type": "string", "enum": LABELS},
                    "confidence": {"type": "string", "enum": ["高", "中", "低"]},
                    "reason": {"type": "string"},
                },
                "required": ["id", "genre", "confidence", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def build_prompt(batch, context_names):
    lines = [f'{r["id"]}\t{r["name"]}\t{r["category"]}\t{r["alternates"]}\t{r["address"]}' for r in batch]
    return ("次の店のジャンルを判定してください。列は id、店名、Overture分類、別分類、住所（タブ区切り）。\n\n"
            + "\n".join(lines)
            + "\n\n参考: 同じ駅圏にある他の店の名前（同じ店の別表記を見つける手がかり）\n"
            + " / ".join(context_names))


def classify_batch(client, model, batch, context_names):
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": build_prompt(batch, context_names)}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"refusal: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("max_tokens に達した。BATCH を小さくする")
    text = next(b.text for b in response.content if b.type == "text")
    items = json.loads(text)["items"]
    sent = {r["id"] for r in batch}
    return [it for it in items if it["id"] in sent]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("station")
    ap.add_argument("--model", default=os.environ.get("CLASSIFY_MODEL", "claude-opus-5-5"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(f"data/{args.station}/genre.csv", encoding="utf-8")))
    out_path = f"data/{args.station}/genre_claude.csv"
    done = set()
    if os.path.exists(out_path):
        done = {r["id"] for r in csv.DictReader(open(out_path, encoding="utf-8"))}
    todo = [r for r in rows if r["method"] == "unresolved" and r["id"] not in done]
    context_names = sorted({r["name"] for r in rows if r["method"] != "unresolved"})
    print(f"未判定 {len(todo)} 件を {BATCH} 件ずつ送る（モデル {args.model}）", file=sys.stderr)

    if args.dry_run:
        print(SYSTEM)
        print("----")
        print(build_prompt(todo[:BATCH], context_names))
        return

    import anthropic
    client = anthropic.Anthropic()
    new_file = not os.path.exists(out_path)
    with open(out_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "name", "genre", "confidence", "reason"])
        if new_file:
            w.writeheader()
        names = {r["id"]: r["name"] for r in todo}
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            for it in classify_batch(client, args.model, batch, context_names):
                w.writerow({"id": it["id"], "name": names[it["id"]], "genre": it["genre"],
                            "confidence": it["confidence"], "reason": it["reason"]})
            f.flush()
            print(f"  {min(i + BATCH, len(todo))}/{len(todo)}", file=sys.stderr)


if __name__ == "__main__":
    main()
