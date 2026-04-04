"""
fetch_kaisai_list.py
====================
Kドリームスから任意期間の競輪開催リスト（kaisai）を自動探索する。

race_id の構造を利用し、各日付 × 各会場をプローブして有効な開催を発見する。
race_id: {venue_code:02d}{event_start_YYYYMMDD}{day_index:02d}00{race_no:02d}

使い方:
  python fetch_kaisai_list.py --start 2026-01-01 --end 2026-03-31
  python fetch_kaisai_list.py --start 2026-01-01 --end 2026-03-31 --out data/kaisai_list.json
"""

import argparse
import json
import time
import re
from datetime import date, timedelta
from pathlib import Path

from kdreams_scraper import KdreamsScraper

# ── 会場コード・スラグ対応表 ──────────────────────────────────
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

SLEEP_SEC = 0.3          # リクエスト間隔
MAX_EVENT_DAYS = 7       # 開催は最長7日（通常3-4日）
PROBE_RACE_NO = 7        # プローブ用レース番号（S級帯の中央）


def _build_race_url(slug: str, race_id: str) -> str:
    return f"https://keirin.kdreams.jp/{slug}/racedetail/{race_id}/"


def _is_valid_race_page(resp) -> bool:
    """HTTP応答が有効なレースページかどうかを判定"""
    if resp.status_code != 200:
        return False
    # リダイレクトでトップページに飛ばされた場合を除外
    if '/racedetail/' not in resp.url:
        return False
    # ページ内にレース情報があるか確認
    if 'race_info' in resp.text or '車番' in resp.text or '選手名' in resp.text:
        return True
    return False


def discover_kaisai_for_date(
    target_date: date,
    scraper: KdreamsScraper,
    known_events: dict | None = None,
) -> list[dict]:
    """
    特定の日付に開催されていた全会場を探索する。

    known_events: {(venue_code, start_date_str): n_days} の辞書。
                  すでに発見済みの開催情報。ヒットしたらプローブをスキップできる。
    """
    if known_events is None:
        known_events = {}

    results = []

    for venue_code, (venue_name, slug) in VENUE_SLUG.items():
        found = False

        # すでに発見済みの開催に含まれるか確認
        for (kvc, kstart), kdays in known_events.items():
            if kvc != venue_code:
                continue
            start_d = _parse_date(kstart)
            if start_d <= target_date < start_d + timedelta(days=kdays):
                day_idx = (target_date - start_d).days + 1
                kaisai_id = f"{venue_code:02d}{kstart}{day_idx:02d}00"
                results.append({
                    "venue_code": venue_code,
                    "venue_name": venue_name,
                    "slug": slug,
                    "kaisai_id": kaisai_id,
                    "start_date": kstart,
                    "day_index": day_idx,
                    "race_date": target_date,
                })
                found = True
                break
        if found:
            continue

        # 開催初日の候補を探索（当日〜最大MAX_EVENT_DAYS日前）
        for offset in range(MAX_EVENT_DAYS):
            candidate_start = target_date - timedelta(days=offset)
            start_str = candidate_start.strftime("%Y%m%d")
            day_idx = offset + 1
            kaisai_id = f"{venue_code:02d}{start_str}{day_idx:02d}00"
            race_id = f"{kaisai_id}{PROBE_RACE_NO:02d}"
            url = _build_race_url(slug, race_id)

            try:
                resp = scraper.session.get(url, timeout=10, allow_redirects=True)
                time.sleep(SLEEP_SEC)
            except Exception:
                time.sleep(SLEEP_SEC)
                continue

            if _is_valid_race_page(resp):
                results.append({
                    "venue_code": venue_code,
                    "venue_name": venue_name,
                    "slug": slug,
                    "kaisai_id": kaisai_id,
                    "start_date": start_str,
                    "day_index": day_idx,
                    "race_date": target_date,
                })
                # 開催日数を推定してキャッシュに登録
                n_days_est = _estimate_event_days(
                    scraper, venue_code, slug, start_str, day_idx
                )
                known_events[(venue_code, start_str)] = n_days_est
                break

    return results


def _estimate_event_days(
    scraper: KdreamsScraper, venue_code: int, slug: str,
    start_str: str, known_day_idx: int,
) -> int:
    """開催日数を前方プローブで推定（最大7日）"""
    max_days = known_day_idx
    for di in range(known_day_idx + 1, MAX_EVENT_DAYS + 1):
        kaisai_id = f"{venue_code:02d}{start_str}{di:02d}00"
        race_id = f"{kaisai_id}{PROBE_RACE_NO:02d}"
        url = _build_race_url(slug, race_id)
        try:
            resp = scraper.session.get(url, timeout=8, allow_redirects=True)
            time.sleep(SLEEP_SEC)
        except Exception:
            break
        if _is_valid_race_page(resp):
            max_days = di
        else:
            break
    return max_days


def discover_kaisai_range(
    start_date: date,
    end_date: date,
    scraper: KdreamsScraper | None = None,
) -> list[dict]:
    """
    指定期間内の全開催を探索する。

    Returns:
        kaisai ごとに1件の dict（同一 kaisai_id は1回だけ）。
        各要素: {venue_code, venue_name, slug, kaisai_id, start_date,
                 day_index, race_date, n_days}
    """
    if scraper is None:
        scraper = KdreamsScraper()

    total_days = (end_date - start_date).days + 1
    known_events: dict[tuple[int, str], int] = {}  # (venue_code, start_str) -> n_days
    all_kaisai: dict[str, dict] = {}  # kaisai_id -> info

    print(f"🔍 開催探索: {start_date} 〜 {end_date}  ({total_days}日間)")
    print(f"   会場数: {len(VENUE_SLUG)}  最大プローブ: {total_days * len(VENUE_SLUG)} 回")

    for i, d_offset in enumerate(range(total_days)):
        current = start_date + timedelta(days=d_offset)
        found = discover_kaisai_for_date(current, scraper, known_events)
        venues = [f"{r['venue_name']}" for r in found]
        new_count = 0
        for r in found:
            if r['kaisai_id'] not in all_kaisai:
                all_kaisai[r['kaisai_id']] = r
                new_count += 1
        if found:
            print(f"  [{i+1}/{total_days}] {current}  "
                  f"{len(found)}会場  新規{new_count}件  ({', '.join(venues)})")
        else:
            print(f"  [{i+1}/{total_days}] {current}  開催なし")

    result = sorted(all_kaisai.values(),
                    key=lambda x: (x['race_date'].isoformat(), x['venue_code']))
    print(f"\n✅ 探索完了: {len(result)} 開催日（ユニーク kaisai_id）")
    return result


def _parse_date(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


# ── CLI ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Kドリームス 開催リスト自動探索")
    parser.add_argument("--start", required=True, help="開始日 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="終了日 YYYY-MM-DD")
    parser.add_argument("--out", default=None,
                        help="出力先 JSON (省略時は stdout)")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    scraper = KdreamsScraper()
    kaisai_list = discover_kaisai_range(start, end, scraper)

    # JSON シリアライズ用に date を文字列に変換
    for k in kaisai_list:
        k['race_date'] = k['race_date'].isoformat()

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(kaisai_list, f, ensure_ascii=False, indent=2)
        print(f"\n📁 保存: {out_path}  ({len(kaisai_list)} 件)")
    else:
        print(json.dumps(kaisai_list, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
