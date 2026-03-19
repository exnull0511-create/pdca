"""
test_hitcheck.py
================
いわき平10R（テスト通知のレース）の当落判定をフル通しでテストする。

実行手順:
  1. いわき平10R の実際の結果を取得
  2. bets_log に test 用 pending エントリを追加
  3. update_result → send_race_result を実行
  4. テストエントリを bets_log から削除（クリーンアップ）
"""

import json
import os
import time
from datetime import date, datetime
from kdreams_scraper import KdreamsScraper
from fetch_results import get_race_result
from bet_logger import update_result, get_daily_summary, _load_all, _save_all, BETS_LOG, COLUMNS
from send_discord import send_race_result
import csv

# ── 設定 ──────────────────────────────────────────────────────────────────────
# テスト通知時の予想内容（いわき平10R 軸:車番2 塩島嵩一朗）
TEST_RACE_ID   = "TEST_1320260309010010"   # テスト専用ID（既存ログと衝突しないよう接頭辞付け）
TEST_VENUE     = "いわき平"
TEST_RACE_NO   = 10
TEST_RACE_NAME = "Ｓ級予選"
TEST_START     = "19:34"

# テスト用購入目（実際の予想結果から12点 ¥2,100）
# 軸=2 で上位12点を仮で設定
TEST_BETS = [
    ["2-1-3", 200], ["2-1-4", 200], ["2-1-5", 200],
    ["2-3-1", 200], ["2-3-4", 100], ["2-4-1", 100],
    ["2-4-3", 100], ["2-5-1", 100], ["2-5-3", 100],
    ["2-6-1", 100], ["2-6-3", 100], ["2-7-1", 100],
]
TEST_TOTAL = sum(a for _, a in TEST_BETS)

RACEDETAIL_URL = "https://keirin.kdreams.jp/iwakitaira/racedetail/1320260309010010/?pageType=result"


def add_test_pending():
    """bets_log にテスト用 pending エントリを追加"""
    rows = _load_all()
    # 既に同じIDがあれば削除して新規追加
    rows = [r for r in rows if r["race_id"] != TEST_RACE_ID]

    test_row = {
        "date":         date.today().isoformat(),
        "race_id":      TEST_RACE_ID,
        "venue":        TEST_VENUE,
        "venue_slug":   "iwakitaira",
        "race_no":      TEST_RACE_NO,
        "race_name":    TEST_RACE_NAME,
        "start_time":   TEST_START,
        "bets_json":    json.dumps(TEST_BETS, ensure_ascii=False),
        "total_bet":    TEST_TOTAL,
        "result_combo": "",
        "payout":       0,
        "profit":       -TEST_TOTAL,
        "status":       "pending",
        "grade":        "☆☆☆",
    }
    rows.append(test_row)
    _save_all(rows)
    print(f"✅ テストエントリ追加: {TEST_RACE_ID}  {len(TEST_BETS)}点  ¥{TEST_TOTAL:,}")


def cleanup_test():
    """bets_log からテストエントリを削除"""
    rows = _load_all()
    rows = [r for r in rows if r["race_id"] != TEST_RACE_ID]
    _save_all(rows)
    print("🗑️  テストエントリを削除しました")


def main():
    print(f"🧪 いわき平10R 当落判定テスト")
    print(f"🌐 WEBHOOK: {'✅' if os.environ.get('DISCORD_WEBHOOK_URL') else '❌ 未設定'}")

    # 1. 実際の結果を取得
    print(f"\n📡 レース結果を取得中: {RACEDETAIL_URL}")
    scraper = KdreamsScraper()
    result  = get_race_result(scraper, RACEDETAIL_URL)

    if not result:
        print("❌ 結果取得失敗（未確定 or ページ形式が異なる）")
        return

    print(f"✅ 確定結果: {result['combo']}  払戻 ¥{result['payout']:,}")

    # 2. テスト pending エントリを追加
    print("\n📝 bets_log にテストエントリを追加...")
    add_test_pending()

    # 3. 当落判定
    print("\n🔍 当落判定を実行...")
    updated = update_result(TEST_RACE_ID, result['combo'], result['payout'])
    if not updated:
        print("❌ update_result 失敗（race_idが見つからない or 状態が不正）")
        cleanup_test()
        return

    # 4. 結果を取得して Discord 通知
    summary = get_daily_summary()
    row = next(
        (r for r in summary['hits'] + summary['misses']
         if r['race_id'] == TEST_RACE_ID), None
    )
    if row:
        hit    = row['status'] == 'hit'
        profit = int(row['profit'])
        payout = int(row['payout'])
        total_today = summary['profit']

        print(f"\n{'🎊 的中！' if hit else '💀 外れ'}")
        print(f"  着順: {result['combo']}  払戻: ¥{payout:,}  収支: {'+' if profit>=0 else ''}¥{profit:,}")

        if os.environ.get('DISCORD_WEBHOOK_URL'):
            print("📤 Discord に当落通知を送信中...")
            ok = send_race_result(
                venue=TEST_VENUE, race_no=TEST_RACE_NO,
                race_name=TEST_RACE_NAME + "【テスト】",
                result_combo=result['combo'],
                payout=payout, hit=hit,
                profit=profit, total_today=total_today,
            )
            print(f"  {'✅ 送信成功' if ok else '❌ 送信失敗'}")
        else:
            print("⚠️  DISCORD_WEBHOOK_URL 未設定のため通知スキップ")
    else:
        print("❌ 結果行が見つかりませんでした")

    # 5. クリーンアップ
    print("\n🗑️  テストエントリをクリーンアップ...")
    cleanup_test()
    print("✅ 完了")


if __name__ == "__main__":
    main()
