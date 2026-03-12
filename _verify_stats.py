"""
_verify_stats.py
================
hardcore_ev.py の analyze_race / should_bet_race と
完全に同一のロジック・関数を使い、
  - 買い判定レース数
  - 的中レース数
  - 的中率
  - 総投資額 / 総回収額 / ROI
を算出する。

ログファイルは一切書かず、サマリーのみ出力。
"""

import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# =========================================================
# ★ STRATEGY 設定
#    ここを変えるだけで別戦略の数字もすぐ出せる
# =========================================================
STRATEGY = "CURRENT"  # 本番採用: skip_chaos=True / min_top_ev=60

STRATEGY_CONFIGS = {
    # 現在のcheck_and_notify.py設定と完全一致
    "CURRENT": {
        "name":               "[check_and_notify現在設定] skip_chaos=True / min_top_ev=60",
        "skip_chaos":         True,
        "min_top_ev":         60,
        "require_monster":    False,
        "s3_chaos_filter":    False,
        "use_full_permutation": False,
        "top_n_prob_bets":    14,
        "ev_alloc":           True,
        "bet_base":           100,
        "skip_low_bank":      True,
    },
    "S_MAXHIT_14_EV_LOOSE_B": {
        "name":               "EV傾斜【LOOSE-B: 鬼脚なし+EV70+カオス除外+低bank除外】",
        "skip_chaos":         True,
        "min_top_ev":         70,
        "require_monster":    False,
        "s3_chaos_filter":    False,
        "use_full_permutation": False,   # 軸固定モード
        "top_n_prob_bets":    14,
        "ev_alloc":           True,
        "bet_base":           100,
        "skip_low_bank":      True,
    },
    "S_MAXHIT_14_EV_LOOSE_A": {
        "name":               "EV傾斜【LOOSE-A: 鬼脚なし+EV75+カオス除外+低bank除外】",
        "skip_chaos":         True,
        "min_top_ev":         75,
        "require_monster":    False,
        "s3_chaos_filter":    False,
        "use_full_permutation": False,
        "top_n_prob_bets":    14,
        "ev_alloc":           True,
        "bet_base":           100,
        "skip_low_bank":      True,
    },
    "S_MAXHIT_14_EV_FINAL": {
        "name":               "EV傾斜配分【最適フィルター MAX-ROI】鬼脚必須+EV75",
        "skip_chaos":         True,
        "min_top_ev":         75,
        "require_monster":    True,
        "s3_chaos_filter":    False,
        "use_full_permutation": False,
        "top_n_prob_bets":    14,
        "ev_alloc":           True,
        "bet_base":           100,
        "skip_low_bank":      True,
    },
}

SCFG = STRATEGY_CONFIGS[STRATEGY]
print(f"🎮 Strategy: {STRATEGY} — {SCFG['name']}")
print("🔥 Loading data...")

# =========================================================
# データロード（hardcore_ev.py と完全同一）
# =========================================================
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
    '前橋':     {'type': '超高速', 'length': 335, 'sashi': 0.8, 'makuri': 1.2, 'roi_tier': 'mid'},
    '宇都宮':   {'type': '重い',   'length': 500, 'sashi': 1.5, 'makuri': 1.1, 'roi_tier': 'high'},
    '豊橋':     {'type': '風強',   'length': 400, 'sashi': 1.3, 'makuri': 1.2, 'roi_tier': 'high'},
    '岸和田':   {'type': '波状',   'length': 400, 'sashi': 1.1, 'makuri': 1.3, 'roi_tier': 'low'},
    '熊本':     {'type': '標準',   'length': 400, 'sashi': 1.2, 'makuri': 1.1, 'roi_tier': 'high'},
    'いわき平': {'type': '短走路', 'length': 335, 'sashi': 0.9, 'makuri': 1.3, 'roi_tier': 'mid'},
    '広島':     {'type': '重い',   'length': 400, 'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'mid'},
    '別府':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '松山':     {'type': '標準',   'length': 333, 'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '小倉':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '京王閣':   {'type': '標準',   'length': 400, 'sashi': 1.0, 'makuri': 1.1, 'roi_tier': 'high'},
    '立川':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'high'},
    '取手':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '伊東':     {'type': '標準',   'length': 333, 'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '久留米':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '奈良':     {'type': '標準',   'length': 400, 'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'low'},
    '岐阜':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '小松島':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'low'},
    '防府':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '静岡':     {'type': '標準',   'length': 400, 'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'low'},
    '松阪':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '高知':     {'type': '標準',   'length': 400, 'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '松戸':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'mid'},
    '平塚':     {'type': '標準',   'length': 400, 'sashi': 1.2, 'makuri': 1.1, 'roi_tier': 'mid'},
    '西武園':   {'type': '標準',   'length': 335, 'sashi': 1.0, 'makuri': 1.1, 'roi_tier': 'mid'},
    '函館':     {'type': '標準',   'length': 400, 'sashi': 1.0, 'makuri': 1.0, 'roi_tier': 'mid'},
    '青森':     {'type': '標準',   'length': 400, 'sashi': 1.0, 'makuri': 1.0, 'roi_tier': 'mid'},
    '向日町':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '大垣':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '名古屋':   {'type': '標準',   'length': 400, 'sashi': 1.0, 'makuri': 1.1, 'roi_tier': 'mid'},
    '川崎':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '大宮':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
}

SENPO_LEAD = {
    '逃げ切り': 5, '逃げ粘り': 4, '突っ張り先行': 4, '抑え先行': 4,
    'カマシ先行': 5, '先行逃げ切り': 5, '先行': 4, '逃げ': 5,
    '先行争い敗北': 3, '先行争い敗': 3,
    '一発捲り': 3, 'ロング捲り': 3, '捲り': 3, '番手捲り': 3,
    'カマシ捲り': 4, '捲り差し': 3, '捲り追い込み': 2, '捲り不発': 2,
    '番手差し': 2, '差し': 2, '追い込み': 2, '流れ込み': 1,
    '追走': 1, 'マーク': 1,
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
        lno  = int(row['line_no']) if not pd.isna(row['line_no']) else 0
        bibs = str(row['line_bibs'])
        if lno not in lines:
            try:   lines[lno] = [int(x) for x in bibs.split('-') if x.isdigit()]
            except: lines[lno] = []
    return lines

# =========================================================
# analyze_race: hardcore_ev.py と完全同一コピー
# =========================================================
def analyze_race(race_id, venue, current_date, race_info, race_odds, past_db):
    bank_prof = bank_dict.get(venue, {'type': '標準', 'length': 400, 'sashi': 1.0, 'makuri': 1.0})
    if race_info.empty:
        return "", [], [], {}

    racer_nums = race_info['車番'].tolist()
    line_map   = parse_lines(race_info)
    num_to_line = {}
    for lno, bibs in line_map.items():
        for b in bibs:
            num_to_line[b] = lno
    line_leaders = {lno: bibs[0] for lno, bibs in line_map.items() if bibs}

    player_scores = {}
    for _, row in race_info.iterrows():
        num  = int(row['車番'])
        name = str(row['選手名'])
        norm = normalize_name(name)
        base_score = float(row['競走得点'])
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
            ip_avg    = wmean(hist['IP'])
            ep_avg    = wmean(hist['EP'])
            dp_avg    = wmean(hist['DP'])
            bp_avg    = wmean(hist['BP'])
            avg_nobi  = wmean(hist[nobi_col].apply(nobi_score))
            avg_senpo = wmean(hist['戦法'].apply(senpo_lead))
            comments  = " ".join(hist['解析コメント'].astype(str).tolist())
        else:
            ip_avg = ep_avg = 4.0
            dp_avg = bp_avg = 3.0
            avg_nobi = avg_senpo = 2.0
            comments = ""

        ip_avg    = ip_avg    if (ip_avg    is not None and not np.isnan(ip_avg))    else 4.0
        ep_avg    = ep_avg    if (ep_avg    is not None and not np.isnan(ep_avg))    else 4.0
        dp_avg    = dp_avg    if (dp_avg    is not None and not np.isnan(dp_avg))    else 3.0
        bp_avg    = bp_avg    if (bp_avg    is not None and not np.isnan(bp_avg))    else 3.0
        avg_nobi  = avg_nobi  if (avg_nobi  is not None and not np.isnan(avg_nobi))  else 2.0
        avg_senpo = avg_senpo if (avg_senpo is not None and not np.isnan(avg_senpo)) else 2.0

        is_monster    = any(kw in comments for kw in ["脚余し", "鬼脚", "別次元", "圧倒", "豪快"])
        is_unreliable = any(kw in comments for kw in ["共倒れ", "位置取り失敗", "不発", "失速"])

        lno            = num_to_line.get(num, 0)
        line_bibs      = line_map.get(lno, [])
        pos_in_line    = line_bibs.index(num) + 1 if num in line_bibs else 1
        line_pos_bonus = 0.5 if pos_in_line == 1 else (-0.3 * (pos_in_line - 1))

        ev_score = (
            base_score * 0.4
            + ip_avg   * 1.5
            + ep_avg   * 1.2
            + dp_avg   * bank_prof['makuri']
            + bp_avg   * bank_prof['sashi']
            + avg_nobi * 2.0
            + avg_senpo * 0.5
            + line_pos_bonus
            + (3.0 if is_monster   else 0)
            - (2.0 if is_unreliable else 0)
        )

        player_scores[num] = {
            'name':          name,
            'ev_score':      ev_score,
            'base_score':    base_score,
            'ip':            ip_avg,
            'ep':            ep_avg,
            'dp':            dp_avg,
            'bp':            bp_avg,
            'nobi':          avg_nobi,
            'senpo':         avg_senpo,
            'is_monster':    is_monster,
            'is_unreliable': is_unreliable,
            'hist_count':    len(hist),
            'style':         str(row['脚質']),
            'line_no':       lno,
            'pos_in_line':   pos_in_line,
        }

    ranked = sorted(player_scores.items(), key=lambda x: x[1]['ev_score'], reverse=True)

    strong_leaders = [
        d['name'] for _, d in player_scores.items()
        if d['ip'] >= 5.5 and d['pos_in_line'] == 1
    ]
    hidden_monsters = [(n, d) for n, d in ranked if d['is_monster']]
    is_chaos = len(strong_leaders) >= 2

    all_nums = [n for n, _ in ranked]
    n        = len(all_nums)
    max_ev   = ranked[0][1]['ev_score']
    raw_s    = {num: np.exp(player_scores[num]['ev_score'] - max_ev) for num in all_nums}

    def pl_prob(first, second, third):
        s  = raw_s
        d1 = sum(s[n] for n in all_nums)
        if d1 == 0: return 0.0
        d2 = sum(s[n] for n in all_nums if n != first)
        if d2 == 0: return 0.0
        d3 = sum(s[n] for n in all_nums if n not in (first, second))
        if d3 == 0: return 0.0
        return (s[first]/d1) * (s[second]/d2) * (s[third]/d3)

    n_combos = n * (n - 1) * (n - 2) if n >= 3 else 1
    p_floor  = 1.0 / n_combos

    odds_dict = {}
    if not race_odds.empty:
        for _, orow in race_odds.iterrows():
            odds_dict[str(orow['組み合わせ']).strip()] = float(orow['オッズ'])

    ev_positive_bets = []
    all_ev_bets      = []
    fallback_bets    = []

    # ── 軸固定モード（LOOSE-B は use_full_permutation=False）──
    axis_num   = hidden_monsters[0][0] if hidden_monsters else ranked[0][0]
    others_all = [num for num, _ in ranked if num != axis_num]

    for second in others_all:
        for third in others_all:
            if second == third: continue
            combo  = f"{axis_num}-{second}-{third}"
            p_trio = pl_prob(axis_num, second, third)
            if combo in odds_dict:
                ev_val = p_trio * odds_dict[combo]
                all_ev_bets.append((ev_val, combo, p_trio, odds_dict[combo]))
                if ev_val > 1.0:
                    ev_positive_bets.append((ev_val, combo, p_trio, odds_dict[combo]))
            else:
                fallback_bets.append((p_trio, combo, p_trio, 0.0))

    ev_positive_bets.sort(key=lambda x: x[0], reverse=True)
    all_ev_bets.sort(key=lambda x: x[0], reverse=True)
    all_prob_bets = sorted(all_ev_bets, key=lambda x: x[2], reverse=True)  # P確率降順

    top_n_prob = SCFG.get('top_n_prob_bets', None)

    if top_n_prob is not None:
        if all_prob_bets:
            selected_prob_bets = all_prob_bets[:top_n_prob]
            bet_combinations   = [c for _, c, _, _ in selected_prob_bets]
            ev_lookup          = {c: ev for ev, c, p, o in all_ev_bets}
            bet_ev_list        = [(c, ev_lookup.get(c, 0.0)) for c in bet_combinations]
        else:
            bet_combinations = []
            bet_ev_list      = []
    else:
        if ev_positive_bets:
            bet_combinations = [c for _, c, _, _ in ev_positive_bets[:14]]
            bet_ev_list      = [(c, ev) for ev, c, p, o in ev_positive_bets[:14]]
        else:
            bet_combinations = []
            bet_ev_list      = []

    max_combo_ev = ev_positive_bets[0][0] if ev_positive_bets else 0.0

    return "OK", bet_combinations, bet_ev_list, {
        'is_chaos':      is_chaos,
        'has_monster':   bool(hidden_monsters),
        'top_ev':        ranked[0][1]['ev_score'] if ranked else 0,
        'ev_gap':        (ranked[0][1]['ev_score'] - ranked[1][1]['ev_score']) if len(ranked) >= 2 else 0,
        'chaos_count':   len(strong_leaders),
        'ev_positive_n': len(ev_positive_bets),
        'max_combo_ev':  max_combo_ev,
        'has_odds_data': bool(odds_dict),
    }

# =========================================================
# should_bet_race: hardcore_ev.py と完全同一コピー
# =========================================================
def should_bet_race(meta: dict) -> bool:
    cfg         = SCFG
    is_chaos    = meta['is_chaos']
    has_monster = meta['has_monster']
    top_ev      = meta['top_ev']
    ev_gap      = meta['ev_gap']
    chaos_count = meta['chaos_count']

    if top_ev < cfg['min_top_ev']:
        return False
    if cfg['require_monster'] and not has_monster:
        return False
    if is_chaos:
        if cfg.get('s3_chaos_filter'):
            buy_on_leaders = chaos_count >= cfg['chaos_buy_leaders_ge']
            buy_on_ev      = top_ev      >= cfg['chaos_buy_ev_ge']
            buy_on_gap     = ev_gap      <= cfg['chaos_buy_ev_gap_le'] and has_monster
            if not (buy_on_leaders or buy_on_ev or buy_on_gap):
                return False
        elif cfg['skip_chaos']:
            return False
    return True

# =========================================================
# バックテスト集計
# =========================================================
def run_verify():
    dates            = sorted(racecard_raw['date'].unique())
    total_investment = 0
    total_return     = 0
    hit_count        = 0
    total_races_bet  = 0
    skipped_count    = 0
    bet_base         = SCFG.get('bet_base', 100)

    for current_date in dates:
        past_db  = db_all[db_all['開催日'] < current_date]
        daily_rc = racecard_raw[racecard_raw['date'] == current_date]
        race_ids = daily_rc['race_id'].unique()

        for rid in race_ids:
            race_info = daily_rc[daily_rc['race_id'] == rid].copy()
            if race_info.empty: continue

            venue     = race_info['venue'].iloc[0]
            race_odds = odds_raw[odds_raw['race_id'] == rid]

            ok, bets, bet_ev_list, meta = analyze_race(
                rid, venue, current_date, race_info, race_odds, past_db)
            if not ok: continue

            # ストラテジーフィルタ
            if not should_bet_race(meta):
                skipped_count += 1
                continue

            # バンクROIフィルタ
            bank_prof = bank_dict.get(venue, {'roi_tier': 'mid'})
            if SCFG.get('skip_low_bank') and bank_prof.get('roi_tier') == 'low':
                skipped_count += 1
                continue

            if not bets:
                skipped_count += 1
                continue

            total_races_bet += 1

            # ── EV傾斜配分（常時適用）──
            n_bets     = len(bets)
            total_pool = bet_base * n_bets
            ev_vals    = np.array([max(ev, 0.0) for _, ev in bet_ev_list])
            if ev_vals.sum() == 0:
                alloc_units = [bet_base] * n_bets
            else:
                raw_alloc   = (ev_vals / ev_vals.sum()) * total_pool
                alloc_100   = (raw_alloc // 100).astype(int) * 100
                remainder   = int(total_pool - alloc_100.sum())
                remainder   = (remainder // 100) * 100
                best_idx    = int(np.argmax(ev_vals))
                alloc_100[best_idx] += remainder
                alloc_units = [max(int(a), 100) for a in alloc_100]

            cost = sum(alloc_units)
            total_investment += cost

            # 払戻チェック
            race_payout = payouts_raw[payouts_raw['race_id'] == rid]
            if not race_payout.empty:
                raw_payout = race_payout['payout_trifecta'].values[0]
                if not pd.isna(raw_payout):
                    actual_result = str(race_payout['result_trifecta'].values[0]).strip()
                    if actual_result in bets:
                        hit_idx    = bets.index(actual_result)
                        hit_unit   = alloc_units[hit_idx]
                        payout_val = int(raw_payout * hit_unit / 100)
                        total_return += payout_val
                        hit_count    += 1

    roi      = (total_return  / total_investment) * 100 if total_investment > 0 else 0
    hit_rate = (hit_count / total_races_bet) * 100      if total_races_bet  > 0 else 0
    total_r  = total_races_bet + skipped_count

    print("\n" + "=" * 55)
    print(f"🏁 【検証バックテスト結果】 {STRATEGY}")
    print(f"   {SCFG['name']}")
    print("=" * 55)
    print(f"  全レース数         : {total_r:>5} R")
    print(f"  スキップ           : {skipped_count:>5} R")
    print(f"  ─────────────────────────────────────────────")
    print(f"  買い判定レース数   : {total_races_bet:>5} R")
    print(f"  的中レース数       : {hit_count:>5} R")
    print(f"  的中率             : {hit_rate:>7.1f}%")
    print(f"  ─────────────────────────────────────────────")
    print(f"  総投資額           : ¥{total_investment:>10,}")
    print(f"  総回収額           : ¥{total_return:>10,}")
    print(f"  ROI（回収率）      : {roi:>7.2f}%")
    print("=" * 55)

print("\n🚀 バックテスト開始...")
run_verify()
