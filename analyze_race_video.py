"""
analyze_race_video.py
=====================
Gemini 2.0 Flash API を使って競輪レース映像(MP4)を分析し、
各選手の「戦法」と「直線の伸び」を自動判定してCSVに保存するスクリプト。

使い方（単体）:
  python analyze_race_video.py --video videos/seibu_9R.mp4 \
      --date 2026-03-09 --venue 西武園 --race 9 \
      --riders '[{"車番":1,"選手名":"山崎芳仁"},{"車番":2,"選手名":"佐藤慎太郎"}]'

使い方（バッチ）:
  python analyze_race_video.py --batch batch_input.csv

  batch_input.csv の形式:
    date,venue,race_no,video_path,riders_json
    2026-03-09,西武園,9,videos/seibu_9R.mp4,"[{""車番"":1,""選手名"":""山崎""}]"

環境変数:
  GEMINI_API_KEY  - Google AI Studio で発行したAPIキー

出力:
  data/video_analysis.csv  (追記形式)
"""

import os
import csv
import json
import re
import time
import argparse
from pathlib import Path

import google.generativeai as genai

# ── 設定 ─────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL_NAME     = "gemini-2.0-flash"
OUTPUT_CSV     = Path("data/video_analysis.csv")

OUTPUT_COLUMNS = [
    "date", "venue", "race_no",
    "車番", "選手名", "戦法", "直線の伸び", "備考",
]

SENPO_VALUES = [
    "逃げ切り", "逃げ粘り", "突っ張り先行", "抑え先行", "カマシ先行",
    "先行逃げ切り", "先行", "逃げ", "先行争い敗北",
    "捲り", "番手捲り", "カマシ捲り", "捲り差し", "捲り不発",
    "番手差し", "差し", "追い込み", "流れ込み", "追走", "マーク",
]

ANALYSIS_PROMPT = """\
あなたは競輪レースの映像分析の専門家です。
以下の出走表を参考に、このレース映像を詳しく分析してください。

【出走表】
{riders_text}

【分析項目】
各選手について以下を判定してください：

1. 戦法 — 下記から最も当てはまるものを1つ選ぶ
   {senpo_list}

2. 直線の伸び — 最終直線での加速・伸びを以下で評価
   S: 圧倒的な伸び（他選手と別次元）
   A: 良い伸び（平均以上）
   B: 普通またはそれ以下

【出力形式】
必ず以下のJSON形式のみで出力してください（他の文章は不要）:
```json
[
  {{"車番": 1, "選手名": "山崎芳仁", "戦法": "逃げ切り", "直線の伸び": "A", "備考": "序盤から主導権"}},
  {{"車番": 2, "選手名": "佐藤慎太郎", "戦法": "差し", "直線の伸び": "S", "備考": "直線で鋭く伸びた"}}
]
```
"""


# ── Gemini セットアップ ────────────────────────────────────────────────────────
def setup_genai():
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY 環境変数が未設定です。\n"
                         "set GEMINI_API_KEY=your_key_here (Windows)")
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel(MODEL_NAME)


# ── 動画アップロード ────────────────────────────────────────────────────────────
def upload_video(video_path: str):
    """
    MP4をGemini File APIにアップロードし、処理完了を待って返す。
    """
    print(f"  📤 アップロード中: {video_path}")
    video_file = genai.upload_file(video_path, mime_type="video/mp4")

    # 処理完了まで待機（通常10〜30秒）
    poll = 0
    while video_file.state.name == "PROCESSING":
        poll += 1
        print(f"  ⏳ Gemini処理中... ({poll * 5}秒)", end="\r")
        time.sleep(5)
        video_file = genai.get_file(video_file.name)

    if video_file.state.name == "FAILED":
        raise RuntimeError(f"動画アップロード失敗: {video_file.state}")

    print(f"\n  ✅ アップロード完了: {video_file.uri}")
    return video_file


# ── Gemini 分析 ───────────────────────────────────────────────────────────────
def analyze_race(model, video_file, riders: list[dict]) -> list[dict]:
    """
    映像と出走表を渡してGeminiに分析させ、JSONリストを返す。
    """
    riders_text = "\n".join(
        f"  車番{r['車番']}: {r['選手名']}" for r in riders
    )
    senpo_list = "、".join(SENPO_VALUES)

    prompt = ANALYSIS_PROMPT.format(
        riders_text=riders_text,
        senpo_list=senpo_list,
    )

    print("  🤖 Geminiが映像を分析中...")
    response = model.generate_content(
        [video_file, prompt],
        generation_config={"temperature": 0.1},  # 出力を安定させる
    )

    text = response.text
    m = re.search(r'```json\s*([\s\S]+?)\s*```', text)
    if not m:
        # フォールバック: JSONブロックなしでも試みる
        m = re.search(r'(\[[\s\S]+\])', text)
    if not m:
        raise ValueError(f"JSONパース失敗。レスポンス:\n{text[:400]}")

    return json.loads(m.group(1))


# ── CSV保存 ────────────────────────────────────────────────────────────────────
def save_results(results: list[dict], date: str, venue: str, race_no: int):
    OUTPUT_CSV.parent.mkdir(exist_ok=True)
    write_header = not OUTPUT_CSV.exists()

    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for r in results:
            w.writerow({
                "date":      date,
                "venue":     venue,
                "race_no":   race_no,
                "車番":      r.get("車番", ""),
                "選手名":    r.get("選手名", ""),
                "戦法":      r.get("戦法", ""),
                "直線の伸び": r.get("直線の伸び", ""),
                "備考":      r.get("備考", ""),
            })
    print(f"  💾 保存完了: {OUTPUT_CSV}  ({len(results)}選手分)")


# ── 単体処理 ──────────────────────────────────────────────────────────────────
def process_single(video_path: str, date: str, venue: str, race_no: int,
                   riders: list[dict]) -> list[dict]:
    model      = setup_genai()
    video_file = upload_video(video_path)
    results    = analyze_race(model, video_file, riders)
    save_results(results, date, venue, race_no)

    # アップロードファイルを削除（無料枠の容量節約）
    try:
        genai.delete_file(video_file.name)
    except Exception:
        pass

    return results


# ── バッチ処理 ────────────────────────────────────────────────────────────────
def process_batch(batch_csv: str):
    """
    batch_input.csv を読み込んで複数レースをまとめて処理する。

    CSVフォーマット（ヘッダー行必須）:
      date,venue,race_no,video_path,riders_json
    """
    model = setup_genai()
    errors = []

    with open(batch_csv, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print(f"📋 バッチ処理: {len(rows)}レース")
    for i, row in enumerate(rows, 1):
        print(f"\n[{i}/{len(rows)}] 🎬 {row['venue']} {row['race_no']}R"
              f"  ({row['video_path']})")
        try:
            riders     = json.loads(row["riders_json"])
            video_file = upload_video(row["video_path"])
            results    = analyze_race(model, video_file, riders)
            save_results(results, row["date"], row["venue"], int(row["race_no"]))
            try:
                genai.delete_file(video_file.name)
            except Exception:
                pass
            time.sleep(2)  # レート制限: 15RPM = 4秒/リクエスト余裕
        except Exception as e:
            print(f"  ⚠️ エラー: {e}")
            errors.append(f"{row['venue']} {row['race_no']}R: {e}")

    print(f"\n{'='*50}")
    print(f"✅ 完了: {len(rows) - len(errors)}/{len(rows)} 成功")
    if errors:
        print("⚠️ エラー:")
        for e in errors:
            print(f"  - {e}")


# ── メイン ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="競輪レース映像分析（Gemini 2.0 Flash）"
    )
    parser.add_argument("--video",  help="MP4ファイルパス（単体処理）")
    parser.add_argument("--date",   help="開催日 YYYY-MM-DD")
    parser.add_argument("--venue",  help="開催場名 例: 西武園")
    parser.add_argument("--race",   type=int, help="レース番号")
    parser.add_argument("--riders",
                        help='選手情報JSON 例: [{"車番":1,"選手名":"山崎芳仁"}]')
    parser.add_argument("--batch",  help="バッチ処理用CSVパス")
    args = parser.parse_args()

    if args.batch:
        process_batch(args.batch)

    elif args.video:
        if not all([args.date, args.venue, args.race]):
            parser.error("--video 使用時は --date / --venue / --race も必須です")
        riders  = json.loads(args.riders) if args.riders else []
        results = process_single(args.video, args.date, args.venue,
                                 args.race, riders)
        print(f"\n✅ 分析結果:")
        print(f"  {'車番':<4} {'選手名':<12} {'戦法':<12} {'直線'}")
        print(f"  {'-'*40}")
        for r in results:
            print(f"  {r.get('車番',''):<4} {r.get('選手名',''):<12}"
                  f" {r.get('戦法',''):<12} {r.get('直線の伸び','')}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
