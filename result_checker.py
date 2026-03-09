"""
result_checker.py
=================
bets_log.csv の pending レースに対して結果を確認し、
的中/外れを判定して Discord に通知するスタンドアロンスクリプト。

使い方:
  python result_checker.py              # 通常実行
  python result_checker.py --dry-run    # Discord通知なし
  python result_checker.py --expire-old # 当日以外の古いpendingをexpiredに変更
  python result_checker.py --summary    # 全処理後に日次サマリーも送信

開催コード構造（メモ）:
  race_id（16桁）: {場コード2}{初日日付8}{開催日目2}{固定2}{レース番号2}
  kaisai_id（14桁）: race_id の先頭14桁 → raceresult URLに使用
"""

import argparse
import os
import time
from datetime import date, datetime
from pathlib import Path

from kdreams_scraper import KdreamsScraper
from fetch_results import get_race_result
from bet_logger import (
    _load_all, _save_all,
    update_result, get_daily_summary, get_pending_races
)
from send_discord import send_race_result, send_daily_summary


def expire_old_pending():
    """当日以外の date を持つ pending レコードを expired に変更する。"""
    today = date.today().isoformat()
    rows = _load_all()
    changed = 0
    for r in rows:
        if r['status'] == 'pending' and r.get('date', '') != today:
            r['status'] = 'expired'
            r['profit'] = 0  # 期限切れは損益なし
            changed += 1
    if changed:
        _save_all(rows)
        print(f"⏰ {changed}件の古い pending を expired に変更しました")
    else:
        print("📋 古い pending レコードはありませんでした")


def build_result_url(venue_slug: str, race_id: str) -> str:
    """
    racedetail の ?pageType=result URL を構築する。
    """
    if not venue_slug:
        # venue_slug が bets_log に記録されていない場合は空文字を返す
        return ''
    return f"https://keirin.kdreams.jp/{venue_slug}/racedetail/{race_id}/?pageType=result"


def check_results(dry_run: bool = False) -> list[dict]:
    """
    pending レースの結果を確認して Discord に通知する。

    Args:
        dry_run: True の場合 Discord 通知はせず、判定結果のみ表示する

    Returns:
        処理結果のリスト [{race_id, combo, hit, profit, payout}]
    """
    now = datetime.now()
    today = date.today().isoformat()

    pending = get_pending_races()  # 発走から10分以上経過したもの
    today_pending = [p for p in pending if p.get('date', '') == today]

    if not today_pending:
        print("📋 結果確認が必要な pending レースはありません")
        return []

    print(f"\n🔎 結果確認対象: {len(today_pending)}件")
    scraper = KdreamsScraper()
    processed = []

    for pr in today_pending:
        race_id    = pr['race_id']
        venue      = pr['venue']
        venue_slug = pr.get('venue_slug', '')
        race_no    = int(pr['race_no'])
        race_name  = pr.get('race_name', 'S級')
        start_time = pr.get('start_time', '?')

        print(f"\n  🏁 {venue} {race_no}R ({race_id}) 発走:{start_time}")

        # URL 構築
        result_url = build_result_url(venue_slug, race_id)
        if not result_url:
            print(f"     ⚠️  venue_slug が未記録 → スキップ")
            continue

        # 結果取得
        res = get_race_result(scraper, result_url)
        time.sleep(0.5)

        if not res:
            print(f"     ⏳ 結果未確定（または取得失敗）— スキップ")
            continue

        combo  = res['combo']
        payout = res['payout']
        print(f"     ✅ 確定: {combo}  払戻 ¥{payout:,}")

        if dry_run:
            # ドライランは bets_log を更新せず判定だけ表示
            import json
            bets = json.loads(pr['bets_json'])
            hit = any(c == combo for c, _ in bets)
            print(f"     [dry-run] {'🎊 的中' if hit else '💀 外れ'}")
            processed.append({'race_id': race_id, 'combo': combo, 'hit': hit,
                               'payout': payout, 'profit': None})
            continue

        # bets_log を更新
        updated = update_result(race_id, combo, payout)
        if not updated:
            print(f"     ⚠️  update_result 失敗（既に処理済み?）")
            continue

        # Discord 通知
        summary     = get_daily_summary()
        total_today = summary['profit']
        row = next(
            (r for r in summary['hits'] + summary['misses']
             if str(r['race_id']) == str(race_id)), None
        )
        if not row:
            print(f"     ⚠️  結果行が見つからない（サマリー取得失敗）")
            continue

        hit    = row['status'] == 'hit'
        profit = int(row['profit'])

        print(f"     {'🎊 的中！' if hit else '💀 外れ'}  収支: {'+' if profit >= 0 else ''}¥{profit:,}")

        ok = send_race_result(
            venue=venue, race_no=race_no,
            race_name=race_name,
            result_combo=combo,
            payout=int(row['payout']),
            hit=hit,
            profit=profit,
            total_today=total_today,
        )
        print(f"     Discord: {'✅ 送信済' if ok else '⚠️ 送信失敗'}")

        processed.append({
            'race_id': race_id, 'combo': combo, 'hit': hit,
            'payout': int(row['payout']), 'profit': profit
        })

    return processed


def main():
    parser = argparse.ArgumentParser(description='本日のpendingレース結果を確認してDiscordに通知')
    parser.add_argument('--dry-run',    action='store_true', help='Discord通知なし（確認のみ）')
    parser.add_argument('--expire-old', action='store_true', help='当日以外の古いpendingをexpiredに変更')
    parser.add_argument('--summary',    action='store_true', help='全処理後に日次サマリーも送信')
    args = parser.parse_args()

    webhook_ok = bool(os.environ.get('DISCORD_WEBHOOK_URL'))
    print(f"🏁 result_checker 起動")
    print(f"   WEBHOOK: {'✅ 設定済' if webhook_ok else '❌ 未設定（通知スキップ)'}")
    print(f"   モード: {'DRY-RUN' if args.dry_run else '通常'}")

    if args.expire_old:
        expire_old_pending()

    results = check_results(dry_run=args.dry_run)

    hits   = [r for r in results if r.get('hit')]
    misses = [r for r in results if not r.get('hit')]
    print(f"\n📊 本回処理: {len(results)}件  的中:{len(hits)}件  外れ:{len(misses)}件")

    if args.summary and not args.dry_run:
        summary = get_daily_summary()
        if summary.get('n_races', 0) > 0:
            print(f"\n📤 日次サマリーを送信...")
            send_daily_summary(summary)


if __name__ == '__main__':
    main()
