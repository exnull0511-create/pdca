"""
backtest_model_comparison.py
============================
確率モデル改善: 4エンジン比較バックテスト

Engine Baseline : 現行 PL（軸1着固定, Top14確率順）
Engine A        : マルチ軸 PL（全選手1着展開, Top14確率順）
Engine B        : ライン相関 PL（同一ライン共倒れペナルティ）
Engine C        : Nested Logit（ラインをネスト構造としたモデル）

使い方:
  python backtest_model_comparison.py
"""

import sys, os, copy
import pandas as pd
import numpy as np
from datetime import datetime, date
from pathlib import Path
from itertools import permutations

# ═══════════════════════════════════════════════════════════════════════
#  設 定
# ═══════════════════════════════════════════════════════════════════════
DB_SLIM = "data/S級DB_slim.xlsx"
DB_OLD  = "data/S級選手究極DB(1).xlsx"

LOW_BANK  = {'岸和田','久留米','奈良','岐阜','小松島','防府','静岡','小倉'}
STRATEGY  = dict(skip_chaos=True, min_top_ev=70, skip_low_bank=True, top_n_prob_bets=14)
BET_BASE  = 100

BANK_DICT = {
    '前橋':     {'roi_tier':'mid', 'sashi':0.8,'makuri':1.2},
    '宇都宮':   {'roi_tier':'high','sashi':1.5,'makuri':1.1},
    '豊橋':     {'roi_tier':'high','sashi':1.3,'makuri':1.2},
    '岸和田':   {'roi_tier':'low', 'sashi':1.1,'makuri':1.3},
    '熊本':     {'roi_tier':'high','sashi':1.2,'makuri':1.1},
    'いわき平': {'roi_tier':'mid', 'sashi':0.9,'makuri':1.3},
    '広島':     {'roi_tier':'mid', 'sashi':1.2,'makuri':1.0},
    '別府':     {'roi_tier':'mid', 'sashi':1.1,'makuri':1.1},
    '松山':     {'roi_tier':'mid', 'sashi':1.0,'makuri':1.2},
    '小倉':     {'roi_tier':'low', 'sashi':1.1,'makuri':1.1},
    '京王閣':   {'roi_tier':'high','sashi':1.0,'makuri':1.1},
    '立川':     {'roi_tier':'high','sashi':1.1,'makuri':1.0},
    '取手':     {'roi_tier':'mid', 'sashi':1.1,'makuri':1.1},
    '伊東':     {'roi_tier':'mid', 'sashi':1.0,'makuri':1.2},
    '久留米':   {'roi_tier':'low', 'sashi':1.1,'makuri':1.1},
    '奈良':     {'roi_tier':'low', 'sashi':1.2,'makuri':1.0},
    '岐阜':     {'roi_tier':'low', 'sashi':1.1,'makuri':1.1},
    '小松島':   {'roi_tier':'low', 'sashi':1.1,'makuri':1.0},
    '防府':     {'roi_tier':'low', 'sashi':1.1,'makuri':1.1},
    '静岡':     {'roi_tier':'low', 'sashi':1.2,'makuri':1.0},
    '松阪':     {'roi_tier':'mid', 'sashi':1.1,'makuri':1.1},
    '高知':     {'roi_tier':'mid', 'sashi':1.0,'makuri':1.2},
    '松戸':     {'roi_tier':'mid', 'sashi':1.1,'makuri':1.0},
    '平塚':     {'roi_tier':'mid', 'sashi':1.2,'makuri':1.1},
    '西武園':   {'roi_tier':'mid', 'sashi':1.0,'makuri':1.1},
    '小田原':   {'roi_tier':'mid', 'sashi':1.0,'makuri':1.1},
}

SENPO_LEAD = {
    '逃げ切り':5,'逃げ粘り':4,'突っ張り先行':4,'抑え先行':4,
    '先行':4,'逃げ':5,'カマシ先行':5,'先行逃げ切り':5,
    '捲り':3,'番手捲り':3,'カマシ捲り':4,'捲り差し':3,
    '差し':2,'番手差し':2,'追い込み':2,'流れ込み':1,'追走':1,'マーク':1,
}

# Engine B パラメータ
LINE_CORR = 0.3      # 同一ライン相関ペナルティ係数

# Engine C パラメータ
NEST_SIGMA = 0.7     # ネスト内代替性 (0<σ≤1, 1.0でPLと等価)


# ═══════════════════════════════════════════════════════════════════════
#  ユーティリティ
# ═══════════════════════════════════════════════════════════════════════
def norm(s):  return str(s).replace(' ','').replace('\u3000','')
def nobi_score(v):
    m = {'S':5,'A':4,'B':3,'C':2,'D':1,'E':0}
    s = str(v).strip()
    return m.get(s, m.get(s[:1] if s else '', 2.5))
def senpo_lead(v):
    s = str(v).strip()
    for k, sc in SENPO_LEAD.items():
        if k in s: return sc
    return 2
def safe(v, d):
    try: return d if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v)
    except: return d


# ═══════════════════════════════════════════════════════════════════════
#  DB読み込み
# ═══════════════════════════════════════════════════════════════════════
def load_db():
    db_slim = db_all = pd.DataFrame()
    try:
        r = pd.read_excel(DB_SLIM)
        r['開催日'] = pd.to_datetime(r['開催日'], errors='coerce')
        r['選手名_norm'] = r['選手名'].apply(norm)
        db_slim = r[r['開催日'].notna()].reset_index(drop=True)
    except Exception as e:
        print(f"slimDB失敗: {e}")
    try:
        r2 = pd.read_excel(DB_OLD)
        if '例' in str(r2.iloc[0].get('開催日', '')):
            r2 = r2.iloc[1:].reset_index(drop=True)
        r2['開催日'] = pd.to_datetime(r2['開催日'], format='%Y/%m/%d', errors='coerce')
        r2['選手名_norm'] = r2['選手名'].apply(norm)
        db_all = r2[r2['開催日'].notna()].reset_index(drop=True)
    except Exception as e:
        print(f"oldDB失敗: {e}")
    nobi_col = next((c for c in db_all.columns if '伸び' in c and '直線' not in c), None)
    print(f"slimDB:{len(db_slim)}件  oldDB:{len(db_all)}件  伸び列:{nobi_col}")
    return db_slim, db_all, nobi_col


# ═══════════════════════════════════════════════════════════════════════
#  共通: 選手スコア算出
# ═══════════════════════════════════════════════════════════════════════
def compute_player_scores(venue, race_card, lines_df, db_slim, db_all, nobi_col, race_dt):
    """選手スコア・ライン情報を算出（全エンジン共通）"""
    bp = BANK_DICT.get(venue, {'roi_tier':'mid','sashi':1.0,'makuri':1.0})

    # ライン辞書構築
    line_map    = {}
    num_to_line = {}
    for _, row in lines_df.iterrows():
        lno = int(row['line_no'])
        num = int(row['車番'])
        if lno not in line_map:
            line_map[lno] = []
        line_map[lno].append(num)
        num_to_line[num] = lno

    past_slim = db_slim[db_slim['開催日'] < race_dt] if not db_slim.empty else db_slim
    past_all  = db_all[db_all['開催日']  < race_dt] if not db_all.empty  else db_all

    player_scores = {}
    for _, row in race_card.iterrows():
        try:
            num = int(row['車番'])
        except:
            continue
        nm   = norm(str(row.get('選手名', '')))
        base = float(row.get('競走得点', 80) or 80)

        hist     = past_slim[past_slim['選手名_norm'] == nm] if not past_slim.empty else pd.DataFrame()
        use_slim = not hist.empty
        if hist.empty:
            hist = past_all[past_all['選手名_norm'] == nm] if not past_all.empty else pd.DataFrame()

        ip = ep = 4.0; dp = bp_v = 3.0; nb = sp = 2.0; is_m = is_u = False
        if not hist.empty:
            RECENT_W = 3.0
            sd = sorted(hist['開催日'].dropna().unique(), reverse=True)
            rd = set(sd[:2])
            def wm(series):
                v = pd.to_numeric(series, errors='coerce')
                w = np.where(hist['開催日'].isin(rd), RECENT_W, 1.0)
                mk = v.notna()
                return float((v[mk]*w[mk]).sum() / w[mk].sum()) if mk.any() else np.nan
            ip   = safe(wm(hist['IP']), 4.0)
            ep   = safe(wm(hist['EP']), 4.0)
            dp   = safe(wm(hist['DP']), 3.0)
            bp_v = safe(wm(hist['BP']), 3.0)
            if use_slim and '直線の伸び' in hist.columns:
                nb = safe(wm(hist['直線の伸び'].apply(nobi_score)), 2.0)
            elif nobi_col and nobi_col in hist.columns:
                nb = safe(wm(hist[nobi_col].apply(nobi_score)), 2.0)
            if '戦法' in hist.columns:
                sp = safe(wm(hist['戦法'].apply(senpo_lead)), 2.0)
            if use_slim:
                is_m = bool(hist.get('is_monster',   pd.Series([0])).max() >= 1)
                is_u = bool(hist.get('is_unreliable', pd.Series([0])).max() >= 1)
            else:
                cmt = ' '.join(hist.get('解析コメント', pd.Series([''])).astype(str))
                is_m = any(k in cmt for k in ['脚余し','鬼脚','別次元','圧倒'])
                is_u = any(k in cmt for k in ['共倒れ','位置取り失敗','不発','失速'])

        lno  = num_to_line.get(num, 0)
        lbs  = line_map.get(lno, [])
        pos  = lbs.index(num) + 1 if num in lbs else 1
        pos_b= 0.5 if pos == 1 else -0.3 * (pos - 1)

        ev = (base*0.4 + ip*1.5 + ep*1.2 + dp*bp['makuri'] + bp_v*bp['sashi']
              + nb*2.0 + sp*0.5 + pos_b + (3.0 if is_m else 0) - (2.0 if is_u else 0))

        player_scores[num] = {
            'name': str(row.get('選手名', '')),
            'ev': ev, 'ip': ip,
            'is_monster': is_m, 'pos_in_line': pos,
        }

    return player_scores, num_to_line, line_map


def common_filter(venue, player_scores, num_to_line, line_map):
    """共通フィルタ: low_bank / EV不足 / カオス判定"""
    if STRATEGY['skip_low_bank'] and venue in LOW_BANK:
        return None, "低bank"

    ranked = sorted(player_scores.items(), key=lambda x: x[1]['ev'], reverse=True)
    if len(ranked) < 3:
        return None, "選手不足"

    strong_leaders = [n for n, d in player_scores.items()
                      if d['ip'] >= 5.5 and line_map.get(num_to_line.get(n, 0), [None])[0] == n]
    is_chaos = len(strong_leaders) >= 2

    top_ev = ranked[0][1]['ev']
    if top_ev < STRATEGY['min_top_ev']:
        return None, f"EV不足({top_ev:.1f})"
    if is_chaos and STRATEGY['skip_chaos']:
        return None, f"カオス(先行×{len(strong_leaders)})"

    return ranked, None


def compute_raw_strengths(player_scores, ranked):
    """PL用の指数ストレングスを計算"""
    all_nums = [n for n, _ in ranked]
    max_e    = ranked[0][1]['ev']
    raw_s    = {n: np.exp(player_scores[n]['ev'] - max_e) for n in all_nums}
    return all_nums, raw_s


def allocate_bets(selected_combos, ev_lookup):
    """EV比例の賭金配分（共通）"""
    bets  = [c for _, c, _, _ in selected_combos]
    bev   = [(c, ev_lookup.get(c, 0.0)) for c in bets]
    ev_va = np.array([max(e, 0.0) for _, e in bev])
    total_p = BET_BASE * len(bets)
    if ev_va.sum() == 0:
        alloc = [BET_BASE] * len(bets)
    else:
        a = (ev_va / ev_va.sum()) * total_p
        a100 = (a // 100).astype(int) * 100
        a100[int(np.argmax(ev_va))] += (int(total_p - a100.sum()) // 100) * 100
        alloc = [max(int(x), 100) for x in a100]
    return list(zip(bets, alloc)), sum(alloc)


# ═══════════════════════════════════════════════════════════════════════
#  Baseline: 現行PL（軸1着固定）
# ═══════════════════════════════════════════════════════════════════════
def run_baseline(player_scores, ranked, all_nums, raw_s, odds_dict, num_to_line, line_map):
    """現行ロジックそのまま"""
    def pl(f, s, t):
        d1 = sum(raw_s[n] for n in all_nums)
        d2 = sum(raw_s[n] for n in all_nums if n != f)
        d3 = sum(raw_s[n] for n in all_nums if n not in (f, s))
        return 0.0 if 0 in (d1, d2, d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)

    axis_num = next((n for n, d in ranked if d['is_monster']), ranked[0][0])
    others   = [n for n, _ in ranked if n != axis_num]

    all_ev_bets = []
    for s in others:
        for t in others:
            if s == t: continue
            combo = f"{axis_num}-{s}-{t}"
            p_trio = pl(axis_num, s, t)
            odds = odds_dict.get(combo, 0)
            ev_val = p_trio * odds if odds > 0 else 0
            all_ev_bets.append((ev_val, combo, p_trio, odds))

    selected = sorted(all_ev_bets, key=lambda x: x[2], reverse=True)[:STRATEGY['top_n_prob_bets']]
    if not selected:
        return None
    ev_lookup = {c: ev for ev, c, p, o in all_ev_bets}
    bets, total = allocate_bets(selected, ev_lookup)
    return {'bets': bets, 'total': total, 'axis': axis_num, 'engine': 'Baseline'}


# ═══════════════════════════════════════════════════════════════════════
#  Engine A: マルチ軸PL（全選手1着展開）
# ═══════════════════════════════════════════════════════════════════════
def run_engine_a(player_scores, ranked, all_nums, raw_s, odds_dict, num_to_line, line_map):
    """軸を固定せず、全選手の1着パターンを展開"""
    def pl(f, s, t):
        d1 = sum(raw_s[n] for n in all_nums)
        d2 = sum(raw_s[n] for n in all_nums if n != f)
        d3 = sum(raw_s[n] for n in all_nums if n not in (f, s))
        return 0.0 if 0 in (d1, d2, d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)

    all_ev_bets = []
    for f in all_nums:
        for s in all_nums:
            if s == f: continue
            for t in all_nums:
                if t == f or t == s: continue
                combo = f"{f}-{s}-{t}"
                if combo not in odds_dict:
                    continue
                p_trio = pl(f, s, t)
                odds = odds_dict[combo]
                ev_val = p_trio * odds if odds > 0 else 0
                all_ev_bets.append((ev_val, combo, p_trio, odds))

    selected = sorted(all_ev_bets, key=lambda x: x[2], reverse=True)[:STRATEGY['top_n_prob_bets']]
    if not selected:
        return None
    ev_lookup = {c: ev for ev, c, p, o in all_ev_bets}
    bets, total = allocate_bets(selected, ev_lookup)
    # 最も多く1着に現れる選手を「軸」として記録
    first_nums = [int(c.split('-')[0]) for _, c, _, _ in selected]
    axis = max(set(first_nums), key=first_nums.count) if first_nums else ranked[0][0]
    return {'bets': bets, 'total': total, 'axis': axis, 'engine': 'EngineA'}


# ═══════════════════════════════════════════════════════════════════════
#  Engine B: ライン相関PL（共倒れペナルティ）
# ═══════════════════════════════════════════════════════════════════════
def run_engine_b(player_scores, ranked, all_nums, raw_s, odds_dict, num_to_line, line_map):
    """PL確率にライン相関ペナルティを適用 + マルチ軸展開"""
    def pl(f, s, t):
        d1 = sum(raw_s[n] for n in all_nums)
        d2 = sum(raw_s[n] for n in all_nums if n != f)
        d3 = sum(raw_s[n] for n in all_nums if n not in (f, s))
        return 0.0 if 0 in (d1, d2, d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)

    def pl_line_corr(f, s, t):
        base_prob = pl(f, s, t)
        # 上位3名のライン所属を確認
        lines = [num_to_line.get(x, -x) for x in [f, s, t]]
        # 同一ラインペアの数をカウント
        same_pairs = sum(1 for i in range(3) for j in range(i+1, 3) if lines[i] == lines[j])

        if same_pairs >= 3:  # 3名全員同一ライン（理論上ない場合もある）
            return base_prob * (1 - LINE_CORR)
        elif same_pairs >= 1:  # 少なくとも2名が同一ライン
            # ラインの先頭が上位に入っていない場合、番手・3番手が上位に来る確率を下げる
            for pair_line in set(lines):
                if pair_line < 0:
                    continue  # ラインなし
                members_in_top = [x for x in [f, s, t] if num_to_line.get(x, -x) == pair_line]
                if len(members_in_top) >= 2:
                    line_members = line_map.get(pair_line, [])
                    leader = line_members[0] if line_members else None
                    if leader and leader not in [f, s, t]:
                        # ラインリーダーが圏外なのに番手が上位 → 強ペナルティ
                        return base_prob * (1 - LINE_CORR)
                    elif leader and leader == f:
                        # リーダーが1着で番手も上位 → 正常（軽ペナルティ）
                        return base_prob * (1 - LINE_CORR * 0.15)
            return base_prob * (1 - LINE_CORR * 0.3)
        return base_prob

    all_ev_bets = []
    for f in all_nums:
        for s in all_nums:
            if s == f: continue
            for t in all_nums:
                if t == f or t == s: continue
                combo = f"{f}-{s}-{t}"
                if combo not in odds_dict:
                    continue
                p_trio = pl_line_corr(f, s, t)
                odds = odds_dict[combo]
                ev_val = p_trio * odds if odds > 0 else 0
                all_ev_bets.append((ev_val, combo, p_trio, odds))

    # 補正済み確率で再正規化してTop14選択
    total_prob = sum(p for _, _, p, _ in all_ev_bets) if all_ev_bets else 1.0
    all_ev_bets_norm = [(ev, c, p/total_prob if total_prob > 0 else p, o) for ev, c, p, o in all_ev_bets]

    selected = sorted(all_ev_bets_norm, key=lambda x: x[2], reverse=True)[:STRATEGY['top_n_prob_bets']]
    if not selected:
        return None
    # EV lookupは正規化前の値を使用（オッズ×確率）
    ev_lookup = {c: (p * o) for _, c, p, o in all_ev_bets_norm}
    bets, total = allocate_bets(selected, ev_lookup)
    first_nums = [int(c.split('-')[0]) for _, c, _, _ in selected]
    axis = max(set(first_nums), key=first_nums.count) if first_nums else ranked[0][0]
    return {'bets': bets, 'total': total, 'axis': axis, 'engine': 'EngineB'}


# ═══════════════════════════════════════════════════════════════════════
#  Engine C: Nested Logit（ラインをネスト）
# ═══════════════════════════════════════════════════════════════════════
def run_engine_c(player_scores, ranked, all_nums, raw_s, odds_dict, num_to_line, line_map):
    """ラインをネストとするNested Logitモデル"""

    sigma = NEST_SIGMA

    def nested_marginal_prob(target, remaining_nums):
        """Nested Logit: 残り選手集合からtarget選手が1着になる確率"""
        if not remaining_nums:
            return 0.0

        # ネスト（ライン）ごとにグループ化
        nests = {}
        for n in remaining_nums:
            ln = num_to_line.get(n, -n)  # ラインなしは個別ネスト
            if ln not in nests:
                nests[ln] = []
            nests[ln].append(n)

        # 各ネストのInclusive Value (IV)
        IV = {}
        for ln, members in nests.items():
            inner_sum = sum(raw_s[m] ** (1.0 / sigma) for m in members)
            IV[ln] = inner_sum ** sigma if inner_sum > 0 else 0.0

        total_IV = sum(IV.values())
        if total_IV == 0:
            return 0.0

        target_ln = num_to_line.get(target, -target)

        # ネスト選択確率
        nest_prob = IV[target_ln] / total_IV

        # ネスト内選択確率
        nest_members = nests[target_ln]
        inner_denom = sum(raw_s[m] ** (1.0 / sigma) for m in nest_members)
        if inner_denom == 0:
            return 0.0
        within_prob = (raw_s[target] ** (1.0 / sigma)) / inner_denom

        return nest_prob * within_prob

    def nested_trifecta_prob(f, s, t):
        """Nested Logitで3連単確率 P(1着=f, 2着=s, 3着=t) を逐次計算"""
        # P(1着=f | 全選手)
        p1 = nested_marginal_prob(f, all_nums)
        if p1 == 0:
            return 0.0

        # P(2着=s | fを除く)
        remaining_2 = [n for n in all_nums if n != f]
        p2 = nested_marginal_prob(s, remaining_2)
        if p2 == 0:
            return 0.0

        # P(3着=t | f,sを除く)
        remaining_3 = [n for n in all_nums if n not in (f, s)]
        p3 = nested_marginal_prob(t, remaining_3)

        return p1 * p2 * p3

    all_ev_bets = []
    for f in all_nums:
        for s in all_nums:
            if s == f: continue
            for t in all_nums:
                if t == f or t == s: continue
                combo = f"{f}-{s}-{t}"
                if combo not in odds_dict:
                    continue
                p_trio = nested_trifecta_prob(f, s, t)
                odds = odds_dict[combo]
                ev_val = p_trio * odds if odds > 0 else 0
                all_ev_bets.append((ev_val, combo, p_trio, odds))

    selected = sorted(all_ev_bets, key=lambda x: x[2], reverse=True)[:STRATEGY['top_n_prob_bets']]
    if not selected:
        return None
    ev_lookup = {c: ev for ev, c, p, o in all_ev_bets}
    bets, total = allocate_bets(selected, ev_lookup)
    first_nums = [int(c.split('-')[0]) for _, c, _, _ in selected]
    axis = max(set(first_nums), key=first_nums.count) if first_nums else ranked[0][0]
    return {'bets': bets, 'total': total, 'axis': axis, 'engine': 'EngineC'}


# ═══════════════════════════════════════════════════════════════════════
#  メイン
# ═══════════════════════════════════════════════════════════════════════
def main():
    db_slim, db_all, nobi_col = load_db()

    # データ読み込み
    rc_df = pd.read_excel("data/racecard.xlsx")
    od_df = pd.read_excel("data/odds.xlsx")
    py_df = pd.read_excel("data/payouts.xlsx")

    rc_df['date'] = pd.to_datetime(rc_df['date'].astype(str).str.strip(), format='%Y%m%d', errors='coerce')

    def clean_id(v):
        s = str(v).strip()
        if s.startswith('="') and s.endswith('"'): s = s[2:-1]
        return s
    for df in [rc_df, od_df, py_df]:
        df['race_id'] = df['race_id'].apply(clean_id)

    # S級レースのrace_id一覧
    try:
        bt = pd.read_csv("data/backtest_result_v2.csv")
        bt['race_id'] = bt['race_id'].apply(clean_id)
        s_race_ids = set(bt['race_id'].tolist())
        print(f"S級race_id: {len(s_race_ids)}件")
    except Exception:
        s_race_ids = None

    races = rc_df.groupby('race_id')

    ENGINES = {
        'Baseline': run_baseline,
        'EngineA':  run_engine_a,
        'EngineB':  run_engine_b,
        'EngineC':  run_engine_c,
    }

    engine_results = {name: [] for name in ENGINES}
    engine_skipped = {name: 0 for name in ENGINES}

    total_races = 0

    print(f"\n{'='*75}")
    print(f"  確率モデル 4エンジン比較バックテスト")
    print(f"{'='*75}\n")

    for race_id, rc_group in races:
        if s_race_ids is not None and race_id not in s_race_ids:
            continue

        venue   = rc_group.iloc[0]['venue']
        race_no = int(rc_group.iloc[0]['race_no'])
        race_dt = rc_group.iloc[0]['date']
        if pd.isna(race_dt):
            continue

        lines_df = rc_group[['line_no','車番']].dropna()
        if lines_df.empty:
            continue

        od_race   = od_df[od_df['race_id'] == race_id]
        odds_dict = {str(r['組み合わせ']).strip(): float(r['オッズ'])
                     for _, r in od_race.iterrows() if pd.notna(r['オッズ'])}

        py_race = py_df[py_df['race_id'] == race_id]
        if py_race.empty:
            continue
        actual = str(py_race.iloc[0].get('result_trifecta', '')).strip().replace('="','').replace('"','')
        payout = py_race.iloc[0].get('payout_trifecta', 0)
        try:
            payout = int(str(payout).replace(',', ''))
        except:
            payout = 0

        # 共通スコア算出（1回だけ）
        player_scores, num_to_line, line_map = compute_player_scores(
            venue, rc_group, lines_df, db_slim, db_all, nobi_col, race_dt
        )

        result_filter = common_filter(venue, player_scores, num_to_line, line_map)
        ranked, skip_reason = result_filter
        if ranked is None:
            for name in ENGINES:
                engine_skipped[name] += 1
            continue

        all_nums, raw_s = compute_raw_strengths(player_scores, ranked)
        total_races += 1

        # 各エンジン実行
        for eng_name, eng_func in ENGINES.items():
            pred = eng_func(player_scores, ranked, all_nums, raw_s, odds_dict, num_to_line, line_map)
            if pred is None:
                engine_skipped[eng_name] += 1
                continue

            bet_combos = [c for c, _ in pred['bets']]
            hit        = actual in bet_combos
            bet_amt    = dict(pred['bets']).get(actual, 0) if hit else 0
            ret_val    = int(payout * bet_amt / 100) if hit else 0

            engine_results[eng_name].append({
                'race_id':   race_id,
                'venue':     venue,
                'date':      str(race_dt.date()),
                'race_no':   race_no,
                'axis':      pred['axis'],
                'invest':    pred['total'],
                'return':    ret_val,
                'payout_100': payout,
                'hit':       hit,
                'actual':    actual,
                'n_bets':    len(pred['bets']),
                'bets':      ','.join(bet_combos[:5]),
            })

    # ═══════════════════════════ 結 果 集 計 ═══════════════════════════
    print(f"\n{'='*75}")
    print(f"  【モデル比較結果】  対象: {total_races}R")
    print(f"{'='*75}\n")

    summary_rows = []

    for eng_name in ENGINES:
        res = engine_results[eng_name]
        if not res:
            print(f"  {eng_name:12s}: データなし")
            continue
        df = pd.DataFrame(res)
        n        = len(df)
        n_hit    = int(df['hit'].sum())
        total_in = int(df['invest'].sum())
        total_re = int(df['return'].sum())
        profit   = total_re - total_in
        roi      = total_re / total_in * 100 if total_in > 0 else 0
        hit_rate = n_hit / n * 100
        skip     = engine_skipped[eng_name]

        summary_rows.append({
            'Engine':    eng_name,
            'Races':     n,
            'Hits':      n_hit,
            'HitRate%':  round(hit_rate, 1),
            'Invest':    total_in,
            'Return':    total_re,
            'Profit':    profit,
            'ROI%':      round(roi, 1),
            'Skipped':   skip,
        })

    summary_df = pd.DataFrame(summary_rows)
    print(summary_df.to_string(index=False))

    # 詳細レース比較（Baselineで外れ → 他で的中 / その逆）
    print(f"\n{'='*75}")
    print(f"  【差分分析】 Baselineとの比較")
    print(f"{'='*75}\n")

    base_df = pd.DataFrame(engine_results['Baseline']).set_index('race_id') if engine_results['Baseline'] else pd.DataFrame()

    for eng_name in ['EngineA', 'EngineB', 'EngineC']:
        eng_df = pd.DataFrame(engine_results[eng_name]).set_index('race_id') if engine_results[eng_name] else pd.DataFrame()
        if base_df.empty or eng_df.empty:
            continue

        common_ids = base_df.index.intersection(eng_df.index)
        gained = []  # Baselineで外れ → Engで的中
        lost   = []  # Baselineで的中 → Engで外れ

        for rid in common_ids:
            b_hit = base_df.loc[rid, 'hit']
            e_hit = eng_df.loc[rid, 'hit']
            if not b_hit and e_hit:
                gained.append(rid)
            elif b_hit and not e_hit:
                lost.append(rid)

        print(f"  {eng_name} vs Baseline:")
        print(f"    新規的中(+): {len(gained)}件")
        if gained:
            for rid in gained[:5]:
                r = eng_df.loc[rid]
                print(f"      {r['date']} {r['venue']} {r['race_no']}R  "
                      f"結果:{r['actual']}  払戻¥{r['payout_100']:,}")
        print(f"    失った的中(-): {len(lost)}件")
        if lost:
            for rid in lost[:5]:
                r = base_df.loc[rid]
                print(f"      {r['date']} {r['venue']} {r['race_no']}R  "
                      f"結果:{r['actual']}  払戻¥{r['payout_100']:,}")
        print()

    # CSV保存（全エンジンの結果を統合）
    all_results = []
    for eng_name, res_list in engine_results.items():
        for r in res_list:
            r['engine'] = eng_name
            all_results.append(r)
    if all_results:
        out_df = pd.DataFrame(all_results)
        out_df.to_csv("data/model_comparison_result.csv", index=False, encoding='utf-8-sig')
        print(f"\n💾 data/model_comparison_result.csv 保存完了")

    # サマリーCSV
    if not summary_df.empty:
        summary_df.to_csv("data/model_comparison_summary.csv", index=False, encoding='utf-8-sig')
        print(f"💾 data/model_comparison_summary.csv 保存完了")

    print(f"\n{'='*75}")


if __name__ == "__main__":
    main()
