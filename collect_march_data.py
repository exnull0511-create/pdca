"""
collect_march_data.py
=====================
3月分（2026年3月1日〜本日）のS級レースデータを Kdreams からスクレイピングし、
バックテスト用の3ファイルに追記する。

出力ファイル（data/ 以下、既存データに追記）:
  data/racecard_march.xlsx  — 出走表+ライン (race_id, venue, race_no, date, 車番, 選手名, 競走得点, 脚質, line_no, line_bibs)
  data/odds_march.xlsx      — 3連単オッズ    (race_id, 組み合わせ, オッズ)
  data/payouts_march.xlsx   — 結果・払戻     (race_id, result_trifecta, payout_trifecta)

使い方:
  python collect_march_data.py
  python collect_march_data.py --start 2026-03-01 --end 2026-03-11
  python collect_march_data.py --resume   # 未取得分のみ追加（race_id重複スキップ）
"""

import argparse
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from kdreams_scraper import KdreamsScraper
from fetch_schedule import fetch_today_f1_g3_races
from fetch_results import get_race_result

# ── 出力先 ─────────────────────────────────────────────────────────────────────
OUT_RACECARD = Path("data/racecard_march.xlsx")
OUT_ODDS     = Path("data/odds_march.xlsx")
OUT_PAYOUTS  = Path("data/payouts_march.xlsx")

SLEEP_SEC  = 0.5   # リクエスト間スリープ（秒）
MAX_RETRY  = 2     # スクレイピング失敗時のリトライ回数


# ── ユーティリティ ────────────────────────────────────────────────────────────
def load_existing(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_excel(path, dtype={"race_id": str})
    return pd.DataFrame()


def save_df(df: pd.DataFrame, path: Path):
    path.parent.mkdir(exist_ok=True)
    df.to_excel(path, index=False)
    print(f"   💾 {path}  ({len(df)}行)")


def make_date_range(start_str: str, end_str: str) -> list[date]:
    s = datetime.strptime(start_str, "%Y-%m-%d").date()
    e = datetime.strptime(end_str,   "%Y-%m-%d").date()
    days = []
    cur = s
    while cur <= e:
        days.append(cur)
        cur += timedelta(days=1)
    return days


# ── オッズ取得（racedetailページ本体のoddspop_table_wrapper） ────────────────
def scrape_odds_from_detail(scraper: KdreamsScraper, race_url: str, race_id: str) -> list[dict]:
    """
    racedetail ページから3連単オッズを取得。
    Returns: [{'race_id': ..., '組み合わせ': '1-2-3', 'オッズ': 12.5}, ...]
    """
    for attempt in range(MAX_RETRY + 1):
        try:
            r    = scraper.session.get(race_url, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")

            result = []
            wrappers = soup.find_all("div", class_="oddspop_table_wrapper")
            for wrapper in wrappers:
                for tr in wrapper.find_all("tr"):
                    txt = tr.get_text(separator=" ", strip=True)
                    m   = re.search(r"(\d)-(\d)-(\d)\s+([\d,]+\.?\d*)", txt)
                    if m:
                        combo = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                        try:
                            odds = float(m.group(4).replace(",", ""))
                            if odds > 1.0:
                                result.append({"race_id": race_id, "組み合わせ": combo, "オッズ": odds})
                        except ValueError:
                            pass

            # フォールバック: wrapperなし
            if not result:
                for tr in soup.find_all("tr"):
                    txt = tr.get_text(separator=" ", strip=True)
                    m   = re.search(r"(\d)-(\d)-(\d)\s+([\d,]+\.?\d*)", txt)
                    if m:
                        combo = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                        try:
                            odds = float(m.group(4).replace(",", ""))
                            if odds > 1.0:
                                result.append({"race_id": race_id, "組み合わせ": combo, "オッズ": odds})
                        except ValueError:
                            pass

            return result

        except Exception as e:
            if attempt < MAX_RETRY:
                print(f"      ⚠️  オッズ取得リトライ {attempt+1}: {e}")
                time.sleep(2)
            else:
                print(f"      ⚠️  オッズ取得失敗: {e}")
                return []


# ── 出走表取得 ────────────────────────────────────────────────────────────────
def scrape_racecard_rows(scraper: KdreamsScraper, race_url: str,
                          race_id: str, venue: str, race_no: int,
                          race_date: date) -> list[dict]:
    """
    KdreamsScraper.get_race_card() + get_race_lines() を使って
    racecard 形式の行リストを返す。
    """
    for attempt in range(MAX_RETRY + 1):
        try:
            card_df = scraper.get_race_card(race_url)
            if card_df is None or card_df.empty:
                return []

            lines_list = scraper.get_race_lines(race_url)  # [{'line':N,'bibs':[...]}]
            bib_to_line = {}
            bib_to_bibs = {}
            for linfo in lines_list:
                lno  = linfo.get("line", 0)
                bibs = linfo.get("bibs", [])
                bibs_str = "-".join(str(b) for b in bibs)
                for b in bibs:
                    bib_to_line[b] = lno
                    bib_to_bibs[b] = bibs_str

            rows = []
            date_int = int(race_date.strftime("%Y%m%d"))
            for _, row in card_df.iterrows():
                try:
                    bib = int(row.get("車番", 0))
                except Exception:
                    continue
                name  = str(row.get("選手名", ""))
                score = float(row.get("競走得点", 80) or 80)
                style = str(row.get("脚質", ""))
                rows.append({
                    "race_id":    race_id,
                    "venue":      venue,
                    "race_no":    race_no,
                    "date":       date_int,
                    "車番":       bib,
                    "選手名":     name,
                    "競走得点":   score,
                    "脚質":       style,
                    "line_no":    bib_to_line.get(bib, 0),
                    "line_bibs":  bib_to_bibs.get(bib, str(bib)),
                })
            return rows

        except Exception as e:
            if attempt < MAX_RETRY:
                print(f"      ⚠️  出走表リトライ {attempt+1}: {e}")
                time.sleep(2)
            else:
                print(f"      ⚠️  出走表取得失敗: {e}")
                return []


# ── 結果取得（過去レース用） ──────────────────────────────────────────────────
def scrape_result(scraper: KdreamsScraper, race_url: str, race_id: str) -> dict | None:
    """fetch_results.get_race_result() のラッパー"""
    result_url = race_url.rstrip("/") + "/?pageType=result"
    for attempt in range(MAX_RETRY + 1):
        try:
            res = get_race_result(scraper, result_url)
            return res
        except Exception as e:
            if attempt < MAX_RETRY:
                print(f"      ⚠️  結果取得リトライ {attempt+1}: {e}")
                time.sleep(2)
            else:
                print(f"      ⚠️  結果取得失敗: {e}")
                return None


# ── メイン ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="3月分S級レースデータ収集")
    parser.add_argument("--start",  default="2026-03-01", help="開始日 YYYY-MM-DD")
    parser.add_argument("--end",    default=date.today().strftime("%Y-%m-%d"), help="終了日 YYYY-MM-DD")
    parser.add_argument("--resume", action="store_true", help="既取得のrace_idはスキップ")
    args = parser.parse_args()

    target_dates = make_date_range(args.start, args.end)
    print(f"📅 対象期間: {args.start} 〜 {args.end}  ({len(target_dates)}日間)")

    # 既存データをロード
    rc_existing = load_existing(OUT_RACECARD)
    od_existing = load_existing(OUT_ODDS)
    py_existing = load_existing(OUT_PAYOUTS)

    already_done = set()
    if args.resume and not rc_existing.empty:
        already_done = set(rc_existing["race_id"].astype(str).unique())
        print(f"   （resume: {len(already_done)}件スキップ予定）")

    scraper = KdreamsScraper()

    all_rc_rows = []
    all_od_rows = []
    all_py_rows = []
    total_hit = total_miss = total_skip = 0

    for target_date in target_dates:
        print(f"\n{'='*60}")
        print(f"📆 {target_date}  レース一覧取得中...")

        races = fetch_today_f1_g3_races(target_date, min_grade="F1", fetch_times=True)
        if not races:
            print("   → 開催なし or 取得失敗")
            continue

        s_races = [r for r in races if r.get("race_name")]
        print(f"   → S級 {len(s_races)}R")

        for r in s_races:
            race_id  = str(r["race_id"])
            venue    = r["venue"]
            race_no  = r["race_no"]
            race_url = r["race_url"]
            race_name = r.get("race_name", "")

            if race_id in already_done:
                total_skip += 1
                print(f"   ⏩ {venue} {race_no}R  スキップ済み")
                continue

            print(f"   🔎 {venue} {race_no}R  [{race_name}]  {race_id}")

            # ① 出走表
            rc_rows = scrape_racecard_rows(scraper, race_url, race_id, venue, race_no, target_date)
            time.sleep(SLEEP_SEC)

            if not rc_rows:
                print(f"      ⚠️  出走表なし → スキップ")
                total_skip += 1
                continue

            # ② オッズ
            od_rows = scrape_odds_from_detail(scraper, race_url, race_id)
            time.sleep(SLEEP_SEC)

            if not od_rows:
                print(f"      ⚠️  オッズなし → スキップ")
                total_skip += 1
                continue

            # ③ 結果（過去レース）
            res = scrape_result(scraper, race_url, race_id)
            time.sleep(SLEEP_SEC)

            if res:
                py_row = {
                    "race_id":          race_id,
                    "result_trifecta":  res["combo"],
                    "payout_trifecta":  res["payout"],
                }
                all_py_rows.append(py_row)
                print(f"      ✅ 出走{len(rc_rows)}人  オッズ{len(od_rows)}点  結果:{res['combo']} ¥{res['payout']:,}")
                total_hit += 1
            else:
                # 結果なし（当日レース or 未確定）→ 結果行は空
                py_row = {
                    "race_id":          race_id,
                    "result_trifecta":  "",
                    "payout_trifecta":  0,
                }
                all_py_rows.append(py_row)
                print(f"      ⚠️  結果未取得  出走{len(rc_rows)}人  オッズ{len(od_rows)}点")
                total_miss += 1

            all_rc_rows.extend(rc_rows)
            all_od_rows.extend(od_rows)
            already_done.add(race_id)

    # ── 保存 ──────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"📊 収集まとめ: 取得={total_hit}R  結果なし={total_miss}R  スキップ={total_skip}R")

    if not all_rc_rows:
        print("⚠️  新規データなし。ファイル更新をスキップします。")
        return

    new_rc = pd.DataFrame(all_rc_rows)
    new_od = pd.DataFrame(all_od_rows)
    new_py = pd.DataFrame(all_py_rows)

    # 既存に追記
    rc_final = pd.concat([rc_existing, new_rc], ignore_index=True) if not rc_existing.empty else new_rc
    od_final = pd.concat([od_existing, new_od], ignore_index=True) if not od_existing.empty else new_od
    py_final = pd.concat([py_existing, new_py], ignore_index=True) if not py_existing.empty else new_py

    # race_id重複削除（resume時の二重追加防止）
    rc_final = rc_final.drop_duplicates(subset=["race_id", "車番"])
    od_final = od_final.drop_duplicates(subset=["race_id", "組み合わせ"])
    py_final = py_final.drop_duplicates(subset=["race_id"])

    save_df(rc_final, OUT_RACECARD)
    save_df(od_final, OUT_ODDS)
    save_df(py_final, OUT_PAYOUTS)

    print(f"\n✅ 完了！")
    print(f"   racecard : {len(rc_final)}行 ({len(rc_final['race_id'].unique())}レース)")
    print(f"   odds     : {len(od_final)}行")
    print(f"   payouts  : {len(py_final)}行")
    print(f"\n次のステップ:")
    print(f"  python run_march_backtest.py")


if __name__ == "__main__":
    main()
