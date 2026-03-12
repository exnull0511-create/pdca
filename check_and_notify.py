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
from bet_logger   import log_bet, update_result, get_pending_races, get_daily_summary, \
                         get_candidates, confirm_candidate, cancel_candidate
from send_discord import send_prediction, send_skip, send_race_result, send_daily_summary, \
                         send_candidate, send_cancel

# ── 設定 ─────────────────────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
DB_SLIM_PATH    = os.environ.get("DB_SLIM_PATH", "data/S級デビーslim.xlsx")
DB_OLD_PATH     = os.environ.get("DB_OLD_PATH",  r"data/S級選手究極DB(1).xlsx")

# 締切連動スケジューリング設定
# 1分おきcron前提:
#   Phase1: 7〜12分前の5分ウィンドウ（連続5回スキップしない限り取りこぼしない）
#   Phase2: 3〜5分前の3分ウィンドウ（通知後ユーザーに3-5分の購入時間）
# log_betの重複防止機能によりPhase1が複数回ヒットしても候補登録は1回のみ
PHASE1_LO = 7   # Phase1: 締切N分前（候補判定）最大値
PHASE1_HI = 12  # Phase1: 締切N分前最小値＊5分ウィンドウ
PHASE2_LO = 3   # Phase2: 締切N分前（最終確認・通知）最大値
PHASE2_HI = 5   # Phase2: 締切N分前最小値  ← 通知後5分の余裕でユーザーが購入可能
BET_BASE  = 100

STRATEGY_CFG = dict(
    skip_chaos=True, min_top_ev=60,
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
    low_bank = STRATEGY_CFG['skip_low_bank'] and bp['roi_tier'] == 'low'
    if race_card is None or race_card.empty:
        return None

    past_db   = db_all[db_all['開催日'] < today_dt]   if not db_all.empty   else db_all
    past_slim = db_slim[db_slim['開催日'] < today_dt]  if not db_slim.empty  else pd.DataFrame()

    # num_to_bibs からライン順序を保持して line_map を構築
    # ※ num_to_line の挿入順に依存すると順序が崩れるため num_to_bibs を使う
    line_map = {}
    for num, bibs_str in num_to_bibs.items():
        lno = num_to_line.get(num, 0)
        if lno not in line_map:
            bibs_list = [int(b) for b in bibs_str.split('-') if b.isdigit()]
            line_map[lno] = bibs_list

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
                return float((v[mk]*w[mk]).sum()/w[mk].sum()) if mk.any() else None
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
                               'ip':ip, 'is_monster':is_m, 'pos_in_line':pos}

    ranked = sorted(player_scores.items(), key=lambda x: x[1]['ev'], reverse=True)
    if len(ranked) < 3: return None

    # カオス判定: ライン先頭でIP≥5.5の選手が2人以上 → カオス展開
    # ※ バックテスト(_verify_stats.py)と完全同一ロジック
    strong_leaders = [
        n for n, d in player_scores.items()
        if d['ip'] >= 5.5 and d['pos_in_line'] == 1
    ]
    is_chaos = len(strong_leaders) >= 2

    top_ev = ranked[0][1]['ev']
    if pd.isna(top_ev): return None
    # ── グレード判定（フィルタ=スキップではなく☆で表現） ─────────────────
    low_ev    = top_ev < STRATEGY_CFG['min_top_ev']
    chaos_hit = is_chaos and STRATEGY_CFG['skip_chaos']
    grade = "☆" if (low_bank or low_ev or chaos_hit) else "☆☆☆"

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
        'venue': venue, 'race_no': race_no,
        'top_ev':  top_ev,                             # フィルター用（ランキング1位EV）
        'axis_ev': player_scores[axis_num]['ev'],      # 軸選手の実EV
        'axis':    f"車番{axis_num} {player_scores[axis_num]['name']}",
        'bets':    list(zip(bets, alloc)), 'total': sum(alloc),
        'grade':   grade,
    }

# ── Discord 通知は send_discord.py に失買──────────────────────────────────────────

# ── メイン ─────────────────────────────────────────────────────────────────────
def main():
    now      = datetime.now()
    today    = date.today()
    today_dt = datetime.combine(today, datetime.min.time())

    print(f"🕐 {now.strftime('%H:%M')} — Phase1ウィンドウ: 締切{PHASE1_LO}〜{PHASE1_HI}分前 / Phase2ウィンドウ: {PHASE2_LO}〜{PHASE2_HI}分前")

    # ── Phase0: 発走済みレースの結果確認 ─────────────────────────────────
    pending = get_pending_races()
    today_str = today.strftime('%Y-%m-%d')
    # 当日以外の古いpendingはスキップ（前日以前の未処理ログ）
    pending = [p for p in pending if p.get('date', '') == today_str]
    if pending:
        print(f"\n🔎 結果確認: {len(pending)}件")
        scraper0 = KdreamsScraper()
        for pr in pending:
            venue_slug = pr.get('venue_slug', '') or pr.get('venue', '')
            # ?pageType=result を付与して結果ページを取得
            result_url = f"https://keirin.kdreams.jp/{venue_slug}/racedetail/{pr['race_id']}/?pageType=result"
            res = get_race_result(scraper0, result_url)
            if res:
                updated = update_result(pr['race_id'], res['combo'], res['payout'])
                if updated:
                    summary = get_daily_summary()
                    total_today = summary['profit']
                    row = next((r for r in summary['hits'] + summary['misses']
                                if str(r['race_id']) == str(pr['race_id'])), None)
                    if row:
                        hit     = row['status'] == 'hit'
                        profit  = int(row['profit'])
                        payout  = int(row['payout'])
                        # ☆☆☆（勝負レース）のみ結果をDiscordに投稿
                        if pr.get('grade', '☆☆☆') == '☆☆☆':
                            send_race_result(
                                venue=pr['venue'], race_no=int(pr['race_no']),
                                race_name=pr.get('race_name', 'S級'),
                                result_combo=res['combo'], payout=payout,
                                hit=hit, profit=profit,
                            )
            time.sleep(0.5)

    # 全レース取得
    print("\n📡 当日開催を取得中...")
    races = fetch_today_f1_g3_races(today, min_grade="F1", fetch_times=True)
    if not races:
        print("開催なし or 取得失敗")
        return

    # ── 時間外ガード: JST 21:05 以降は予想通知を行わない ─────────────────────
    # ★ 全レース終了後の毎分サマリー送信を防ぐため、残レースチェックより前に配置
    if now.hour > 21 or (now.hour == 21 and now.minute >= 5):
        print(f"🕐 {now.strftime('%H:%M')} — 21:05以降のため予想通知をスキップ（結果確認のみ実施済み）")
        return

    # ── 残レースチェック: 全S級レース終了後は終了 ───────────────────────────
    # 日次サマリーは weekly_summary.yml（毎日 21:00 JST）に委譲
    remaining = [r for r in races if r.get('deadline_time') and r['deadline_time'] > now]
    if not remaining:
        print("✅ 本日のS級レースは全て終了。（日次サマリーは 21:00 JST の weekly_summary.yml から送信）")
        return

    # bets_logで重複チェックするのでcronが何度叩いても安全
    NOTIFY_LO = 7    # 締切N分前・最大値（ここを超えたらもう対象外）
    NOTIFY_HI = 15   # 締切N分前・最小値（= 8分ウィンドウ）
    p_lo = now + timedelta(minutes=NOTIFY_LO)
    p_hi = now + timedelta(minutes=NOTIFY_HI)

    notify_target = [r for r in races
                     if r.get('deadline_time') and p_lo <= r['deadline_time'] <= p_hi]

    print(f"\n🔔 通知対象: {len(notify_target)}R (締切{NOTIFY_LO}〜{NOTIFY_HI}分前)")
    if not notify_target:
        return

    db_all, db_slim, nobi_col = load_db()
    scraper = KdreamsScraper()

    # 既に記録済みのrace_idを取得（重複通知防止）
    from bet_logger import _load_all
    existing_rows = _load_all()  # list[dict]
    today_str = today.strftime('%Y-%m-%d')
    already_logged = {
        r['race_id'] for r in existing_rows
        if r.get('date', '') == today_str
        and r.get('status', '') in ('pending', 'hit', 'miss')
    }

    for r in notify_target:
        venue    = r['venue']
        race_no  = r['race_no']
        race_url = r['race_url']
        deadline = r['deadline_time']
        start    = r.get('start_time')
        mins_left = int((deadline - now).total_seconds() / 60)
        race_id  = r['race_id']
        # race_url から venue_slug を抽出 (例: .../matsuyama/racecard/...)
        try:
            venue_slug = race_url.split('keirin.kdreams.jp/')[1].split('/')[0]
        except Exception:
            venue_slug = ''

        if str(race_id) in already_logged:
            print(f"  ⏩ {venue} {race_no}R 通知済みスキップ")
            continue

        print(f"  🔎 {venue} {race_no}R  締切{r['deadline_str']}(あと{mins_left}分)")

        race_card, num_to_line, num_to_bibs = get_race_info(scraper, race_url)
        time.sleep(0.5)
        odds_dict = get_odds(scraper, race_url)
        time.sleep(0.5)

        if race_card.empty:
            print(f"  ⚠️  出走表取得失敗")
            continue
        if not odds_dict:
            print(f"  ⚠️  オッズ取得失敗")
            continue

        result = run_prediction(
            venue, race_no, race_card, num_to_line, num_to_bibs,
            odds_dict, db_all, db_slim, nobi_col, today_dt
        )

        if result:
            log_bet(
                race_id=race_id, venue=venue, race_no=race_no,
                race_name=r.get('race_name', 'S級'),
                start_time=start,
                bets=result['bets'],
                total=result['total'],
                status='pending',
                venue_slug=r.get('venue_slug', ''),
                grade=result['grade'],
            )
            lines_for_discord = [
                {'line': lno, 'bibs': [b for b, ln in num_to_line.items() if ln == lno]}
                for lno in sorted(set(num_to_line.values()))
            ]
            send_prediction(
                venue=venue, race_no=race_no,
                race_name=r.get('race_name', 'S級'),
                start_str=r['start_time_str'],
                deadline_str=r['deadline_str'],
                mins_left=mins_left,
                lines=lines_for_discord,
                result=result,
                grade=result['grade'],
            )
            print(f"  ✅ 通知送信: {venue} {race_no}R  {result['grade']}  軸:{result['axis']}")
        else:
            print(f"  ⏭️  スキップ（EVScore/カオスフィルタ）")


if __name__ == "__main__":
    main()
