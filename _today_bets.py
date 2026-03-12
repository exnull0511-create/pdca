"""今日の勝負判定レースの全買い目表示"""
import os, sys, time
from datetime import datetime, date
from pathlib import Path
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
sys.path.insert(0, str(Path(__file__).parent))
from check_and_notify import load_db, get_race_info, get_odds, run_prediction
from kdreams_scraper import KdreamsScraper
from fetch_schedule import fetch_today_f1_g3_races

today    = date.today()
today_dt = datetime.combine(today, datetime.min.time())
now      = datetime.now()

print("📦 DB読み込み中...")
db_all, db_slim, nobi_col = load_db()
scraper = KdreamsScraper()

print("📡 レース取得中...")
races = fetch_today_f1_g3_races(today, min_grade="F1", fetch_times=True)

# 全レースを判定して勝負ありのみ表示
bet_races = []
for r in races:
    race_card, num_to_line, num_to_bibs = get_race_info(scraper, r['race_url'])
    time.sleep(0.4)
    odds = get_odds(scraper, r['race_url'])
    time.sleep(0.4)
    if race_card.empty or not odds:
        continue
    result = run_prediction(r['venue'], r['race_no'], race_card, num_to_line,
                            num_to_bibs, odds, db_all, db_slim, nobi_col, today_dt)
    if result:
        bet_races.append((r, result, odds, num_to_line))

print(f"\n🎯 本日の勝負判定レース: {len(bet_races)}R\n")
for r, result, odds, num_to_line in bet_races:
    print(f"{'='*60}")
    print(f" 🏁 {r['venue']} {r['race_no']}R  締切{r.get('deadline_str','?')}  {r.get('race_name','')}")
    print(f"   軸: {result['axis']}  EV={result['top_ev']:.1f}")
    print(f"{'─'*60}")
    print(f"  {'組み合わせ':<10}  {'配分':>7}  {'オッズ':>8}")
    print(f"  {'─'*35}")
    for combo, amt in result['bets']:
        o = odds.get(combo, 0)
        print(f"  {combo:<10}  ¥{amt:>6,}  {o:>7.1f}倍")
    print(f"\n  合計: ¥{result['total']:,}  ({len(result['bets'])}点)")
    print()
