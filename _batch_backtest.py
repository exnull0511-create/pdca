"""
_batch_backtest.py
==================
全戦略 × 2モード（軸固定 / 全順列）でバックテストを一括実行。
各組み合わせについて：
  - コンソールにサマリー出力
  - 的中レース一覧を hits_{strategy}_{mode}.csv に保存
    （hits_engine_a.csv と同一フォーマット）

EV傾斜配分は常時適用。
"""
import pandas as pd
import numpy as np
import warnings
import os
warnings.filterwarnings('ignore')

# =========================================================
# 全戦略定義（hardcore_ev.py から転記）
# =========================================================
ALL_STRATEGIES = {
    "S1": {
        "name":                "ベースライン（フィルタなし・全レース）",
        "skip_chaos":          False, "min_top_ev": 0,
        "require_monster":     False, "s3_chaos_filter": False,
        "use_full_permutation": True,
        "bet_base": 100, "skip_low_bank": False,
    },
    "S2": {
        "name":                "改善版（カオス除外 / EV<70除外 / 鬼脚必須）",
        "skip_chaos":          True,  "min_top_ev": 70,
        "require_monster":     True,  "s3_chaos_filter": False,
        "use_full_permutation": True,
        "bet_base": 100, "skip_low_bank": False,
    },
    "S3": {
        "name":                "カオス細分判定版（読めるカオスは買う）",
        "skip_chaos":          False, "min_top_ev": 70,
        "require_monster":     True,  "s3_chaos_filter": True,
        "chaos_buy_leaders_ge": 5, "chaos_buy_ev_ge": 91, "chaos_buy_ev_gap_le": 3,
        "use_full_permutation": False, "top_n_bets": 1,
        "bet_base": 100, "bet_high": 200, "bet_high_ev_th": 90, "skip_low_bank": False,
    },
    "S4": {
        "name":                "ROI最大化版（EV80 / カオスEV91 / 鬼脚必須）",
        "skip_chaos":          False, "min_top_ev": 80,
        "require_monster":     True,  "s3_chaos_filter": True,
        "chaos_buy_leaders_ge": 5, "chaos_buy_ev_ge": 91, "chaos_buy_ev_gap_le": 0,
        "use_full_permutation": False, "top_n_bets": 1,
        "bet_base": 100, "bet_high": 200, "bet_high_ev_th": 90, "skip_low_bank": True,
    },
    "S_MAXHIT_14_EV_FINAL": {
        "name":                "EV傾斜【MAX-ROI: 鬼脚必須+EV75+カオス除外+低bank除外】",
        "skip_chaos":          True,  "min_top_ev": 75,
        "require_monster":     True,  "s3_chaos_filter": False,
        "use_full_permutation": False, "top_n_prob_bets": 14,
        "ev_alloc": True, "bet_base": 100, "skip_low_bank": True,
    },
    "S_MAXHIT_14_EV_BAL": {
        "name":                "EV傾斜【BALANCE: 鬼脚必須+EV70+カオス除外+低bank除外】",
        "skip_chaos":          True,  "min_top_ev": 70,
        "require_monster":     True,  "s3_chaos_filter": False,
        "use_full_permutation": False, "top_n_prob_bets": 14,
        "ev_alloc": True, "bet_base": 100, "skip_low_bank": True,
    },
    "S_MAXHIT_14_EV_LOOSE_A": {
        "name":                "EV傾斜【LOOSE-A: 鬼脚なし+EV75+カオス除外+低bank除外】",
        "skip_chaos":          True,  "min_top_ev": 75,
        "require_monster":     False, "s3_chaos_filter": False,
        "use_full_permutation": False, "top_n_prob_bets": 14,
        "ev_alloc": True, "bet_base": 100, "skip_low_bank": True,
    },
    "S_MAXHIT_14_EV_LOOSE_B": {
        "name":                "EV傾斜【LOOSE-B: 鬼脚なし+EV70+カオス除外+低bank除外】",
        "skip_chaos":          True,  "min_top_ev": 70,
        "require_monster":     False, "s3_chaos_filter": False,
        "use_full_permutation": False, "top_n_prob_bets": 14,
        "ev_alloc": True, "bet_base": 100, "skip_low_bank": True,
    },
    "S_MAXHIT_14_EV_LOOSE_C": {
        "name":                "EV傾斜【LOOSE-C: 鬼脚なし+EV65+カオス除外+低bank除外】",
        "skip_chaos":          True,  "min_top_ev": 65,
        "require_monster":     False, "s3_chaos_filter": False,
        "use_full_permutation": False, "top_n_prob_bets": 14,
        "ev_alloc": True, "bet_base": 100, "skip_low_bank": True,
    },
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
            try: lines[lno] = [int(x) for x in bibs.split('-') if x.isdigit()]
            except: lines[lno] = []
    return lines

# =========================================================
# 選手スコアと共通メタ情報を構築
# =========================================================
def build_race_data(race_info, race_odds, past_db, venue):
    bank_prof = bank_dict.get(venue, {'sashi': 1.0, 'makuri': 1.0, 'roi_tier': 'mid'})
    if race_info.empty:
        return None

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
            RECENT_W     = 3.0
            sorted_dates = sorted(hist['開催日'].dropna().unique(), reverse=True)
            recent_dates = set(sorted_dates[:2])
            def wmean(series):
                vals    = pd.to_numeric(series, errors='coerce')
                is_rec  = hist['開催日'].isin(recent_dates)
                weights = np.where(is_rec, RECENT_W, 1.0)
                mask    = vals.notna()
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

        for val, default in [(ip_avg,4.0),(ep_avg,4.0),(dp_avg,3.0),(bp_avg,3.0),(avg_nobi,2.0),(avg_senpo,2.0)]:
            pass  # 下でまとめてフォールバック
        ip_avg    = ip_avg    if ip_avg    is not None and not np.isnan(ip_avg)    else 4.0
        ep_avg    = ep_avg    if ep_avg    is not None and not np.isnan(ep_avg)    else 4.0
        dp_avg    = dp_avg    if dp_avg    is not None and not np.isnan(dp_avg)    else 3.0
        bp_avg    = bp_avg    if bp_avg    is not None and not np.isnan(bp_avg)    else 3.0
        avg_nobi  = avg_nobi  if avg_nobi  is not None and not np.isnan(avg_nobi)  else 2.0
        avg_senpo = avg_senpo if avg_senpo is not None and not np.isnan(avg_senpo) else 2.0

        is_monster    = any(kw in comments for kw in ["脚余し", "鬼脚", "別次元", "圧倒", "豪快"])
        is_unreliable = any(kw in comments for kw in ["共倒れ", "位置取り失敗", "不発", "失速"])

        lno         = num_to_line.get(num, 0)
        line_bibs   = line_map.get(lno, [])
        pos_in_line = line_bibs.index(num) + 1 if num in line_bibs else 1
        bonus       = 0.5 if pos_in_line == 1 else (-0.3 * (pos_in_line - 1))

        ev_score = (
            float(row['競走得点']) * 0.4
            + ip_avg   * 1.5 + ep_avg * 1.2
            + dp_avg   * bank_prof['makuri']
            + bp_avg   * bank_prof['sashi']
            + avg_nobi * 2.0 + avg_senpo * 0.5
            + bonus
            + (3.0 if is_monster    else 0)
            - (2.0 if is_unreliable else 0)
        )
        player_scores[num] = {
            'name': str(row['選手名']), 'ev_score': ev_score,
            'is_monster': is_monster, 'is_unreliable': is_unreliable,
            'ip': ip_avg, 'pos_in_line': pos_in_line,
        }

    ranked = sorted(player_scores.items(), key=lambda x: x[1]['ev_score'], reverse=True)
    all_nums = [n for n, _ in ranked]
    if not all_nums: return None

    # カオス・鬼脚
    strong_leaders  = [d['name'] for _, d in player_scores.items()
                       if d['ip'] >= 5.5 and d['pos_in_line'] == 1]
    hidden_monsters = [(n, d) for n, d in ranked if d['is_monster']]
    is_chaos        = len(strong_leaders) >= 2

    # オッズ辞書
    odds_dict = {}
    if not race_odds.empty:
        for _, orow in race_odds.iterrows():
            odds_dict[str(orow['組み合わせ']).strip()] = float(orow['オッズ'])

    return {
        'ranked': ranked, 'all_nums': all_nums,
        'hidden_monsters': hidden_monsters, 'is_chaos': is_chaos,
        'strong_leaders': strong_leaders, 'odds_dict': odds_dict,
        'player_scores': player_scores,
        'top_ev': ranked[0][1]['ev_score'],
        'ev_gap': ranked[0][1]['ev_score'] - ranked[1][1]['ev_score'] if len(ranked) >= 2 else 0,
    }

# =========================================================
# 買い目生成
# =========================================================
def generate_bets(rd, cfg, force_fullperm=False):
    """
    rd         : build_race_data の戻り値
    cfg        : ストラテジー設定辞書
    force_fullperm : True=全順列強制, False=cfg['use_full_permutation']に従う
    """
    ranked          = rd['ranked']
    all_nums        = rd['all_nums']
    hidden_monsters = rd['hidden_monsters']
    odds_dict       = rd['odds_dict']

    max_ev = max(rd['player_scores'][n]['ev_score'] for n in all_nums)
    raw_s  = {n: np.exp(rd['player_scores'][n]['ev_score'] - max_ev) for n in all_nums}

    def pl(first, second, third):
        d1 = sum(raw_s[n] for n in all_nums)
        if d1 == 0: return 0.0
        d2 = sum(raw_s[n] for n in all_nums if n != first)
        if d2 == 0: return 0.0
        d3 = sum(raw_s[n] for n in all_nums if n not in (first, second))
        if d3 == 0: return 0.0
        return (raw_s[first]/d1) * (raw_s[second]/d2) * (raw_s[third]/d3)

    use_full = force_fullperm or cfg.get('use_full_permutation', False)

    all_ev_bets   = []
    ev_pos_bets   = []

    if use_full:
        # 全順列 + 均等確率下限フィルタ
        n = len(all_nums)
        n_combos = n * (n-1) * (n-2) if n >= 3 else 1
        p_floor  = 1.0 / n_combos
        for first in all_nums:
            for second in all_nums:
                if second == first: continue
                for third in all_nums:
                    if third in (first, second): continue
                    combo  = f"{first}-{second}-{third}"
                    p_trio = pl(first, second, third)
                    if p_trio < p_floor: continue
                    if combo in odds_dict:
                        ev = p_trio * odds_dict[combo]
                        all_ev_bets.append((ev, combo, p_trio, odds_dict[combo]))
                        if ev > 1.0:
                            ev_pos_bets.append((ev, combo, p_trio, odds_dict[combo]))
    else:
        # 軸固定
        axis_num   = hidden_monsters[0][0] if hidden_monsters else ranked[0][0]
        others_all = [num for num, _ in ranked if num != axis_num]
        for second in others_all:
            for third in others_all:
                if second == third: continue
                combo  = f"{axis_num}-{second}-{third}"
                p_trio = pl(axis_num, second, third)
                if combo in odds_dict:
                    ev = p_trio * odds_dict[combo]
                    all_ev_bets.append((ev, combo, p_trio, odds_dict[combo]))
                    if ev > 1.0:
                        ev_pos_bets.append((ev, combo, p_trio, odds_dict[combo]))

    ev_pos_bets.sort(key=lambda x: x[0], reverse=True)
    all_ev_bets.sort(key=lambda x: x[0], reverse=True)
    all_prob_bets = sorted(all_ev_bets, key=lambda x: x[2], reverse=True)

    top_n_prob = cfg.get('top_n_prob_bets', None)
    top_n      = cfg.get('top_n_bets',      None)

    if top_n_prob is not None:
        selected = all_prob_bets[:top_n_prob]
        bet_combinations = [c for _, c, _, _ in selected]
        ev_lookup        = {c: ev for ev, c, p, o in all_ev_bets}
        bet_ev_list      = [(c, ev_lookup.get(c, 0.0)) for c in bet_combinations]
    elif top_n is not None:
        selected         = all_ev_bets[:top_n]
        bet_combinations = [c for _, c, _, _ in selected]
        bet_ev_list      = [(c, ev) for ev, c, p, o in selected]
    else:
        # EV>1.0 カットオフ（S1/S2）
        selected         = ev_pos_bets[:14]
        bet_combinations = [c for _, c, _, _ in selected]
        bet_ev_list      = [(c, ev) for ev, c, p, o in selected]

    return bet_combinations, bet_ev_list

# =========================================================
# EV傾斜配分
# =========================================================
def ev_alloc(bet_combinations, bet_ev_list, bet_base):
    n_bets     = len(bet_combinations)
    total_pool = bet_base * n_bets
    ev_vals    = np.array([max(ev, 0.0) for _, ev in bet_ev_list])
    if ev_vals.sum() == 0:
        return [bet_base] * n_bets
    raw_alloc = (ev_vals / ev_vals.sum()) * total_pool
    alloc_100 = (raw_alloc // 100).astype(int) * 100
    remainder = int(total_pool - alloc_100.sum()); remainder = (remainder // 100) * 100
    alloc_100[int(np.argmax(ev_vals))] += remainder
    return [max(int(a), 100) for a in alloc_100]

# =========================================================
# ストラテジーフィルタ（hardcore_ev.py と完全同一）
# =========================================================
def should_bet(rd, cfg):
    top_ev      = rd['top_ev']
    ev_gap      = rd['ev_gap']
    is_chaos    = rd['is_chaos']
    chaos_count = len(rd['strong_leaders'])
    has_monster = bool(rd['hidden_monsters'])

    if top_ev < cfg.get('min_top_ev', 0): return False
    if cfg.get('require_monster') and not has_monster: return False
    if is_chaos:
        if cfg.get('s3_chaos_filter'):
            buy_l = chaos_count >= cfg.get('chaos_buy_leaders_ge', 999)
            buy_e = top_ev      >= cfg.get('chaos_buy_ev_ge',      999)
            buy_g = ev_gap      <= cfg.get('chaos_buy_ev_gap_le',   -1) and has_monster
            if not (buy_l or buy_e or buy_g): return False
        elif cfg.get('skip_chaos'): return False
    return True

# =========================================================
# 1ストラテジー×1モードのバックテスト実行
# =========================================================
def run_one(strategy_name, cfg, force_fullperm=False):
    mode_label = "全順列" if (force_fullperm or cfg.get('use_full_permutation')) else "軸固定"
    mode_tag   = "fullperm" if (force_fullperm or cfg.get('use_full_permutation')) else "axisfixed"

    total_investment = 0; total_return = 0
    hit_count = 0; total_races_bet = 0; skipped_count = 0
    hit_rows  = []

    dates    = sorted(racecard_raw['date'].unique())
    bet_base = cfg.get('bet_base', 100)

    for current_date in dates:
        past_db  = db_all[db_all['開催日'] < current_date]
        daily_rc = racecard_raw[racecard_raw['date'] == current_date]

        for rid in daily_rc['race_id'].unique():
            race_info = daily_rc[daily_rc['race_id'] == rid].copy()
            if race_info.empty: continue
            venue     = race_info['venue'].iloc[0]
            race_odds = odds_raw[odds_raw['race_id'] == rid]

            rd = build_race_data(race_info, race_odds, past_db, venue)
            if rd is None or not rd['odds_dict']:
                skipped_count += 1; continue

            if not should_bet(rd, cfg):
                skipped_count += 1; continue

            if cfg.get('skip_low_bank') and \
               bank_dict.get(venue, {}).get('roi_tier') == 'low':
                skipped_count += 1; continue

            bets, bet_ev_list = generate_bets(rd, cfg, force_fullperm)
            if not bets:
                skipped_count += 1; continue

            alloc_units = ev_alloc(bets, bet_ev_list, bet_base)
            cost        = sum(alloc_units)
            total_investment += cost
            total_races_bet  += 1

            race_payout  = payouts_raw[payouts_raw['race_id'] == rid]
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

            # CSVに全買い目を記録（的中レースのみ）
            if is_hit:
                for rank_i, (combo, (_, ev), unit) in enumerate(
                        zip(bets, bet_ev_list, alloc_units), 1):
                    ret_val = int(payout_odds * unit / 100) if combo == actual_result else 0
                    hit_rows.append({
                        '的中No':     hit_count,
                        'race_id':    f'="{rid}"',
                        '日付':       f'="{str(current_date.date())}"',
                        'venue':      venue,
                        '決着':       f'="{actual_result}"',
                        '決着オッズ': payout_odds,
                        '買い目順位': rank_i,
                        '組み合わせ': f'="{combo}"',
                        'EV':         round(ev, 4),
                        '配分(円)':   unit,
                        '的中フラグ': 1 if combo == actual_result else 0,
                        '回収(円)':   ret_val,
                        '総投資(円)': cost,
                    })

    roi      = (total_return  / total_investment) * 100 if total_investment > 0 else 0
    hit_rate = (hit_count / total_races_bet) * 100      if total_races_bet  > 0 else 0

    # CSVに保存
    csv_path = f"data/hits_{strategy_name}_{mode_tag}.csv"
    if hit_rows:
        pd.DataFrame(hit_rows).to_csv(csv_path, index=False, encoding='utf-8-sig')

    return {
        'strategy': strategy_name, 'mode': mode_label, 'mode_tag': mode_tag,
        'bet_r': total_races_bet, 'skip_r': skipped_count,
        'hits': hit_count, 'hit_rate': hit_rate,
        'invest': total_investment, 'ret': total_return, 'roi': roi,
        'csv': csv_path if hit_rows else "(的中なし)",
    }

# =========================================================
# 全バッチ実行
# =========================================================
print("\n🚀 全戦略バッチバックテスト開始...\n")
summary_rows = []

for sname, scfg in ALL_STRATEGIES.items():
    orig_is_full = scfg.get('use_full_permutation', False)

    # ── オリジナルモード ──
    print(f"  [{sname}] {'全順列' if orig_is_full else '軸固定'} ... ", end='', flush=True)
    r = run_one(sname, scfg, force_fullperm=False)
    summary_rows.append(r)
    print(f"  買い{r['bet_r']}R / 的中{r['hits']}R / 的中率{r['hit_rate']:.1f}% / ROI {r['roi']:.1f}%")

    # ── 軸固定しないモード（既に全順列の戦略はスキップ）──
    if not orig_is_full:
        print(f"  [{sname}] 全順列（強制） ... ", end='', flush=True)
        r2 = run_one(sname, scfg, force_fullperm=True)
        summary_rows.append(r2)
        print(f"  買い{r2['bet_r']}R / 的中{r2['hits']}R / 的中率{r2['hit_rate']:.1f}% / ROI {r2['roi']:.1f}%")

# =========================================================
# サマリー表示
# =========================================================
print("\n" + "=" * 95)
print(f"{'戦略':<28} {'モード':6}  {'買いR':>5}  {'的中R':>5}  {'的中率':>7}  {'総投資':>10}  {'総回収':>10}  {'ROI':>8}  CSV")
print("-" * 95)
for r in summary_rows:
    print(f"  {r['strategy']:<26} {r['mode']:6}  {r['bet_r']:>5}  {r['hits']:>5}"
          f"  {r['hit_rate']:>6.1f}%  ¥{r['invest']:>9,}  ¥{r['ret']:>9,}"
          f"  {r['roi']:>7.1f}%  {r['csv']}")
print("=" * 95)
print("\n💾 個別CSVは data/ ディレクトリに保存済み。")
