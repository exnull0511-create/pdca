"""
fetch_results.py
================
KdreamsScraper を使ってレース結果（3連単払戻）を取得する。
"""

import re
import time
from bs4 import BeautifulSoup


def get_race_result(scraper, race_url: str) -> dict | None:
    """
    racedetailページから3連単の確定結果を取得する。

    Returns:
        {'combo': '5-1-7', 'payout': 420}  (100円あたりの払戻)
        None  (未確定 or 取得失敗)
    """
    try:
        r    = scraper.session.get(race_url, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        txt  = soup.get_text(separator=' ', strip=True)

        # 「確定」テキストがなければ未確定
        if '確定' not in txt and '払戻' not in txt:
            return None

        # 3連単の払戻パターン: 「3連単 X-X-X XX,XXX円」or「3連単 X-X-X 1,234」
        m = re.search(
            r'3連単[^\d]*(\d)[-−](\d)[-−](\d)[^\d]*?([\d,]+)',
            txt
        )
        if m:
            combo  = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            payout = int(m.group(4).replace(',', ''))
            return {'combo': combo, 'payout': payout}

        # 別パターン: 払戻テーブルから探す
        for table in soup.find_all('table'):
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                row_text = ' '.join(c.get_text(strip=True) for c in cells)
                m2 = re.search(r'3連単', row_text)
                if m2:
                    combo_m  = re.search(r'(\d)[-−](\d)[-−](\d)', row_text)
                    payout_m = re.search(r'([\d,]{3,})', row_text)
                    if combo_m and payout_m:
                        combo  = f"{combo_m.group(1)}-{combo_m.group(2)}-{combo_m.group(3)}"
                        payout = int(payout_m.group(1).replace(',', ''))
                        return {'combo': combo, 'payout': payout}

        return None

    except Exception as e:
        print(f"⚠️  結果取得エラー: {e}")
        return None
