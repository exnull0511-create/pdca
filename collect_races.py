"""
collect_races.py
================
任意期間のS級レースデータ（出走表・オッズ・結果）をKドリームスから収集する。
collect_march_v2.py の汎用版。

使い方:
  # 開催リスト自動探索 → データ収集
  python collect_races.py --start 2026-01-01 --end 2026-03-31

  # 既存データへの追記（デフォルト: data/racecard_hist.xlsx 等）
  python collect_races.py --start 2026-02-01 --end 2026-02-28

  # 開催探索だけ実行（データ収集しない）
  python collect_races.py --start 2026-01-01 --end 2026-03-31 --discover-only
"""

import argparse
import re
import time
import warnings
warnings.filterwarnings("ignore")

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from kdreams_scraper import KdreamsScraper
from fetch_results import get_race_result
from fetch_kaisai_list import discover_kaisai_range, VENUE_SLUG

# ── 出力先（累積ファイル） ──────────────────────────────────────
OUT_DIR      = Path("data")
OUT_RACECARD = OUT_DIR / "racecard_hist.xlsx"
OUT_ODDS     = OUT_DIR / "odds_hist.xlsx"
OUT_PAYOUTS  = OUT_DIR / "payouts_hist.xlsx"

SLEEP_SEC       = 0.3
MAX_RETRY       = 2
RACE_SCAN_START = 5   # S級は通常5R以降
RACE_SCAN_END   = 12


# ── S級判定（collect_march_v2.py と同一） ──────────────────────
def is_s_class(scraper, race_url):
    """racedetailページのtitleタグに「Ｓ級」or「S級」が含まれるかチェック"""
    try:
        r = scraper.session.get(race_url, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        title = soup.find('title')
        title_txt = title.string if title and title.string else ''
        is_s = bool(re.search(r'[ＳS]級', title_txt))
        m = re.search(r'\d+R\s+([^\|]+)', title_txt)
        race_name = m.group(1).strip() if m else ''
        return is_s, race_name
    except Exception:
        return False, ''


# ── オッズ取得 ─────────────────────────────────────────────────
def scrape_odds(scraper, race_url, race_id):
    """racedetailページから3連単オッズを取得"""
    for attempt in range(MAX_RETRY + 1):
        try:
            r = scraper.session.get(race_url, timeout=15)
            soup = BeautifulSoup(r.text, 'html.parser')
            result = []
            wrappers = soup.find_all('div', class_='oddspop_table_wrapper')
            for wrapper in wrappers:
                for tr in wrapper.find_all('tr'):
                    txt = tr.get_text(separator=' ', strip=True)
                    m = re.search(r'(\d)-(\d)-(\d)\s+([\d,]+\.?\d*)', txt)
                    if m:
                        combo = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                        try:
                            odds = float(m.group(4).replace(',', ''))
                            if odds > 1.0:
                                result.append({"race_id": race_id, "組み合わせ": combo, "オッズ": odds})
                        except ValueError:
                            pass
            # フォールバック: wrapper が無い場合
            if not result:
                for tr in soup.find_all('tr'):
                    txt = tr.get_text(separator=' ', strip=True)
                    m = re.search(r'(\d)-(\d)-(\d)\s+([\d,]+\.?\d*)', txt)
                    if m:
                        combo = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                        try:
                            odds = float(m.group(4).replace(',', ''))
                            if odds > 1.0:
                                result.append({"race_id": race_id, "組み合わせ": combo, "オッズ": odds})
                        except ValueError:
                            pass
            return result
        except Exception as e:
            if attempt < MAX_RETRY:
                time.sleep(2)
            else:
                print(f"      ⚠️  オッズ取得失敗: {e}")
                return []


# ── 出走表取得 ─────────────────────────────────────────────────
def scrape_racecard(scraper, race_url, race_id, venue, race_no, race_date_int):
    """出走表+ライン情報を取得"""
    for attempt in range(MAX_RETRY + 1):
        try:
            card_df = scraper.get_race_card(race_url)
            if card_df is None or card_df.empty:
                return []
            lines_list = scraper.get_race_lines(race_url)
            bib_to_line = {}
            bib_to_bibs = {}
            for linfo in lines_list:
                lno = linfo.get('line', 0)
                bibs = linfo.get('bibs', [])
                bibs_str = '-'.join(str(b) for b in bibs)
                for b in bibs:
                    bib_to_line[b] = lno
                    bib_to_bibs[b] = bibs_str
            rows = []
            for _, row in card_df.iterrows():
                try:
                    bib = int(row.get('車番', 0))
                except Exception:
                    continue
                rows.append({
                    "race_id":   race_id,
                    "venue":     venue,
                    "race_no":   race_no,
                    "date":      race_date_int,
                    "車番":      bib,
                    "選手名":    str(row.get('選手名', '')),
                    "競走得点":  float(row.get('競走得点', 80) or 80),
                    "脚質":      str(row.get('脚質', '')),
                    "line_no":   bib_to_line.get(bib, 0),
                    "line_bibs": bib_to_bibs.get(bib, str(bib)),
                })
            return rows
        except Exception as e:
            if attempt < MAX_RETRY:
                time.sleep(2)
            else:
                print(f"      ⚠️  出走表取得失敗: {e}")
                return []


# ── 結果取得 ──────────────────────────────────────────────────
def scrape_result(scraper, race_url, race_id):
    """racedetailの結果ページから3連単結果を取得"""
    result_url = race_url.rstrip('/') + '/?pageType=result'
    for attempt in range(MAX_RETRY + 1):
        try:
            res = get_race_result(scraper, result_url)
            return res
        except Exception:
            if attempt < MAX_RETRY:
                time.sleep(2)
            else:
                return None


# ── 既存データ読込 ─────────────────────────────────────────────
def _load_existing(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_excel(path, dtype={"race_id": str})
    return pd.DataFrame()


# ── メイン収集ループ ──────────────────────────────────────────
def collect(kaisai_list: list[dict], scraper: KdreamsScraper, skip_existing: bool = True):
    """
    kaisai_list を受け取り、各開催のS級レースを収集して Excel に保存する。
    """
    rc_existing = _load_existing(OUT_RACECARD)
    od_existing = _load_existing(OUT_ODDS)
    py_existing = _load_existing(OUT_PAYOUTS)

    already_done = set()
    if not rc_existing.empty:
        already_done = set(rc_existing["race_id"].astype(str).unique())
        print(f"📂 既存データ: {len(already_done)} レース（スキップ対象）")

    all_rc, all_od, all_py = [], [], []
    total_ok = total_skip = total_no_result = 0

    for ki, kaisai in enumerate(kaisai_list, 1):
        venue_code = kaisai['venue_code']
        venue_name = kaisai['venue_name']
        slug = kaisai['slug']
        kaisai_id = kaisai['kaisai_id']
        race_date = kaisai['race_date']
        if isinstance(race_date, str):
            race_date = date.fromisoformat(race_date)
        race_date_int = int(race_date.strftime("%Y%m%d"))

        print(f"\n[{ki}/{len(kaisai_list)}] 📍 {venue_name}  {race_date}  (kaisai={kaisai_id})")

        for race_no in range(RACE_SCAN_START, RACE_SCAN_END + 1):
            race_id = f"{kaisai_id}{race_no:02d}"

            if skip_existing and race_id in already_done:
                total_skip += 1
                continue

            race_url = f"https://keirin.kdreams.jp/{slug}/racedetail/{race_id}/"

            # S級判定
            is_s, race_name = is_s_class(scraper, race_url)
            time.sleep(SLEEP_SEC)
            if not is_s:
                continue

            print(f"    {race_no:2d}R  [{race_name[:20]}]", end='')

            # 出走表
            rc_rows = scrape_racecard(scraper, race_url, race_id, venue_name, race_no, race_date_int)
            time.sleep(SLEEP_SEC)
            if not rc_rows:
                print(f"  ⚠️ 出走表なし")
                continue

            # オッズ
            od_rows = scrape_odds(scraper, race_url, race_id)
            time.sleep(SLEEP_SEC)
            if not od_rows:
                print(f"  ⚠️ オッズなし")
                continue

            # 結果
            res = scrape_result(scraper, race_url, race_id)
            time.sleep(SLEEP_SEC)

            if res:
                py_row = {
                    "race_id": race_id,
                    "result_trifecta": res["combo"],
                    "payout_trifecta": res["payout"],
                }
                all_py.append(py_row)
                print(f"  ✅ {len(rc_rows)}人 {len(od_rows)}点 結果:{res['combo']} ¥{res['payout']:,}")
                total_ok += 1
            else:
                py_row = {"race_id": race_id, "result_trifecta": "", "payout_trifecta": 0}
                all_py.append(py_row)
                print(f"  ⚠️ 結果未取得 {len(rc_rows)}人 {len(od_rows)}点")
                total_no_result += 1

            all_rc.extend(rc_rows)
            all_od.extend(od_rows)
            already_done.add(race_id)

    # ── 保存 ──────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"📊 収集まとめ: 完了={total_ok}R  結果なし={total_no_result}R  スキップ={total_skip}R")

    if not all_rc:
        print("⚠️  新規データなし")
        return

    new_rc = pd.DataFrame(all_rc)
    new_od = pd.DataFrame(all_od)
    new_py = pd.DataFrame(all_py)

    rc_final = pd.concat([rc_existing, new_rc], ignore_index=True) if not rc_existing.empty else new_rc
    od_final = pd.concat([od_existing, new_od], ignore_index=True) if not od_existing.empty else new_od
    py_final = pd.concat([py_existing, new_py], ignore_index=True) if not py_existing.empty else new_py

    rc_final = rc_final.drop_duplicates(subset=["race_id", "車番"])
    od_final = od_final.drop_duplicates(subset=["race_id", "組み合わせ"])
    py_final = py_final.drop_duplicates(subset=["race_id"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rc_final.to_excel(OUT_RACECARD, index=False)
    od_final.to_excel(OUT_ODDS, index=False)
    py_final.to_excel(OUT_PAYOUTS, index=False)

    print(f"\n✅ 保存完了！")
    print(f"   racecard : {OUT_RACECARD}  ({len(rc_final)}行 / {len(rc_final['race_id'].unique())}レース)")
    print(f"   odds     : {OUT_ODDS}  ({len(od_final)}行)")
    print(f"   payouts  : {OUT_PAYOUTS}  ({len(py_final)}行)")


# ── CLI ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="S級レースデータ収集（任意期間）")
    parser.add_argument("--start", required=True, help="開始日 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="終了日 YYYY-MM-DD")
    parser.add_argument("--discover-only", action="store_true",
                        help="開催探索だけ実行し、データ収集はしない")
    parser.add_argument("--no-skip", action="store_true",
                        help="既存データがあっても再取得する")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    print(f"🏁 S級レースデータ収集  {start} 〜 {end}")
    print(f"   出力先: {OUT_RACECARD.parent}/")

    scraper = KdreamsScraper()

    # Step 1: 開催リスト探索
    kaisai_list = discover_kaisai_range(start, end, scraper)

    if args.discover_only:
        print(f"\n📋 発見した開催一覧 ({len(kaisai_list)} 件):")
        for k in kaisai_list:
            rd = k['race_date'] if isinstance(k['race_date'], str) else k['race_date'].isoformat()
            print(f"  {rd}  {k['venue_name']:6s}  kaisai={k['kaisai_id']}")
        return

    if not kaisai_list:
        print("⚠️  開催が見つかりませんでした")
        return

    # Step 2: データ収集
    print(f"\n📥 データ収集開始: {len(kaisai_list)} 開催日")
    collect(kaisai_list, scraper, skip_existing=not args.no_skip)


if __name__ == "__main__":
    main()
