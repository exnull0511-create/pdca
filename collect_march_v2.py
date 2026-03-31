"""
collect_march_v2.py
=====================
3月分のS級レースデータを、ブラウザで取得したkaisai_idリストから直接収集する。
fetch_today_f1_g3_races()（＝当日トップページ依存）をバイパスし、
過去の全開催に直接アクセスしてデータを取得。

出力ファイル:
  data/racecard_march.xlsx  — 出走表+ライン
  data/odds_march.xlsx      — 3連単オッズ
  data/payouts_march.xlsx   — 結果・払戻
"""

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

# ── 出力先 ──────────────────────────────────────────────────
OUT_RACECARD = Path("data/racecard_march.xlsx")
OUT_ODDS     = Path("data/odds_march.xlsx")
OUT_PAYOUTS  = Path("data/payouts_march.xlsx")

SLEEP_SEC  = 0.3
MAX_RETRY  = 2
# S級レースは通常5R以降に配置される（1-4RはA級）
RACE_SCAN_START = 5
RACE_SCAN_END   = 12

# ── 会場スラグ対応表 ────────────────────────────────────────
VENUE_SLUG = {
    11: ("函館", "hakodate"), 12: ("青森", "aomori"), 13: ("いわき平", "iwakitaira"),
    21: ("弥彦", "yahiko"), 22: ("前橋", "maebashi"), 23: ("取手", "toride"),
    24: ("宇都宮", "utsunomiya"), 25: ("大宮", "omiya"), 26: ("西武園", "seibuen"),
    27: ("京王閣", "keiokaku"), 28: ("立川", "tachikawa"),
    31: ("松戸", "matsudo"), 32: ("千葉", "chiba"), 34: ("川崎", "kawasaki"),
    35: ("平塚", "hiratsuka"), 36: ("小田原", "odawara"), 37: ("伊東", "ito"),
    38: ("静岡", "shizuoka"),
    42: ("名古屋", "nagoya"), 43: ("岐阜", "gifu"), 44: ("大垣", "ogaki"),
    45: ("豊橋", "toyohashi"), 46: ("富山", "toyama"), 47: ("松阪", "matsusaka"),
    48: ("四日市", "yokkaichi"),
    51: ("福井", "fukui"), 53: ("奈良", "nara"), 54: ("向日町", "mukomachi"),
    55: ("和歌山", "wakayama"), 56: ("岸和田", "kishiwada"),
    61: ("玉野", "tamano"), 62: ("広島", "hiroshima"), 63: ("防府", "hofu"),
    71: ("高松", "takamatsu"), 73: ("小松島", "komatsushima"),
    74: ("高知", "kochi"), 75: ("松山", "matsuyama"),
    81: ("小倉", "kokura"), 83: ("久留米", "kurume"), 84: ("武雄", "takeo"),
    85: ("佐世保", "sasebo"), 86: ("別府", "beppu"), 87: ("熊本", "kumamoto"),
}

# ── 3月の全F1/G3+開催リスト ──────────────────────────────────
# ブラウザで取得したkaisai_idリスト
# 形式: (場コード, 開催開始日YYYYMMDD, 開催日数, グレード)
MARCH_KAISAI = [
    # いわき平
    (13, "20260319", 3, "F1"),
    # 前橋
    (22, "20260307", 3, "F1"),
    # 取手
    (23, "20260312", 4, "G3"),
    (23, "20260319", 3, "F1"),
    # 宇都宮
    (24, "20260304", 3, "F1"),
    (24, "20260309", 4, "F1"),
    (24, "20260317", 3, "F1"),
    # 西武園
    (26, "20260312", 4, "G3"),
    (26, "20260322", 3, "F1"),
    # 京王閣
    (27, "20260301", 3, "F1"),
    # 立川
    (28, "20260307", 3, "F1"),
    (28, "20260322", 3, "F1"),
    # 松戸
    (31, "20260304", 3, "F1"),
    (31, "20260316", 3, "F1"),
    (31, "20260327", 3, "F1"),  # 今日〜のため結果は一部なし
    # 小田原
    (36, "20260303", 3, "F1"),
    (36, "20260326", 3, "F1"),  # 今日〜のため結果は一部なし
    # 静岡
    (38, "20260301", 3, "F1"),
    (38, "20260310", 3, "F1"),
    # 名古屋
    (42, "20260325", 3, "F1"),
    # 岐阜
    (43, "20260307", 3, "F1"),
    (43, "20260322", 3, "F1"),
    # 大垣
    (44, "20260228", 3, "G3"),  # 2/28開始で3月にまたがる
    (44, "20260313", 3, "F1"),
    (44, "20260325", 3, "F1"),
    # 豊橋
    (45, "20260304", 3, "F1"),
    (45, "20260310", 3, "F1"),
    (45, "20260328", 4, "G3"),  # 未来分は除外
    # 松阪
    (47, "20260322", 3, "F1"),
    # 奈良
    (53, "20260227", 3, "F1"),  # 2/27開始
    (53, "20260314", 3, "F1"),
    # 和歌山
    (55, "20260312", 3, "F1"),
    (55, "20260317", 3, "F1"),
    # 岸和田
    (56, "20260301", 3, "F1"),
    (56, "20260325", 3, "F1"),
    # 玉野
    (61, "20260326", 3, "F1"),  # 3/26〜
    # 広島
    (62, "20260228", 3, "F1"),  # 2/28開始
    (62, "20260313", 3, "F1"),
    # 防府
    (63, "20260319", 4, "G2"),
    # 小松島
    (73, "20260301", 3, "F1"),
    # 高知
    (74, "20260310", 3, "F1"),
    (74, "20260316", 3, "F1"),
    (74, "20260324", 3, "F1"),
    # 松山
    (75, "20260305", 4, "G3"),
    (75, "20260313", 3, "F1"),
    # 小倉
    (81, "20260319", 3, "F1"),
    (81, "20260326", 3, "F1"),
    # 久留米
    (83, "20260307", 3, "F1"),
    # 武雄
    (84, "20260309", 3, "F1"),
    (84, "20260319", 3, "F1"),
    # 熊本
    (87, "20260304", 3, "F1"),
    (87, "20260314", 3, "F1"),
]

# ── S級判定 ──────────────────────────────────────────────────
def is_s_class(scraper, race_url):
    """racedetailページのtitleタグに「Ｓ級」or「S級」が含まれるかチェック"""
    try:
        r = scraper.session.get(race_url, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        title = soup.find('title')
        title_txt = title.string if title and title.string else ''
        is_s = bool(re.search(r'[ＳS]級', title_txt))
        # レース名を抽出
        m = re.search(r'\d+R\s+([^\|]+)', title_txt)
        race_name = m.group(1).strip() if m else ''
        return is_s, race_name
    except:
        return False, ''


# ── オッズ取得 ──────────────────────────────────────────────
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


# ── 出走表取得 ──────────────────────────────────────────────
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
                except:
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


# ── 結果取得 ──────────────────────────────────────────────
def scrape_result(scraper, race_url, race_id):
    """racedetailの結果ページから3連単結果を取得"""
    result_url = race_url.rstrip('/') + '/?pageType=result'
    for attempt in range(MAX_RETRY + 1):
        try:
            res = get_race_result(scraper, result_url)
            return res
        except Exception as e:
            if attempt < MAX_RETRY:
                time.sleep(2)
            else:
                return None


# ── メイン ──────────────────────────────────────────────────
def main():
    today = date.today()
    cutoff = date(2026, 3, 27)  # 本日まで（3/27以降のレースは結果なしの可能性）

    print(f"📅 3月S級レースデータ収集 v2")
    print(f"   開催数: {len(MARCH_KAISAI)} 開催")
    print(f"   カットオフ: {cutoff}")

    # 既存データロード（追記用）
    rc_existing = pd.read_excel(OUT_RACECARD, dtype={"race_id": str}) if OUT_RACECARD.exists() else pd.DataFrame()
    od_existing = pd.read_excel(OUT_ODDS,     dtype={"race_id": str}) if OUT_ODDS.exists()     else pd.DataFrame()
    py_existing = pd.read_excel(OUT_PAYOUTS,  dtype={"race_id": str}) if OUT_PAYOUTS.exists()  else pd.DataFrame()

    already_done = set()
    if not rc_existing.empty:
        already_done = set(rc_existing["race_id"].astype(str).unique())
        print(f"   既存データ: {len(already_done)} レース（スキップ対象）")

    scraper = KdreamsScraper()

    all_rc = []
    all_od = []
    all_py = []
    total_ok = total_skip = total_no_result = 0

    for venue_code, start_str, n_days, grade in MARCH_KAISAI:
        venue_name, slug = VENUE_SLUG.get(venue_code, (f"場{venue_code}", f"venue{venue_code}"))

        print(f"\n{'='*60}")
        print(f"📍 {venue_name} [{grade}]  開始={start_str}  {n_days}日間")

        for day_idx in range(n_days):
            from datetime import datetime
            start_date = datetime.strptime(start_str, "%Y%m%d").date()
            race_date = start_date + timedelta(days=day_idx)

            # 3月の範囲外はスキップ
            if race_date.month != 3 or race_date > cutoff:
                continue

            day_count = f"{day_idx + 1:02d}"
            kaisai_id = f"{venue_code:02d}{start_str}{day_count}00"
            race_date_int = int(race_date.strftime("%Y%m%d"))

            print(f"\n  📆 {race_date}  {venue_name}  (kaisai={kaisai_id})")

            # 12レース分をスキャン
            for race_no in range(RACE_SCAN_START, RACE_SCAN_END + 1):
                race_id = f"{kaisai_id}{race_no:02d}"

                if race_id in already_done:
                    total_skip += 1
                    continue

                race_url = f"https://keirin.kdreams.jp/{slug}/racedetail/{race_id}/"

                # S級判定
                is_s, race_name = is_s_class(scraper, race_url)
                time.sleep(SLEEP_SEC)

                if not is_s:
                    continue

                print(f"    {race_no:2d}R  [{race_name[:20]}]")

                # 出走表
                rc_rows = scrape_racecard(scraper, race_url, race_id, venue_name, race_no, race_date_int)
                time.sleep(SLEEP_SEC)
                if not rc_rows:
                    print(f"        ⚠️  出走表なし")
                    continue

                # オッズ
                od_rows = scrape_odds(scraper, race_url, race_id)
                time.sleep(SLEEP_SEC)
                if not od_rows:
                    print(f"        ⚠️  オッズなし")
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
                    print(f"        ✅ {len(rc_rows)}人 {len(od_rows)}点 結果:{res['combo']} ¥{res['payout']:,}")
                    total_ok += 1
                else:
                    py_row = {"race_id": race_id, "result_trifecta": "", "payout_trifecta": 0}
                    all_py.append(py_row)
                    print(f"        ⚠️  結果未取得 {len(rc_rows)}人 {len(od_rows)}点")
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

    rc_final.to_excel(OUT_RACECARD, index=False)
    od_final.to_excel(OUT_ODDS, index=False)
    py_final.to_excel(OUT_PAYOUTS, index=False)

    print(f"\n✅ 完了！")
    print(f"   racecard : {len(rc_final)}行 ({len(rc_final['race_id'].unique())}レース)")
    print(f"   odds     : {len(od_final)}行")
    print(f"   payouts  : {len(py_final)}行")
    print(f"\n次のステップ:")
    print(f"  python run_march_backtest.py --all-strategies")


if __name__ == "__main__":
    main()
