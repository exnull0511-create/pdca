"""
predict.py — 当日予想実行スクリプト
================================
hardcore_ev.py のバックテストエンジンを「当日予想モード」に変換。
payouts.xlsx は不要。racecard.xlsx + odds.xlsx + DB があれば動く。

使い方:
  python predict.py
  python predict.py --date 20260304          # 特定日を指定
  python predict.py --race 2620260304010101  # 特定race_idのみ

出力:
  predict_{YYYYMMDD}.txt  — 買い目レポート（テキスト）
  predict_{YYYYMMDD}.csv  — 買い目一覧（CSV: race_id, 組み合わせ, 金額）
"""

import argparse
import pandas as pd
import numpy as np
import warnings
import datetime
from pathlib import Path
warnings.filterwarnings('ignore')

# ──────────────────────────────────────────────────────────────────
# ストラテジー固定（本採用: LOOSE_B）
# ──────────────────────────────────────────────────────────────────
STRATEGY = "S_MAXHIT_14_EV_LOOSE_B"
SCFG = {
    "name":               "EV傾斜【LOOSE-B: 鬼脚なし+EV70+カオス除外+低bank除外】",
    "skip_chaos":         True,
    "min_top_ev":         70,
    "require_monster":    False,
    "s3_chaos_filter":    False,
    "use_full_permutation": False,
    "top_n_prob_bets":    14,
    "ev_alloc":           True,
    "bet_base":           100,
    "skip_low_bank":      True,
}

# ──────────────────────────────────────────────────────────────────
# データロード（hardcore_ev.py と同じ前処理）
# ──────────────────────────────────────────────────────────────────
def normalize_name(s):
    return str(s).replace(" ", "").replace("\u3000", "").strip()

def nobi_score(val):
    s = str(val).strip().upper()
    if s.startswith('S'): return 5
    elif s.startswith('A'): return 4
    elif s.startswith('B'): return 3
    elif s.startswith('C'): return 1
    return 2

SENPO_LEAD = {
    '逃げ切り':5,'逃げ粘り':4,'突っ張り先行':4,'抑え先行':4,
    'カマシ先行':5,'先行逃げ切り':5,'先行':4,'逃げ':5,
    '先行争い敗北':3,'先行争い敗':3,'一発捲り':3,'ロング捲り':3,
    '捲り':3,'番手捲り':3,'カマシ捲り':4,'捲り差し':3,
    '捲り追い込み':2,'捲り不発':2,'番手差し':2,'差し':2,
    '追い込み':2,'流れ込み':1,'追走':1,'マーク':1,
}
def senpo_lead(val): return SENPO_LEAD.get(str(val).strip(), 1)

bank_dict = {
    '前橋':{'type':'超高速','length':335,'sashi':0.8,'makuri':1.2,'roi_tier':'mid'},
    '宇都宮':{'type':'重い','length':500,'sashi':1.5,'makuri':1.1,'roi_tier':'high'},
    '豊橋':{'type':'風強','length':400,'sashi':1.3,'makuri':1.2,'roi_tier':'high'},
    '岸和田':{'type':'波状','length':400,'sashi':1.1,'makuri':1.3,'roi_tier':'low'},
    '熊本':{'type':'標準','length':400,'sashi':1.2,'makuri':1.1,'roi_tier':'high'},
    'いわき平':{'type':'短走路','length':335,'sashi':0.9,'makuri':1.3,'roi_tier':'mid'},
    '広島':{'type':'重い','length':400,'sashi':1.2,'makuri':1.0,'roi_tier':'mid'},
    '別府':{'type':'標準','length':400,'sashi':1.1,'makuri':1.1,'roi_tier':'mid'},
    '松山':{'type':'標準','length':333,'sashi':1.0,'makuri':1.2,'roi_tier':'mid'},
    '小倉':{'type':'標準','length':400,'sashi':1.1,'makuri':1.1,'roi_tier':'low'},
    '京王閣':{'type':'標準','length':400,'sashi':1.0,'makuri':1.1,'roi_tier':'high'},
    '立川':{'type':'標準','length':400,'sashi':1.1,'makuri':1.0,'roi_tier':'high'},
    '取手':{'type':'標準','length':400,'sashi':1.1,'makuri':1.1,'roi_tier':'mid'},
    '伊東':{'type':'標準','length':333,'sashi':1.0,'makuri':1.2,'roi_tier':'mid'},
    '久留米':{'type':'標準','length':400,'sashi':1.1,'makuri':1.1,'roi_tier':'low'},
    '奈良':{'type':'標準','length':400,'sashi':1.2,'makuri':1.0,'roi_tier':'low'},
    '岐阜':{'type':'標準','length':400,'sashi':1.1,'makuri':1.1,'roi_tier':'low'},
    '小松島':{'type':'標準','length':400,'sashi':1.1,'makuri':1.0,'roi_tier':'low'},
    '防府':{'type':'標準','length':400,'sashi':1.1,'makuri':1.1,'roi_tier':'low'},
    '静岡':{'type':'標準','length':400,'sashi':1.2,'makuri':1.0,'roi_tier':'low'},
    '松阪':{'type':'標準','length':400,'sashi':1.1,'makuri':1.1,'roi_tier':'mid'},
    '高知':{'type':'標準','length':400,'sashi':1.0,'makuri':1.2,'roi_tier':'mid'},
    '松戸':{'type':'標準','length':400,'sashi':1.1,'makuri':1.0,'roi_tier':'mid'},
    '平塚':{'type':'標準','length':400,'sashi':1.2,'makuri':1.1,'roi_tier':'mid'},
}

print("📦 データ読み込み中...")
racecard_raw = pd.read_excel("data/racecard.xlsx", dtype={'race_id': str})
odds_raw     = pd.read_excel("data/odds.xlsx",     dtype={'race_id': str})

# DB読み込み（旧DB）
xl     = pd.ExcelFile("data/S級選手究極DB(1).xlsx")
db_f1  = xl.parse('F1')
db_g3  = xl.parse('G3~1')
db_all = pd.concat([db_f1, db_g3], ignore_index=True)
db_all['開催日']      = pd.to_datetime(db_all['開催日'], errors='coerce')
db_all['IP']          = pd.to_numeric(db_all['IP'], errors='coerce')
db_all['EP']          = pd.to_numeric(db_all['EP'], errors='coerce')
db_all['DP']          = pd.to_numeric(db_all['DP'], errors='coerce')
db_all['BP']          = pd.to_numeric(db_all['BP'], errors='coerce')
db_all['選手名_norm'] = db_all['選手名'].apply(normalize_name)
nobi_col = [c for c in db_all.columns if '直線' in c][0]

# slim DB があれば読み込んで優先使用
slim_path = Path("data/S級DB_slim.xlsx")
db_slim = pd.DataFrame()
if slim_path.exists():
    try:
        sl_f1 = pd.ExcelFile(slim_path).parse('F1')
        sl_g3 = pd.ExcelFile(slim_path).parse('G3~1')
        db_slim = pd.concat([sl_f1, sl_g3], ignore_index=True)
        db_slim['開催日']      = pd.to_datetime(db_slim['開催日'], errors='coerce')
        db_slim['選手名_norm'] = db_slim['選手名'].apply(normalize_name)
        for col in ['IP','EP','DP','BP']:
            db_slim[col] = pd.to_numeric(db_slim[col], errors='coerce')
        print(f"✅ slim DB 読み込み: {len(db_slim)}行")
    except Exception as e:
        print(f"⚠️  slim DB 読み込み失敗: {e}")
        db_slim = pd.DataFrame()

# race_id 整形
for df in [racecard_raw, odds_raw]:
    df['race_id'] = df['race_id'].apply(
        lambda v: str(v)[2:-1] if str(v).startswith('="') else str(v))
racecard_raw['date'] = pd.to_datetime(racecard_raw['date'].astype(str), format='%Y%m%d')
for col in ['競走得点','S','B','逃','捲','差','マ','1着','2着','3着','着外']:
    racecard_raw[col] = pd.to_numeric(racecard_raw[col], errors='coerce').fillna(0)
odds_raw['オッズ'] = pd.to_numeric(odds_raw['オッズ'], errors='coerce')

# ──────────────────────────────────────────────────────────────────
# 予想コアロジック（hardcore_ev.py の analyze_race を流用）
# ──────────────────────────────────────────────────────────────────
def parse_lines(race_info):
    lines = {}
    for _, row in race_info.iterrows():
        lno  = int(row['line_no']) if not pd.isna(row['line_no']) else 0
        bibs = str(row['line_bibs'])
        if lno not in lines:
            try: lines[lno] = [int(x) for x in bibs.split('-') if x.isdigit()]
            except: lines[lno] = []
    return lines

def analyze_race_predict(race_id, venue, race_info, race_odds, past_db, past_slim):
    """predict用: payouts不要, 結果判定なし"""
    bp = bank_dict.get(venue, {'type':'標準','length':400,'sashi':1.0,'makuri':1.0,'roi_tier':'mid'})
    if race_info.empty: return "", [], []

    line_map    = parse_lines(race_info)
    num_to_line = {}
    for lno, bibs in line_map.items():
        for b in bibs: num_to_line[b] = lno

    player_scores = {}
    for _, row in race_info.iterrows():
        num  = int(row['車番'])
        norm = normalize_name(str(row['選手名']))
        base_score = float(row['競走得点'])

        # slim DB優先 → 旧DB フォールバック
        hist = past_slim[past_slim['選手名_norm'] == norm] if not past_slim.empty else pd.DataFrame()
        use_slim = not hist.empty
        if hist.empty:
            hist = past_db[past_db['選手名_norm'] == norm]

        if not hist.empty:
            RECENT_W = 3.0
            sorted_dates = sorted(hist['開催日'].dropna().unique(), reverse=True)
            recent_dates = set(sorted_dates[:2])
            def wmean(series):
                vals    = pd.to_numeric(series, errors='coerce')
                is_rec  = hist['開催日'].isin(recent_dates)
                weights = np.where(is_rec, RECENT_W, 1.0)
                mask    = vals.notna()
                if not mask.any(): return np.nan
                return float((vals[mask]*weights[mask]).sum()/weights[mask].sum())
            ip_avg = wmean(hist['IP']); ep_avg = wmean(hist['EP'])
            dp_avg = wmean(hist['DP']); bp_avg = wmean(hist['BP'])
            if use_slim:
                avg_nobi  = wmean(hist['直線の伸び'].apply(nobi_score)) if '直線の伸び' in hist.columns else 2.0
                is_monster    = bool(hist['is_monster'].max() >= 1)    if 'is_monster'    in hist.columns else False
                is_unreliable = bool(hist['is_unreliable'].max() >= 1) if 'is_unreliable' in hist.columns else False
                avg_senpo = wmean(hist['戦法'].apply(senpo_lead)) if '戦法' in hist.columns else 2.0
            else:
                avg_nobi  = wmean(hist[nobi_col].apply(nobi_score))
                avg_senpo = wmean(hist['戦法'].apply(senpo_lead))
                comments  = " ".join(hist['解析コメント'].astype(str).tolist())
                is_monster    = any(kw in comments for kw in ["脚余し","鬼脚","別次元","圧倒","豪快"])
                is_unreliable = any(kw in comments for kw in ["共倒れ","位置取り失敗","不発","失速"])
        else:
            ip_avg=ep_avg=4.0; dp_avg=bp_avg=3.0
            avg_nobi=avg_senpo=2.0; is_monster=is_unreliable=False

        for attr, default in [('ip_avg',4.0),('ep_avg',4.0),('dp_avg',3.0),('bp_avg',3.0),('avg_nobi',2.0),('avg_senpo',2.0)]:
            val = locals()[attr]
            if val is None or (isinstance(val, float) and np.isnan(val)):
                locals()[attr]  # フォールバックはすでに代入済みなのでそのまま

        lno         = num_to_line.get(num, 0)
        line_bibs_l = line_map.get(lno, [])
        pos_in_line = line_bibs_l.index(num)+1 if num in line_bibs_l else 1
        line_pos_bonus = 0.5 if pos_in_line==1 else (-0.3*(pos_in_line-1))

        ev_score = (
            base_score*0.4 + ip_avg*1.5 + ep_avg*1.2
            + dp_avg*bp['makuri'] + bp_avg*bp['sashi']
            + avg_nobi*2.0 + avg_senpo*0.5 + line_pos_bonus
            + (3.0 if is_monster else 0) - (2.0 if is_unreliable else 0)
        )
        player_scores[num] = {
            'name': str(row['選手名']), 'ev_score': ev_score,
            'ip': ip_avg, 'is_monster': is_monster, 'pos_in_line': pos_in_line,
            'style': str(row['脚質']),
        }

    ranked = sorted(player_scores.items(), key=lambda x: x[1]['ev_score'], reverse=True)
    if not ranked: return "", [], []

    is_chaos    = sum(1 for _,d in player_scores.items() if d['ip']>=5.5 and d['pos_in_line']==1) >= 2
    has_monster = any(d['is_monster'] for _,d in player_scores.items())
    top_ev      = ranked[0][1]['ev_score']
    ev_gap      = (ranked[0][1]['ev_score']-ranked[1][1]['ev_score']) if len(ranked)>=2 else 0
    chaos_count = sum(1 for _,d in player_scores.items() if d['ip']>=5.5 and d['pos_in_line']==1)

    meta = {'is_chaos':is_chaos,'has_monster':has_monster,'top_ev':top_ev,'ev_gap':ev_gap,'chaos_count':chaos_count}

    # ──── フィルター判定 ────
    if top_ev < SCFG['min_top_ev']: return "", [], []
    if is_chaos and SCFG['skip_chaos']: return "", [], []
    if SCFG['skip_low_bank'] and bank_dict.get(venue,{}).get('roi_tier')=='low': return "", [], []

    # ──── PL計算 ────
    all_nums = [n for n,_ in ranked]
    max_ev_s = ranked[0][1]['ev_score']
    raw_s    = {n: np.exp(player_scores[n]['ev_score']-max_ev_s) for n in all_nums}
    def pl_prob(f,s,t):
        d1=sum(raw_s[n] for n in all_nums); d2=sum(raw_s[n] for n in all_nums if n!=f)
        d3=sum(raw_s[n] for n in all_nums if n not in (f,s))
        if d1==0 or d2==0 or d3==0: return 0.0
        return (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)

    odds_dict = {}
    if not race_odds.empty:
        for _,orow in race_odds.iterrows():
            odds_dict[str(orow['組み合わせ']).strip()] = float(orow['オッズ'])

    hidden_monsters = [(n,d) for n,d in ranked if d['is_monster']]
    axis_num   = hidden_monsters[0][0] if hidden_monsters else ranked[0][0]
    others     = [n for n,_ in ranked if n!=axis_num]

    all_ev_bets = []
    for second in others:
        for third in others:
            if second==third: continue
            combo = f"{axis_num}-{second}-{third}"
            p     = pl_prob(axis_num, second, third)
            if combo in odds_dict:
                all_ev_bets.append((p*odds_dict[combo], combo, p, odds_dict[combo]))

    all_ev_bets.sort(key=lambda x: x[0], reverse=True)
    all_prob_bets = sorted(all_ev_bets, key=lambda x: x[2], reverse=True)

    selected = all_prob_bets[:14]
    bets     = [c for _,c,_,_ in selected]
    ev_lookup = {c:ev for ev,c,p,o in all_ev_bets}
    bet_ev_list = [(c, ev_lookup.get(c,0.0)) for c in bets]

    # ──── EV傾斜配分 ────
    bet_base   = SCFG['bet_base']
    total_pool = bet_base * len(bets)
    ev_vals    = np.array([max(ev, 0.0) for _,ev in bet_ev_list])
    if ev_vals.sum() == 0:
        alloc_units = [bet_base] * len(bets)
    else:
        raw_alloc  = (ev_vals/ev_vals.sum()) * total_pool
        alloc_100  = (raw_alloc//100).astype(int)*100
        remainder  = (int(total_pool-alloc_100.sum())//100)*100
        alloc_100[int(np.argmax(ev_vals))] += remainder
        alloc_units = [max(int(a),100) for a in alloc_100]

    # ──── レポート生成 ────
    total_cost = sum(alloc_units)
    report  = f"{'='*55}\n"
    report += f"🎯 {venue}バンク  Race ID: {race_id}\n"
    report += f"{'='*55}\n"
    report += f"カオス={is_chaos}  鬼脚={has_monster}  top_EV={top_ev:.1f}  総投資予定=¥{total_cost:,}\n\n"
    report += f"📋 EVランキング\n"
    for i,(n,d) in enumerate(ranked[:5], 1):
        report += f"  {i}位 車番{n} {d['name']} ({d['style']}) EV:{d['ev_score']:.1f}"
        if d['is_monster']: report += " 🔥"
        report += "\n"
    report += f"\n🎰 買い目（EV傾斜配分 / 計{len(bets)}点 ¥{total_cost:,}）\n"
    for (c, ev), unit in zip(bet_ev_list, alloc_units):
        odds_v = odds_dict.get(c, 0)
        report += f"  {c}  ¥{unit:>5,}  オッズ{odds_v:.1f}倍  EV={ev:.3f}\n"
    report += "\n"

    return report, bets, bet_ev_list, alloc_units

# ──────────────────────────────────────────────────────────────────
# メイン実行
# ──────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument('--date', type=str, default=None, help='対象日 YYYYMMDD（省略時=最新日）')
parser.add_argument('--race', type=str, default=None, help='特定race_idのみ実行')
args = parser.parse_args()

if args.date:
    target_date = pd.Timestamp(args.date)
else:
    target_date = racecard_raw['date'].max()

print(f"\n🗓️  予想対象日: {target_date.strftime('%Y/%m/%d')}")
print(f"🎮 ストラテジー: {STRATEGY}\n")

daily_rc = racecard_raw[racecard_raw['date'] == target_date]
past_db  = db_all[db_all['開催日'] < target_date]
past_slim = db_slim[db_slim['開催日'] < target_date] if not db_slim.empty else pd.DataFrame()

race_ids = [args.race] if args.race else daily_rc['race_id'].unique().tolist()

date_str  = target_date.strftime('%Y%m%d')
out_txt   = f"predict_{date_str}.txt"
out_csv   = f"predict_{date_str}.csv"
csv_rows  = []

with open(out_txt, 'w', encoding='utf-8') as f:
    f.write(f"🏁 当日予想レポート [{STRATEGY}]  {target_date.strftime('%Y/%m/%d')}\n\n")

    bet_count = 0
    for rid in race_ids:
        race_info = daily_rc[daily_rc['race_id'] == rid].copy()
        if race_info.empty: continue
        venue     = race_info['venue'].iloc[0]
        race_odds = odds_raw[odds_raw['race_id'] == rid]

        result = analyze_race_predict(rid, venue, race_info, race_odds, past_db, past_slim)
        if not result or not result[0]:
            f.write(f"⏭️  スキップ: {venue} {rid}\n\n")
            continue

        report, bets, bet_ev_list, alloc_units = result
        f.write(report)
        bet_count += 1

        for (combo, ev), unit in zip(bet_ev_list, alloc_units):
            csv_rows.append({'race_id': rid, '会場': venue, '組み合わせ': combo,
                             '投資額': unit, 'EV': round(ev,3)})

    total_invest = sum(r['投資額'] for r in csv_rows)
    f.write(f"\n{'='*55}\n")
    f.write(f"✅ 購入対象レース: {bet_count}R  総予定投資: ¥{total_invest:,}\n")

pd.DataFrame(csv_rows).to_csv(out_csv, index=False, encoding='utf-8-sig')
print(f"✅ レポート: {out_txt}")
print(f"✅ 買い目CSV: {out_csv}")
print(f"   購入対象: {bet_count}R  予定投資: ¥{total_invest:,}")
