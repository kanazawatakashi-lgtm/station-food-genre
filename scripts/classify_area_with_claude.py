"""23区の判定不能の店名を、Claude の Message Batches API でまとめて判定する（ローカルで実行）。

  python scripts/classify_area_with_claude.py tokyo23 --dry-run   # 件数・リクエスト数・送る内容を確認するだけ
  python scripts/classify_area_with_claude.py tokyo23 submit      # バッチを送る（ANTHROPIC_API_KEY が必要）
  python scripts/classify_area_with_claude.py tokyo23 collect     # 終わったバッチの結果を取り込む（何度でも実行可）

入力: data/areas/<area>_unresolved_names.csv（classify_area.py の出力。店名は重複なし）
出力: data/areas/<area>_claude.csv に追記（列: name, genre, confidence, reason）
      data/areas/<area>_claude_batch.txt に送ったバッチの ID
その後 classify_area.py を再実行すると反映される。

- 1リクエストに店名 BATCH_SIZE 件をまとめる。判定の基準は classify_with_claude.py（亀戸用）と同じ
- Batch API は通常の半額。結果はたいてい1時間以内に返る（最長24時間）
- 外部サイトは調べない。店名・Overture の分類・住所だけから判断させる
- このスクリプトは実 API で未実行
"""
import argparse
import csv
import json
import os
import sys
import time

from classify_with_claude import SCHEMA, SYSTEM

BATCH_SIZE = 100
DEFAULT_MODEL = os.environ.get("CLASSIFY_MODEL", "claude-opus-5-5")


def load_todo(area):
    names = list(csv.DictReader(open(f"data/areas/{area}_unresolved_names.csv", encoding="utf-8")))
    done_path = f"data/areas/{area}_claude.csv"
    done = set()
    if os.path.exists(done_path):
        done = {r["name"] for r in csv.DictReader(open(done_path, encoding="utf-8"))}
    return [r for r in names if r["name"] not in done]


def chunks(todo):
    for i in range(0, len(todo), BATCH_SIZE):
        yield i // BATCH_SIZE, todo[i:i + BATCH_SIZE]


def build_prompt(chunk):
    lines = [f'n{i}\t{r["name"]}\t{r["category"]}\t{r["alternates"]}\t{r["address_example"]}\t{r["count"]}'
             for i, r in enumerate(chunk)]
    return ("次の店のジャンルを判定してください。列は id、店名、Overture分類、別分類、住所の例、"
            "東京23区内で同じ店名の店の数（タブ区切り）。同じ店名が複数ある場合はチェーンや同名の別店のことがある。\n\n"
            + "\n".join(lines))


def request_params(model, chunk):
    return {
        "model": model,
        "max_tokens": 16000,
        "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": build_prompt(chunk)}],
        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}}
        | ({} if "haiku" in model else {"effort": "low"}),  # Haiku 4.5 は effort に未対応
    }


def submit(area, model):
    import anthropic
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    todo = load_todo(area)
    reqs = [Request(custom_id=f"c{k}", params=MessageCreateParamsNonStreaming(**request_params(model, ch)))
            for k, ch in chunks(todo)]
    client = anthropic.Anthropic()
    batch = client.messages.batches.create(requests=reqs)
    with open(f"data/areas/{area}_claude_batch.txt", "w", encoding="utf-8") as f:
        f.write(json.dumps({"batch_id": batch.id, "model": model, "names": [r["name"] for r in todo]}, ensure_ascii=False))
    print(f"送信: {len(todo)} 店名を {len(reqs)} リクエストで。batch_id={batch.id}")
    print("終わったら collect を実行する（状態は collect で確認できる）")


def collect(area):
    import anthropic

    meta = json.load(open(f"data/areas/{area}_claude_batch.txt", encoding="utf-8"))
    client = anthropic.Anthropic()
    batch = client.messages.batches.retrieve(meta["batch_id"])
    if batch.processing_status != "ended":
        c = batch.request_counts
        print(f"まだ処理中: processing={c.processing} succeeded={c.succeeded} errored={c.errored}")
        return
    names = meta["names"]
    out_path = f"data/areas/{area}_claude.csv"
    new_file = not os.path.exists(out_path)
    ok = ng = 0
    with open(out_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["name", "genre", "confidence", "reason"])
        if new_file:
            w.writeheader()
        for res in client.messages.batches.results(meta["batch_id"]):
            k = int(res.custom_id[1:])
            chunk = names[k * BATCH_SIZE:(k + 1) * BATCH_SIZE]
            if res.result.type != "succeeded":
                ng += 1
                print(f"  {res.custom_id}: {res.result.type}（collect 後にもう一度 submit すれば未判定分だけ送り直す）")
                continue
            msg = res.result.message
            if msg.stop_reason in ("refusal", "max_tokens"):
                ng += 1
                print(f"  {res.custom_id}: stop_reason={msg.stop_reason}")
                continue
            text = next(b.text for b in msg.content if b.type == "text")
            for it in json.loads(text)["items"]:
                i = int(it["id"][1:]) if it["id"].startswith("n") and it["id"][1:].isdigit() else -1
                if 0 <= i < len(chunk):
                    w.writerow({"name": chunk[i], "genre": it["genre"], "confidence": it["confidence"],
                                "reason": it["reason"]})
            ok += 1
    print(f"取り込み: 成功 {ok} リクエスト / 失敗 {ng} -> {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("area")
    ap.add_argument("action", nargs="?", choices=["submit", "collect"])
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.dry_run or not a.action:
        todo = load_todo(a.area)
        chs = list(chunks(todo))
        chars = sum(len(build_prompt(ch)) for _, ch in chs)
        print(f"未判定の店名 {len(todo)} 件 → {len(chs)} リクエスト（{BATCH_SIZE} 件ずつ）、モデル {a.model}")
        print(f"送る本文 約 {chars:,} 文字（システムプロンプトは別。キャッシュされる）")
        if chs:
            print("---- 1件目のリクエストの冒頭 ----")
            print(build_prompt(chs[0][1])[:1500])
        return
    if a.action == "submit":
        submit(a.area, a.model)
    else:
        collect(a.area)


if __name__ == "__main__":
    main()
