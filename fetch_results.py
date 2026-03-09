"""
fetch_results.py
================
KdreamsScraper を使ってレース結果（3連単払戻）を取得する。

URL構造（開催コード仕様）:
  race_id（16桁）: {場コード2}{初日日付8}{開催日目2}{固定2}{レース番号2}
    例: 1320260309010010 → いわき平 / 2026年3月9日1日目開催 / 10R

  kaisai_id（14桁）: race_id の先頭14桁 → raceresult URL に使用
    例: 13202603090100

取得方式:
  raceresult/{kaisai_id}/ ページから当該 race_id のliブロックを特定し、
  3連単払戻を正規表現で取得する。
"""

import re
import time
from bs4 import BeautifulSoup


def race_id_to_kaisai_id(race_id: str) -> str:
    """
    race_id（16桁）から kaisai_id（先頭14桁）を返す。
    raceresult URL の構築に使用。
    """
    return str(race_id)[:14]


def get_race_result(scraper, race_url: str) -> dict | None:
    """
    レース結果（3連単払戻）を取得する。

    race_url は racedetail URL 形式で渡す:
      https://keirin.kdreams.jp/{venue_slug}/racedetail/{race_id}/

    内部では raceresult/{kaisai_id}/ エンドポイントを参照し、
    race_id に対応する li ブロックから3連単払戻を取得する。

    Returns:
        {'combo': '3-1-7', 'payout': 3730}  (100円あたりの払戻)
        None  (未確定 or 取得失敗)
    """
    try:
        # URLから venue_slug と race_id を抽出
        m = re.search(r'keirin\.kdreams\.jp/([^/]+)/racedetail/(\d+)', race_url)
        if not m:
            print(f"⚠️  URLパース失敗: {race_url}")
            return None
        venue_slug = m.group(1)
        race_id    = m.group(2)
        kaisai_id  = race_id_to_kaisai_id(race_id)

        result_page_url = f"https://keirin.kdreams.jp/{venue_slug}/raceresult/{kaisai_id}/"

        r    = scraper.session.get(result_page_url, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')

        # ── 対象レースの li ブロックを特定 ────────────────────────────────
        # raceresult ページでは各レースが <li> 内に入っており、
        # そのレースへのリンク（KS_RACE_CARD_PAGE_TYPE_SHOW_RESULT）が目印
        target_href_pattern = f'/{venue_slug}/racedetail/{race_id}/'
        link = soup.find(
            'a',
            href=lambda h: h and race_id in h and 'KS_RACE_CARD_PAGE_TYPE_SHOW_RESULT' in h
        )

        if not link:
            # フォールバック: 任意のリンクで対象 race_id の li を探す
            link = soup.find('a', href=lambda h: h and target_href_pattern in h)

        if not link:
            print(f"⚠️  {race_id} のブロックが raceresult ページ内に見つかりません")
            return None

        parent_li = link.find_parent('li')
        if not parent_li:
            return None

        li_text = parent_li.get_text(separator=' ', strip=True)

        # ── 3連単払戻の正規表現 ────────────────────────────────────────────
        # フォーマット例: 「単 3-1-7 3,730円」
        # ※ 「単」は 2車単・3連単… の最後の「単」なので末尾側から探す
        m_payout = re.search(
            r'単\s+(\d)-(\d)-(\d)\s+([\d,]+)円',
            li_text
        )
        if m_payout:
            combo  = f"{m_payout.group(1)}-{m_payout.group(2)}-{m_payout.group(3)}"
            payout = int(m_payout.group(4).replace(',', ''))
            if payout > 100:   # 最低払戻100円以上
                return {'combo': combo, 'payout': payout}

        # フォールバック: 「X-X-X \n数字円」 の緩いパターン
        m2 = re.search(r'(\d)-(\d)-(\d)\s+([\d,]+)円', li_text)
        if m2:
            combo  = f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}"
            payout = int(m2.group(4).replace(',', ''))
            if payout > 100:
                return {'combo': combo, 'payout': payout}

        # 「未確定」の場合は li_text に着順データが入っていない
        return None

    except Exception as e:
        print(f"⚠️  結果取得エラー: {e}")
        return None
