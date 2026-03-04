"""
Kドリームス競輪スクレイピングモジュール
requests + BeautifulSoup4を使用したHTTPベースのスクレイピング
"""
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
from typing import Dict, List, Tuple, Optional
from datetime import datetime


class KdreamsScraper:
    """Kドリームスのスクレイピングクラス"""
    
    BASE_URL = "https://keirin.kdreams.jp"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def get_races(self, date_type: str = "today") -> List[Dict]:
        """
        指定日のレース一覧を取得
        
        Args:
            date_type: "today" (本日) または "yesterday" (前日)
        
        Returns:
            レース情報のリスト [{"name": "熊本 1R", "url": "...", "grade": "GI"}]
        """
        try:
            response = self.session.get(self.BASE_URL, timeout=10)
            response.raise_for_status()
            time.sleep(1)
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            races = []
            
            # 開催レース一覧のセクションを探す (race_list クラス)
            race_lists = soup.find_all('dl', class_='race_list')
            
            for race_list in race_lists:
                # 競輪場名を取得
                velodrome_elem = race_list.find('p', class_='velodrome')
                if not velodrome_elem:
                    continue
                    
                velodrome_name = velodrome_elem.get_text(strip=True)
                
                # Gradeアイコンを取得
                grade_icon = race_list.find('li', class_=lambda c: c and 'icon_grade' in ' '.join(c) if isinstance(c, list) else False)
                grade = "F級"
                if grade_icon:
                    grade_text = grade_icon.get_text(strip=True)
                    if grade_text:
                        grade = grade_text
                
                # 日付タイプに応じてセクションを選択
                if date_type == "yesterday":
                    # 前日: rPrev内のリンクを探す
                    target_section = race_list.find('ul', class_='rPrev')
                    if not target_section:
                        continue
                    
                    # 結果リンクを探す（class="res"）
                    result_link = target_section.find('a', class_='res')
                    if not result_link:
                        continue
                    
                    race_url = result_link.get('href', '')
                    if race_url and not race_url.startswith('http'):
                        race_url = self.BASE_URL.rstrip('/') + race_url
                    
                    # 日程情報
                    day_elem = target_section.find('li')
                    day_info = day_elem.get_text(strip=True) if day_elem else ""
                    
                    race_status = "結果"
                    race_time = ""
                    
                else:  # today
                    # 本日: 元のロジックを使用（currentクラス）
                    current_div = race_list.find('div', class_='current')
                    if not current_div:
                        continue
                    
                    # 出走表リンクを取得
                    racecard_link = current_div.find('a', href=lambda h: h and ('/racecard/' in h or '/AllRaceList.do' in h))
                    if not racecard_link:
                        continue
                    
                    race_url = racecard_link.get('href', '')
                    if race_url and not race_url.startswith('http'):
                        race_url = self.BASE_URL.rstrip('/') + race_url
                    
                    # レース状態を取得
                    status_elem = current_div.find('span', class_='race')
                    race_status = status_elem.get_text(strip=True) if status_elem else ""
                    
                    # 締切時刻を取得
                    time_elem = current_div.find('span', class_='num')
                    race_time = time_elem.get_text(strip=True) if time_elem else ""
                    
                    # 日程情報を取得
                    day_elem = current_div.find('p', class_='day')
                    day_info = day_elem.get_text(strip=True) if day_elem else ""
                
                # レース情報を追加
                races.append({
                    'name': f"{velodrome_name} ({grade}) {day_info}",
                    'url': race_url,
                    'grade': grade,
                    'velodrome': velodrome_name,
                    'status': race_status,
                    'time': race_time,
                    'day': day_info,
                    'date_type': date_type
                })
            
            # Gradeでソート
            grade_order = {
                'ＧⅠ': 1, 'GⅠ': 1, 'GI': 1,
                'ＧⅡ': 2, 'GⅡ': 2, 'GII': 2,
                'ＧⅢ': 3, 'GⅢ': 3, 'GIII': 3,
                'ＦⅠ': 4, 'FⅠ': 4, 'FI': 4,
                'ＦⅡ': 5, 'FⅡ': 5, 'FII': 5,
                'F級': 9
            }
            races.sort(key=lambda x: grade_order.get(x['grade'], 10))
            
            print(f"取得したレース数 ({date_type}): {len(races)}")
            return races
            
        except Exception as e:
            print(f"レース一覧取得エラー ({date_type}): {e}")
            import traceback
            traceback.print_exc()
            return []
    
    
    def get_todays_races(self) -> List[Dict]:
        """
        当日開催のレース一覧を取得（後方互換性のため）
        
        Returns:
            レース情報のリスト
        """
        return self.get_races("today")
    
    def get_all_races_from_venue(self, racecard_url: str) -> List[Dict]:
        """
        開催場のracecardURLから全レース（1R-12R）のracedetail URLを生成
        
        Args:
            racecard_url: 開催場の出走表URL (例: .../racecard/73202602050300/)
            
        Returns:
            各レースの情報リスト [{"race_number": 1, "name": "1R", "url": "..."}]
        """
        try:
            # racecardのURLから開催IDを抽出
            # 例: https://keirin.kdreams.jp/komatsushima/racecard/73202602050300/
            match = re.search(r'/racecard/(\d+)/', racecard_url)
            if not match:
                print(f"URLパターンが不正: {racecard_url}")
                return []
            
            kaisai_id = match.group(1)  # 例: "73202602050300"
            
            # ベースURLを取得
            base_url = racecard_url.split('/racecard/')[0]
            
            # 各レース（1R-12R）のURLを生成
            races = []
            for race_no in range(1, 13):  # 1R～12R
                race_id = f"{kaisai_id}{race_no:02d}"  # 例: 7320260205030001
                race_url = f"{base_url}/racedetail/{race_id}/"
                races.append({
                    'race_number': race_no,
                    'name': f"{race_no}R",
                    'url': race_url,
                    'race_id': race_id
                })
            
            print(f"生成したレース数: {len(races)}")
            return races
            
        except Exception as e:
            print(f"レースURL生成エラー: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_race_card(self, race_url: str) -> pd.DataFrame:
        """
        出走表データを取得（racedetailページから23カラム・バリデーション付き）
        
        Args:
            race_url: 出走表ページのURL (racecardでもracedetailでも可)
            
        Returns:
            出走表のDataFrame (23カラム)
        """
        try:
            # racecardのURLをracedetailに変換
            if '/racecard/' in race_url:
                parts = race_url.split('/racecard/')
                if len(parts) == 2:
                    base_url = parts[0]
                    race_id = parts[1].rstrip('/')
                    race_detail_url = f"{base_url}/racedetail/{race_id}01/"
                    print(f"URL変換: racecard → racedetail")
                else:
                    race_detail_url = race_url
            else:
                race_detail_url = race_url
            
            response = self.session.get(race_detail_url, timeout=10)
            response.raise_for_status()
            time.sleep(1)
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 出走表テーブルを探す（class="racecard_table"）
            table = soup.find('table', class_='racecard_table')
            
            if not table:
                print("出走表テーブルが見つかりませんでした")
                return pd.DataFrame()
            
            # 固定ヘッダー（19カラム - 予想、好気合、総評、枠番を除外）
            headers = [
                '車番', '選手名', '府県', '年齢', '期別',
                '級班', '脚質', 'ギヤ倍数', '競走得点', 'S', 'B', 
                '逃', '捲', '差', 'マ', '1着', '2着', '3着', '着外'
            ]
            
            # データ行を抽出（class="n1", "n2", ... "n9"）
            rows_data = []
            for tr in table.find_all('tr'):
                tr_class = tr.get('class', [])
                # n1～n9のクラスを持つ行のみ処理
                if not any(c.startswith('n') and len(c) == 2 and c[1:].isdigit() for c in tr_class):
                    continue
                
                cells = tr.find_all('td')
                row = {}  # 辞書形式で一時保存
                
                for td in cells:
                    td_classes = td.get('class', [])
                    
                    # クラス名でセルを識別
                    # 予想、好気合、総評、枠番のセルはスキップ
                    if 'tip' in td_classes or 'kiai' in td_classes or 'evaluation' in td_classes or 'bracket' in td_classes:
                        continue
                    
                    elif 'num' in td_classes:
                        # 車番セル
                        span = td.find('span')
                        row['車番'] = span.get_text(strip=True) if span else td.get_text(strip=True)
                    
                    elif 'rider' in td_classes:
                        # 選手名セル（特別処理: 選手名 + 府県/年齢/期別）
                        html_content = str(td)
                        html_content = html_content.replace('<br>', '\n').replace('<br/>', '\n')
                        temp_soup = BeautifulSoup(html_content, 'html.parser')
                        text = temp_soup.get_text()
                        lines = [line.strip() for line in text.split('\n') if line.strip()]
                        
                        # 選手名（1行目）
                        row['選手名'] = lines[0] if len(lines) > 0 else ''
                        
                        # 府県/年齢/期別（2行目）
                        if len(lines) > 1:
                            info_parts = lines[1].split('/')
                            row['府県'] = info_parts[0].strip() if len(info_parts) > 0 else ''
                            row['年齢'] = info_parts[1].strip() if len(info_parts) > 1 else ''
                            row['期別'] = info_parts[2].strip() if len(info_parts) > 2 else ''
                        else:
                            row['府県'] = ''
                            row['年齢'] = ''
                            row['期別'] = ''
                
                # クラスなしセルを順番に処理（級班、脚質、ギヤ倍数、統計データ）
                # クラスなしセルのインデックスを取得
                classless_cells = []
                for td in cells:
                    td_classes = td.get('class', [])
                    # 特定のクラスを持たないセル、またはbdr_rだけのセル
                    if not td_classes or (len(td_classes) == 1 and 'bdr_r' in td_classes):
                        span = td.find('span')
                        text = span.get_text(strip=True) if span else td.get_text(strip=True)
                        classless_cells.append(text)
                
                # クラスなしセルを順番にマッピング
                # 期待順序: 級班、脚質、ギヤ倍数、競走得点、S、B、逃、捲、差、マ、1着、2着、3着、着外
                cell_map = ['級班', '脚質', 'ギヤ倍数', '競走得点', 'S', 'B', '逃', '捲', '差', 'マ',
                           '1着', '2着', '3着', '着外']
                
                for i, col_name in enumerate(cell_map):
                    if i < len(classless_cells):
                        row[col_name] = classless_cells[i]
                    else:
                        row[col_name] = ''
                
                # 19カラムすべてを含む行を作成（順序保証）
                ordered_row = []
                for header in headers:
                    ordered_row.append(row.get(header, ''))
                
                if ordered_row:
                    rows_data.append(ordered_row)
            
            if not rows_data:
                print("データ行が見つかりませんでした")
                return pd.DataFrame()
            
            # DataFrameを作成
            df = pd.DataFrame(rows_data, columns=headers)
            
            # 数値変換（バリデーション付き）
            # 車番: 1-9の整数
            if '車番' in df.columns:
                df['車番'] = pd.to_numeric(df['車番'], errors='coerce')
                df.loc[(df['車番'] < 1) | (df['車番'] > 9), '車番'] = None
            
            # 年齢: 18-70の整数
            if '年齢' in df.columns:
                df['年齢'] = pd.to_numeric(df['年齢'], errors='coerce')
                df.loc[(df['年齢'] < 18) | (df['年齢'] > 70), '年齢'] = None
            
            # 期別: 1-150の整数
            if '期別' in df.columns:
                df['期別'] = pd.to_numeric(df['期別'], errors='coerce')
                df.loc[(df['期別'] < 1) | (df['期別'] > 150), '期別'] = None
            
            # その他の数値カラム（総評を除外）
            numeric_cols = ['ギヤ倍数', '競走得点', 'S', 'B', '逃', '捲', '差', 'マ',
                           '1着', '2着', '3着', '着外']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            print(f"出走表データ: {len(df)}行 x {len(df.columns)}列取得")
            return df
            
        except Exception as e:
            print(f"出走表取得エラー: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()
    
    def get_line_prediction(self, race_url: str) -> str:
        """
        ライン予想（並び予想）を取得
        
        Args:
            race_url: レース詳細ページのURL
            
        Returns:
            ライン予想文字列（例: "123-45-6"）
        """
        try:
            response = self.session.get(race_url, timeout=10)
            response.raise_for_status()
            time.sleep(1)
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 「並び予想」のセクションを探す
            line_section = soup.find(text=re.compile(r'並び|ライン'))
            
            if line_section:
                # 親要素から数字を抽出
                parent = line_section.parent
                if parent:
                    numbers = re.findall(r'\d', parent.get_text())
                    if numbers:
                        # 連続する数字をグループ化（ヒューリスティック）
                        return ''.join(numbers)
            
            # フォールバック: ページ全体から数字パターンを探す
            text_content = soup.get_text()
            line_match = re.search(r'(\d+[-‐]\d+[-‐]\d+)', text_content)
            if line_match:
                return line_match.group(1).replace('‐', '-')
            
            return ""
            
        except Exception as e:
            print(f"ライン予想取得エラー: {e}")
            return ""
    
    def get_3rentan_odds(self, race_url: str) -> pd.DataFrame:
        """
        3連単オッズを取得
        
        Args:
            race_url: レース詳細ページのURL
            
        Returns:
            3連単オッズのDataFrame (1着,2着,3着,オッズ)
        """
        try:
            # オッズページのURLを構築
            if '/racedetail/' in race_url:
                odds_url = race_url.rstrip('/') + '/odds/3rentan/'
            else:
                odds_url = race_url
            
            response = self.session.get(odds_url, timeout=10)
            response.raise_for_status()
            time.sleep(1)
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # オッズテーブルを探す
            odds_data = []
            
            # パターン1: テーブル形式
            tables = soup.find_all('table')
            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    cell_texts = [c.get_text(strip=True) for c in cells]
                    
                    # 3連単パターンを探す（1-2-3形式または別々のセル）
                    if len(cell_texts) >= 4:
                        # 数字を抽出
                        numbers = []
                        for text in cell_texts:
                            nums = re.findall(r'\d+', text)
                            numbers.extend(nums)
                        
                        if len(numbers) >= 4:
                            # 最後が小数点を含む可能性があるオッズ値
                            try:
                                odds_value = float(numbers[3]) if '.' in cell_texts[-1] else float(numbers[3])
                                odds_data.append({
                                    '1着': int(numbers[0]),
                                    '2着': int(numbers[1]),
                                    '3着': int(numbers[2]),
                                    'オッズ': odds_value
                                })
                            except (ValueError, IndexError):
                                continue
            
            if odds_data:
                df = pd.DataFrame(odds_data)
                return df
            
            return pd.DataFrame(columns=['1着', '2着', '3着', 'オッズ'])
            
        except Exception as e:
            print(f"3連単オッズ取得エラー: {e}")
            return pd.DataFrame(columns=['1着', '2着', '3着', 'オッズ'])
    
    def get_odds(self, race_url: str, odds_type: str = 'popular') -> pd.DataFrame:
        """
        3連単オッズ（人気順のみ）を取得
        
        Args:
            race_url: レース詳細ページのURL
            odds_type: 'popular' (人気順のみ対応)
        
        Returns:
            人気順オッズのDataFrame (順位, 組み合わせ, オッズ)
        """
        try:
            # オッズページURLを構築
            if '?' in race_url:
                odds_url = f"{race_url}&pageType=odds&kakeshikiType=3rentan"
            else:
                odds_url = f"{race_url}?pageType=odds&kakeshikiType=3rentan"
            
            response = self.session.get(odds_url, timeout=10)
            response.raise_for_status()
            time.sleep(1)
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # オッズセクションを探す
            odds_sections = soup.find_all('div', class_='oddspop_table_wrapper')
            
            if not odds_sections:
                print("⚠️ オッズセクションが見つかりません（JavaScriptレンダリングが必要な可能性）")
                return pd.DataFrame()
            
            # 3連単セクション（最初のセクション）
            sanrentan_section = odds_sections[0]
            
            # テーブルを取得（1つ目が人気順）
            tables = sanrentan_section.find_all('table')
            
            if not tables:
                print("⚠️ オッズテーブルが見つかりません")
                return pd.DataFrame()
            
            # 人気順テーブル（1つ目）
            popular_table = tables[0]
            rows = popular_table.find_all('tr')
            
            odds_data = []
            for row in rows:
                th = row.find('th')
                td = row.find('td')
                
                if th and td:
                    rank = th.get_text(strip=True)
                    num_span = td.find('span', class_='num')
                    odds_span = td.find('span', class_='odds')
                    
                    if num_span and odds_span:
                        combination = num_span.get_text(strip=True)
                        odds = odds_span.get_text(strip=True)
                        odds_data.append({
                            '順位': rank,
                            '組み合わせ': combination,
                            'オッズ': odds
                        })
            
            df = pd.DataFrame(odds_data)
            print(f"✅ オッズデータ取得: {len(df)}通り")
            return df
            
        except Exception as e:
            print(f"❌ オッズデータ取得エラー: {e}")
            return pd.DataFrame()
    
    def get_race_results(self, race_url: str) -> pd.DataFrame:
        """
        レース結果詳細を取得
        
        Args:
            race_url: レース詳細ページのURL
            
        Returns:
            レース結果のDataFrame (着順,車番,選手名,着差,上がり,決まり手,S/B)
        """
        try:
            # 結果ページのURLを構築（?pageType=result パラメータを追加）
            if '?' in race_url:
                results_url = race_url + '&pageType=result'
            else:
                results_url = race_url.rstrip('/') + '/?pageType=result'
            
            print(f"結果ページURL: {results_url}")
            
            response = self.session.get(results_url, timeout=10)
            response.raise_for_status()
            time.sleep(1)
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # result_tableクラスのテーブルを探す
            result_table = soup.find('table', class_='result_table')
            
            if not result_table:
                print("結果テーブルが見つかりません")
                return pd.DataFrame(columns=['着順', '車番', '選手名', '着差', '上がり', '決まり手', 'S/B'])
            
            # データ行を取得
            tbody = result_table.find('tbody')
            if tbody:
                data_rows = tbody.find_all('tr')
            else:
                # tbody がない場合は直接 tr を取得（ヘッダーをスキップ）
                data_rows = result_table.find_all('tr')[1:]
            
            results = []
            
            for row in data_rows:
                cells = row.find_all('td')
                
                if len(cells) > 0:
                    # インデックスベースでセルを取得
                    # HTML構造: tip(予想), 着順, num(車番), rider(選手名), 着差, 上がり, 決まり手, S/B, comment(勝敗因)
                    
                    chakujun_num = ''
                    shaban = ''
                    senshu = ''
                    chakusa = ''
                    agari = ''
                    kimarite = ''
                    sb = ''
                    
                    # 各セルを順番に処理
                    for i, td in enumerate(cells):
                        td_classes = td.get('class', [])
                        text = td.get_text(strip=True)
                        
                        # クラスベースで特定できるセル
                        if 'tip' in td_classes:
                            # 予想マーク - スキップ（位置: 0）
                            continue
                        elif 'num' in td_classes:
                            # 車番（位置: 2）
                            shaban = text
                        elif 'rider' in td_classes:
                            # 選手名（位置: 3）
                            senshu = text
                        elif 'comment' in td_classes:
                            # コメント（位置: 8） - スキップ
                            continue
                    
                    # 位置ベースで通常セルを取得（クラスなしのtd）
                    # インデックスを数えて正確に割り当て
                    normal_cell_index = 0
                    for i, td in enumerate(cells):
                        td_classes = td.get('class', [])
                        
                        # 特殊クラスを持つセルはスキップ
                        if any(cls in td_classes for cls in ['tip', 'num', 'rider', 'comment']):
                            continue
                        
                        text = td.get_text(strip=True)
                        
                        # 通常セルの順序: 着順(0), 着差(1), 上がり(2), 決まり手(3), S/B(4)
                        if normal_cell_index == 0:
                            chakujun_num = text
                        elif normal_cell_index == 1:
                            chakusa = text
                        elif normal_cell_index == 2:
                            agari = text
                        elif normal_cell_index == 3:
                            kimarite = text
                        elif normal_cell_index == 4:
                            sb = text
                        
                        normal_cell_index += 1
                    
                    # 結果データを構築
                    result_data = {
                        '着順': chakujun_num,
                        '車番': shaban,
                        '選手名': senshu,
                        '着差': chakusa,
                        '上がり': agari,
                        '決まり手': kimarite,
                        'S/B': sb,
                    }
                    
                    results.append(result_data)
            
            if results:
                df = pd.DataFrame(results)
                print(f"取得した結果数: {len(df)}")
                return df
            
            return pd.DataFrame(columns=['着順', '車番', '選手名', '着差', '上がり', '決まり手', 'S/B'])
            
        except Exception as e:
            print(f"レース結果取得エラー: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame(columns=['着順', '車番', '選手名', '着差', '上がり', '決まり手', 'S/B'])
    
    def get_all_race_data(self, race_url: str) -> Tuple[pd.DataFrame, str, pd.DataFrame]:
        """
        1つのレースの全データを取得
        
        Args:
            race_url: レース詳細ページのURL
            
        Returns:
            (出走表DataFrame, ライン予想str, 3連単オッズDataFrame)
        """
        print(f"データ取得中: {race_url}")
        
        race_card = self.get_race_card(race_url)
        line_prediction = self.get_line_prediction(race_url)
        odds_3rentan = self.get_3rentan_odds(race_url)
        
        return race_card, line_prediction, odds_3rentan
    
    def get_venue_all_data(self, venue_name: str, racecard_url: str) -> Dict:
        """
        開催場の全レース（1R-12R）のデータを一括取得（本日のみ対応）
        
        Args:
            venue_name: 開催場名（例: "熊本"）
            racecard_url: 開催場の出走表URL
        
        Returns:
            {
                'venue_name': '熊本',
                'grade': 'GI',
                'race_cards': DataFrame,  # 全レースの出走表（レース列を追加）
                'odds_list': DataFrame,   # 全レースのオッズ（レース列を追加）
                'results_list': DataFrame # 全レースの結果（レース列を追加）
            }
        """
        print(f"\n{'='*60}")
        print(f"開催場一括取得開始: {venue_name}")
        print(f"{'='*60}\n")
        
        # 全レース（1R-12R）のURLを取得
        all_races = self.get_all_races_from_venue(racecard_url)
        
        if not all_races:
            print("レースURLの生成に失敗しました")
            return {
                'venue_name': venue_name,
                'grade': '',
                'race_cards': pd.DataFrame(),
                'odds_list': pd.DataFrame(),
                'results_list': pd.DataFrame()
            }
        
        # データを格納するリスト
        all_race_cards = []
        all_odds = []
        all_results = []
        
        total_races = len(all_races)
        
        # 各レースのデータを取得
        for i, race in enumerate(all_races, 1):
            race_no = race['race_number']
            race_url = race['url']
            
            print(f"\n[{i}/{total_races}] {race_no}R のデータ取得中...")
            
            try:
                # 出走表を取得
                race_card = self.get_race_card(race_url)
                if not race_card.empty:
                    race_card.insert(0, 'レース', f"{race_no}R")
                    all_race_cards.append(race_card)
                    print(f"  ✅ 出走表: {len(race_card)}名")
                else:
                    print(f"  ⚠️ 出走表: データなし")
                
                # オッズを取得
                odds = self.get_odds(race_url, 'popular')
                if not odds.empty:
                    odds.insert(0, 'レース', f"{race_no}R")
                    all_odds.append(odds)
                    print(f"  ✅ オッズ: {len(odds)}通り")
                else:
                    print(f"  ⚠️ オッズ: データなし")
                
                # レース結果を取得
                results = self.get_race_results(race_url)
                if not results.empty:
                    results.insert(0, 'レース', f"{race_no}R")
                    all_results.append(results)
                    print(f"  ✅ 結果: {len(results)}名")
                else:
                    print(f"  ℹ️ 結果: 未確定またはデータなし")
                
            except Exception as e:
                print(f"  ❌ {race_no}R のデータ取得エラー: {e}")
                continue
        
        # DataFrameを統合
        combined_race_cards = pd.concat(all_race_cards, ignore_index=True) if all_race_cards else pd.DataFrame()
        combined_odds = pd.concat(all_odds, ignore_index=True) if all_odds else pd.DataFrame()
        combined_results = pd.concat(all_results, ignore_index=True) if all_results else pd.DataFrame()
        
        print(f"\n{'='*60}")
        print(f"一括取得完了: {venue_name}")
        print(f"  出走表: {len(combined_race_cards)}行")
        print(f"  オッズ: {len(combined_odds)}行")
        print(f"  結果: {len(combined_results)}行")
        print(f"{'='*60}\n")
        
        return {
            'venue_name': venue_name,
            'grade': '',  # 必要に応じて開催情報から取得
            'race_cards': combined_race_cards,
            'odds_list': combined_odds,
            'results_list': combined_results
        }



    def get_race_lines(self, race_url: str) -> List[Dict]:
        """
        ライン構成を取得する。

        HTML構造:
          <div class="line_position">
            <span class="icon_p"><span class="p007">7</span>...</span>  # 車番7
            <span class="icon_p"><span class="p001">1</span>...</span>  # 車番1
            <span class="icon_p space"></span>                          # ライン区切り
            <span class="icon_p"><span class="p002">2</span>...</span>  # 車番2
            ...
          </div>
        """
        import re as _re

        try:
            if '/racecard/' in race_url:
                parts = race_url.split('/racecard/')
                if len(parts) == 2:
                    race_url = parts[0] + '/racedetail/' + parts[1]

            response = self.session.get(race_url, timeout=10)
            response.raise_for_status()
            time.sleep(0.5)
            soup = BeautifulSoup(response.text, 'html.parser')

            # line_position div 内の span.icon_p を値得る
            line_pos_div = soup.find('div', class_='line_position')
            if not line_pos_div:
                return []

            result   = []
            line_no  = 1
            cur_bibs: List[int] = []
            seen:     set       = set()

            for span in line_pos_div.find_all('span', class_='icon_p'):
                classes = span.get('class', [])

                # space クラス = ライン区切り
                if 'space' in classes:
                    if cur_bibs:
                        result.append({"line": line_no, "bibs": cur_bibs})
                        line_no += 1
                        cur_bibs = []
                        seen     = set()
                    continue

                # p00X クラスを持つ子要素から車番を取得
                # 例: p007 → 7号車, p001 → 1号車
                for child in span.find_all('span'):
                    child_classes = child.get('class', [])
                    for c in child_classes:
                        m = _re.match(r'^p0+([1-9])$', c)   # p001/p007 など
                        if m:
                            b = int(m.group(1))
                            if b not in seen:
                                seen.add(b)
                                cur_bibs.append(b)

            # 末尾のライン
            if cur_bibs:
                result.append({"line": line_no, "bibs": cur_bibs})

            return result

        except Exception as e:
            print(f"❌ ライン情報取得エラー: {e}")
            return []


    def get_race_lines_text(self, race_url: str) -> str:
        """
        get_race_lines() の結果を人間可読な文字列で返す。

        例: "ライン1: 3-5-1 / ライン2: 4-7 / ライン3: 2-6-8-9"
        """
        lines = self.get_race_lines(race_url)
        if not lines:
            return "ライン情報なし"
        parts = []
        for ln in lines:
            bib_str = "-".join(str(b) for b in ln["bibs"])
            parts.append(f"ライン{ln['line']}: {bib_str}")
        return " / ".join(parts)


if __name__ == "__main__":

    # テスト実行
    scraper = KdreamsScraper()
    races = scraper.get_todays_races()
    print(f"本日のS級レース: {len(races)}件")
    for race in races[:5]:
        print(f"  - {race['name']}")
