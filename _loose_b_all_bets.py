"""
_loose_b_all_bets.py
====================
LOOSE-B 戦略（軸固定・EV傾斜）で勝負判定となった全レースを出力。
的中・外れ問わず全買い目を記録。
日付・組み合わせ・決着は =\"...\" 形式でExcelの自動日付変換を防止。
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# =========================================================
# 設定（LOOSE-B 軸固定 EV傾斜）
# =========================================================
SCFG = {
    "name":                "LOOSE-B 軸固定 EV傾斜",
    "skip_chaos":          True,
    "min_top_ev":          70,
    "require_monster":     False,
    "s3_chaos_filter":     False,
    "use_full_permutation": False,   # 軸固定
    "top_n_prob_bets":     14,
    "ev_alloc":            True,
    "bet_base":            100,
    "skip_low_bank":       True,
}

# =========================================================
# データロード
# =========================================================
def normalize_name(s):
    return str(s).replace(" ", "").replace("\u3000", "").strip()

print("🔥 Loading data...")
racecard_raw = pd.read_excel("data/racecard.xlsx", dtype={'race_id': str})
odds_raw     = pd.read_excel("data/odds.xlsx",     dtype={'race_id': str})
payouts_raw  = pd.read_excel("data/payouts.xlsx",  dtype={'race_id': str})

xl     = pd.ExcelFile("data/S級選手究極DB(1).xlsx")
db_all = pd.concat([xl.parse('F1'), xl.parse('G3~1')], ignore_index=True)
db_all['開催日']      = pd.to_datetime(db_all['開催日'], errors='coerce')
for c in ['IP', 'EP', 'DP', 'BP']:
    db_all[c] = pd.to_numeric(db_all[c], errors='coerce')
db_all['選手名_norm'] = db_all['選手名'].apply(normalize_name)
nobi_col = [c for c in db_all.columns if '直線' in c][0]

for df in [racecard_raw, odds_raw, payouts_raw]:
    df['race_id'] = df['race_id'].apply(lambda v: str(v)[2:-1] if str(v).startswith('="') else str(v))
payouts_raw['result_trifecta'] = payouts_raw['result_trifecta'].apply(
    lambda v: str(v)[2:-1] if str(v).startswith('="') else str(v))
racecard_raw['date'] = pd.to_datetime(racecard_raw['date'].astype(str), format='%Y%m%d')
for col in ['競走得点', 'S', 'B', '逃', '捲', '差', 'マ', '1着', '2着', '3着', '着外']:
    racecard_raw[col] = pd.to_numeric(racecard_raw[col], errors='coerce').fillna(0)
odds_raw['オッズ'] = pd.to_numeric(odds_raw['オッズ'], errors='coerce')

bank_dict = {
    '前橋': {'sashi': 0.8, 'makuri': 1.2, 'roi_tier': 'mid'},
    '宇都宮': {'sashi': 1.5, 'makuri': 1.1, 'roi_tier': 'high'},
    '豊橋': {'sashi': 1.3, 'makuri': 1.2, 'roi_tier': 'high'},
    '岸和田': {'sashi': 1.1, 'makuri': 1.3, 'roi_tier': 'low'},
    '熊本': {'sashi': 1.2, 'makuri': 1.1, 'roi_tier': 'high'},
    'いわき平': {'sashi': 0.9, 'makuri': 1.3, 'roi_tier': 'mid'},
    '広島': {'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'mid'},
    '別府': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '松山': {'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '小倉': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '京王閣': {'sashi': 1.0, 'makuri': 1.1, 'roi_tier': 'high'},
    '立川': {'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'high'},
    '取手': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '伊東': {'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '久留米': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '奈良': {'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'low'},
    '岐阜': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '小松島': {'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'low'},
    '防府': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '静岡': {'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'low'},
    '松阪': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '高知': {'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '松戸': {'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'mid'},
    '平塚': {'sashi': 1.2, 'makuri': 1.1, 'roi_tier': 'mid'},
    '西武園': {'sashi': 1.0, 'makuri': 1.1, 'roi_tier': 'mid'},
    '函館': {'sashi': 1.0, 'makuri': 1.0, 'roi_tier': 'mid'},
    '青森': {'sashi': 1.0, 'makuri': 1.0, 'roi_tier': 'mid'},
    '向日町': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '大垣': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '名古屋': {'sashi': 1.0, 'makuri': 1.1, 'roi_tier': 'mid'},
    '川崎': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '大宮': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
}

SENPO_LEAD = {
    '逃げ切り': 5, '逃げ粘り': 4, '突っ張り先行': 4, '抑え先行': 4,
    'カマシ先行': 5, '先行逃げ切り': 5, '先行': 4, '逃げ': 5,
    '先行争い敗北': 3, '先行争い敗': 3,
    '一発捲り': 3, 'ロング捲り': 3, '捲り': 3, '番手捲り': 3,
    'カマシ捲り': 4, '捲り差し': 3, '捲り追い込み': 2, '捲り不発': 2,
    '番手差し': 2, '差し': 2, '追い込み': 2, '流れ込み': 1, '追走': 1, 'マーク': 1,
}

def nobi_score(val):
    s = str(val).strip().upper()
    if s.startswith('S'): return 5
    elif s.startswith('A'): return 4
    elif s.startswith('B'): return 3
    elif s.startswith('C'): return 1
    return 2

def senpo_lead(val):
    return SENPO_LEAD.get(str(val).strip(), 1)

def parse_lines(race_info):
    lines = {}
    for _, row in race_info.iterrows():
        lno = int(row['line_no']) if not pd.isna(row['line_no']) else 0
        bibs = str(row['line_bibs'])
        if lno not in lines:
            try:   lines[lno] = [int(x) for x in bibs.split('-') if x.isdigit()]
            except: lines[lno] = []
    return lines

# =========================================================
# analyze_race（hardcore_ev.py と完全同一）
# =========================================================
def analyze_race(race_id, venue, current_date, race_info, race_odds, past_db):
    bank_prof = bank_dict.get(venue, {'sashi': 1.0, 'makuri': 1.0, 'roi_tier': 'mid'})
    if race_info.empty: return None

    line_map    = parse_lines(race_info)
    num_to_line = {}
    for lno, bibs in line_map.items():
        for b in bibs: num_to_line[b] = lno

    player_scores = {}
    for _, row in race_info.iterrows():
        num  = int(row['車番'])
        norm = normalize_name(str(row['選手名']))
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
                return float((vals[mask] * weights[mask]).sum() / weights[mask].sum())
            ip_avg = wmean(hist['IP']); ep_avg = wmean(hist['EP'])
            dp_avg = wmean(hist['DP']); bp_avg = wmean(hist['BP'])
            avg_nobi  = wmean(hist[nobi_col].apply(nobi_score))
            avg_senpo = wmean(hist['戦法'].apply(senpo_lead))
            comments  = " ".join(hist['解析コメント'].astype(str).tolist())
        else:
            ip_avg = ep_avg = 4.0; dp_avg = bp_avg = 3.0
            avg_nobi = avg_senpo = 2.0; comments = ""

        ip_avg    = ip_avg    if ip_avg    is not None and not np.isnan(ip_avg)    else 4.0
        ep_avg    = ep_avg    if ep_avg    is not None and not np.isnan(ep_avg)    else 4.0
        dp_avg    = dp_avg    if dp_avg    is not None and not np.isnan(dp_avg)    else 3.0
        bp_avg    = bp_avg    if bp_avg    is not None and not np.isnan(bp_avg)    else 3.0
        avg_nobi  = avg_nobi  if avg_nobi  is not None and not np.isnan(avg_nobi)  else 2.0
        avg_senpo = avg_senpo if avg_senpo is not None and not np.isnan(avg_senpo) else 2.0

        is_monster    = any(kw in comments for kw in ["脚余し","鬼脚","別次元","圧倒","豪快"])
        is_unreliable = any(kw in comments for kw in ["共倒れ","位置取り失敗","不発","失速"])

        lno         = num_to_line.get(num, 0)
        line_bibs   = line_map.get(lno, [])
        pos_in_line = line_bibs.index(num) + 1 if num in line_bibs else 1
        bonus       = 0.5 if pos_in_line == 1 else (-0.3 * (pos_in_line - 1))

        ev_score = (
            float(row['競走得点']) * 0.4
            + ip_avg * 1.5 + ep_avg * 1.2
            + dp_avg * bank_prof['makuri'] + bp_avg * bank_prof['sashi']
            + avg_nobi * 2.0 + avg_senpo * 0.5
            + bonus
            + (3.0 if is_monster else 0) - (2.0 if is_unreliable else 0)
        )
        player_scores[num] = {
            'ev_score': ev_score, 'is_monster': is_monster,
            'ip': ip_avg, 'pos_in_line': pos_in_line,
        }

    ranked = sorted(player_scores.items(), key=lambda x: x[1]['ev_score'], reverse=True)
    all_nums = [n for n, _ in ranked]
    if not all_nums: return None

    strong_leaders  = [d for _, d in player_scores.items()
                       if d['ip'] >= 5.5 and d['pos_in_line'] == 1]
    hidden_monsters = [(n, d) for n, d in ranked if d['is_monster']]
    is_chaos        = len(strong_leaders) >= 2

    max_ev = ranked[0][1]['ev_score']
    raw_s  = {n: np.exp(player_scores[n]['ev_score'] - max_ev) for n in all_nums}

    def pl_prob(first, second, third):
        d1 = sum(raw_s[n] for n in all_nums)
        if d1 == 0: return 0.0
        d2 = sum(raw_s[n] for n in all_nums if n != first)
        if d2 == 0: return 0.0
        d3 = sum(raw_s[n] for n in all_nums if n not in (first, second))
        if d3 == 0: return 0.0
        return (raw_s[first]/d1) * (raw_s[second]/d2) * (raw_s[third]/d3)

    odds_dict = {}
    if not race_odds.empty:
        for _, orow in race_odds.iterrows():
            odds_dict[str(orow['組み合わせ']).strip()] = float(orow['オッズ'])

    # 軸固定
    axis_num   = hidden_monsters[0][0] if hidden_monsters else ranked[0][0]
    others_all = [num for num, _ in ranked if num != axis_num]

    all_ev_bets = []
    for second in others_all:
        for third in others_all:
            if second == third: continue
            combo  = f"{axis_num}-{second}-{third}"
            p_trio = pl_prob(axis_num, second, third)
            if combo in odds_dict:
                ev = p_trio * odds_dict[combo]
                all_ev_bets.append((ev, combo, p_trio, odds_dict[combo]))

    all_ev_bets.sort(key=lambda x: x[0], reverse=True)
    all_prob_bets = sorted(all_ev_bets, key=lambda x: x[2], reverse=True)

    selected         = all_prob_bets[:14]
    bet_combinations = [c for _, c, _, _ in selected]
    ev_lookup        = {c: ev for ev, c, p, o in all_ev_bets}
    bet_ev_list      = [(c, ev_lookup.get(c, 0.0)) for c in bet_combinations]

    top_ev = ranked[0][1]['ev_score']
    ev_gap = top_ev - ranked[1][1]['ev_score'] if len(ranked) >= 2 else 0

    return {
        'bets': bet_combinations, 'bet_ev_list': bet_ev_list,
        'is_chaos': is_chaos, 'has_monster': bool(hidden_monsters),
        'top_ev': top_ev, 'ev_gap': ev_gap,
        'chaos_count': len(strong_leaders), 'axis': axis_num,
    }

# =========================================================
# メイン
# =========================================================
dates    = sorted(racecard_raw['date'].unique())
all_rows = []    # 全勝負レース × 全買い目
race_no  = 0
hit_count = 0; total_invest = 0; total_return = 0

print("\n🚀 LOOSE-B バックテスト（全勝負レース出力）開始...")

for current_date in dates:
    past_db  = db_all[db_all['開催日'] < current_date]
    daily_rc = racecard_raw[racecard_raw['date'] == current_date]

    for rid in daily_rc['race_id'].unique():
        race_info = daily_rc[daily_rc['race_id'] == rid].copy()
        if race_info.empty: continue
        venue     = race_info['venue'].iloc[0]
        race_odds = odds_raw[odds_raw['race_id'] == rid]

        result = analyze_race(rid, venue, current_date, race_info, race_odds, past_db)
        if result is None: continue

        # フィルタ
        if SCFG['skip_chaos'] and result['is_chaos']: continue
        if result['top_ev'] < SCFG['min_top_ev']:     continue
        if SCFG['require_monster'] and not result['has_monster']: continue
        if SCFG['skip_low_bank'] and \
           bank_dict.get(venue, {}).get('roi_tier') == 'low': continue
        if not result['bets']: continue

        race_no += 1
        bets        = result['bets']
        bet_ev_list = result['bet_ev_list']
        bet_base    = SCFG['bet_base']

        # EV傾斜配分
        n_bets     = len(bets)
        total_pool = bet_base * n_bets
        ev_vals    = np.array([max(ev, 0.0) for _, ev in bet_ev_list])
        if ev_vals.sum() == 0:
            alloc_units = [bet_base] * n_bets
        else:
            raw_alloc = (ev_vals / ev_vals.sum()) * total_pool
            alloc_100 = (raw_alloc // 100).astype(int) * 100
            remainder = int(total_pool - alloc_100.sum())
            remainder = (remainder // 100) * 100
            alloc_100[int(np.argmax(ev_vals))] += remainder
            alloc_units = [max(int(a), 100) for a in alloc_100]

        cost = sum(alloc_units)
        total_invest += cost

        # 実際の決着
        race_payout   = payouts_raw[payouts_raw['race_id'] == rid]
        actual_result = None; payout_odds = None
        if not race_payout.empty:
            raw_pay = race_payout['payout_trifecta'].values[0]
            if not pd.isna(raw_pay):
                actual_result = str(race_payout['result_trifecta'].values[0]).strip()
                payout_odds   = float(raw_pay)

        is_hit = (actual_result is not None) and (actual_result in bets)
        if is_hit:
            hit_idx    = bets.index(actual_result)
            payout_val = int(payout_odds * alloc_units[hit_idx] / 100)
            total_return += payout_val
            hit_count    += 1
            race_result_tag = "的中"
        else:
            payout_val      = 0
            race_result_tag = "外れ"

        # 全買い目を記録
        for rank_i, (combo, (_, ev), unit) in enumerate(
                zip(bets, bet_ev_list, alloc_units), 1):
            is_hit_combo = (combo == actual_result)
            all_rows.append({
                # ── レース識別 ──
                'レースNo':    race_no,
                '結果':        race_result_tag,
                'race_id':     f'="{rid}"',
                '日付':        f'="{str(current_date.date())}"',
                'venue':       venue,
                '軸':          f'="{result["axis"]}"',
                # ── 決着情報 ──
                '決着':        f'="{actual_result}"' if actual_result else '="未集計"',
                '決着オッズ':  payout_odds if payout_odds else '',
                # ── 買い目詳細 ──
                '買い目順位':  rank_i,
                '組み合わせ':  f'="{combo}"',
                'EV':          round(ev, 4),
                '配分(円)':    unit,
                '的中フラグ':  1 if is_hit_combo else 0,
                '回収(円)':    int(payout_odds * unit / 100) if is_hit_combo else 0,
                # ── 勝負レース集計 ──
                '総投資(円)':  cost,
                '純益(円)':    payout_val - cost if rank_i == 1 else '',
                # ── カオス/鬼脚 状況 ──
                'カオス':      result['is_chaos'],
                '鬼脚':        result['has_monster'],
                'top_ev':      round(result['top_ev'], 1),
            })

# =========================================================
# 集計・保存
# =========================================================
roi      = (total_return  / total_invest * 100) if total_invest > 0 else 0
hit_rate = (hit_count / race_no * 100)           if race_no > 0      else 0

print(f"\n{'='*55}")
print(f"🏁 LOOSE-B 【全勝負レース】集計")
print(f"{'='*55}")
print(f"  勝負判定レース数 : {race_no:>5} R")
print(f"  的中             : {hit_count:>5} R")
print(f"  的中率           : {hit_rate:>7.1f}%")
print(f"  総投資額         : ¥{total_invest:>10,}")
print(f"  総回収額         : ¥{total_return:>10,}")
print(f"  ROI              : {roi:>7.2f}%")
print(f"{'='*55}")

csv_path = "data/loose_b_all_bets.csv"
pd.DataFrame(all_rows).to_csv(csv_path, index=False, encoding='utf-8-sig')
print(f"\n💾 保存完了: '{csv_path}'")
print(f"   行数: {len(all_rows)} 行（{race_no}レース × 最大14買い目）")
