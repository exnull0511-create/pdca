"""
backtest_allocation.py
======================
資金配分方式の比較バックテスト

Engine C (Nested Logit, σ=0.90) の買い目選択結果を固定し、
配分方式のみを変えてROI・収支を比較する。

方式:
  1. UNIFORM     : 均等配分（全点¥100）
  2. EV_PROP     : EV比例配分（現行）
  3. SQRT_EV     : √EV比例配分（極端さを緩和）
  4. CAPPED_EV   : キャップ付きEV（最低の N倍まで制限）
  5. HALF_KELLY  : ハーフケリー基準（理論的最適）
  6. LOG_EV      : log(1+EV)比例配分

使い方:
  python backtest_allocation.py
"""

import pandas as pd
import numpy as np
from backtest_model_comparison import (
    load_db, compute_player_scores, common_filter, compute_raw_strengths,
    STRATEGY, BET_BASE,
)

# Engine C のパラメータ
NEST_SIGMA = 0.90
BET_UNIT   = 100    # 最低賭金単位


# ═══════════════════════════════════════════════════════════════════════
#  Engine C: Nested Logit — 買い目選択（確率とEVを返す版）
# ═══════════════════════════════════════════════════════════════════════
def engine_c_raw(all_nums, raw_s, odds_dict, num_to_line, **_kw):
    """Engine C で買い目14点を選択し、各点の確率・オッズ・EVを返す"""
    sigma = NEST_SIGMA

    def _build_nests(members):
        nests = {}
        for n in members:
            ln = num_to_line.get(n, -n)
            if ln not in nests: nests[ln] = []
            nests[ln].append(n)
        return nests

    def nested_marginal(target, remaining):
        if not remaining: return 0.0
        nests = _build_nests(remaining)
        IV = {}
        for ln, members in nests.items():
            inner = sum(raw_s[m] ** (1.0 / sigma) for m in members)
            IV[ln] = inner ** sigma if inner > 0 else 0.0
        total_IV = sum(IV.values())
        if total_IV == 0: return 0.0
        t_ln = num_to_line.get(target, -target)
        nest_p = IV[t_ln] / total_IV
        inner_d = sum(raw_s[m] ** (1.0 / sigma) for m in nests[t_ln])
        if inner_d == 0: return 0.0
        within_p = (raw_s[target] ** (1.0 / sigma)) / inner_d
        return nest_p * within_p

    def nested_tri(f, s, t):
        p1 = nested_marginal(f, all_nums)
        if p1 == 0: return 0.0
        r2 = [n for n in all_nums if n != f]
        p2 = nested_marginal(s, r2)
        if p2 == 0: return 0.0
        r3 = [n for n in all_nums if n not in (f, s)]
        p3 = nested_marginal(t, r3)
        return p1 * p2 * p3

    all_data = []
    for f in all_nums:
        for s in all_nums:
            if s == f: continue
            for t in all_nums:
                if t == f or t == s: continue
                combo = f"{f}-{s}-{t}"
                if combo not in odds_dict: continue
                p = nested_tri(f, s, t)
                o = odds_dict[combo]
                all_data.append({'combo': combo, 'prob': p, 'odds': o, 'ev': p * o})

    all_data.sort(key=lambda x: x['prob'], reverse=True)
    selected = all_data[:STRATEGY['top_n_prob_bets']]
    return selected  # [{combo, prob, odds, ev}, ...]


# ═══════════════════════════════════════════════════════════════════════
#  配分方式
# ═══════════════════════════════════════════════════════════════════════
def alloc_uniform(bets_info):
    """① 均等配分: 全点 ¥100"""
    return [BET_UNIT] * len(bets_info)


def alloc_ev_prop(bets_info):
    """② EV比例配分（現行ロジック）"""
    ev_vals = np.array([max(b['ev'], 0.0) for b in bets_info])
    n = len(bets_info)
    total_p = BET_UNIT * n
    if ev_vals.sum() == 0:
        return [BET_UNIT] * n
    a = (ev_vals / ev_vals.sum()) * total_p
    a100 = (a // BET_UNIT).astype(int) * BET_UNIT
    a100[int(np.argmax(ev_vals))] += (int(total_p - a100.sum()) // BET_UNIT) * BET_UNIT
    return [max(int(x), BET_UNIT) for x in a100]


def alloc_sqrt_ev(bets_info):
    """③ √EV比例配分"""
    ev_vals = np.array([max(b['ev'], 0.0) for b in bets_info])
    sqrt_ev = np.sqrt(ev_vals)
    n = len(bets_info)
    total_p = BET_UNIT * n
    if sqrt_ev.sum() == 0:
        return [BET_UNIT] * n
    a = (sqrt_ev / sqrt_ev.sum()) * total_p
    a100 = (a // BET_UNIT).astype(int) * BET_UNIT
    a100[int(np.argmax(sqrt_ev))] += (int(total_p - a100.sum()) // BET_UNIT) * BET_UNIT
    return [max(int(x), BET_UNIT) for x in a100]


def alloc_log_ev(bets_info):
    """⑥ log(1+EV)比例配分"""
    ev_vals = np.array([max(b['ev'], 0.0) for b in bets_info])
    log_ev = np.log1p(ev_vals)
    n = len(bets_info)
    total_p = BET_UNIT * n
    if log_ev.sum() == 0:
        return [BET_UNIT] * n
    a = (log_ev / log_ev.sum()) * total_p
    a100 = (a // BET_UNIT).astype(int) * BET_UNIT
    a100[int(np.argmax(log_ev))] += (int(total_p - a100.sum()) // BET_UNIT) * BET_UNIT
    return [max(int(x), BET_UNIT) for x in a100]


def alloc_capped_ev(bets_info, max_ratio=3.0):
    """④ キャップ付きEV配分（最低額の max_ratio 倍まで制限）"""
    ev_vals = np.array([max(b['ev'], 0.0) for b in bets_info])
    n = len(bets_info)
    if ev_vals.sum() == 0:
        return [BET_UNIT] * n

    # まず正規化
    normed = ev_vals / ev_vals.max() if ev_vals.max() > 0 else np.ones(n)
    # 最低を1.0、最大をmax_ratioにクリップ
    normed = np.clip(normed, 1.0 / max_ratio, 1.0)
    # 配分
    total_p = BET_UNIT * n
    a = (normed / normed.sum()) * total_p
    a100 = (a // BET_UNIT).astype(int) * BET_UNIT
    a100[int(np.argmax(normed))] += (int(total_p - a100.sum()) // BET_UNIT) * BET_UNIT
    return [max(int(x), BET_UNIT) for x in a100]


def alloc_half_kelly(bets_info):
    """⑤ ハーフケリー基準"""
    n = len(bets_info)
    total_bankroll = BET_UNIT * n  # 1レースあたりの予算

    kelly_fracs = []
    for b in bets_info:
        p = b['prob']
        odds = b['odds']  # 100円あたり倍率
        if odds <= 0 or p <= 0:
            kelly_fracs.append(0.0)
            continue
        # ケリー基準: f* = (p * odds - 1) / (odds - 1)
        # ただし odds は100円あたりの倍率（例: 15.0 = 15倍）
        net_odds = odds - 1  # 純利益倍率
        if net_odds <= 0:
            kelly_fracs.append(0.0)
            continue
        f_star = (p * odds - 1) / net_odds
        # ハーフケリー
        f_half = max(f_star * 0.5, 0.0)
        kelly_fracs.append(f_half)

    kelly_arr = np.array(kelly_fracs)
    if kelly_arr.sum() == 0:
        return [BET_UNIT] * n

    # ケリーで「賭けない」判定の点も最低¥100は賭ける（比較公平性のため）
    a = (kelly_arr / kelly_arr.sum()) * total_bankroll
    a100 = (a // BET_UNIT).astype(int) * BET_UNIT
    # 端数を最大フラクションの点に加算
    best_idx = int(np.argmax(kelly_arr))
    a100[best_idx] += (int(total_bankroll - a100.sum()) // BET_UNIT) * BET_UNIT
    return [max(int(x), BET_UNIT) for x in a100]


# ═══════════════════════════════════════════════════════════════════════
#  キャップ付きEV のグリッドサーチ用
# ═══════════════════════════════════════════════════════════════════════
def make_alloc_capped(ratio):
    def fn(bets_info):
        return alloc_capped_ev(bets_info, max_ratio=ratio)
    return fn


# ═══════════════════════════════════════════════════════════════════════
#  データ準備
# ═══════════════════════════════════════════════════════════════════════
def prepare_races(db_slim, db_all, nobi_col):
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

    try:
        bt = pd.read_csv("data/backtest_result_v2.csv")
        bt['race_id'] = bt['race_id'].apply(clean_id)
        s_race_ids = set(bt['race_id'].tolist())
    except:
        s_race_ids = None

    cache = []
    for race_id, rc_group in rc_df.groupby('race_id'):
        if s_race_ids and race_id not in s_race_ids: continue
        venue = rc_group.iloc[0]['venue']
        race_dt = rc_group.iloc[0]['date']
        if pd.isna(race_dt): continue
        lines_df = rc_group[['line_no','車番']].dropna()
        if lines_df.empty: continue

        od_race = od_df[od_df['race_id'] == race_id]
        odds_dict = {str(r['組み合わせ']).strip(): float(r['オッズ'])
                     for _, r in od_race.iterrows() if pd.notna(r['オッズ'])}

        py_race = py_df[py_df['race_id'] == race_id]
        if py_race.empty: continue
        actual = str(py_race.iloc[0].get('result_trifecta','')).strip().replace('="','').replace('"','')
        payout = py_race.iloc[0].get('payout_trifecta', 0)
        try: payout = int(str(payout).replace(',',''))
        except: payout = 0

        ps, ntl, lm = compute_player_scores(venue, rc_group, lines_df, db_slim, db_all, nobi_col, race_dt)
        ranked, skip = common_filter(venue, ps, ntl, lm)
        if ranked is None: continue
        all_nums, raw_s = compute_raw_strengths(ps, ranked)

        # Engine C で買い目を選択
        bets_raw = engine_c_raw(all_nums, raw_s, odds_dict, ntl)
        if not bets_raw: continue

        cache.append({
            'race_id': race_id, 'venue': venue,
            'race_no': int(rc_group.iloc[0]['race_no']),
            'race_dt': race_dt,
            'bets_raw': bets_raw,  # [{combo, prob, odds, ev}, ...]
            'actual': actual, 'payout': payout,
        })

    return cache


def evaluate_alloc(cache, alloc_fn, label=''):
    """同一の買い目選択に対して配分方式のみ変えて評価"""
    hits = 0; n = 0; total_in = 0; total_re = 0
    alloc_ratios = []  # 最大/最小比率の記録

    for r in cache:
        bets_raw = r['bets_raw']
        alloc = alloc_fn(bets_raw)
        n += 1
        total_in += sum(alloc)

        # 最大/最小比率
        if min(alloc) > 0:
            alloc_ratios.append(max(alloc) / min(alloc))

        combos = [b['combo'] for b in bets_raw]
        if r['actual'] in combos:
            idx = combos.index(r['actual'])
            bet_amt = alloc[idx]
            ret = int(r['payout'] * bet_amt / 100)
            total_re += ret
            hits += 1

    roi = total_re / total_in * 100 if total_in > 0 else 0
    hr  = hits / n * 100 if n > 0 else 0
    avg_ratio = np.mean(alloc_ratios) if alloc_ratios else 0

    return {
        'n': n, 'hits': hits, 'hr': hr,
        'invest': total_in, 'ret': total_re,
        'profit': total_re - total_in, 'roi': roi,
        'avg_max_min_ratio': round(avg_ratio, 1),
    }


# ═══════════════════════════════════════════════════════════════════════
#  メイン
# ═══════════════════════════════════════════════════════════════════════
def main():
    db_slim, db_all, nobi_col = load_db()
    print("\n🔄 レースデータ事前計算中（Engine C 買い目選択含む）...")
    cache = prepare_races(db_slim, db_all, nobi_col)
    print(f"  キャッシュ完了: {len(cache)}レース")

    ALLOCATIONS = {
        '① UNIFORM (均等)':        alloc_uniform,
        '② EV_PROP (現行)':        alloc_ev_prop,
        '③ √EV':                   alloc_sqrt_ev,
        '④ log(1+EV)':             alloc_log_ev,
        '⑤ CAPPED ×2.0':          make_alloc_capped(2.0),
        '⑥ CAPPED ×2.5':          make_alloc_capped(2.5),
        '⑦ CAPPED ×3.0':          make_alloc_capped(3.0),
        '⑧ CAPPED ×4.0':          make_alloc_capped(4.0),
        '⑨ CAPPED ×5.0':          make_alloc_capped(5.0),
        '⑩ HALF_KELLY':            alloc_half_kelly,
    }

    print(f"\n{'='*80}")
    print(f"  資金配分方式 比較バックテスト（Engine C σ=0.90 ベース）")
    print(f"{'='*80}\n")

    results = []
    for label, fn in ALLOCATIONS.items():
        res = evaluate_alloc(cache, fn, label)
        medal = ""
        results.append({'label': label, **res})
        print(f"  {label:22s}  "
              f"Hits:{res['hits']:2d}  HR:{res['hr']:.1f}%  "
              f"Invest:¥{res['invest']:>7,}  Return:¥{res['ret']:>8,}  "
              f"ROI:{res['roi']:>6.1f}%  "
              f"Profit:{'+'if res['profit']>=0 else ''}¥{res['profit']:>8,}  "
              f"Max/Min:{res['avg_max_min_ratio']:.1f}x")

    # ランキング
    results.sort(key=lambda x: x['roi'], reverse=True)
    print(f"\n{'='*80}")
    print(f"  【ROI ランキング】")
    print(f"{'='*80}\n")
    for i, r in enumerate(results, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "  "
        print(f"  {medal} {i:2d}. {r['label']:22s}  ROI:{r['roi']:>6.1f}%  "
              f"Profit:{'+'if r['profit']>=0 else ''}¥{r['profit']:>8,}  "
              f"HR:{r['hr']:.1f}%  Max/Min:{r['avg_max_min_ratio']:.1f}x")

    # 的中レースの配分詳細（上位3方式について）
    print(f"\n{'='*80}")
    print(f"  【的中レースの配分比較】 上位3方式")
    print(f"{'='*80}\n")

    top3_fns = [(r['label'], ALLOCATIONS[r['label']]) for r in results[:3]]

    for race in cache:
        actual = race['actual']
        combos = [b['combo'] for b in race['bets_raw']]
        if actual not in combos:
            continue

        idx = combos.index(actual)
        payout = race['payout']

        details = []
        for label, fn in top3_fns:
            alloc = fn(race['bets_raw'])
            bet_amt = alloc[idx]
            ret = int(payout * bet_amt / 100)
            details.append(f"{label}:¥{bet_amt:,}→¥{ret:,}")

        print(f"  {race['race_dt'].date()} {race['venue']} {race['race_no']}R  "
              f"結果:{actual}  払戻{payout//10}倍")
        for d in details:
            print(f"    {d}")
        print()

    # CSV保存
    df = pd.DataFrame(results)
    df.to_csv("data/allocation_comparison.csv", index=False, encoding='utf-8-sig')
    print(f"💾 data/allocation_comparison.csv 保存完了")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
