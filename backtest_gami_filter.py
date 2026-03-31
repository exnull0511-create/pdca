"""
backtest_gami_filter.py
=======================
ガミ買い目除外の検証

「確率×オッズ(=EV) が閾値未満の買い目は買わない」戦略をテスト。
ベース設定: Engine C (σ=0.90) / ev≥70 / chaos=N / low=Y

テストパターン:
  - min_bet_ev = [0(現行), 0.5, 0.8, 1.0, 1.2, 1.5, 2.0]
  - 買い目数制限: [上限なし, 最大10点, 最大7点, 最大5点]

使い方:
  python backtest_gami_filter.py
"""

import pandas as pd
import numpy as np
from itertools import product
from backtest_model_comparison import (
    load_db, compute_player_scores, compute_raw_strengths,
    STRATEGY, BANK_DICT, BET_BASE,
)

NEST_SIGMA = 0.90
BET_UNIT = 100

# 推奨フィルタ設定
FILTER = {'min_top_ev': 70, 'skip_chaos': False, 'skip_low_bank': True}


def engine_c_all_trifectas(all_nums, raw_s, odds_dict, num_to_line):
    """Engine C で全3連単の (ev, combo, prob, odds) を返す"""
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
        return nest_p * (raw_s[target] ** (1.0 / sigma)) / inner_d

    def nested_tri(f, s, t):
        p1 = nested_marginal(f, all_nums)
        if p1 == 0: return 0.0
        p2 = nested_marginal(s, [n for n in all_nums if n != f])
        if p2 == 0: return 0.0
        p3 = nested_marginal(t, [n for n in all_nums if n not in (f, s)])
        return p1 * p2 * p3

    results = []
    for f in all_nums:
        for s in all_nums:
            if s == f: continue
            for t in all_nums:
                if t == f or t == s: continue
                combo = f"{f}-{s}-{t}"
                if combo not in odds_dict: continue
                p = nested_tri(f, s, t)
                o = odds_dict[combo]
                results.append((p * o, combo, p, o))
    return results


def allocate_ev_prop(bets_info, total_budget):
    """EV比例配分"""
    ev_vals = np.array([b['ev'] for b in bets_info])
    ev_vals = np.maximum(ev_vals, 0.0)
    n = len(bets_info)
    if n == 0: return []
    if ev_vals.sum() == 0:
        return [BET_UNIT] * n
    a = (ev_vals / ev_vals.sum()) * total_budget
    a100 = (a // BET_UNIT).astype(int) * BET_UNIT
    a100[int(np.argmax(ev_vals))] += (int(total_budget - a100.sum()) // BET_UNIT) * BET_UNIT
    return [max(int(x), BET_UNIT) for x in a100]


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
        if s_race_ids and race_id not in s_race_ids: continue
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

        # フィルタ判定
        bp = BANK_DICT.get(venue, {'roi_tier': 'mid', 'sashi': 1.0, 'makuri': 1.0})
        top_ev = ranked[0][1]['ev']
        strong_leaders = [n for n, d in ps.items()
                          if d['ip'] >= 5.5 and lm.get(ntl.get(n, 0), [None])[0] == n]
        is_chaos = len(strong_leaders) >= 2
        is_low_bank = bp['roi_tier'] == 'low'

        # 推奨フィルタ適用
        if FILTER['skip_low_bank'] and is_low_bank: continue
        if FILTER['min_top_ev'] > 0 and top_ev < FILTER['min_top_ev']: continue
        if FILTER['skip_chaos'] and is_chaos: continue

        # 全3連単の確率・EV計算
        all_tri = engine_c_all_trifectas(all_nums, raw_s, odds_dict, ntl)
        if not all_tri: continue

        cache.append({
            'race_id': race_id, 'venue': venue,
            'race_no': int(rc_group.iloc[0]['race_no']),
            'all_tri': all_tri,  # [(ev, combo, prob, odds), ...]
            'actual': actual, 'payout': payout,
        })

    print(f"  キャッシュ完了: {len(cache)}R\n")

    # ── ガミ除外パターンのグリッドサーチ ────────────────────────────────
    MIN_BET_EV = [0, 0.3, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0]
    MAX_BETS   = [14, 10, 7, 5]
    SORT_KEYS  = ['prob', 'ev']

    combos = list(product(SORT_KEYS, MIN_BET_EV, MAX_BETS))

    print(f"{'='*95}")
    print(f"  ガミ買い目除外 グリッドサーチ ({len(combos)}パターン)")
    print(f"  ベース: ev≥{FILTER['min_top_ev']} / chaos={'N' if not FILTER['skip_chaos'] else 'Y'} / low={'Y' if FILTER['skip_low_bank'] else 'N'}")
    print(f"{'='*95}\n")

    results = []
    for sort_key, min_ev, max_n in combos:
        hits = 0; n = 0; total_in = 0; total_re = 0
        gami = 0; skipped = 0
        hit_rets = []

        for r in cache:
            all_tri = r['all_tri']

            # ソート & 選択
            if sort_key == 'ev':
                sorted_tri = sorted(all_tri, key=lambda x: x[0], reverse=True)
            else:
                sorted_tri = sorted(all_tri, key=lambda x: x[2], reverse=True)

            # EVフィルタ適用
            filtered = [(ev, c, p, o) for ev, c, p, o in sorted_tri if ev >= min_ev]

            # 上限制限
            selected = filtered[:max_n]

            if not selected:
                skipped += 1
                continue

            # 配分
            bets_info = [{'combo': c, 'ev': ev, 'prob': p, 'odds': o}
                         for ev, c, p, o in selected]
            total_budget = BET_UNIT * len(bets_info)
            alloc = allocate_ev_prop(bets_info, total_budget)
            combos_list = [b['combo'] for b in bets_info]

            n += 1
            invest = sum(alloc)
            total_in += invest

            if r['actual'] in combos_list:
                idx = combos_list.index(r['actual'])
                bet_amt = alloc[idx]
                ret = int(r['payout'] * bet_amt / 100)
                total_re += ret
                hits += 1
                hit_rets.append(ret)
                if ret < invest:
                    gami += 1

        if n == 0: continue

        roi = total_re / total_in * 100 if total_in > 0 else 0
        hr = hits / n * 100 if n > 0 else 0
        gami_rate = gami / hits * 100 if hits > 0 else 0
        profit = total_re - total_in

        # 大穴依存度
        sorted_rets = sorted(hit_rets, reverse=True)
        roi_ex1 = (total_re - sorted_rets[0]) / total_in * 100 if sorted_rets else 0
        roi_ex3 = (total_re - sum(sorted_rets[:3])) / total_in * 100 if len(sorted_rets) >= 3 else 0

        avg_bets = total_in / BET_UNIT / n if n > 0 else 0  # 平均買い目数

        results.append({
            'sort': sort_key, 'min_ev': min_ev, 'max_n': max_n,
            'n': n, 'hits': hits, 'hr': hr, 'roi': roi,
            'profit': profit, 'gami_rate': gami_rate,
            'roi_ex1': roi_ex1, 'avg_bets': avg_bets,
            'skipped': skipped,
        })

    # ROI順ソート
    results.sort(key=lambda x: x['profit'], reverse=True)

    print(f"  {'sort':>4s} {'minEV':>5s} {'max':>3s}  {'R':>3s} {'Hit':>3s} {'HR%':>5s}"
          f" {'ROI%':>7s} {'収支':>10s} {'ガミ率':>5s} {'Ex1':>6s} {'avg点':>5s} {'skip':>4s}")
    print(f"  {'-'*80}")

    for r in results[:30]:
        sign = "+" if r['profit'] >= 0 else ""
        tag = " ◄現行" if (r['sort'] == 'prob' and r['min_ev'] == 0 and r['max_n'] == 14) else ""
        stable = "★" if r['roi_ex1'] >= 100 else " "
        print(f" {stable}{r['sort']:>4s} {r['min_ev']:>5.1f} {r['max_n']:>3d}  "
              f"{r['n']:3d} {r['hits']:3d} {r['hr']:5.1f} {r['roi']:7.1f} "
              f"{sign}{r['profit']:>+8,} {r['gami_rate']:4.0f}% "
              f"{r['roi_ex1']:6.1f} {r['avg_bets']:5.1f} {r['skipped']:4d}{tag}")

    # 安定+利益のベスト
    print(f"\n{'='*95}")
    print(f"  【推奨候補】 Top1除外ROI≥100% & 利益上位")
    print(f"{'='*95}\n")

    stable_profitable = [r for r in results if r['roi_ex1'] >= 100]
    stable_profitable.sort(key=lambda x: x['profit'], reverse=True)

    for r in stable_profitable[:10]:
        sign = "+" if r['profit'] >= 0 else ""
        print(f"  sort={r['sort']:4s}  minEV={r['min_ev']:.1f}  max={r['max_n']:2d}点  "
              f"R:{r['n']:3d}  Hit:{r['hits']:3d} ({r['hr']:.1f}%)  "
              f"ROI:{r['roi']:.1f}%  Ex1:{r['roi_ex1']:.1f}%  "
              f"Profit:{sign}¥{r['profit']:,}  ガミ:{r['gami_rate']:.0f}%  "
              f"平均{r['avg_bets']:.1f}点")

    # CSV保存
    df = pd.DataFrame(results)
    df.to_csv("data/gami_filter_results.csv", index=False, encoding='utf-8-sig')
    print(f"\n💾 data/gami_filter_results.csv 保存完了")
    print(f"{'='*95}")


if __name__ == "__main__":
    main()
