"""店名からのジャンル判定を Opus 5.5 と Haiku 4.5 で比べる（本番の一括判定の前の小さな試験）。ローカルで実行。

  python scripts/compare_models.py            # 両モデルで判定して比較（ANTHROPIC_API_KEY が必要）
  python scripts/compare_models.py --dry-run  # 送る件数と内容を確認するだけ

入力: data/areas/model_compare_input.csv（クラウド側で作成済み）
  set=answer_key  正解付き 300 店。Overture の料理系の細分類（ラーメン・すし・中華など15ジャンル×20店）で
                  ジャンルが決まっていて、店名にはジャンル語が無い店。判定時は分類を伏せ、店名と住所だけを渡す。
                  正解は Overture の分類なので、正解そのものにも1割前後の誤りがありうる（目安として読む）
  set=unresolved  本番と同じ判定不能の店名からランダムに 300 件。正解は無い。両モデルの一致と「不明」の割合を見る
出力: data/areas/model_compare.csv  1店1行で両モデルの答えを並べたもの
      標準出力に比較の要約（正解率・判定できた割合・一致率・実際にかかった費用と本番の費用見込み）

判定の基準（システムプロンプトと出力形式）は本番と同じ classify_with_claude.py のものを使う。
モデルの違いだけを見るため、refusal 時のフォールバック（別モデルでの再実行）は使わない。
通常の API（Batch ではない）で送るので、すぐ結果が出る。費用は両モデル合わせて1ドル以下の見込み。
"""
import argparse
import csv
import json
import sys
import time
from collections import Counter

from classify_with_claude import SCHEMA, SYSTEM

MODELS = {"opus": "claude-opus-5-5", "haiku": "claude-haiku-4-5"}
# 1M トークンあたりのドル（通常料金。Batch API はこの半額）
PRICE = {"opus": (4.0, 20.0), "haiku": (1.0, 5.0)}
CHUNK = 100
ACCEPTED = {"高", "中"}
PRODUCTION_NAMES = 28444  # 本番で送る判定不能の店名の数（data/areas/tokyo23_unresolved_names.csv）


def build_prompt(chunk):
    lines = [f'n{i}\t{r["name"]}\t{r["category"]}\t{r["alternates"]}\t{r["address"]}\t{r["count"]}'
             for i, r in enumerate(chunk)]
    return ("次の店のジャンルを判定してください。列は id、店名、Overture分類、別分類、住所の例、"
            "東京23区内で同じ店名の店の数（タブ区切り。空欄は情報なし）。\n\n" + "\n".join(lines))


def call(client, key, chunk):
    import anthropic

    model = MODELS[key]
    params = {
        "model": model,
        "max_tokens": 16000,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": build_prompt(chunk)}],
        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}}
        | ({} if key == "haiku" else {"effort": "low"}),
    }
    for attempt in range(4):
        try:
            with client.messages.stream(**params) as stream:
                msg = stream.get_final_message()
            break
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.BadRequestError,
                anthropic.NotFoundError) as e:
            # キーの誤り・権限・リクエストの誤りは再試行しても直らないので止める
            raise SystemExit(f"{key}: {type(e).__name__}: {e}\n"
                             "API キー（ANTHROPIC_API_KEY）が正しいか、クレジットがあるかを確認してください")
        except Exception as e:  # 一時的な失敗（混雑・通信エラーなど）は少し待って再試行
            print(f"  {key}: {type(e).__name__}: {e}。再試行", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    else:
        raise SystemExit(f"{key}: 再試行しても失敗")
    if msg.stop_reason != "end_turn":
        print(f"  {key}: stop_reason={msg.stop_reason}（この塊の結果は欠ける）", file=sys.stderr)
        return {}, msg.usage
    text = next(b.text for b in msg.content if b.type == "text")
    out = {}
    for it in json.loads(text)["items"]:
        if it["id"].startswith("n") and it["id"][1:].isdigit() and int(it["id"][1:]) < len(chunk):
            out[int(it["id"][1:])] = it
    return out, msg.usage


def summarize(rows, usage):
    print("\n=== 答え合わせ用 300 店（正解は Overture の細分類。分類は伏せて店名と住所だけで判定）===")
    key_rows = [r for r in rows if r["set"] == "answer_key"]
    for k in MODELS:
        adopted = [r for r in key_rows if r[f"{k}_genre"] not in ("不明", "対象外", "") and r[f"{k}_conf"] in ACCEPTED]
        correct = [r for r in adopted if r[f"{k}_genre"] == r["truth"]]
        print(f"{k:6s}: 採用（確信度 高・中）{len(adopted)}/{len(key_rows)} 店（{len(adopted) / len(key_rows):.0%}）、"
              f"うち正解 {len(correct)}（{len(correct) / max(1, len(adopted)):.0%}）、"
              f"全体に対する正解 {len(correct) / len(key_rows):.0%}")
    both_wrong_same = [r for r in key_rows if r["opus_genre"] == r["haiku_genre"] != r["truth"]
                       and r["opus_genre"] not in ("不明", "対象外", "")]
    print(f"両モデルが同じ答えで正解と違う店 {len(both_wrong_same)} 件（正解側＝Overture の誤りの可能性が高い）")

    print("\n=== 本番と同じ判定不能の店名 300 件（正解なし）===")
    un = [r for r in rows if r["set"] == "unresolved"]
    for k in MODELS:
        adopted = sum(1 for r in un if r[f"{k}_genre"] not in ("不明", "対象外", "") and r[f"{k}_conf"] in ACCEPTED)
        unknown = sum(1 for r in un if r[f"{k}_genre"] in ("不明", "") or r[f"{k}_conf"] == "低")
        print(f"{k:6s}: 採用 {adopted} 件（{adopted / len(un):.0%}）、不明・低 {unknown} 件")
    both = [r for r in un if all(r[f"{k}_genre"] not in ("不明", "対象外", "") and r[f"{k}_conf"] in ACCEPTED for k in MODELS)]
    agree = sum(1 for r in both if r["opus_genre"] == r["haiku_genre"])
    print(f"両モデルとも採用した {len(both)} 件のうち、答えが一致 {agree} 件（{agree / max(1, len(both)):.0%}）")

    print("\n=== 費用 ===")
    n = len(rows)
    for k in MODELS:
        u = usage[k]
        cost = u["in"] / 1e6 * PRICE[k][0] + u["out"] / 1e6 * PRICE[k][1]
        est = cost * PRODUCTION_NAMES / n * 0.5
        print(f"{k:6s}: 入力 {u['in']:,} / 出力 {u['out']:,} トークン、今回 ${cost:.2f}。"
              f"本番 {PRODUCTION_NAMES:,} 店名を Batch API で送ると約 ${est:.0f} の見込み")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    rows = list(csv.DictReader(open("data/areas/model_compare_input.csv", encoding="utf-8")))
    chunks = [rows[i:i + CHUNK] for i in range(0, len(rows), CHUNK)]
    print(f"{len(rows)} 店を {len(chunks)} 回に分けて、{len(MODELS)} モデルで判定する（計 {len(chunks) * len(MODELS)} リクエスト）")
    if args.dry_run:
        print(build_prompt(chunks[0])[:1200])
        return

    import anthropic
    client = anthropic.Anthropic()
    usage = {k: {"in": 0, "out": 0} for k in MODELS}
    for k in MODELS:
        for ci, ch in enumerate(chunks):
            res, u = call(client, k, ch)
            usage[k]["in"] += u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0)
            usage[k]["out"] += u.output_tokens
            for i, r in enumerate(ch):
                it = res.get(i, {})
                r[f"{k}_genre"] = it.get("genre", "")
                r[f"{k}_conf"] = it.get("confidence", "")
                r[f"{k}_reason"] = it.get("reason", "")
            print(f"  {k}: {ci + 1}/{len(chunks)}")

    out = "data/areas/model_compare.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        fields = ["set", "name", "truth", "address"] + [f"{k}_{c}" for k in MODELS for c in ("genre", "conf", "reason")]
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"-> {out}")
    summarize(rows, usage)
    with open("data/areas/model_compare_summary.json", "w", encoding="utf-8") as f:
        json.dump({"usage": usage}, f)


if __name__ == "__main__":
    main()
