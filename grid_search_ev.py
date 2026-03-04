"""
grid_search_ev.py
S_MAXHIT_14_EV ベースのルックフィルター グリッドサーチ

探索パラメータ:
  skip_chaos      : [False, True]
  min_top_ev      : [0, 60, 65, 70, 75]
  require_monster : [False, True]
  skip_low_bank   : [False, True]
→ 合計 2×5×2×2 = 40 組合わせ
"""

import pandas as pd
import numpy as np
import warnings
import itertools
warnings.filterwarnings('ignore')

# ──────────────────────────────────────────────────────────────────
# データロード（hardcore_ev.py と同じ前処理）
# ──────────────────────────────────────────────────────────────────
print("📦 データ読み込み中...")

def normalize_name(s):
    return str(s).replace(" ", "").replace("\u3000", "").strip()

racecard_raw = pd.read_excel("data/racecard.xlsx", dtype={'race_id': str})
odds_raw     = pd.read_excel("data/odds.xlsx",     dtype={'race_id': str})
payouts_raw  = pd.read_excel("data/payouts.xlsx",  dtype={'race_id': str})

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

for df in [racecard_raw, odds_raw, payouts_raw]:
    df['race_id'] = df['race_id'].apply(
        lambda v: str(v)[2:-1] if str(v).startswith('="') else str(v))
payouts_raw['result_trifecta'] = payouts_raw['result_trifecta'].apply(
    lambda v: str(v)[2:-1] if str(v).startswith('="') else str(v))

racecard_raw['date'] = pd.to_datetime(racecard_raw['date'].astype(str), format='%Y%m%d')
for col in ['競走得点', 'S', 'B', '逃', '捲', '差', 'マ', '1着', '2着', '3着', '着外']:
    racecard_raw[col] = pd.to_numeric(racecard_raw[col], errors='coerce').fillna(0)
odds_raw['オッズ'] = pd.to_numeric(odds_raw['オッズ'], errors='coerce')

bank_dict = {
    '前橋':{'roi_tier':'mid'},'宇都宮':{'roi_tier':'high'},'豊橋':{'roi_tier':'high'},
    '岸和田':{'roi_tier':'low'},'熊本':{'roi_tier':'high'},'いわき平':{'roi_tier':'mid'},
    '広島':{'roi_tier':'mid'},'別府':{'roi_tier':'mid'},'松山':{'roi_tier':'mid'},
    '小倉':{'roi_tier':'low'},'京王閣':{'roi_tier':'high'},'立川':{'roi_tier':'high'},
    '取手':{'roi_tier':'mid'},'伊東':{'roi_tier':'mid'},'久留米':{'roi_tier':'low'},
    '奈良':{'roi_tier':'low'},'岐阜':{'roi_tier':'low'},'小松島':{'roi_tier':'low'},
    '防府':{'roi_tier':'low'},'静岡':{'roi_tier':'low'},'松阪':{'roi_tier':'mid'},
    '高知':{'roi_tier':'mid'},'松戸':{'roi_tier':'mid'},'平塚':{'roi_tier':'mid'},
}
bank_prof_full = {
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

SENPO_LEAD = {
    '逃げ切り':5,'逃げ粘り':4,'突っ張り先行':4,'抑え先行':4,
    'カマシ先行':5,'先行逃げ切り':5,'先行':4,'逃げ':5,
    '先行争い敗北':3,'先行争い敗':3,'一発捲り':3,'ロング捲り':3,
    '捲り':3,'番手捲り':3,'カマシ捲り':4,'捲り差し':3,
    '捲り追い込み':2,'捲り不発':2,'番手差し':2,'差し':2,
    '追い込み':2,'流れ込み':1,'追走':1,'マーク':1,
}
def senpo_lead(val): return SENPO_LEAD.get(str(val).strip(), 1)
def nobi_score(val):
    s = str(val).strip().upper()
    if s.startswith('S'): return 5
    elif s.startswith('A'): return 4
    elif s.startswith('B'): return 3
    elif s.startswith('C'): return 1
    return 2

def parse_lines(race_info):
    lines = {}
    for _, row in race_info.iterrows():
        lno  = int(row['line_no']) if not pd.isna(row['line_no']) else 0
        bibs = str(row['line_bibs'])
        if lno not in lines:
            try: lines[lno] = [int(x) for x in bibs.split('-') if x.isdigit()]
            except: lines[lno] = []
    return lines

# ──────────────────────────────────────────────────────────────────
# analyze_race: bets + meta を返す（ログなし版）
# ──────────────────────────────────────────────────────────────────
def analyze_race_fast(race_id, venue, race_info, race_odds, past_db):
    bp = bank_prof_full.get(venue, {'type':'標準','length':400,'sashi':1.0,'makuri':1.0,'roi_tier':'mid'})
    if race_info.empty: return [], {}

    line_map = parse_lines(race_info)
    num_to_line = {}
    for lno, bibs in line_map.items():
        for b in bibs: num_to_line[b] = lno
    line_leaders = {lno: bibs[0] for lno, bibs in line_map.items() if bibs}

    player_scores = {}
    for _, row in race_info.iterrows():
        num  = int(row['車番'])
        norm = normalize_name(str(row['選手名']))
        base_score = float(row['競走得点'])
        hist = past_db[past_db['選手名_norm'] == norm]

        if not hist.empty:
            RECENT_W = 3.0
            sorted_dates = sorted(hist['開催日'].dropna().unique(), reverse=True)
            recent_dates = set(sorted_dates[:2])
            def wmean(series):
                vals = pd.to_numeric(series, errors='coerce')
                is_rec = hist['開催日'].isin(recent_dates)
                weights = np.where(is_rec, RECENT_W, 1.0)
                mask = vals.notna()
                if not mask.any(): return np.nan
                return float((vals[mask]*weights[mask]).sum()/weights[mask].sum())
            ip_avg = wmean(hist['IP']); ep_avg = wmean(hist['EP'])
            dp_avg = wmean(hist['DP']); bp_avg = wmean(hist['BP'])
            avg_nobi  = wmean(hist[nobi_col].apply(nobi_score))
            avg_senpo = wmean(hist['戦法'].apply(senpo_lead))
        else:
            ip_avg=ep_avg=4.0; dp_avg=bp_avg=3.0; avg_nobi=avg_senpo=2.0

        for v, d in [(ip_avg,4.0),(ep_avg,4.0),(dp_avg,3.0),(bp_avg,3.0),(avg_nobi,2.0),(avg_senpo,2.0)]:
            pass  # フォールバックは下で
        ip_avg   = 4.0 if (ip_avg   is None or np.isnan(ip_avg))   else ip_avg
        ep_avg   = 4.0 if (ep_avg   is None or np.isnan(ep_avg))   else ep_avg
        dp_avg   = 3.0 if (dp_avg   is None or np.isnan(dp_avg))   else dp_avg
        bp_avg   = 3.0 if (bp_avg   is None or np.isnan(bp_avg))   else bp_avg
        avg_nobi = 2.0 if (avg_nobi is None or np.isnan(avg_nobi)) else avg_nobi
        avg_senpo= 2.0 if (avg_senpo is None or np.isnan(avg_senpo)) else avg_senpo

        comments = " ".join(hist['解析コメント'].astype(str).tolist()) if not hist.empty else ""
        is_monster    = any(kw in comments for kw in ["脚余し","鬼脚","別次元","圧倒","豪快"])
        is_unreliable = any(kw in comments for kw in ["共倒れ","位置取り失敗","不発","失速"])

        lno          = num_to_line.get(num, 0)
        line_bibs_l  = line_map.get(lno, [])
        pos_in_line  = line_bibs_l.index(num)+1 if num in line_bibs_l else 1
        line_pos_bonus = 0.5 if pos_in_line==1 else (-0.3*(pos_in_line-1))

        ev_score = (
            base_score*0.4 + ip_avg*1.5 + ep_avg*1.2
            + dp_avg*bp['makuri'] + bp_avg*bp['sashi']
            + avg_nobi*2.0 + avg_senpo*0.5 + line_pos_bonus
            + (3.0 if is_monster else 0) - (2.0 if is_unreliable else 0)
        )
        player_scores[num] = {
            'ev_score': ev_score, 'ip': ip_avg, 'is_monster': is_monster,
            'pos_in_line': pos_in_line, 'line_no': lno,
        }

    ranked = sorted(player_scores.items(), key=lambda x: x[1]['ev_score'], reverse=True)
    if not ranked: return [], {}

    strong_leaders = [d['ip'] >= 5.5 and d['pos_in_line']==1 for _, d in player_scores.items()]
    is_chaos     = sum(1 for _, d in player_scores.items()
                        if d['ip'] >= 5.5 and d['pos_in_line']==1) >= 2
    has_monster  = any(d['is_monster'] for _, d in player_scores.items())
    top_ev       = ranked[0][1]['ev_score']
    ev_gap       = (ranked[0][1]['ev_score'] - ranked[1][1]['ev_score']) if len(ranked)>=2 else 0
    chaos_count  = sum(1 for _, d in player_scores.items()
                        if d['ip'] >= 5.5 and d['pos_in_line']==1)

    all_nums = [n for n, _ in ranked]
    n_p      = len(all_nums)
    max_ev   = ranked[0][1]['ev_score']
    raw_s    = {num: np.exp(player_scores[num]['ev_score']-max_ev) for num in all_nums}

    def pl_prob(first, second, third):
        d1 = sum(raw_s[n] for n in all_nums)
        if d1==0: return 0.0
        d2 = sum(raw_s[n] for n in all_nums if n!=first)
        if d2==0: return 0.0
        d3 = sum(raw_s[n] for n in all_nums if n not in (first,second))
        if d3==0: return 0.0
        return (raw_s[first]/d1)*(raw_s[second]/d2)*(raw_s[third]/d3)

    odds_dict = {}
    if not race_odds.empty:
        for _, orow in race_odds.iterrows():
            odds_dict[str(orow['組み合わせ']).strip()] = float(orow['オッズ'])

    # 軸固定-PL（S_MAXHIT_14_EVと同じ）
    hidden_monsters = [(n,d) for n,d in ranked if d['is_monster']]
    axis_num  = hidden_monsters[0][0] if hidden_monsters else ranked[0][0]
    others    = [num for num,_ in ranked if num!=axis_num]

    all_ev_bets   = []
    all_prob_bets = []
    for second in others:
        for third in others:
            if second==third: continue
            combo  = f"{axis_num}-{second}-{third}"
            p_trio = pl_prob(axis_num, second, third)
            if combo in odds_dict:
                ev_val = p_trio * odds_dict[combo]
                all_ev_bets.append((ev_val, combo, p_trio, odds_dict[combo]))

    all_ev_bets.sort(key=lambda x: x[0], reverse=True)
    all_prob_bets = sorted(all_ev_bets, key=lambda x: x[2], reverse=True)

    # PL確率Top14を買い目とし、EV値を辞書引き
    selected = all_prob_bets[:14]
    bets     = [c for _,c,_,_ in selected]
    ev_lookup = {c: ev for ev,c,p,o in all_ev_bets}
    bet_ev_list = [(c, ev_lookup.get(c, 0.0)) for c in bets]

    meta = {
        'is_chaos': is_chaos, 'has_monster': has_monster,
        'top_ev': top_ev, 'ev_gap': ev_gap, 'chaos_count': chaos_count,
    }
    return bets, bet_ev_list, meta

# ──────────────────────────────────────────────────────────────────
# フィルター判定
# ──────────────────────────────────────────────────────────────────
def should_bet(meta, venue, cfg):
    if meta['top_ev'] < cfg['min_top_ev']: return False
    if cfg['require_monster'] and not meta['has_monster']: return False
    if meta['is_chaos'] and cfg['skip_chaos']: return False
    if cfg['skip_low_bank']:
        if bank_dict.get(venue, {}).get('roi_tier') == 'low': return False
    return True

# ──────────────────────────────────────────────────────────────────
# EV傾斜配分でコスト計算
# ──────────────────────────────────────────────────────────────────
BET_BASE = 100

def ev_alloc_units(bets, bet_ev_list, n_bets):
    total_pool = BET_BASE * n_bets
    ev_vals = np.array([max(ev, 0.0) for _, ev in bet_ev_list])
    if ev_vals.sum() == 0:
        return [BET_BASE] * n_bets
    raw_alloc  = (ev_vals / ev_vals.sum()) * total_pool
    alloc_100  = (raw_alloc // 100).astype(int) * 100
    remainder  = int(total_pool - alloc_100.sum())
    remainder  = (remainder // 100) * 100
    best_idx   = int(np.argmax(ev_vals))
    alloc_100[best_idx] += remainder
    return [max(int(a), 100) for a in alloc_100]

# ──────────────────────────────────────────────────────────────────
# グリッドサーチ本体
# ──────────────────────────────────────────────────────────────────
param_grid = list(itertools.product(
    [False, True],         # skip_chaos
    [0, 60, 65, 70, 75],   # min_top_ev
    [False, True],         # require_monster
    [False, True],         # skip_low_bank
))

# レースをあらかじめ計算して再利用（重い analyze_race を1回だけ走らせる）
print("🔍 全レース事前計算中...")
dates    = sorted(racecard_raw['date'].unique())
race_cache = {}  # race_id -> (bets, bet_ev_list, meta, venue)

for current_date in dates:
    past_db  = db_all[db_all['開催日'] < current_date]
    daily_rc = racecard_raw[racecard_raw['date'] == current_date]
    for rid in daily_rc['race_id'].unique():
        race_info = daily_rc[daily_rc['race_id'] == rid].copy()
        if race_info.empty: continue
        venue     = race_info['venue'].iloc[0]
        race_odds = odds_raw[odds_raw['race_id'] == rid]
        bets, bet_ev_list, meta = analyze_race_fast(rid, venue, race_info, race_odds, past_db)
        if bets:
            race_cache[rid] = (bets, bet_ev_list, meta, venue)

print(f"✅ 事前計算完了: {len(race_cache)} レース\n")

# payouts辞書
pay_dict = {}
for _, row in payouts_raw.iterrows():
    pay_dict[str(row['race_id'])] = (row['result_trifecta'], row['payout_trifecta'])

results = []
total_combos = len(param_grid)
for idx, (skip_chaos, min_top_ev, require_monster, skip_low_bank) in enumerate(param_grid):
    cfg = {
        'skip_chaos': skip_chaos, 'min_top_ev': min_top_ev,
        'require_monster': require_monster, 'skip_low_bank': skip_low_bank,
    }
    total_i = 0; total_r = 0; hits = 0; n_bets = 0

    for rid, (bets, bet_ev_list, meta, venue) in race_cache.items():
        if not should_bet(meta, venue, cfg): continue
        alloc = ev_alloc_units(bets, bet_ev_list, len(bets))
        cost  = sum(alloc)
        total_i += cost
        n_bets  += 1

        if rid in pay_dict:
            result_tri, payout_raw = pay_dict[rid]
            result_tri = str(result_tri).strip()
            if pd.isna(payout_raw): continue
            if result_tri in bets:
                hit_idx = bets.index(result_tri)
                payout_val = int(payout_raw * alloc[hit_idx] / 100)
                total_r += payout_val
                hits += 1

    roi      = total_r / total_i * 100 if total_i > 0 else 0
    hit_rate = hits / n_bets * 100      if n_bets  > 0 else 0
    results.append({
        'skip_chaos': skip_chaos,
        'min_top_ev': min_top_ev,
        'req_monster': require_monster,
        'skip_low_bank': skip_low_bank,
        'races': n_bets,
        'hits': hits,
        'hit_rate': round(hit_rate, 1),
        'invest': total_i,
        'return': total_r,
        'roi': round(roi, 2),
        'profit': total_r - total_i,
    })
    print(f"  [{idx+1:02d}/{total_combos}] chaos={skip_chaos} ev>={min_top_ev} "
          f"monster={require_monster} lowbank={skip_low_bank} "
          f"→ ROI={roi:.1f}% / {n_bets}R / ¥{total_r-total_i:+,}")

# ──────────────────────────────────────────────────────────────────
# 結果表示（ROI降順）
# ──────────────────────────────────────────────────────────────────
df = pd.DataFrame(results).sort_values('roi', ascending=False)
print("\n\n" + "="*80)
print("🏆 グリッドサーチ結果 TOP20（ROI降順）")
print("="*80)
print(df.head(20).to_string(index=False))

# CSVに保存
df.to_csv("grid_search_results.csv", index=False, encoding="utf-8-sig")
print(f"\n✅ 全結果保存: grid_search_results.csv")

# ベスト1を表示
best = df.iloc[0]
print(f"\n🥇 最適フィルター:")
print(f"   skip_chaos={best['skip_chaos']}  min_top_ev={best['min_top_ev']}")
print(f"   require_monster={best['req_monster']}  skip_low_bank={best['skip_low_bank']}")
print(f"   → ROI={best['roi']}%  的中率={best['hit_rate']}%  "
      f"対象:{best['races']}R  損益:¥{int(best['profit']):+,}")
