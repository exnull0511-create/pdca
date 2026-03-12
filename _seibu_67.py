"""西武園 6R・7R の全買い目確認"""
import os, sys, time
import pandas as pd
from datetime import datetime, date
from pathlib import Path

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
os.environ.setdefault('PYTHONUTF8', '1')

sys.path.insert(0, str(Path(__file__).parent))
from check_and_notify import load_db, get_race_info, get_odds, run_prediction
from kdreams_scraper import KdreamsScraper
from fetch_schedule import fetch_today_f1_g3_races

today    = date.today()
today_dt = datetime.combine(today, datetime.min.time())
now      = datetime.now()

print("📦 DB 読み込み中...")
db_all, db_slim, nobi_col = load_db()
scraper = KdreamsScraper()

print("📡 スケジュール取得中...")
races = fetch_today_f1_g3_races(today, min_grade="F1", fetch_times=True)

targets = [r for r in races if r['venue'] == '西武園' and r['race_no'] in [6, 7]]

for r in targets:
    venue   = r['venue']
    race_no = r['race_no']
    print(f"\n{'='*60}")
    print(f" 🏁 {venue} {race_no}R  締切{r.get('deadline_str','?')}")
    print(f"{'='*60}")

    race_card, num_to_line, num_to_bibs = get_race_info(scraper, r['race_url'])
    time.sleep(0.5)
    odds_dict = get_odds(scraper, r['race_url'])
    time.sleep(0.5)

    result = run_prediction(
        venue, race_no, race_card, num_to_line, num_to_bibs,
        odds_dict, db_all, db_slim, nobi_col, today_dt
    )

    if result:
        axis   = result.get('axis', '?')
        top_ev = result.get('top_ev', 0)
        bets   = result.get('bets', [])
        total  = result.get('total', 0)
        print(f"  軸: {axis}  top_ev={top_ev:.2f}")
        print(f"  {'組み合わせ':<10}  {'配分':>7}  {'オッズ':>8}")
        print(f"  {'─'*35}")
        for combo, amt in bets:
            o = odds_dict.get(combo, 0)
            print(f"  {combo:<10}  ¥{amt:>6,}  {o:>7.1f}倍")
        print(f"\n  合計投資: ¥{total:,}  ({len(bets)}点)")
    else:
        print(f"  ⏭️ スキップ")
