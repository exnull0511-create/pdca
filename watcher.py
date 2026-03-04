"""
watcher.py — 当日レース監視 & LINE通知デーモン
================================================
Oracle Cloud Free Tier (Ubuntu) で systemd サービスとして常駐させる。

動作:
  1. 毎朝 7:30 に当日のレーススケジュールを取得
  2. 各レースの「発走10分前」にトリガー
  3. 最新オッズ + 出走表で LOOSE_B 予想を実行
  4. 買い判定が出た場合のみ LINE Notify で通知

起動方法:
  export LINE_NOTIFY_TOKEN="your_token_here"
  export DB_SLIM_PATH="/home/ubuntu/pdca/data/S級DB_slim.xlsx"
  python watcher.py
"""

import os
import time
import threading
import traceback
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from pathlib import Path

# 環境変数
LINE_TOKEN   = os.environ.get("LINE_NOTIFY_TOKEN", "")
DB_SLIM_PATH = os.environ.get("DB_SLIM_PATH", "data/S級DB_slim.xlsx")
DB_OLD_PATH  = os.environ.get("DB_OLD_PATH",  "data/S級選手究極DB(1).xlsx")
NOTIFY_MIN_BEFORE = 10  # 発走N分前に通知

# ─── インポート ───────────────────────────────────────────────────────────────
try:
    import requests
    from scraper import (
        get_today_schedule, scrape_racecard, scrape_odds,
        SLUG_TO_VENUE, VENUE_SLUG
    )
except ImportError as e:
    print(f"❌ import失敗: {e}")
    exit(1)

# ─── 設定 ────────────────────────────────────────────────────────────────────
STRATEGY_CFG = {
    "skip_chaos":      True,
    "min_top_ev":      70,
    "require_monster": False,
    "skip_low_bank":   True,
    "top_n_prob_bets": 14,
    "bet_base":        100,
}

BANK_DICT = {
    '前橋':  {'roi_tier':'mid', 'sashi':0.8,  'makuri':1.2},
    '宇都宮':{'roi_tier':'high','sashi':1.5,  'makuri':1.1},
    '豊橋':  {'roi_tier':'high','sashi':1.3,  'makuri':1.2},
    '岸和田':{'roi_tier':'low', 'sashi':1.1,  'makuri':1.3},
    '熊本':  {'roi_tier':'high','sashi':1.2,  'makuri':1.1},
    'いわき平':{'roi_tier':'mid','sashi':0.9, 'makuri':1.3},
    '広島':  {'roi_tier':'mid', 'sashi':1.2,  'makuri':1.0},
    '別府':  {'roi_tier':'mid', 'sashi':1.1,  'makuri':1.1},
    '松山':  {'roi_tier':'mid', 'sashi':1.0,  'makuri':1.2},
    '小倉':  {'roi_tier':'low', 'sashi':1.1,  'makuri':1.1},
    '京王閣':{'roi_tier':'high','sashi':1.0,  'makuri':1.1},
    '立川':  {'roi_tier':'high','sashi':1.1,  'makuri':1.0},
    '取手':  {'roi_tier':'mid', 'sashi':1.1,  'makuri':1.1},
    '伊東':  {'roi_tier':'mid', 'sashi':1.0,  'makuri':1.2},
    '久留米':{'roi_tier':'low', 'sashi':1.1,  'makuri':1.1},
    '奈良':  {'roi_tier':'low', 'sashi':1.2,  'makuri':1.0},
    '岐阜':  {'roi_tier':'low', 'sashi':1.1,  'makuri':1.1},
    '小松島':{'roi_tier':'low', 'sashi':1.1,  'makuri':1.0},
    '防府':  {'roi_tier':'low', 'sashi':1.1,  'makuri':1.1},
    '静岡':  {'roi_tier':'low', 'sashi':1.2,  'makuri':1.0},
    '松阪':  {'roi_tier':'mid', 'sashi':1.1,  'makuri':1.1},
    '高知':  {'roi_tier':'mid', 'sashi':1.0,  'makuri':1.2},
    '松戸':  {'roi_tier':'mid', 'sashi':1.1,  'makuri':1.0},
    '平塚':  {'roi_tier':'mid', 'sashi':1.2,  'makuri':1.1},
    '西武園':{'roi_tier':'mid', 'sashi':1.0,  'makuri':1.1},
}

SENPO_LEAD = {
    '逃げ切り':5,'逃げ粘り':4,'突っ張り先行':4,'抑え先行':4,
    'カマシ先行':5,'先行逃げ切り':5,'先行':4,'逃げ':5,
    '先行争い敗北':3,'先行争い敗':3,'一発捲り':3,'ロング捲り':3,
    '捲り':3,'番手捲り':3,'カマシ捲り':4,'捲り差し':3,
    '捲り追い込み':2,'捲り不発':2,'番手差し':2,'差し':2,
    '追い込み':2,'流れ込み':1,'追走':1,'マーク':1,
}

def nobi_score(v):
    s=str(v).strip().upper()
    return 5 if s.startswith('S') else 4 if s.startswith('A') else 3 if s.startswith('B') else 1
def senpo_lead(v): return SENPO_LEAD.get(str(v).strip(), 1)
def norm_name(s): return str(s).replace(' ','').replace('\u3000','').strip()

# ─── DB ロード ────────────────────────────────────────────────────────────────
def load_db():
    db_all  = pd.DataFrame()
    db_slim = pd.DataFrame()
    nobi_col = '直線の伸び'

    if Path(DB_OLD_PATH).exists():
        xl = pd.ExcelFile(DB_OLD_PATH)
        db_all = pd.concat([xl.parse('F1'), xl.parse('G3~1')], ignore_index=True)
        db_all['開催日'] = pd.to_datetime(db_all['開催日'], errors='coerce')
        for c in ['IP','EP','DP','BP']:
            db_all[c] = pd.to_numeric(db_all[c], errors='coerce')
        db_all['選手名_norm'] = db_all['選手名'].apply(norm_name)
        cols = [c for c in db_all.columns if '直線' in c]
        nobi_col = cols[0] if cols else nobi_col
        print(f"📦 旧DB: {len(db_all)}行")

    if Path(DB_SLIM_PATH).exists():
        try:
            sl = pd.ExcelFile(DB_SLIM_PATH)
            sheets = sl.sheet_names
            dfs = []
            for sh in ['F1','G3~1']:
                if sh in sheets:
                    dfs.append(sl.parse(sh))
            db_slim = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
            db_slim['開催日'] = pd.to_datetime(db_slim['開催日'], errors='coerce')
            for c in ['IP','EP','DP','BP']:
                if c in db_slim.columns:
                    db_slim[c] = pd.to_numeric(db_slim[c], errors='coerce')
            db_slim['選手名_norm'] = db_slim['選手名'].apply(norm_name)
            print(f"📦 slim DB: {len(db_slim)}行")
        except Exception as e:
            print(f"⚠️  slim DB読み込み失敗: {e}")

    return db_all, db_slim, nobi_col

# ─── 予想コアロジック ─────────────────────────────────────────────────────────
def run_prediction(race_id: str, venue: str,
                   race_info: pd.DataFrame, race_odds: pd.DataFrame,
                   db_all: pd.DataFrame, db_slim: pd.DataFrame,
                   nobi_col: str, target_date: datetime):
    """LOOSE_Bフィルターで予想実行。買い判定ならbet情報を返す。"""
    bp = BANK_DICT.get(venue, {'sashi':1.0,'makuri':1.0,'roi_tier':'mid'})

    # ── 低ROIバンク除外 ──
    if STRATEGY_CFG['skip_low_bank'] and bp.get('roi_tier') == 'low':
        return None

    if race_info.empty:
        return None

    # 未来データ遮断
    past_db   = db_all[db_all['開催日'] < target_date] if not db_all.empty else db_all
    past_slim = db_slim[db_slim['開催日'] < target_date] if not db_slim.empty else db_slim

    # ライン解析
    num_to_line = {}
    line_map = {}
    for _, row in race_info.iterrows():
        lno  = int(row['line_no']) if not pd.isna(row.get('line_no', float('nan'))) else 0
        bibs_s = str(row.get('line_bibs', ''))
        if lno not in line_map:
            try: line_map[lno] = [int(x) for x in bibs_s.split('-') if x.isdigit()]
            except: line_map[lno] = []
    for lno, bibs in line_map.items():
        for b in bibs: num_to_line[b] = lno

    player_scores = {}
    for _, row in race_info.iterrows():
        num  = int(row['車番'])
        norm = norm_name(str(row['選手名']))
        base = float(row['競走得点'])

        # slim DB優先
        hist = past_slim[past_slim['選手名_norm']==norm] if not past_slim.empty else pd.DataFrame()
        use_slim = not hist.empty
        if hist.empty:
            hist = past_db[past_db['選手名_norm']==norm] if not past_db.empty else pd.DataFrame()

        if not hist.empty:
            RECENT_W = 3.0
            sorted_d = sorted(hist['開催日'].dropna().unique(), reverse=True)
            recent_d = set(sorted_d[:2])
            def wmean(series):
                vals = pd.to_numeric(series, errors='coerce')
                is_r = hist['開催日'].isin(recent_d)
                w    = np.where(is_r, RECENT_W, 1.0)
                mask = vals.notna()
                return float((vals[mask]*w[mask]).sum()/w[mask].sum()) if mask.any() else np.nan

            ip = wmean(hist['IP']); ep = wmean(hist['EP'])
            dp = wmean(hist['DP']); bp_v = wmean(hist['BP'])
            nb = wmean(hist['直線の伸び'].apply(nobi_score)) if (use_slim and '直線の伸び' in hist.columns) else \
                 wmean(hist[nobi_col].apply(nobi_score)) if nobi_col in hist.columns else np.nan
            sp = wmean(hist['戦法'].apply(senpo_lead)) if '戦法' in hist.columns else np.nan

            if use_slim:
                is_m = bool(hist['is_monster'].max()>=1)    if 'is_monster'    in hist.columns else False
                is_u = bool(hist['is_unreliable'].max()>=1) if 'is_unreliable' in hist.columns else False
            else:
                cmt  = ' '.join(hist['解析コメント'].astype(str).tolist()) if '解析コメント' in hist.columns else ''
                is_m = any(k in cmt for k in ['脚余し','鬼脚','別次元','圧倒','豪快'])
                is_u = any(k in cmt for k in ['共倒れ','位置取り失敗','不発','失速'])
        else:
            ip=ep=4.0; dp=bp_v=3.0; nb=sp=2.0; is_m=is_u=False

        for attr_name, default in [('ip',4.0),('ep',4.0),('dp',3.0),('bp_v',3.0),('nb',2.0),('sp',2.0)]:
            val = locals()[attr_name]
            if val is None or (isinstance(val,float) and np.isnan(val)):
                locals = locals()  # スコープ固定用
                # フォールバック値はすでに設定済み

        lno  = num_to_line.get(num, 0)
        lbibs = line_map.get(lno, [])
        pos  = lbibs.index(num)+1 if num in lbibs else 1
        pos_b = 0.5 if pos==1 else -0.3*(pos-1)

        ev = (base*0.4 + (ip or 4.0)*1.5 + (ep or 4.0)*1.2
              + (dp or 3.0)*bp['makuri'] + (bp_v or 3.0)*bp['sashi']
              + (nb or 2.0)*2.0 + (sp or 2.0)*0.5 + pos_b
              + (3.0 if is_m else 0) - (2.0 if is_u else 0))

        player_scores[num] = {
            'name': str(row['選手名']), 'ev': ev,
            'ip': ip or 4.0, 'is_monster': is_m, 'pos': pos,
        }

    ranked = sorted(player_scores.items(), key=lambda x: x[1]['ev'], reverse=True)
    if len(ranked) < 3:
        return None

    is_chaos = sum(1 for _,d in player_scores.items() if d['ip']>=5.5 and d['pos']==1) >= 2
    top_ev   = ranked[0][1]['ev']

    # フィルター
    if top_ev < STRATEGY_CFG['min_top_ev']: return None
    if is_chaos and STRATEGY_CFG['skip_chaos']: return None

    # PL確率計算
    all_nums = [n for n,_ in ranked]
    max_e    = ranked[0][1]['ev']
    raw_s    = {n: np.exp(player_scores[n]['ev']-max_e) for n in all_nums}

    def pl(f,s,t):
        d1=sum(raw_s[n] for n in all_nums)
        d2=sum(raw_s[n] for n in all_nums if n!=f)
        d3=sum(raw_s[n] for n in all_nums if n not in (f,s))
        if d1==0 or d2==0 or d3==0: return 0.0
        return (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)

    odds_dict = {}
    if not race_odds.empty:
        for _,or_ in race_odds.iterrows():
            odds_dict[str(or_['組み合わせ']).strip()] = float(or_['オッズ'])

    axis = [n for n,d in ranked if d['is_monster']]
    axis_num = axis[0] if axis else ranked[0][0]
    others   = [n for n,_ in ranked if n!=axis_num]

    ev_bets = []
    for s in others:
        for t in others:
            if s==t: continue
            c = f"{axis_num}-{s}-{t}"
            p = pl(axis_num,s,t)
            if c in odds_dict:
                ev_bets.append((p*odds_dict[c], c, p, odds_dict[c]))

    ev_bets.sort(key=lambda x: x[0], reverse=True)
    prob_bets = sorted(ev_bets, key=lambda x: x[2], reverse=True)[:14]
    bets      = [c for _,c,_,_ in prob_bets]
    el        = {c:ev for ev,c,p,o in ev_bets}
    bet_ev    = [(c, el.get(c,0.0)) for c in bets]

    # EV傾斜配分
    base_amt  = STRATEGY_CFG['bet_base']
    total_pool = base_amt * len(bets)
    ev_vals   = np.array([max(ev,0.0) for _,ev in bet_ev])
    if ev_vals.sum()==0:
        alloc = [base_amt]*len(bets)
    else:
        raw   = (ev_vals/ev_vals.sum())*total_pool
        a100  = (raw//100).astype(int)*100
        rem   = (int(total_pool-a100.sum())//100)*100
        a100[int(np.argmax(ev_vals))] += rem
        alloc = [max(int(a),100) for a in a100]

    return {
        'race_id':   race_id,
        'venue':     venue,
        'top_ev':    top_ev,
        'is_chaos':  is_chaos,
        'axis':      f"車番{axis_num} {player_scores[axis_num]['name']}",
        'bets':      [(c, u) for (c,_),u in zip(bet_ev, alloc)],
        'total':     sum(alloc),
        'ev_scores': [(n, d['ev'], d['name']) for n,d in ranked[:5]],
    }


# ─── LINE 通知 ────────────────────────────────────────────────────────────────
def send_line(message: str) -> bool:
    if not LINE_TOKEN:
        print(f"[LINE省略] {message[:80]}")
        return False
    try:
        r = requests.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {LINE_TOKEN}"},
            data={"message": message}, timeout=10
        )
        return r.status_code == 200
    except Exception as e:
        print(f"⚠️  LINE送信失敗: {e}")
        return False


def build_buy_message(result: dict, race_no: int, start_time: datetime) -> str:
    start_str = start_time.strftime('%H:%M') if start_time else '?'
    lines = [
        f"\n🎯 【買い】 {result['venue']} {race_no}R  発走{start_str}",
        f"軸: {result['axis']}  EV={result['top_ev']:.1f}",
        f"投資予定: ¥{result['total']:,}  ({len(result['bets'])}点)",
        "─────────────",
    ]
    for i, (combo, amt) in enumerate(result['bets'][:5], 1):
        lines.append(f" {i}. {combo}  ¥{amt}")
    if len(result['bets']) > 5:
        lines.append(f" ...他{len(result['bets'])-5}点")
    return '\n'.join(lines)


# ─── スケジューラ ─────────────────────────────────────────────────────────────
def schedule_race(race: dict, db_all, db_slim, nobi_col):
    """発走10分前にスリープして予想を実行するスレッド関数"""
    start_time = race.get('start_time')
    if start_time is None:
        print(f"⚠️  {race['race_id']} 発走時刻不明 → スキップ")
        return

    trigger_dt = start_time - timedelta(minutes=NOTIFY_MIN_BEFORE)
    now = datetime.now()

    wait_sec = (trigger_dt - now).total_seconds()
    if wait_sec < -60:
        print(f"⏭️   {race['venue']} {race['race_no']}R → 既に通知時刻を過ぎている ({trigger_dt.strftime('%H:%M')})")
        return

    if wait_sec > 0:
        print(f"⏰  {race['venue']} {race['race_no']}R → {trigger_dt.strftime('%H:%M')}に予想実行予定 "
              f"(発走{start_time.strftime('%H:%M')} の{NOTIFY_MIN_BEFORE}分前)")
        time.sleep(wait_sec)

    print(f"\n🔍 予想実行: {race['venue']} {race['race_no']}R ({race['race_id']})")
    try:
        venue_slug = VENUE_SLUG.get(race['venue'], race['venue'])
        race_info  = scrape_racecard(race['race_id'], venue_slug)
        race_odds  = scrape_odds(race['race_id'], venue_slug)
        time.sleep(1)  # リクエスト間隔

        result = run_prediction(
            race['race_id'], race['venue'],
            race_info, race_odds,
            db_all, db_slim, nobi_col,
            datetime.combine(date.today(), datetime.min.time())
        )

        if result:
            msg = build_buy_message(result, race['race_no'], start_time)
            print(msg)
            send_line(msg)
        else:
            print(f"⏭️   {race['venue']} {race['race_no']}R → フィルター除外（スキップ）")

    except Exception as e:
        err = f"❌ {race['venue']} {race['race_no']}R 予想エラー: {e}"
        print(err); traceback.print_exc()


# ─── メインループ ─────────────────────────────────────────────────────────────
def main():
    print("🚀 競輪予想 Watcher 起動")
    print(f"   LINE通知: {'有効' if LINE_TOKEN else '❌ TOKEN未設定'}")
    print(f"   発走 {NOTIFY_MIN_BEFORE}分前に予想実行\n")

    if LINE_TOKEN:
        send_line("\n🚀 競輪予想 Watcher 起動しました")

    # DB は一度だけロード（DBは毎日更新後に再起動で反映）
    db_all, db_slim, nobi_col = load_db()

    while True:
        today = date.today()
        print(f"\n📅 {today} のスケジュール取得中...")
        races = get_today_schedule(today)

        if not races:
            send_line(f"\n📅 {today} 開催なし（または取得失敗）")
        else:
            summary = f"\n📅 {today} 本日の開催: "
            venue_counts = {}
            for r in races: venue_counts[r['venue']] = venue_counts.get(r['venue'],0)+1
            summary += " / ".join(f"{v} {n}R" for v,n in venue_counts.items())
            print(summary)
            send_line(summary)

            # 各レースを別スレッドで監視
            threads = []
            for race in races:
                t = threading.Thread(
                    target=schedule_race,
                    args=(race, db_all, db_slim, nobi_col),
                    daemon=True
                )
                t.start()
                threads.append(t)
                time.sleep(0.2)  # スレッド起動間隔

            # 全スレッド完了まで待機
            for t in threads:
                t.join()

        # 翌朝 7:30 まで待機
        now    = datetime.now()
        target = datetime.combine(today + timedelta(days=1),
                                  datetime.strptime("07:30", "%H:%M").time())
        sleep_sec = (target - now).total_seconds()
        print(f"\n😴 翌日 {target.strftime('%m/%d %H:%M')} まで待機 ({sleep_sec/3600:.1f}h)")
        if LINE_TOKEN:
            send_line(f"\n😴 本日終了。翌日{target.strftime('%H:%M')}に再開します")
        time.sleep(max(sleep_sec, 60))


if __name__ == "__main__":
    main()
