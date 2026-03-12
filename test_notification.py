"""
test_notification.py
====================
本日終了済みレース（実データ）を使って
予想 → Discord通知 の通しテストを行うスクリプト。

実行方法:
  python test_notification.py

環境変数:
  DISCORD_WEBHOOK_URL  - 予想通知チャンネルのWebhook URL
"""

import os
import sys
import time
import traceback
from datetime import datetime, date, timedelta

# check_and_notify.py の関数をそのまま使う（本番設定のまま）
from check_and_notify import (
    load_db, get_race_info, get_odds, run_prediction,
)
from fetch_schedule import fetch_today_f1_g3_races
from send_discord import send_prediction
from kdreams_scraper import KdreamsScraper

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

def main():
    now      = datetime.now()
    today    = date.today()
    today_dt = datetime.combine(today, datetime.min.time())

    print(f"🧪 Discord通知エンドツーエンドテスト")
    print(f"⏱  現在時刻: {now.strftime('%H:%M')}")
    print(f"🌐 WEBHOOK: {'✅ 設定あり' if DISCORD_WEBHOOK else '❌ 未設定(DISCORD_WEBHOOK_URL)'}")
    print()

    # ── 当日レース取得 ────────────────────────────────────────────────────────
    print("📡 当日開催を取得中...")
    races = fetch_today_f1_g3_races(today, min_grade="F1", fetch_times=True)
    if not races:
        print("❌ 開催なし or 取得失敗")
        sys.exit(1)

    print(f"  {len(races)}レース取得")

    # ── 終了済みレースを絞り込む（締切が過去のもの）────────────────────────
    ended = [r for r in races if r.get('deadline_time') and r['deadline_time'] < now]
    if not ended:
        print("⚠️  本日の終了済みレースが見つかりません。")
        sys.exit(1)

    # 直近の終了済みレースから順番に試す（最大5レース）
    targets = sorted(ended, key=lambda r: r['deadline_time'], reverse=True)[:5]
    print(f"\n🔍 終了済みから最大{len(targets)}レースを試みます")

    db_all, db_slim, nobi_col = load_db()
    scraper = KdreamsScraper()

    for r in targets:
        venue    = r['venue']
        race_no  = r['race_no']
        race_url = r['race_url']
        deadline = r['deadline_time']

        print(f"\n{'─'*50}")
        print(f"🏁 {venue} {race_no}R  (締切: {r['deadline_str']})")

        try:
            race_card, num_to_line, num_to_bibs = get_race_info(scraper, race_url)
            time.sleep(0.5)
            odds_dict = get_odds(scraper, race_url)
            time.sleep(0.5)

            if race_card is None or race_card.empty:
                print(f"  ⚠️  出走表取得失敗 → スキップ")
                continue
            if not odds_dict:
                print(f"  ⚠️  オッズ取得失敗（終了済みのため取得不可の場合あり）→ スキップ")
                continue

            print(f"  ✅ 出走表: {len(race_card)}名 / オッズ: {len(odds_dict)}点")

            result = run_prediction(
                venue, race_no, race_card, num_to_line, num_to_bibs,
                odds_dict, db_all, db_slim, nobi_col, today_dt
            )

            if result:
                print(f"\n  🎯 勝負判定あり！")
                print(f"     軸: {result['axis']}  EV: {result['top_ev']:.1f}")
                print(f"     買い目: {len(result['bets'])}点  合計: ¥{result['total']:,}")

                # ライン情報を Discord 用に整形
                lines_for_discord = [
                    {'line': lno, 'bibs': [b for b, ln in num_to_line.items() if ln == lno]}
                    for lno in sorted(set(num_to_line.values()))
                ]

                print(f"\n  📤 Discord通知を送信中...")
                ok = send_prediction(
                    venue=venue,
                    race_no=race_no,
                    race_name=r.get('race_name', 'S級') + "【テスト】",
                    start_str=r.get('start_time_str', '?'),
                    deadline_str=r['deadline_str'],
                    mins_left=0,     # 終了済みなので0
                    lines=lines_for_discord,
                    result=result,
                )

                if ok:
                    print(f"  ✅ Discord送信成功！ Discordを確認してください。")
                    return  # 1件成功したら終了
                else:
                    print(f"  ❌ Discord送信失敗（WEBHOOK URL未設定 or エラー）")
                    return

            else:
                print(f"  ⏭️  勝負判定なし（EVフィルタ/カオス除外）")

        except Exception as e:
            print(f"  ⚠️  エラー: {e}")
            traceback.print_exc()

    print(f"\n{'─'*50}")
    print("⚠️  試したレースで全て勝負判定なし（フィルタ除外）でした。")
    print("   これは正常動作の可能性があります（その日のレースが全て除外対象）。")
    print("   DISCORD_WEBHOOK_URL の設定を直接テストしますか？")
    print("   → python send_discord.py  でテスト通知を送信できます")


if __name__ == "__main__":
    main()
