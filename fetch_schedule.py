"""
fetch_schedule.py v2
====================
既存 KdreamsScraper を活用した当日 F1/G3+ 全レース情報取得。

keirinbusines/kdreams_scraper.py の実装をベースに:
  - dl.race_list → 会場名・グレード・racecard URL 取得
  - racecard URL の kaisai_id から race_id を計算（1R〜12R）
  - 各 racedetail ページから発走時刻・投票締切時刻を取得

使い方:
  python fetch_schedule.py               → 当日全開催
  python fetch_schedule.py --grade G3    → G3以上のみ
  python fetch_schedule.py --save schedule.json
"""

import sys
import re
import json
import time
import argparse
from datetime import date, datetime
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# ── keirinbusines の既存スクレイパーを利用 ────────────────────────────────
from kdreams_scraper import KdreamsScraper

BASE = "https://keirin.kdreams.jp"

# グレードクラス対応表（Kdreamsトップページ dl.race_list の li.icon_grade クラス）
# ★ 実測確認済み:
#   gr1 = F2（夜間・下位グレード） → 除外対象
#   gr2 = F1（通常開催）           → 対象
#   gr3 = G3（記念競輪）           → 対象
#   gr4 = G2                       → 対象
#   gr5 = G1 / GP                  → 対象
GR_CLASS_TO_GRADE = {
    'gr5': 'G1', 'gr4': 'G2', 'gr3': 'G3',
    'gr2': 'F1',
    'gr1': 'F2',  # F2: 除外
}
EXCLUDED_GRADES = {'F2'}


def get_venues_today(scraper: KdreamsScraper) -> list[dict]:
    """
    Kdреamsトップページの dl.race_list から当日開催場を解析する。
    Returns: [{"venue":str, "grade":str, "slug":str, "racecard_url":str}]
    """
    r    = scraper.session.get(BASE, timeout=15)
    soup = BeautifulSoup(r.text, 'html.parser')

    result = []
    for rl in soup.find_all('dl', class_='race_list'):
        # 会場名
        p_vel = rl.find('p', class_='velodrome')
        if not p_vel:
            continue
        venue = p_vel.get_text(strip=True)

        # グレード（li.icon_grade の gr* クラスで判定）
        grade_li = rl.find('li', class_='icon_grade')
        grade = 'F1'
        if grade_li:
            for cls in grade_li.get('class', []):
                if cls in GR_CLASS_TO_GRADE:
                    grade = GR_CLASS_TO_GRADE[cls]
                    break

        # 現在発売中の racecard URL（current div）
        cur = rl.find('div', class_='current')
        if not cur:
            continue
        a_card = cur.find('a', href=lambda h: h and '/racecard/' in h)
        if not a_card:
            continue
        rc_url = a_card['href']
        if not rc_url.startswith('http'):
            rc_url = BASE.rstrip('/') + rc_url

        # スラグをURLpathから抽出
        m = re.search(r'/([\w]+)/racecard/', rc_url)
        slug = m.group(1) if m else VENUE_SLUG.get(venue, venue.lower())

        result.append({
            'venue': venue, 'grade': grade,
            'slug': slug, 'racecard_url': rc_url,
        })

    return result

VENUE_SLUG = {
    "前橋":"maebashi","宇都宮":"utsunomiya","豊橋":"toyohashi",
    "岸和田":"kishiwada","熊本":"kumamoto","いわき平":"iwakitaira",
    "広島":"hiroshima","別府":"beppu","松山":"matsuyama",
    "小倉":"kokura","京王閣":"keiokaku","立川":"tachikawa",
    "取手":"toride","伊東":"ito","久留米":"kurume",
    "奈良":"nara","岐阜":"gifu","小松島":"komatsushima",
    "防府":"hofu","静岡":"shizuoka","松阪":"matsusaka",
    "高知":"kochi","松戸":"matsudo","平塚":"hiratsuka",
    "西武園":"seibuyen","大宮":"omiya","函館":"hakodate",
    "青森":"aomori","大垣":"ogaki","名古屋":"nagoya","弥彦":"yahiko",
}


def get_start_and_deadline(scraper: KdreamsScraper,
                            race_url: str,
                            year: int, month: int, day: int
                            ) -> tuple[datetime | None, datetime | None]:
    """
    racedetail ページから発走予定時刻・投票締切時刻を取得する。
    ページ上の「発走予定 14:16」「投票締切 14:11」を検索。
    Returns: (start_time, deadline_time) as datetime or None
    """
    try:
        r    = scraper.session.get(race_url, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')

        # ページ全体のテキストから時刻パターンを探す
        txt  = soup.get_text(separator=' ')

        start_dt    = None
        deadline_dt = None

        # 「発走予定 HH:MM」 or「発走 HH:MM」
        m = re.search(r'発走(?:予定)?\s*(\d{1,2}):(\d{2})', txt)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            if 8 <= h <= 22:
                start_dt = datetime(year, month, day, h, mi)

        # 「投票締切 HH:MM」 or「締切 HH:MM」
        m2 = re.search(r'(?:投票)?締切\s*(\d{1,2}):(\d{2})', txt)
        if m2:
            h, mi = int(m2.group(1)), int(m2.group(2))
            if 8 <= h <= 22:
                deadline_dt = datetime(year, month, day, h, mi)

        return start_dt, deadline_dt

    except Exception:
        return None, None


def fetch_today_f1_g3_races(target_date: date = None,
                              min_grade: str = "F1",
                              fetch_times: bool = True
                              ) -> list[dict]:
    """
    当日の F1/G3+ の全レース情報を取得する。

    Args:
        target_date: 対象日（省略時=今日）
        min_grade:   "F1"=F1以上, "G3"=G3以上のみ
        fetch_times: True=各レースの発走時刻をracedetailページから取得

    Returns:
        リスト of dict:
          venue, grade, race_no, race_id,
          race_url, start_time, deadline_time, start_time_str, deadline_str,
          venue_slug
    """
    if target_date is None:
        target_date = date.today()

    year, month, day = target_date.year, target_date.month, target_date.day
    scraper = KdreamsScraper()

    # ── Step1: 当日開催場一覧を取得（grクラス対応表ベース）──────────────────
    print(f"\n🔍 {target_date} の開催場一覧を取得中...")
    venues_today = get_venues_today(scraper)
    print(f"   → {len(venues_today)}場 取得")

    if not venues_today:
        print("⚠️  当日開催なし or 取得失敗")
        return []

    # ── Step2: グレードフィルタ ────────────────────────────────────────────
    GRADE_RANK = {'GP':0,'G1':1,'G2':2,'G3':3,'F1':4}
    MIN_RANK   = 4 if min_grade == 'F1' else 3  # G3以上=rank<=3

    filtered = []
    for v in venues_today:
        grade = v.get('grade', 'F1')
        # F2（gr1クラス）は除外
        if grade in EXCLUDED_GRADES:
            print(f"   ⏭️  {v['venue']} [{grade}] → F2除外")
            continue
        rank = GRADE_RANK.get(grade, 4)
        if rank > MIN_RANK:
            print(f"   ⏭️  {v['venue']} [{grade}] → グレード除外")
            continue
        filtered.append(v)

    print(f"\n対象: {len(filtered)}場")
    for v in filtered:
        print(f"   {v['venue']} [{v['grade']}]  {v['racecard_url'][:60]}")

    # ── Step3: 各開催場の全レース（1R〜12R）を生成 ─────────────────────────
    all_races: list[dict] = []

    for venue_info in filtered:
        venue     = venue_info['venue']
        grade     = venue_info['grade']
        rc_url    = venue_info['racecard_url']
        slug      = venue_info['slug']

        # get_all_races_from_venue で 1R〜12R の URL を生成
        race_list = scraper.get_all_races_from_venue(rc_url)
        if not race_list:
            print(f"⚠️  {venue}: レースURL生成失敗")
            continue

        print(f"\n📋 {venue} [{grade}]  {len(race_list)}R")

        for r in race_list:
            race_no  = r['race_number']
            race_id  = r['race_id']
            race_url = r['url']

            entry = {
                'venue':        venue,
                'grade':        grade,
                'venue_slug':   slug,
                'race_no':      race_no,
                'race_id':      race_id,
                'race_url':     race_url,
                'start_time':   None,
                'deadline_time': None,
                'start_time_str': '?',
                'deadline_str': '?',
            }
            all_races.append(entry)

        # ── Step4: racedetailページ情報取得（発走時刻・S級判定）────────────
        # ★ titleタグに「Ｓ級予選」「Ｓ級選抜」等が含まれるレースのみ残す
        print(f"   ⏱️  racedetailページから情報取得中...")
        venue_entries = [r for r in all_races if r['venue'] == venue]
        s_class_entries = []

        for entry in venue_entries:
            try:
                r2   = scraper.session.get(entry['race_url'], timeout=10)
                soup = BeautifulSoup(r2.text, 'html.parser')

                # ── S級判定: titleタグに「Ｓ級」or「S級」が含まれるか ──
                title_tag = soup.find('title')
                title_txt = title_tag.string if title_tag and title_tag.string else ''
                is_s = bool(re.search(r'[ＳS]級', title_txt))

                if not is_s:
                    print(f"      {entry['race_no']:2d}R  ⏭️  S級以外 [{title_txt[title_txt.find('R')+1:title_txt.find('|',title_txt.find('R'))].strip()[:20]}]")
                    time.sleep(0.3)
                    continue  # S級以外は除外

                # ── 発走時刻・締切時刻 ──────────────────────────────────
                txt = soup.get_text(separator=' ')
                start_dt = deadline_dt = None
                m = re.search(r'発走(?:予定)?\s*(\d{1,2}):(\d{2})', txt)
                if m:
                    h, mi = int(m.group(1)), int(m.group(2))
                    if 8 <= h <= 22:
                        start_dt = datetime(year, month, day, h, mi)
                m2 = re.search(r'(?:投票)?締切\s*(\d{1,2}):(\d{2})', txt)
                if m2:
                    h, mi = int(m2.group(1)), int(m2.group(2))
                    if 8 <= h <= 22:
                        deadline_dt = datetime(year, month, day, h, mi)

                if start_dt:
                    entry['start_time']     = start_dt
                    entry['start_time_str'] = start_dt.strftime('%H:%M')
                if deadline_dt:
                    entry['deadline_time'] = deadline_dt
                    entry['deadline_str']  = deadline_dt.strftime('%H:%M')

                # レース名をtitleから抽出
                m_name = re.search(r'\d+R\s+([^\|]+)', title_txt)
                race_name = m_name.group(1).strip() if m_name else ''
                entry['race_name'] = race_name

                print(f"      {entry['race_no']:2d}R  ✅  [{race_name[:20]}]  発走{entry['start_time_str']}  締切{entry['deadline_str']}")
                s_class_entries.append(entry)
                time.sleep(0.3)

            except Exception as e:
                print(f"      {entry['race_no']:2d}R  ⚠️  エラー: {e}")
                time.sleep(0.3)

        # S級以外をall_racesから取り除いてS級のみ追加し直す
        for entry in venue_entries:
            if entry in all_races:
                all_races.remove(entry)
        all_races.extend(s_class_entries)


    # ── ソート（発走時刻順 → 会場 → レース番号）──────────────────────────
    all_races.sort(key=lambda x: (
        x.get('start_time') or datetime(year, month, day, 23, 59),
        x['venue'], x['race_no']
    ))

    print(f"\n✅ 合計 {len(all_races)}R 取得完了")
    print("   内訳: " + ", ".join(
        f"{v}({sum(1 for r in all_races if r['venue']==v)}R)"
        for v in dict.fromkeys(r['venue'] for r in all_races)
    ))
    return all_races


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="当日F1/G3+レース一覧取得")
    parser.add_argument("--date",  type=str, default=None,
                        help="対象日 YYYY-MM-DD")
    parser.add_argument("--grade", type=str, default="F1",
                        choices=["F1","G3"])
    parser.add_argument("--no-times", action="store_true",
                        help="発走時刻を取得しない（高速）")
    parser.add_argument("--save",  type=str, default=None,
                        help="JSON保存先パス")
    args = parser.parse_args()

    target = (datetime.strptime(args.date, "%Y-%m-%d").date()
              if args.date else date.today())

    races = fetch_today_f1_g3_races(
        target, min_grade=args.grade,
        fetch_times=not args.no_times
    )

    if args.save:
        out = []
        for r in races:
            row = {k: v for k, v in r.items() if k not in ('start_time','deadline_time')}
            out.append(row)
        Path(args.save).write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"💾 JSON保存: {args.save}")
