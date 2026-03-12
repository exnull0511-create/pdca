"""
analyze_kokura_videos.py
========================
「video」フォルダ内のExcelデータと映像ファイルを自動で紐づけ、
Gemini 2.0 Flash API で各レースを分析するスクリプト。

出力カラム（13列）:
  開催日 | 開催場 | レース番号 | 車番 | 選手名
  IP | EP | DP | BP | 直線の伸び | 戦法 | is_monster | is_unreliable

実行方法:
  $env:GEMINI_API_KEY = "your_api_key_here"
  python analyze_kokura_videos.py

  # 特定レースのみ
  python analyze_kokura_videos.py --races 9 11
"""

import os
import re
import csv
import json
import glob
import time
import argparse
from pathlib import Path

import pandas as pd
from google import genai
from google.genai import types

# ── 設定 ─────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL_NAME     = "gemini-2.0-flash"
VIDEO_DIR      = Path("video")
BANK_DATA_PATH = Path("data/keirin_bank_data.txt")
OUTPUT_CSV     = Path("data/video_analysis.csv")

OUTPUT_COLUMNS = [
    "開催日", "開催場", "レース番号",
    "車番", "選手名",
    "IP", "EP", "DP", "BP",
    "直線の伸び", "戦法", "is_monster", "is_unreliable",
]

# ── バンクデータ読み込み ───────────────────────────────────────────────────────
def load_bank_data() -> str:
    if BANK_DATA_PATH.exists():
        return BANK_DATA_PATH.read_text(encoding="utf-8")
    return "(バンクデータファイルが見つかりません)"

def extract_bank_info(venue: str, bank_data: str) -> str:
    lines  = bank_data.splitlines()
    result = []
    for i, line in enumerate(lines):
        if venue in line and ("]" in line or "バンク" in line):
            result = lines[i:i+4]
            break
    return "\n".join(result) if result else f"（{venue}のバンクデータが見つかりません）"

# ── 分析プロンプト ─────────────────────────────────────────────────────────────
ANALYSIS_PROMPT = """\
あなたは競輪レース映像・結果を分析し、予想モデル用の学習データを
作成する競輪アナリストです。

ユーザーが提示する出走選手リスト・ライン構成を元に、
mp4形式で提示されたレース映像データを精度重視で分析してください。

【出走表】
{runners_text}

【ライン構成】
{lines_text}

【レース結果（着順・決まり手）】
{result_text}

【バンク情報】
{bank_info}

─────────────────────────────────────────────────────
【各カラムの評価基準】

■ IP / EP / DP / BP（整数 1〜10、基準値5）
  IP: 初手の位置取り精度・ライン構成力
  EP: 逃げ・先行時のペース維持力・突っ張り強度
  DP: 捲り・カマシの爆発力とスピード
  BP: 横の動き・競り強さ・ブロック・追走安定性
  ※ 選手が使わなかった戦法の項目は "-" とする
  ※ 着順バイアス禁止。1着でも内容が悪ければ低評価。

■ 直線の伸び（S / A / B / C の1文字のみ）

  S【鬼脚】- 以下のいずれかに該当すれば付与：
    ① 直線で他の選手が止まって見えるほどの加速があった（視覚的に明確）
    ② 後方7番手以降から直線だけで掲示板（3着以内）に突っ込んだ
    ③ 上がりタイムが表示されている場合: 単独1位かつ2位と0.2秒以上の差
    ④ G3以上で、そのレースの中で明らかに次元が違う末脚を見せた
    ※ ①〜④のどれか1つに該当すれば S。複数条件の一致は不要。

  A【伸びた / 粘った】
    - 直線で明確に伸びている、または先行して垂れなかった

  B【標準 / 流れ込み】
    - 番手から流れ込み、普通に追走。特段の伸び・失速なし

  C【失速 / 不発 / 一杯】
    - 直線で明確にタレた、捲って不発、先行して脚が止まった

■ 戦法（以下のリストから最も近い1語を選ぶ）
  逃げ切り / 逃げ粘り / 突っ張り先行 / 抑え先行 / カマシ先行 /
  先行逃げ切り / 先行 / 逃げ / 先行争い敗 /
  一発捲り / ロング捲り / 捲り / 番手捲り / カマシ捲り /
  捲り差し / 捲り追い込み / 捲り不発 /
  番手差し / 差し / 追い込み / 流れ込み / 追走 / マーク

■ is_monster（0 or 1）
  1【鬼脚 or 脚余し】= 以下のいずれかに該当：
    ・直線の伸び=S を与えた選手（必ず is_monster=1 とセット）
    ・詰まり・外回りで踏み出しが遅れたが最後だけ猛烈に伸びた
    ・進路を塞がれて止まらざるを得なかったが一瞬開いたときに鋭く加速した
    ・上がりタイムが他選手より明らかに速いのに4着以下
  ※ 判断が難しいなら積極的に1を付与してよい（過剰にならない範囲で）
  0 = 着順通りの力負け、展開による影響なし

■ is_unreliable（0 or 1）
  1 = 以下のいずれかに該当：
    ・巻き込まれ落車・接触で離脱 / ライン崩壊 / 位置取り完全失敗
    ・仕掛け完全不発（直線C評価）/ 失格・反則
  0 = 上記に非該当
  ※ is_monster=1 と is_unreliable=1 の同時付与可

─────────────────────────────────────────────────────
【バンク補正】
バンク情報を参照してIP/EP/DP/BPに反映すること。

【特殊状況】
  ・欠場（DNS）: 行を作らない
  ・巻き込まれ落車: is_unreliable=1、観察不能項目は "-"
  ・失格: is_unreliable=1

【出力形式】
JSON形式のみ。自然言語コメント・理由文は一切不要。

```json
[
  {{
    "車番": 1,
    "選手名": "岡村潤",
    "IP": 6,
    "EP": "-",
    "DP": "-",
    "BP": 5,
    "直線の伸び": "A",
    "戦法": "追い込み",
    "is_monster": 0,
    "is_unreliable": 0
  }}
]
```
"""

# ── Excel 読み込み ─────────────────────────────────────────────────────────────
def load_excel(video_dir: Path):
    xlsx_files = glob.glob(str(video_dir / "*.xlsx"))
    if not xlsx_files:
        raise FileNotFoundError(f"{video_dir} に xlsx ファイルが見つかりません")
    xl_path = xlsx_files[0]
    print(f"📂 Excelファイル: {Path(xl_path).name}")
    xl   = pd.ExcelFile(xl_path)
    df_r = xl.parse("出走表")
    df_l = xl.parse("ライン情報")
    df_s = xl.parse("レース結果")
    for df in (df_r, df_l, df_s):
        df["レース"] = df["レース"].astype(str).str.strip()
    return df_r, df_l, df_s

# ── 映像ファイルマッピング ─────────────────────────────────────────────────────
def get_video_map(video_dir: Path) -> dict[str, Path]:
    mp4_files = glob.glob(str(video_dir / "*.mp4"))
    v_map = {}
    for f in mp4_files:
        m = re.search(r'(\d+)[Rr]', Path(f).stem)
        if m:
            v_map[f"{m.group(1)}R"] = Path(f)
    return v_map

# ── プロンプト用テキスト整形 ─────────────────────────────────────────────────
def format_race_texts(race_key, df_r, df_l, df_s):
    runners = df_r[df_r["レース"] == race_key]
    lines   = df_l[df_l["レース"] == race_key]
    results = df_s[df_s["レース"] == race_key]

    r_lines = [
        f"  車番{r['車番']}: {r['選手名']}  脚質:{r.get('脚質','不明')}  競走得点:{r.get('競走得点','?')}"
        for _, r in runners.iterrows()
    ]
    l_parts = [f"  ライン{l['ライン番号']}: {l['車番']}" for _, l in lines.iterrows()]
    res_lines = []
    for _, rs in results.sort_values("着順").iterrows():
        k = rs.get("決まり手", "")
        ks = f"  決まり手:{k}" if pd.notna(k) and str(k).strip() else ""
        res_lines.append(f"  {rs['着順']}着: 車番{rs['車番']} {rs['選手名']}{ks}")

    return (
        "\n".join(r_lines) or "  データなし",
        "\n".join(l_parts) or "  データなし",
        "\n".join(res_lines) or "  データなし",
    )

# ── Gemini クライアント ────────────────────────────────────────────────────────
def setup_client():
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY 環境変数が未設定です。\n"
                         "  $env:GEMINI_API_KEY = 'your_key'")
    return genai.Client(api_key=GEMINI_API_KEY)

# ── 動画アップロード ────────────────────────────────────────────────────────────
def upload_video(client, video_path: Path):
    print(f"  📤 アップロード中: {video_path.name}")
    vf   = client.files.upload(file=str(video_path))
    poll = 0
    while vf.state.name == "PROCESSING":
        poll += 1
        print(f"  ⏳ Gemini処理中... ({poll * 5}秒)", end="\r")
        time.sleep(5)
        vf = client.files.get(name=vf.name)
    if vf.state.name == "FAILED":
        raise RuntimeError(f"動画アップロード失敗: {vf.state}")
    print(f"\n  ✅ アップロード完了")
    return vf

# ── Gemini 分析（リトライ付き）────────────────────────────────────────────────
def analyze_race(client, video_file, runners_text, lines_text, result_text, bank_info,
                 max_retry: int = 3):
    prompt = ANALYSIS_PROMPT.format(
        runners_text=runners_text,
        lines_text=lines_text,
        result_text=result_text,
        bank_info=bank_info,
    )
    for attempt in range(1, max_retry + 1):
        try:
            print(f"  🤖 Gemini映像分析中... (試行{attempt}/{max_retry})")
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=[
                    types.Part.from_uri(file_uri=video_file.uri, mime_type="video/mp4"),
                    prompt,
                ],
                config=types.GenerateContentConfig(temperature=0.1),
            )
            text = response.text
            m = re.search(r'```json\s*([\s\S]+?)\s*```', text)
            if not m:
                m = re.search(r'(\[[\s\S]+\])', text)
            if not m:
                raise ValueError(f"JSONパース失敗。レスポンス:\n{text[:500]}")
            return json.loads(m.group(1))

        except Exception as e:
            err_str = str(e)
            # 429 クォータ超過 → retryDelay を取得して待機してリトライ
            if '429' in err_str and attempt < max_retry:
                delay_m = re.search(r'retryDelay.*?(\d+)s', err_str)
                wait_s  = int(delay_m.group(1)) + 5 if delay_m else 60
                print(f"  ⚠️  クォータ超過。{wait_s}秒後にリトライします...")
                time.sleep(wait_s)
            else:
                raise

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
                "開催日":      date,
                "開催場":      venue,
                "レース番号":  race_no,
                "車番":        r.get("車番", ""),
                "選手名":      r.get("選手名", ""),
                "IP":          r.get("IP", "-"),
                "EP":          r.get("EP", "-"),
                "DP":          r.get("DP", "-"),
                "BP":          r.get("BP", "-"),
                "直線の伸び":  r.get("直線の伸び", ""),
                "戦法":        r.get("戦法", ""),
                "is_monster":  r.get("is_monster", 0),
                "is_unreliable": r.get("is_unreliable", 0),
            })
    print(f"  💾 保存: {OUTPUT_CSV.name}  ({len(results)}選手)")

# ── 結果テーブル表示 ──────────────────────────────────────────────────────────
def print_result_table(results: list[dict]):
    print(f"\n  {'車番':<4} {'選手名':<12} {'IP':>3} {'EP':>3} {'DP':>3} {'BP':>3}"
          f"  {'直線':<4} {'戦法':<14} {'mon'} {'unr'}")
    print(f"  {'-'*60}")
    for r in results:
        print(f"  {r.get('車番',''):<4} {r.get('選手名',''):<12}"
              f" {str(r.get('IP','-')):>3} {str(r.get('EP','-')):>3}"
              f" {str(r.get('DP','-')):>3} {str(r.get('BP','-')):>3}"
              f"  {r.get('直線の伸び',''):<4}"
              f" {r.get('戦法',''):<14}"
              f" {r.get('is_monster',0):<4}"
              f" {r.get('is_unreliable',0)}")

# ── メイン ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="競輪レース映像分析（Gemini 2.0 Flash）")
    parser.add_argument("--races", nargs="*", type=int,
                        help="処理するレース番号（省略時は全レース）")
    parser.add_argument("--date",  default="2026/03/07", help="開催日")
    parser.add_argument("--venue", default="小倉",       help="開催場名")
    args = parser.parse_args()

    df_runners, df_lines, df_results = load_excel(VIDEO_DIR)
    video_map = get_video_map(VIDEO_DIR)
    bank_data = load_bank_data()
    bank_info = extract_bank_info(args.venue, bank_data)

    print(f"🎬 映像: {sorted(video_map.keys(), key=lambda x: int(x.replace('R','')))}  ({len(video_map)}本)")
    print(f"🏟️  バンク補正:\n{bank_info}\n")

    all_races = sorted(video_map.keys(), key=lambda x: int(x.replace("R", "")))
    if args.races:
        target  = [f"{r}R" for r in args.races if f"{r}R" in video_map]
        missing = [r for r in args.races if f"{r}R" not in video_map]
        if missing:
            print(f"⚠️  映像が見つからないレース: {missing}")
    else:
        target = all_races

    print(f"📋 処理対象: {target}")
    client = setup_client()
    errors = []

    for race_key in target:
        race_no = int(race_key.replace("R", ""))
        print(f"\n{'='*60}")
        print(f"🏁 {args.venue} {race_key}  ({args.date})")

        try:
            runners_text, lines_text, result_text = format_race_texts(
                race_key, df_runners, df_lines, df_results
            )
            vf      = upload_video(client, video_map[race_key])
            results = analyze_race(client, vf, runners_text, lines_text,
                                   result_text, bank_info)
            print_result_table(results)
            save_results(results, args.date, args.venue, race_no)
            try:
                client.files.delete(name=vf.name)
            except Exception:
                pass
            time.sleep(60)  # 無料枠のTPM制限対応: 1分待機

        except Exception as e:
            print(f"  ⚠️  エラー: {e}")
            errors.append(f"{race_key}: {e}")

    print(f"\n{'='*60}")
    print(f"✅ 完了: {len(target) - len(errors)}/{len(target)} 成功")
    if errors:
        for e in errors:
            print(f"  ⚠️  {e}")
    print(f"📄 出力: {OUTPUT_CSV.resolve()}")


if __name__ == "__main__":
    main()
