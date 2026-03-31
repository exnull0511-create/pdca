"""
backtest_filter_search.py
=========================
フィルタ閾値のグリッドサーチ

489R全データで以下のパラメータを変動させ、
ROI / 的中率 / ガミ率 / 大穴依存度(Top1除外ROI) のバランスが最も良い設定を探す。

パラメータ:
  - min_top_ev    : [0(無効), 40, 50, 55, 60(現行), 65, 70]
  - skip_chaos    : [True(現行), False]
  - skip_low_bank : [True(現行), False]

使い方:
  python backtest_filter_search.py
"""

import pandas as pd
import numpy as np
from itertools import product
from backtest_model_comparison import (
    load_db, compute_player_scores, compute_raw_strengths,
    allocate_bets, STRATEGY, BANK_DICT,
)

NEST_SIGMA = 0.90


def engine_c_predict(all_nums, raw_s, odds_dict, num_to_line):
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
        return (nest_p * (raw_s[target] ** (1.0 / sigma)) / inner_d)

    def nested_tri(f, s, t):
        p1 = nested_marginal(f, all_nums)
        if p1 == 0: return 0.0
        p2 = nested_marginal(s, [n for n in all_nums if n != f])
        if p2 == 0: return 0.0
        p3 = nested_marginal(t, [n for n in all_nums if n not in (f, s)])
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
                all_data.append((p * o, combo, p, o))

    selected = sorted(all_data, key=lambda x: x[2], reverse=True)[:STRATEGY['top_n_prob_bets']]
    if not selected: return None
    ev_lookup = {c: ev for ev, c, p, o in all_data}
    bets, total = allocate_bets(selected, ev_lookup)
    return {'bets': bets, 'total': total, 'combos': [c for c, _ in bets]}


def main():
    db_slim, db_all, nobi_col = load_db()

    rc_df = pd.read_excel("data/racecard.xlsx")
    od_df = pd.read_excel("data/odds.xlsx")
    py_df = pd.read_excel("data/payouts.xlsx")
    rc_df['date'] = pd.to_datetime(rc_df['date'].astype(str).str.strip(),
                                    format='%Y%m%d', errors='coerce')

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

    # ── 全レース事前計算 ────────────────────────────────────────────────
    print("🔄 全レース事前計算中...")
    cache = []
    for race_id, rc_group in rc_df.groupby('race_id'):
        if s_race_ids and race_id not in s_race_ids:
            continue
        venue = rc_group.iloc[0]['venue']
        race_dt = rc_group.iloc[0]['date']
        if pd.isna(race_dt): continue
        lines_df = rc_group[['line_no', '車番']].dropna()
        if lines_df.empty: continue

        od_race = od_df[od_df['race_id'] == race_id]
        odds_dict = {str(r['組み合わせ']).strip(): float(r['オッズ'])
                     for _, r in od_race.iterrows() if pd.notna(r['オッズ'])}
        py_race = py_df[py_df['race_id'] == race_id]
        if py_race.empty: continue
        actual = str(py_race.iloc[0].get('result_trifecta', '')).strip().replace('="', '').replace('"', '')
        payout = py_race.iloc[0].get('payout_trifecta', 0)
        try: payout = int(str(payout).replace(',', ''))
        except: payout = 0

        ps, ntl, lm = compute_player_scores(venue, rc_group, lines_df,
                                              db_slim, db_all, nobi_col, race_dt)
        ranked = sorted(ps.items(), key=lambda x: x[1]['ev'], reverse=True)
        if len(ranked) < 3: continue
        all_nums, raw_s = compute_raw_strengths(ps, ranked)

        # フィルタ情報を事前計算
        bp = BANK_DICT.get(venue, {'roi_tier': 'mid', 'sashi': 1.0, 'makuri': 1.0})
        top_ev = ranked[0][1]['ev']
        strong_leaders = [n for n, d in ps.items()
                          if d['ip'] >= 5.5 and lm.get(ntl.get(n, 0), [None])[0] == n]
        is_chaos = len(strong_leaders) >= 2
        is_low_bank = bp['roi_tier'] == 'low'

        # 予測結果を事前計算（フィルタに関係なく共通）
        pred = engine_c_predict(all_nums, raw_s, odds_dict, ntl)
        if pred is None: continue

        combos = pred['combos']
        hit = actual in combos
        if hit:
            idx = combos.index(actual)
            bet_amt = pred['bets'][idx][1]
            ret = int(payout * bet_amt / 100)
        else:
            ret = 0

        cache.append({
            'race_id': race_id, 'venue': venue,
            'top_ev': top_ev, 'is_chaos': is_chaos,
            'is_low_bank': is_low_bank,
            'invest': pred['total'], 'hit': hit, 'ret': ret,
        })

    print(f"  キャッシュ完了: {len(cache)}R\n")

    # ── グリッドサーチ ──────────────────────────────────────────────────
    MIN_TOP_EV_VALS  = [0, 40, 45, 50, 55, 60, 65, 70]
    SKIP_CHAOS_VALS  = [True, False]
    SKIP_LOW_VALS    = [True, False]

    grid = list(product(MIN_TOP_EV_VALS, SKIP_CHAOS_VALS, SKIP_LOW_VALS))
    print(f"{'='*90}")
    print(f"  フィルタ グリッドサーチ ({len(grid)}パターン)")
    print(f"{'='*90}\n")

    results = []
    for min_ev, skip_chaos, skip_low in grid:
        races = []
        for r in cache:
            # フィルタ適用
            if skip_low and r['is_low_bank']:
                continue
            if min_ev > 0 and r['top_ev'] < min_ev:
                continue
            if skip_chaos and r['is_chaos']:
                continue
            races.append(r)

        n = len(races)
        if n == 0:
            continue
        hits = sum(1 for r in races if r['hit'])
        total_in = sum(r['invest'] for r in races)
        total_re = sum(r['ret'] for r in races)
        hit_rets = sorted([r['ret'] for r in races if r['hit']], reverse=True)

        roi = total_re / total_in * 100 if total_in > 0 else 0
        hr = hits / n * 100 if n > 0 else 0
        profit = total_re - total_in

        # ガミ率
        gami = sum(1 for r in races if r['hit'] and r['ret'] < r['invest'])
        gami_rate = gami / hits * 100 if hits > 0 else 0

        # 大穴依存度: Top1除外ROI
        if hit_rets:
            roi_ex1 = (total_re - hit_rets[0]) / total_in * 100
        else:
            roi_ex1 = 0

        # Top3除外ROI
        if len(hit_rets) >= 3:
            roi_ex3 = (total_re - sum(hit_rets[:3])) / total_in * 100
        else:
            roi_ex3 = 0

        # スコア: ROI × 安定性（Top1除外ROIとの乖離が小さいほど安定）
        stability = roi_ex1 / roi * 100 if roi > 0 else 0

        results.append({
            'min_ev': min_ev, 'skip_chaos': skip_chaos,
            'skip_low': skip_low,
            'n': n, 'hits': hits, 'hr': hr, 'roi': roi,
            'profit': profit, 'gami_rate': gami_rate,
            'roi_ex1': roi_ex1, 'roi_ex3': roi_ex3,
            'stability': stability,
        })

    # ROI順ソート
    results.sort(key=lambda x: x['roi'], reverse=True)

    print(f"  {'min_ev':>6s} {'chaos':>5s} {'lowB':>5s}  {'R数':>4s} {'的中':>4s}"
          f" {'HR%':>5s} {'ROI%':>7s} {'収支':>10s} {'ガミ率':>5s}"
          f" {'ExTop1':>7s} {'ExTop3':>7s} {'安定度':>6s}")
    print(f"  {'-'*85}")

    for r in results[:25]:  # Top25のみ表示
        sign = "+" if r['profit'] >= 0 else ""
        chaos_s = "Yes" if r['skip_chaos'] else "No"
        low_s = "Yes" if r['skip_low'] else "No"
        current = " ◄現行" if (r['min_ev'] == 60 and r['skip_chaos'] and r['skip_low']) else ""
        print(f"  {r['min_ev']:>6d} {chaos_s:>5s} {low_s:>5s}  "
              f"{r['n']:4d} {r['hits']:4d} {r['hr']:5.1f} {r['roi']:7.1f} "
              f"{sign}¥{r['profit']:>8,} {r['gami_rate']:4.0f}% "
              f"{r['roi_ex1']:7.1f} {r['roi_ex3']:7.1f} {r['stability']:5.1f}%{current}")

    # 安定度スコア（Top1除外でも100%超）でフィルタ
    print(f"\n{'='*90}")
    print(f"  【Top1除外でもROI 100%超のパターン】 (安定して勝てる設定)")
    print(f"{'='*90}\n")

    stable = [r for r in results if r['roi_ex1'] >= 100]
    stable.sort(key=lambda x: x['profit'], reverse=True)

    for r in stable:
        sign = "+" if r['profit'] >= 0 else ""
        chaos_s = "Yes" if r['skip_chaos'] else "No"
        low_s = "Yes" if r['skip_low'] else "No"
        current = " ◄現行" if (r['min_ev'] == 60 and r['skip_chaos'] and r['skip_low']) else ""
        print(f"  ev≥{r['min_ev']:2d}  chaos={chaos_s:3s}  low={low_s:3s}  "
              f"R:{r['n']:3d}  Hit:{r['hits']:3d} ({r['hr']:.1f}%)  "
              f"ROI:{r['roi']:.1f}%  ExTop1:{r['roi_ex1']:.1f}%  "
              f"Profit:{sign}¥{r['profit']:,}  ガミ:{r['gami_rate']:.0f}%{current}")

    # CSV保存
    df = pd.DataFrame(results)
    df.to_csv("data/filter_search_results.csv", index=False, encoding='utf-8-sig')
    print(f"\n💾 data/filter_search_results.csv 保存完了")
    print(f"{'='*90}")


if __name__ == "__main__":
    main()
