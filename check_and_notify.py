"""
check_and_notify.py v2
======================
GitHub Actions が 30分おきに実行する予想・通知スクリプト。

Phase1: 当日F1/G3+レース取得（fetch_schedule.py）
Phase2: 締切直前レースのオッズ取得（KdreamsScraper）
Phase3: LOOSE_B予想 → 買い判定 → LINE通知

通知ウィンドウ:
  「今から NOTIFY_BEFORE_MIN 〜 NOTIFY_BEFORE_MIN+25 分後に締め切り」のレースを対象。
  30分おき実行なので、このウィンドウで重複なしにカバーできる。
"""

import os
import sys
import re
import time
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from pathlib import Path
from bs4 import BeautifulSoup

from kdreams_scraper import KdreamsScraper
from fetch_schedule import fetch_today_f1_g3_races
from fetch_results import get_race_result
from bet_logger   import log_bet, update_result, get_pending_races, get_daily_summary
from send_discord import send_prediction, send_skip, send_race_result, send_daily_summary

# ── 設定 ─────────────────────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
DB_SLIM_PATH    = os.environ.get("DB_SLIM_PATH", "data/S級デビーslim.xlsx")
DB_OLD_PATH     = os.environ.get("DB_OLD_PATH",  r"data/S級選手究極DB(1).xlsx")

NOTIFY_BEFORE_MIN = 5    # 締切N分前〜(N+18)分前のレースを対象
WINDOW_SPAN_MIN   = 18   # 通知ウィンドウ幅（20分サイクルより少し短め、重複防止）
BET_BASE          = 100

STRATEGY_CFG = dict(
    skip_chaos=True, min_top_ev=70,
    skip_low_bank=True, top_n_prob_bets=14,
)

BANK_DICT = {
    '前橋':{'roi_tier':'mid','sashi':0.8,'makuri':1.2},
    '宇都宮':{'roi_tier':'high','sashi':1.5,'makuri':1.1},
    '豊橋':{'roi_tier':'high','sashi':1.3,'makuri':1.2},
    '岸和田':{'roi_tier':'low','sashi':1.1,'makuri':1.3},
    '熊本':{'roi_tier':'high','sashi':1.2,'makuri':1.1},
    'いわき平':{'roi_tier':'mid','sashi':0.9,'makuri':1.3},
    '広島':{'roi_tier':'mid','sashi':1.2,'makuri':1.0},
    '別府':{'roi_tier':'mid','sashi':1.1,'makuri':1.1},
    '松山':{'roi_tier':'mid','sashi':1.0,'makuri':1.2},
    '小倉':{'roi_tier':'low','sashi':1.1,'makuri':1.1},
    '京王閣':{'roi_tier':'high','sashi':1.0,'makuri':1.1},
    '立川':{'roi_tier':'high','sashi':1.1,'makuri':1.0},
    '取手':{'roi_tier':'mid','sashi':1.1,'makuri':1.1},
    '伊東':{'roi_tier':'mid','sashi':1.0,'makuri':1.2},
    '久留米':{'roi_tier':'low','sashi':1.1,'makuri':1.1},
    '奈良':{'roi_tier':'low','sashi':1.2,'makuri':1.0},
    '岐阜':{'roi_tier':'low','sashi':1.1,'makuri':1.1},
    '小松島':{'roi_tier':'low','sashi':1.1,'makuri':1.0},
    '防府':{'roi_tier':'low','sashi':1.1,'makuri':1.1},
    '静岡':{'roi_tier':'low','sashi':1.2,'makuri':1.0},
    '松阪':{'roi_tier':'mid','sashi':1.1,'makuri':1.1},
    '高知':{'roi_tier':'mid','sashi':1.0,'makuri':1.2},
    '松戸':{'roi_tier':'mid','sashi':1.1,'makuri':1.0},
    '平塚':{'roi_tier':'mid','sashi':1.2,'makuri':1.1},
    '西武園':{'roi_tier':'mid','sashi':1.0,'makuri':1.1},
    '小田原':{'roi_tier':'mid','sashi':1.0,'makuri':1.1},
}

SENPO_LEAD = {
    '逃げ切り':5,'逃げ粘り':4,'突っ張り先行':4,'抑え先行':4,
    'カマシ先行':5,'先行逃げ切り':5,'先行':4,'逃げ':5,
    '先行争い敗北':3,'捲り':3,'番手捲り':3,'カマシ捲り':4,
    '捲り差し':3,'捲り不発':2,'番手差し':2,'差し':2,
    '追い込み':2,'流れ込み':1,'追走':1,'マーク':1,
}

def nobi_score(v):
    s = str(v).strip().upper()
    return 5 if s.startswith('S') else 4 if s.startswith('A') else 3 if s.startswith('B') else 1
def senpo_lead(v): return SENPO_LEAD.get(str(v).strip(), 1)
def norm(s): return str(s).replace(' ','').replace('\u3000','').strip()

# ── DB ロード ─────────────────────────────────────────────────────────────────
def load_db():
    db_all = db_slim = pd.DataFrame()
    nobi_col = '直線の伸び'

    if Path(DB_OLD_PATH).exists():
        xl = pd.ExcelFile(DB_OLD_PATH)
        sheets = [s for s in ['F1','G3~1'] if s in xl.sheet_names]
        db_all = pd.concat([xl.parse(s) for s in sheets], ignore_index=True)
        db_all['開催日'] = pd.to_datetime(db_all['開催日'], errors='coerce')
        for c in ['IP','EP','DP','BP']:
            db_all[c] = pd.to_numeric(db_all[c], errors='coerce')
        db_all['選手名_norm'] = db_all['選手名'].apply(norm)
        nb_cols = [c for c in db_all.columns if '直線' in c]
        nobi_col = nb_cols[0] if nb_cols else nobi_col

    if Path(DB_SLIM_PATH).exists():
        sl = pd.ExcelFile(DB_SLIM_PATH)
        dfs = [sl.parse(s) for s in ['F1','G3~1'] if s in sl.sheet_names]
        if dfs:
            db_slim = pd.concat(dfs, ignore_index=True)
            db_slim['開催日'] = pd.to_datetime(db_slim['開催日'], errors='coerce')
            for c in ['IP','EP','DP','BP']:
                if c in db_slim.columns:
                    db_slim[c] = pd.to_numeric(db_slim[c], errors='coerce')
            db_slim['選手名_norm'] = db_slim['選手名'].apply(norm)
    return db_all, db_slim, nobi_col

# ── Phase2: オッズ取得 ────────────────────────────────────────────────────────
def get_odds(scraper: KdreamsScraper, race_url: str) -> dict[str, float]:
    """
    racedetail ページ本体から3連単オッズを取得する。
    div.oddspop_table_wrapper → 各 TR が「組み合わせ オッズ」を含む。
    Returns: {"1-2-3": 4.5, ...}
    """
    try:
        r    = scraper.session.get(race_url, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')

        result = {}
        wrappers = soup.find_all('div', class_='oddspop_table_wrapper')

        for wrapper in wrappers:
            for tr in wrapper.find_all('tr'):
                txt = tr.get_text(separator=' ', strip=True)
                # 「5-1-7 4.5」または「5-1-7\n4.5」のようなパターン
                m = re.search(r'(\d)-(\d)-(\d)\s+([\d,]+\.?\d*)', txt)
                if m:
                    combo = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                    try:
                        odds = float(m.group(4).replace(',',''))
                        if odds > 1.0:
                            result[combo] = odds
                    except ValueError:
                        pass

        # フォールバック: wrapper なしでページ全体から探す
        if not result:
            for tr in soup.find_all('tr'):
                txt = tr.get_text(separator=' ', strip=True)
                m = re.search(r'(\d)-(\d)-(\d)\s+([\d,]+\.?\d*)', txt)
                if m:
                    combo = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                    try:
                        odds = float(m.group(4).replace(',',''))
                        if odds > 1.0:
                            result[combo] = odds
                    except ValueError:
                        pass

        return result

    except Exception as e:
        print(f"⚠️  オッズ取得エラー: {e}")
        return {}


# ── Phase2: 出走表・ライン取得 ────────────────────────────────────────────────
def get_race_info(scraper: KdreamsScraper, race_url: str) -> tuple[pd.DataFrame, dict]:
    """
    出走表 DataFrame + ライン情報 {車番: (line_no, line_bibs_str)} を返す。
    """
    df = scraper.get_race_card(race_url)
    lines_list = scraper.get_race_lines(race_url)  # [{'line': 1, 'bibs': [...]}]
    num_to_line = {}
    num_to_bibs = {}
    for linfo in lines_list:
        lno  = linfo.get('line', 0)   # ← 'line'（line_noではない）
        bibs = linfo.get('bibs', [])
        for b in bibs:
            num_to_line[b] = lno
            num_to_bibs[b] = '-'.join(str(x) for x in bibs)
    return df, num_to_line, num_to_bibs

# ── Phase3: 予想コア ──────────────────────────────────────────────────────────
def run_prediction(venue, race_no, race_card, num_to_line, num_to_bibs,
                   odds_dict, db_all, db_slim, nobi_col, today_dt):
    bp = BANK_DICT.get(venue, {'roi_tier':'mid','sashi':1.0,'makuri':1.0})
    if STRATEGY_CFG['skip_low_bank'] and bp['roi_tier'] == 'low':
        return None
    if race_card is None or race_card.empty:
        return None

    past_db   = db_all[db_all['開催日'] < today_dt]   if not db_all.empty   else db_all
    past_slim = db_slim[db_slim['開催日'] < today_dt]  if not db_slim.empty  else db_slim

    line_map = {}
    for num, lno in num_to_line.items():
        if lno not in line_map:
            line_map[lno] = []
        line_map[lno].append(num)

    player_scores = {}
    for _, row in race_card.iterrows():
        try: num = int(row['車番'])
        except: continue
        nm   = norm(str(row.get('選手名','')))
        base = float(row.get('競走得点', 80) or 80)

        hist = past_slim[past_slim['選手名_norm']==nm] if not past_slim.empty else pd.DataFrame()
        use_slim = not hist.empty
        if hist.empty:
            hist = past_db[past_db['選手名_norm']==nm] if not past_db.empty else pd.DataFrame()

        ip=ep=4.0; dp=bp_v=3.0; nb=sp=2.0; is_m=is_u=False
        if not hist.empty:
            RECENT_W = 3.0
            sd = sorted(hist['開催日'].dropna().unique(), reverse=True)
            rd = set(sd[:2])
            def wm(series):
                v = pd.to_numeric(series, errors='coerce')
                w = np.where(hist['開催日'].isin(rd), RECENT_W, 1.0)
                mk = v.notna()
                return float((v[mk]*w[mk]).sum()/w[mk].sum()) if mk.any() else np.nan
            ip   = wm(hist['IP'])   or 4.0
            ep   = wm(hist['EP'])   or 4.0
            dp   = wm(hist['DP'])   or 3.0
            bp_v = wm(hist['BP'])   or 3.0
            nb   = wm(hist['直線の伸び'].apply(nobi_score)) if use_slim and '直線の伸び' in hist.columns else \
                   (wm(hist[nobi_col].apply(nobi_score)) if nobi_col in hist.columns else 2.0)
            sp   = wm(hist['戦法'].apply(senpo_lead)) if '戦法' in hist.columns else 2.0
            if use_slim:
                is_m = bool(hist.get('is_monster',   pd.Series([0])).max() >= 1)
                is_u = bool(hist.get('is_unreliable', pd.Series([0])).max() >= 1)
            else:
                cmt = ' '.join(hist.get('解析コメント', pd.Series([''])).astype(str))
                is_m = any(k in cmt for k in ['脚余し','鬼脚','別次元','圧倒'])
                is_u = any(k in cmt for k in ['共倒れ','位置取り失敗','不発','失速'])

        lno   = num_to_line.get(num, 0)
        lbs   = line_map.get(lno, [])
        pos   = lbs.index(num)+1 if num in lbs else 1
        pos_b = 0.5 if pos==1 else -0.3*(pos-1)

        ev = (base*0.4 + ip*1.5 + ep*1.2 + dp*bp['makuri'] + bp_v*bp['sashi']
              + nb*2.0 + sp*0.5 + pos_b + (3.0 if is_m else 0) - (2.0 if is_u else 0))
        player_scores[num] = {'name':str(row.get('選手名','')), 'ev':ev,
                               'ip':ip, 'is_monster':is_m}

    ranked = sorted(player_scores.items(), key=lambda x: x[1]['ev'], reverse=True)
    if len(ranked) < 3: return None

    # カオス判定: ライン先頭でIP≥5.5の選手が2人以上 → チャオス展開
    strong_leaders = [
        n for n, d in player_scores.items()
        if d['ip'] >= 5.5
        and line_map.get(num_to_line.get(n, 0), [None])[0] == n
    ]
    is_chaos = len(strong_leaders) >= 2

    top_ev = ranked[0][1]['ev']
    if top_ev < STRATEGY_CFG['min_top_ev']: return None
    if is_chaos and STRATEGY_CFG['skip_chaos']: return None

    all_nums = [n for n,_ in ranked]
    max_e = ranked[0][1]['ev']
    raw_s = {n: np.exp(player_scores[n]['ev']-max_e) for n in all_nums}

    def pl(f,s,t):
        d1=sum(raw_s[n] for n in all_nums)
        d2=sum(raw_s[n] for n in all_nums if n!=f)
        d3=sum(raw_s[n] for n in all_nums if n not in (f,s))
        return 0.0 if 0 in (d1,d2,d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)

    axis_num = next((n for n,d in ranked if d['is_monster']), ranked[0][0])
    others   = [n for n,_ in ranked if n!=axis_num]

    ev_bets = sorted(
        [(pl(axis_num,s,t)*odds_dict.get(f"{axis_num}-{s}-{t}",0),
          f"{axis_num}-{s}-{t}", pl(axis_num,s,t), odds_dict.get(f"{axis_num}-{s}-{t}",0))
         for s in others for t in others if s!=t and f"{axis_num}-{s}-{t}" in odds_dict],
        key=lambda x: x[2], reverse=True)
    bets = [c for _,c,_,_ in ev_bets[:14]]
    if not bets: return None

    el   = {c:ev for ev,c,p,o in sorted(ev_bets, key=lambda x: x[0], reverse=True)}
    bev  = [(c, el.get(c,0.0)) for c in bets]
    ev_vals = np.array([max(e,0.0) for _,e in bev])
    total_p = BET_BASE * len(bets)
    if ev_vals.sum()==0:
        alloc = [BET_BASE]*len(bets)
    else:
        a = (ev_vals/ev_vals.sum())*total_p
        a100 = (a//100).astype(int)*100
        a100[int(np.argmax(ev_vals))] += (int(total_p-a100.sum())//100)*100
        alloc = [max(int(x),100) for x in a100]

    return {
        'venue': venue, 'race_no': race_no, 'top_ev': top_ev,
        'axis': f"車番{axis_num} {player_scores[axis_num]['name']}",
        'bets': list(zip(bets, alloc)), 'total': sum(alloc),
    }

# ── Discord 通知は send_discord.py に失買──────────────────────────────────────────

# ── メイン ─────────────────────────────────────────────────────────────────────
def main():
    now     = datetime.now()
    today   = date.today()
    today_dt = datetime.combine(today, datetime.min.time())

    # 通知ウィンドウ: 締切が「今から5〜30分後」のレース
    dl_lo = now + timedelta(minutes=NOTIFY_BEFORE_MIN)
    dl_hi = now + timedelta(minutes=NOTIFY_BEFORE_MIN + WINDOW_SPAN_MIN)

    print(f"🕐 {now.strftime('%H:%M')} — 締切ウィンドウ: {dl_lo.strftime('%H:%M')}〜{dl_hi.strftime('%H:%M')}")

    # ── フェーズ0: 発走済みレースの結果確認 ──────────────────────────────────
    pending = get_pending_races()
    if pending:
        print(f"\n🔎 結果確認: {len(pending)}件")
        scraper0 = KdreamsScraper()
        for pr in pending:
            res = get_race_result(scraper0, f"https://keirin.kdreams.jp/{pr.get('venue_slug', pr['venue'])}/racedetail/{pr['race_id']}/")
            if res:
                updated = update_result(pr['race_id'], res['combo'], res['payout'])
                if updated:
                    summary = get_daily_summary()
                    total_today = summary['profit']
                    # 的中/外れをDiscordに通知
                    row = next((r for r in summary['hits'] + summary['misses']
                                if r['race_id'] == pr['race_id']), None)
                    if row:
                        hit     = row['status'] == 'hit'
                        profit  = int(row['profit'])
                        payout  = int(row['payout'])
                        send_race_result(
                            venue=pr['venue'], race_no=int(pr['race_no']),
                            race_name=pr.get('race_name', 'S級'),
                            result_combo=res['combo'], payout=payout,
                            hit=hit, profit=profit, total_today=total_today,
                        )
            time.sleep(0.5)

    # Phase1: 当日レース一覧取得
    print("\n📡 当日開催を取得中...")
    races = fetch_today_f1_g3_races(today, min_grade="F1", fetch_times=True)

    if not races:
        print("開催なし or 取得失敗")
        return

    # 通知ウィンドウ内のレースを絞り込む
    target = []
    for r in races:
        dl = r.get('deadline_time')
        if dl and dl_lo <= dl <= dl_hi:
            target.append(r)

    print(f"🎯 {len(target)}R が通知ウィンドウ内（締切 {dl_lo.strftime('%H:%M')}〜{dl_hi.strftime('%H:%M')}）")
    if not target:
        return

    # DB ロード
    print("📦 DB 読み込み中...")
    db_all, db_slim, nobi_col = load_db()
    scraper = KdreamsScraper()

    for r in target:
        venue    = r['venue']
        race_no  = r['race_no']
        race_url = r['race_url']
        deadline = r['deadline_time']
        start    = r['start_time']
        mins_left = int((deadline - now).total_seconds() / 60) if deadline else -1

        print(f"\n🔍 {venue} {race_no}R  締切{r['deadline_str']}(あと{mins_left}分)  発走{r['start_time_str']}")

        # Phase2: オッズ・出走表取得
        race_card, num_to_line, num_to_bibs = get_race_info(scraper, race_url)
        time.sleep(0.5)
        odds_dict = get_odds(scraper, race_url)
        time.sleep(0.5)

        if race_card.empty:
            print(f"⏭️  出走表取得失敗 → スキップ")
            continue
        if not odds_dict:
            print(f"⏭️  オッズ取得失敗 → スキップ")
            continue

        print(f"   出走表: {len(race_card)}名  オッズ: {len(odds_dict)}通り")

        # Phase3: 予想実行
        result = run_prediction(
            venue, race_no, race_card, num_to_line, num_to_bibs,
            odds_dict, db_all, db_slim, nobi_col, today_dt
        )

        if result:
            lines_for_discord = [
                {'line': lno, 'bibs': bibs}
                for lno, bibs in sorted(
                    {lno: [b for b,ln in num_to_line.items() if ln==lno]
                     for lno in set(num_to_line.values())}.items()
                )
            ]
            send_prediction(
                venue=venue, race_no=race_no,
                race_name=r.get('race_name', 'S級'),
                start_str=r['start_time_str'],
                deadline_str=r['deadline_str'],
                mins_left=mins_left,
                lines=lines_for_discord,
                result=result,
            )
            # 買い目を記録（結果確認のため）
            log_bet(
                race_id=r['race_id'],
                venue=venue, race_no=race_no,
                race_name=r.get('race_name', 'S級'),
                start_time=r.get('start_time'),
                bets=result['bets'],
                total=result['total'],
            )
        else:
            print(f"⏭️  フィルター除外（スキップ）")

if __name__ == "__main__":
    main()
