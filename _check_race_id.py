"""race_id確認スクリプト"""
from datetime import date
from fetch_schedule import fetch_today_f1_g3_races
today = date(2026, 3, 9)
races = fetch_today_f1_g3_races(today, min_grade="F1", fetch_times=True)
for r in races:
    if "いわき" in r.get("venue", ""):
        print(r["race_no"], r["race_id"], r["race_url"])
