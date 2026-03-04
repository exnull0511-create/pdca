"""
scraper.py — Kdreams スクレイパーモジュール
==========================================
当日レーススケジュール・出走表・ライン・3連単オッズを取得する。
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, date
import pandas as pd

BASE = "https://keirin.kdreams.jp"

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})

# ─── バンク名 → URLスラグ マッピング ─────────────────────────────────────────
VENUE_SLUG = {
    '前橋':   'maebashi', '宇都宮': 'utsunomiya', '豊橋':   'toyohashi',
    '岸和田': 'kishiwada', '熊本':   'kumamoto',   'いわき平':'iwakitaira',
    '広島':   'hiroshima', '別府':   'beppu',      '松山':   'matsuyama',
    '小倉':   'kokura',   '京王閣': 'keiokaku',   '立川':   'tachikawa',
    '取手':   'toride',   '伊東':   'ito',        '久留米': 'kurume',
    '奈良':   'nara',     '岐阜':   'gifu',       '小松島': 'komatsushima',
    '防府':   'hofu',     '静岡':   'shizuoka',   '松阪':   'matsusaka',
    '高知':   'kochi',    '松戸':   'matsudo',    '平塚':   'hiratsuka',
    '西武園': 'seibuyen', '大宮':   'omiya',      '函館':   'hakodate',
    '青森':   'aomori',   '大垣':   'ogaki',      '名古屋': 'nagoya',
}
SLUG_TO_VENUE = {v: k for k, v in VENUE_SLUG.items()}


def get_today_schedule(target_date: date = None) -> list[dict]:
    """
    Kdreams トップページから当日の全race_idを直接収集し、
    各バンク番組ページで発走時刻を補完する。
    Returns: [{'race_id':'...','venue':'...','race_no':N,'start_time':datetime}, ...]
    """
    if target_date is None:
        target_date = date.today()
    date_str = target_date.strftime('%Y%m%d')
    year     = int(date_str[:4])
    month    = int(date_str[4:6])
    day      = int(date_str[6:8])

    try:
        resp = SESSION.get(BASE, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
    except Exception as e:
        print(f"⚠️  トップページ取得失敗: {e}")
        return []

    # ─── Step1: トップページから当日の race_id を全収集 ───────────────────
    race_ids_raw = set()
    for a in soup.find_all('a', href=True):
        m = re.search(r'/racedetail/(\d{16})/', a['href'])
        if m and date_str in m.group(1):
            race_ids_raw.add(m.group(1))

    # kaisaiDateId から venue_slug を検出
    kaisai_to_slug: dict[str, str] = {}
    for a in soup.find_all('a', href=True):
        href = a['href']
        km   = re.search(r'kaisaiDateId=(26' + date_str + r'\d+)', href)
        if not km:
            continue
        kid = km.group(1)
        if kid in kaisai_to_slug:
            continue
        for slug in SLUG_TO_VENUE:
            if f'/{slug}/' in href:
                kaisai_to_slug[kid] = slug
                break

    print(f"📅 {date_str} — トップページ race_id: {len(race_ids_raw)}件  開催バンク: {len(kaisai_to_slug)}場")
    if not race_ids_raw and not kaisai_to_slug:
        print("⚠️  当日開催データなし")
        return []

    # ─── Step2: バンク番組ページから発走時刻を取得 ──────────────────────────
    # race_id → start_time マッピング
    time_map: dict[str, datetime] = {}
    extra_ids: set[str] = set()   # 番組ページで追加発見した race_id

    for kid, slug in kaisai_to_slug.items():
        url = f"{BASE}/{slug}/program/"
        try:
            resp2 = SESSION.get(url, params={'kaisaiDateId': kid}, timeout=10)
            soup2 = BeautifulSoup(resp2.text, 'html.parser')
        except Exception:
            continue

        for a in soup2.find_all('a', href=True):
            rm = re.search(r'/racedetail/(\d{16})/', a['href'])
            if not rm:
                continue
            rid = rm.group(1)
            extra_ids.add(rid)
            if rid in time_map:
                continue
            # 親要素から時刻を探す
            parent = a
            for _ in range(5):
                txt = parent.get_text()
                tm  = re.search(r'(\d{1,2}):(\d{2})', txt)
                if tm:
                    h, mi = int(tm.group(1)), int(tm.group(2))
                    if 8 <= h <= 22:
                        try:
                            time_map[rid] = datetime(year, month, day, h, mi)
                        except ValueError:
                            pass
                        break
                parent = parent.parent if parent.parent else parent

    all_ids = race_ids_raw | extra_ids

    # ─── Step3: race_id → venue / race_no / start_time に変換 ─────────────
    # race_id 例: 2620260304010007 → date=26..0304 / line02 / venue_code?
    # venue は kaisaiDateId とバンクスラグの対応から逆引き
    #   venue_code (race_id先頭2桁) → slug  という直接マッピングは非公式のため、
    #   番組ページで見つかった race_id はそのバンクのもの、と紐付ける
    id_to_slug: dict[str, str] = {}
    for kid, slug in kaisai_to_slug.items():
        for rid in extra_ids:
            if rid in time_map or rid in race_ids_raw:
                # venue_prefix (先頭2桁) でグルーピングを試みる
                pass
        # 番組ページで見つかったIDはそのバンク
    # シンプル実装: race_id のデータ中に含まれるバンク情報は先頭2桁のrace_id prefix
    # 同じ prefix なら同じバンク（経験則）
    prefix_to_slug: dict[str, str] = {}
    for kid, slug in kaisai_to_slug.items():
        # kid = 26YYYYMMDD02xx → 先頭2桁は venue コード (26, 31, 37 等)
        prefix = kid[:2]  # 暫定
        # より確実な方法: 番組ページで見つかったIDの先頭2桁
        for rid in extra_ids:
            if date_str in rid:
                prefix_to_slug[rid[:2]] = slug

    races = []
    seen  = set()
    for rid in sorted(all_ids):
        if rid in seen:
            continue
        seen.add(rid)
        if date_str not in rid:
            continue

        slug    = prefix_to_slug.get(rid[:2], '')
        venue   = SLUG_TO_VENUE.get(slug, '')
        race_no_str = rid[-4:-2]
        race_no = int(race_no_str) if race_no_str.isdigit() else 0
        races.append({
            'race_id':    rid,
            'venue':      venue,
            'race_no':    race_no,
            'venue_slug': slug,
            'start_time': time_map.get(rid),
        })

    races.sort(key=lambda x: (x.get('venue',''), x['race_no']))
    print(f"✅ 合計 {len(races)}R 取得完了")
    for r in races[:5]:
        st = r['start_time'].strftime('%H:%M') if r['start_time'] else '?'
        print(f"   {r['venue']} {r['race_no']}R  発走{st}  {r['race_id']}")
    if len(races) > 5:
        print(f"   ...他{len(races)-5}R")
    return races



def scrape_racecard(race_id: str, venue_slug: str) -> pd.DataFrame:
    """
    racedetail ページから出走表・ライン情報を取得。
    Returns: racecard DataFrame (hardcore_ev.py の race_info 互換)
    """
    url = f"{BASE}/{venue_slug}/racedetail/{race_id}/"
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
    except Exception as e:
        print(f"⚠️  出走表取得失敗 {race_id}: {e}")
        return pd.DataFrame()

    # ── 出走選手テーブル ──
    rows  = []
    table = soup.find('table', class_=re.compile(r'race_?entry|syutsu'))
    if not table:
        table = soup.find('table')

    if table:
        for tr in table.find_all('tr')[1:]:
            tds = tr.find_all('td')
            if len(tds) < 3:
                continue
            try:
                bib_text = re.sub(r'\D', '', tds[0].get_text())
                if not bib_text:
                    continue
                bib     = int(bib_text)
                name    = tds[1].get_text(strip=True)
                score   = float(re.search(r'\d+\.\d+|\d+', tds[-1].get_text() or '80').group())
                rows.append({'車番': bib, '選手名': name, '競走得点': score,
                             '脚質': '', 'race_id': race_id, 'venue': SLUG_TO_VENUE.get(venue_slug,'')})
            except Exception:
                continue

    # ── ライン情報 ──
    line_data = _parse_line_info(soup)
    bib_to_line   = {}
    bib_to_bibs   = {}
    for lno, bibs in line_data.items():
        for b in bibs:
            bib_to_line[b] = lno
            bib_to_bibs[b] = '-'.join(str(x) for x in bibs)

    for r in rows:
        b = r['車番']
        r['line_no']   = bib_to_line.get(b, 0)
        r['line_bibs'] = bib_to_bibs.get(b, str(b))

    df = pd.DataFrame(rows)
    return df


def _parse_line_info(soup: BeautifulSoup) -> dict:
    """line_position div からライン構成を {line_no: [bibs]} で返す"""
    div = soup.find('div', class_='line_position')
    if not div:
        return {}

    lines    = {}
    line_no  = 1
    cur_bibs = []
    seen     = set()

    for span in div.find_all('span', class_='icon_p'):
        if 'space' in span.get('class', []):
            if cur_bibs:
                lines[line_no] = cur_bibs
                line_no += 1
                cur_bibs = []
                seen = set()
            continue
        for child in span.find_all('span'):
            for c in child.get('class', []):
                m = re.match(r'^p0+([1-9])$', c)
                if m:
                    b = int(m.group(1))
                    if b not in seen:
                        seen.add(b)
                        cur_bibs.append(b)

    if cur_bibs:
        lines[line_no] = cur_bibs
    return lines


def scrape_odds(race_id: str, venue_slug: str) -> pd.DataFrame:
    """
    3連単オッズページを取得。
    Returns: DataFrame with columns ['組み合わせ', 'オッズ']
    """
    # Kdreams の3連単オッズURL（typical pattern）
    url = f"{BASE}/{venue_slug}/odds/3t/{race_id}/"
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
    except Exception as e:
        print(f"⚠️  オッズ取得失敗 {race_id}: {e}")
        return pd.DataFrame(columns=['組み合わせ','オッズ'])

    rows = []
    for td in soup.find_all('td', class_=re.compile(r'odds')):
        # 組み合わせ
        combo_el = td.find_previous_sibling('td') or td.find_parent('tr', recursive=False)
        text = td.get_text(strip=True)
        combo_m = re.search(r'(\d)-(\d)-(\d)', text)
        odds_m  = re.search(r'[\d,]+\.?\d*', text)
        if combo_m and odds_m:
            combo = f"{combo_m.group(1)}-{combo_m.group(2)}-{combo_m.group(3)}"
            odds  = float(odds_m.group().replace(',',''))
            rows.append({'組み合わせ': combo, 'オッズ': odds})

    # テーブル全体をパース（別パターン）
    if not rows:
        for tr in soup.find_all('tr'):
            tds = tr.find_all('td')
            if len(tds) >= 2:
                combo_m = re.search(r'(\d)-(\d)-(\d)', tds[0].get_text())
                odds_m  = re.search(r'[\d.]+', tds[-1].get_text())
                if combo_m and odds_m:
                    combo = f"{combo_m.group(1)}-{combo_m.group(2)}-{combo_m.group(3)}"
                    odds  = float(odds_m.group())
                    if odds > 1.0:
                        rows.append({'組み合わせ': combo, 'オッズ': odds})

    df = pd.DataFrame(rows)
    return df
