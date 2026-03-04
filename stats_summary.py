"""
stats_summary.py
================
週次・月次の収支サマリーを集計してDiscordに投稿する。
GitHub Actions の weekly_summary.yml から実行される。

Usage:
  python stats_summary.py weekly   # 週次（直近7日）
  python stats_summary.py monthly  # 月次（今月全体）
"""

import sys
import os
from datetime import date, timedelta
from bet_logger import get_period_summary
from send_discord import send_period_summary


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "weekly"
    today = date.today()

    if mode == "monthly":
        # 今月1日〜今日
        date_from = today.replace(day=1).isoformat()
        date_to   = today.isoformat()
        label = f"{today.year}年{today.month}月"
    else:
        # 直近7日（月曜〜日曜 or 直近7日）
        date_from = (today - timedelta(days=6)).isoformat()
        date_to   = today.isoformat()
        label = f"{date_from} 〜 {date_to}"

    print(f"📊 {mode}サマリー: {date_from} 〜 {date_to}")
    summary = get_period_summary(date_from, date_to, label)
    print(f"   {summary['n_races']}R  {summary['n_hits']}的中  収支{'+'if summary['profit']>=0 else ''}¥{summary['profit']:,}")

    ok = send_period_summary(summary)
    print(f"Discord送信: {'✅' if ok else '⚠️ 失敗'}")


if __name__ == "__main__":
    main()
