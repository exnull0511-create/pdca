"""
_list_hits_a.py
===============
現行ロジック (LOOSE-B / ENGINE A) の的中レース一覧を出力。
各レースの買い目・資金配分・決着オッズを表示する。
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# ==================利用する設定（compare_engines.py と同一）====================
SKIP_CHAOS    = True
MIN_TOP_EV_A  = 70
SKIP_LOW_BANK = True
TOP_N_PROB    = 14
BET_BASE      = 100
EV_ALLOC      = True

# ==================データロード================================================
def normalize_name(s):
    return str(s).replace(" ", "").replace("\u3000", "").strip()

racecard_raw = pd.read_excel("data/racecard.xlsx", dtype={'race_id': str})
odds_raw     = pd.read_excel("data/odds.xlsx",     dtype={'race_id': str})
payouts_raw  = pd.read_excel("data/payouts.xlsx",  dtype={'race_id': str})

xl     = pd.ExcelFile("data/S級選手究極DB(1).xlsx")
db_all = pd.concat([xl.parse('F1'), xl.parse('G3~1')], ignore_index=True)
db_all['開催日']      = pd.to_datetime(db_all['開催日'], errors='coerce')
db_all['IP']          = pd.to_numeric(db_all['IP'], errors='coerce')
db_all['EP']          = pd.to_numeric(db_all['EP'], errors='coerce')
db_all['DP']          = pd.to_numeric(db_all['DP'], errors='coerce')
db_all['BP']          = pd.to_numeric(db_all['BP'], errors='coerce')
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
            try: lines[lno] = [int(x) for x in bibs.split('-') if x.isdigit()]
            except: lines[lno] = []
    return lines

def build_player_base(race_info, past_db):
    result = {}
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
            avg_nobi = wmean(hist[nobi_col].apply(nobi_score))
            avg_senpo = wmean(hist['戦法'].apply(senpo_lead))
            comments = " ".join(hist['解析コメント'].astype(str).tolist())
        else:
            ip_avg = ep_avg = 4.0; dp_avg = bp_avg = 3.0
            avg_nobi = avg_senpo = 2.0; comments = ""
        ip_avg    = ip_avg    if (ip_avg    is not None and not np.isnan(ip_avg))    else 4.0
        ep_avg    = ep_avg    if (ep_avg    is not None and not np.isnan(ep_avg))    else 4.0
        dp_avg    = dp_avg    if (dp_avg    is not None and not np.isnan(dp_avg))    else 3.0
        bp_avg    = bp_avg    if (bp_avg    is not None and not np.isnan(bp_avg))    else 3.0
        avg_nobi  = avg_nobi  if (avg_nobi  is not None and not np.isnan(avg_nobi))  else 2.0
        avg_senpo = avg_senpo if (avg_senpo is not None and not np.isnan(avg_senpo)) else 2.0
        is_monster    = any(kw in comments for kw in ["脚余し", "鬼脚", "別次元", "圧倒", "豪快"])
        is_unreliable = any(kw in comments for kw in ["共倒れ", "位置取り失敗", "不発", "失速"])
        result[num] = {
            'name': str(row['選手名']), 'base_score': float(row['競走得点']),
            'ip': ip_avg, 'ep': ep_avg, 'dp': dp_avg, 'bp': bp_avg,
            'nobi': avg_nobi, 'senpo': avg_senpo,
            'is_monster': is_monster, 'is_unreliable': is_unreliable,
        }
    return result

def score_engine_a(player_base, line_map, num_to_line, bank_prof):
    scores = {}
    s = bank_prof.get('sashi', 1.0); m = bank_prof.get('makuri', 1.0)
    for num, d in player_base.items():
        lno = num_to_line.get(num, 0)
        bibs = line_map.get(lno, [])
        pos = bibs.index(num) + 1 if num in bibs else 1
        bonus = 0.5 if pos == 1 else (-0.3 * (pos - 1))
        scores[num] = (
            d['base_score'] * 0.4 + d['ip'] * 1.5 + d['ep'] * 1.2
            + d['dp'] * m + d['bp'] * s + d['nobi'] * 2.0 + d['senpo'] * 0.5
            + bonus + (3.0 if d['is_monster'] else 0) - (2.0 if d['is_unreliable'] else 0)
        )
    return scores

def select_bets(scores, odds_dict, all_nums, player_base):
    """
    軸固定モード（実際の LOOSE-B と同一ロジック）
    axis = 鬼脚選手の中でEVスコア最高 or （鬼脚なしなら）EVスコア1位
    買い目 = {axis}-{2着}-{3着} の全組み合わせ → PL確率上位14点
    """
    # EVスコアでランク付け
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    # 鬼脚選手（hidden_monsters）を特定
    hidden_monsters = [(n, scores[n]) for n, d in player_base.items()
                       if d['is_monster']]
    hidden_monsters.sort(key=lambda x: x[1], reverse=True)

    # 軸決定: 鬼脚がいればEVスコア最高の鬼脚、なければEVスコア1位
    axis_num   = hidden_monsters[0][0] if hidden_monsters else ranked[0][0]
    others_all = [num for num, _ in ranked if num != axis_num]

    # PL計算用
    max_ev = max(scores[n] for n in all_nums)
    raw_s  = {n: np.exp(scores[n] - max_ev) for n in all_nums}

    all_prob_bets = []
    for second in others_all:
        for third in others_all:
            if second == third: continue
            combo = f"{axis_num}-{second}-{third}"
            d1 = sum(raw_s[n] for n in all_nums)
            d2 = sum(raw_s[n] for n in all_nums if n != axis_num)
            d3 = sum(raw_s[n] for n in all_nums if n not in (axis_num, second))
            if d1 == 0 or d2 == 0 or d3 == 0: continue
            p = (raw_s[axis_num]/d1) * (raw_s[second]/d2) * (raw_s[third]/d3)
            if combo in odds_dict:
                ev = p * odds_dict[combo]
                all_prob_bets.append((p, ev, combo))

    if not all_prob_bets:
        return [], []

    # PL確率降順でTop-14点
    all_prob_bets.sort(key=lambda x: x[0], reverse=True)
    selected   = all_prob_bets[:TOP_N_PROB]
    bet_combos = [c for _, _, c in selected]
    ev_list    = [(c, ev) for _, ev, c in selected]

    # EV傾斜配分
    n_bets     = len(bet_combos)
    total_pool = BET_BASE * n_bets
    ev_vals    = np.array([max(ev, 0.0) for _, ev in ev_list])
    if ev_vals.sum() == 0:
        alloc = [BET_BASE] * n_bets
    else:
        raw_alloc = (ev_vals / ev_vals.sum()) * total_pool
        alloc_100 = (raw_alloc // 100).astype(int) * 100
        remainder = int(total_pool - alloc_100.sum()); remainder = (remainder // 100) * 100
        alloc_100[int(np.argmax(ev_vals))] += remainder
        alloc = [max(int(a), 100) for a in alloc_100]

    return list(zip(bet_combos, ev_list, alloc)), alloc


# ==================メイン処理================================================
dates    = sorted(racecard_raw['date'].unique())
hit_rows = []   # CSV出力用
hit_no   = 0

print("="*80)
print("🎉 ENGINE A（現行ロジック LOOSE-B）的中レース一覧")
print("="*80)

for current_date in dates:
    past_db  = db_all[db_all['開催日'] < current_date]
    daily_rc = racecard_raw[racecard_raw['date'] == current_date]
    race_ids = daily_rc['race_id'].unique()

    for rid in race_ids:
        race_info = daily_rc[daily_rc['race_id'] == rid].copy()
        if race_info.empty: continue
        venue     = race_info['venue'].iloc[0]
        race_odds = odds_raw[odds_raw['race_id'] == rid]

        odds_dict = {}
        if not race_odds.empty:
            for _, orow in race_odds.iterrows():
                odds_dict[str(orow['組み合わせ']).strip()] = float(orow['オッズ'])
        if not odds_dict: continue

        player_base = build_player_base(race_info, past_db)
        if not player_base: continue

        line_map    = parse_lines(race_info)
        num_to_line = {}
        for lno, bibs in line_map.items():
            for b in bibs: num_to_line[b] = lno

        bank_prof = bank_dict.get(venue, {'sashi': 1.0, 'makuri': 1.0, 'roi_tier': 'mid'})

        # カオス判定
        strong_leaders = [
            d['name'] for n, d in player_base.items()
            if d['ip'] >= 5.5 and line_map.get(num_to_line.get(n, 0), [None])[0] == n
        ]
        is_chaos = len(strong_leaders) >= 2

        scores_a = score_engine_a(player_base, line_map, num_to_line, bank_prof)
        top_ev_a = max(scores_a.values()) if scores_a else 0

        # フィルタ
        if SKIP_CHAOS and is_chaos: continue
        if top_ev_a < MIN_TOP_EV_A: continue
        if SKIP_LOW_BANK and bank_dict.get(venue, {}).get('roi_tier') == 'low': continue

        bets_detail, alloc_units = select_bets(scores_a, odds_dict, list(player_base.keys()), player_base)
        if not bets_detail: continue

        bet_combos = [c for c, _, _ in bets_detail]

        race_payout = payouts_raw[payouts_raw['race_id'] == rid]
        if race_payout.empty: continue
        raw_pay = race_payout['payout_trifecta'].values[0]
        if pd.isna(raw_pay): continue
        actual_result = str(race_payout['result_trifecta'].values[0]).strip()
        payout_odds   = float(raw_pay)

        if actual_result not in bet_combos:
            continue  # 外れは表示しない

        hit_no += 1
        hit_idx   = bet_combos.index(actual_result)
        hit_unit  = alloc_units[hit_idx]
        payout_val = int(payout_odds * hit_unit / 100)
        total_invest = sum(alloc_units)

        print(f"\n{'─'*80}")
        print(f"  #{hit_no:02d}  {str(current_date.date())}  {venue}バンク  Race: {rid}")
        print(f"  決着: {actual_result}  配当: {payout_odds:.1f}倍  的中買い目配分: ¥{hit_unit:,}  回収: ¥{payout_val:,}")
        print(f"  総投資: ¥{total_invest:,}  純益: ¥{payout_val - total_invest:,}")
        print(f"  {'組み合わせ':<12}  {'EV':>7}  {'配分':>8}")
        print(f"  {'─'*44}")
        for (combo, (_, ev), unit) in bets_detail:
            mark = "★" if combo == actual_result else "  "
            print(f"  {mark}{combo:<12}  EV={ev:>6.3f}  ¥{unit:>7,}")

        # CSV用に1行分記録
        # 「=\"...\" 」形式でラップ → Excel自動日付変換を防止
        for rank_i, (combo, (_, ev), unit) in enumerate(bets_detail, 1):
            hit_rows.append({
                '的中No':      hit_no,
                'race_id':     f'="{rid}"',
                '日付':        f'="{str(current_date.date())}"',
                'venue':       venue,
                '決着':        f'="{actual_result}"',
                '決着オッズ':  payout_odds,
                '買い目順位':  rank_i,
                '組み合わせ':  f'="{combo}"',
                'EV':          round(ev, 4),
                '配分(円)':    unit,
                '的中フラグ':  1 if combo == actual_result else 0,
                '回収(円)':    int(payout_odds * unit / 100) if combo == actual_result else 0,
                '総投資(円)':  total_invest,
            })

print(f"\n{'='*80}")
print(f"  合計的中: {hit_no} R")
print(f"{'='*80}")

if hit_rows:
    df_hits = pd.DataFrame(hit_rows)
    df_hits.to_csv("data/hits_engine_a.csv", index=False, encoding='utf-8-sig')
    print(f"\n💾 CSVファイル: 'data/hits_engine_a.csv' に保存しました。")
