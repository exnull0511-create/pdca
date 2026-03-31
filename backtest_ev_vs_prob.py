"""
backtest_ev_vs_prob.py
======================
確率順 vs EV順 の買い目選択比較バックテスト

パターン:
  A) 確率順 Top14 + フィルタ有 (現行)
  B) EV順   Top14 + フィルタ有
  C) 確率順 Top14 + フィルタ無 (全レース対象)
  D) EV順   Top14 + フィルタ無 (全レース対象)

使い方:
  python backtest_ev_vs_prob.py
"""

import pandas as pd
import numpy as np
from backtest_model_comparison import (
    load_db, compute_player_scores, common_filter, compute_raw_strengths,
    allocate_bets, STRATEGY, BET_BASE, BANK_DICT, LOW_BANK,
)

NEST_SIGMA = 0.90


def engine_c_select(all_nums, raw_s, odds_dict, num_to_line, sort_by='prob'):
    """Engine C (Nested Logit) で買い目を選択。sort_by='prob' or 'ev'"""
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
                ev = p * o
                all_data.append((ev, combo, p, o))

    # ソートキーの切り替え
    if sort_by == 'ev':
        selected = sorted(all_data, key=lambda x: x[0], reverse=True)[:STRATEGY['top_n_prob_bets']]
    else:
        selected = sorted(all_data, key=lambda x: x[2], reverse=True)[:STRATEGY['top_n_prob_bets']]

    if not selected:
        return None
    ev_lookup = {c: ev for ev, c, p, o in all_data}
    bets, total = allocate_bets(selected, ev_lookup)
    return {'bets': bets, 'total': total}


def main():
    db_slim, db_all, nobi_col = load_db()

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

    # 全レースを事前計算
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
        ranked = sorted(ps.items(), key=lambda x: x[1]['ev'], reverse=True)
        if len(ranked) < 3: continue
        all_nums, raw_s = compute_raw_strengths(ps, ranked)

        # フィルタ情報
        bp = BANK_DICT.get(venue, {'roi_tier':'mid','sashi':1.0,'makuri':1.0})
        low_bank = bp['roi_tier'] == 'low'
        top_ev = ranked[0][1]['ev']
        strong_leaders = [n for n, d in ps.items()
                          if d['ip'] >= 5.5 and lm.get(ntl.get(n, 0), [None])[0] == n]
        is_chaos = len(strong_leaders) >= 2
        low_ev = top_ev < STRATEGY['min_top_ev']
        passes_filter = not (low_bank or low_ev or (is_chaos and STRATEGY['skip_chaos']))

        cache.append({
            'race_id': race_id, 'venue': venue,
            'race_no': int(rc_group.iloc[0]['race_no']),
            'all_nums': all_nums, 'raw_s': raw_s, 'odds_dict': odds_dict,
            'num_to_line': ntl, 'line_map': lm,
            'actual': actual, 'payout': payout,
            'passes_filter': passes_filter, 'top_ev': top_ev,
        })

    print(f"\n全レース: {len(cache)}R (フィルタ通過: {sum(1 for c in cache if c['passes_filter'])}R)")

    # 4パターン実行
    patterns = [
        ('A) 確率順 + フィルタ有 (現行)', 'prob', True),
        ('B) EV順   + フィルタ有',        'ev',   True),
        ('C) 確率順 + フィルタ無',        'prob', False),
        ('D) EV順   + フィルタ無',        'ev',   False),
    ]

    print(f"\n{'='*85}")
    print(f"  確率順 vs EV順 × フィルタ有無  比較バックテスト")
    print(f"{'='*85}\n")

    all_results = {}
    for label, sort_by, use_filter in patterns:
        hits = 0; n = 0; total_in = 0; total_re = 0
        gami = 0  # 的中したが投資額を回収できなかったケース
        max_ret = 0; hit_returns = []

        for r in cache:
            if use_filter and not r['passes_filter']:
                continue
            pred = engine_c_select(r['all_nums'], r['raw_s'], r['odds_dict'],
                                   r['num_to_line'], sort_by=sort_by)
            if pred is None: continue
            n += 1
            combos = [c for c, _ in pred['bets']]
            total_in += pred['total']
            if r['actual'] in combos:
                idx = combos.index(r['actual'])
                bet_amt = pred['bets'][idx][1]
                ret = int(r['payout'] * bet_amt / 100)
                total_re += ret
                hits += 1
                hit_returns.append(ret)
                if ret < pred['total']:
                    gami += 1
                if ret > max_ret:
                    max_ret = ret

        roi = total_re / total_in * 100 if total_in > 0 else 0
        hr = hits / n * 100 if n > 0 else 0
        gami_rate = gami / hits * 100 if hits > 0 else 0

        # 大穴依存度: Top1除外時のROI
        if hit_returns:
            sorted_rets = sorted(hit_returns, reverse=True)
            top1_ret = sorted_rets[0]
            roi_ex_top1 = (total_re - top1_ret) / (total_in - 0) * 100  # 投資は変わらない想定
        else:
            roi_ex_top1 = 0

        # 的中時の平均オッズ
        avg_hit_ret = np.mean(hit_returns) if hit_returns else 0
        median_hit_ret = np.median(hit_returns) if hit_returns else 0

        all_results[label] = {
            'n': n, 'hits': hits, 'hr': hr, 'invest': total_in,
            'ret': total_re, 'profit': total_re - total_in, 'roi': roi,
            'gami': gami, 'gami_rate': gami_rate,
            'max_ret': max_ret, 'avg_hit_ret': avg_hit_ret,
            'median_hit_ret': median_hit_ret,
            'roi_ex_top1': roi_ex_top1,
        }

        sign = "+" if total_re - total_in >= 0 else ""
        print(f"  {label}")
        print(f"    Races:{n:3d}  Hits:{hits:2d} ({hr:.1f}%)  "
              f"ROI:{roi:.1f}%  収支:{sign}¥{total_re-total_in:,}")
        print(f"    ガミ率:{gami_rate:.0f}% ({gami}/{hits})  "
              f"中央値:¥{median_hit_ret:,.0f}  平均:¥{avg_hit_ret:,.0f}  "
              f"最大:¥{max_ret:,}")
        print(f"    Top1除外ROI:{roi_ex_top1:.1f}%  (大穴依存度)")
        print()

    # 比較テーブル
    print(f"{'='*85}")
    print(f"  【まとめ】")
    print(f"{'='*85}\n")
    print(f"  {'パターン':30s}  {'R数':>4s} {'的中':>4s} {'HR%':>5s} {'ROI%':>7s} {'ガミ率':>6s} {'中央値':>8s} {'Top1除外':>8s}")
    print(f"  {'-'*75}")
    for label, r in all_results.items():
        print(f"  {label:30s}  {r['n']:4d} {r['hits']:4d} {r['hr']:5.1f} {r['roi']:7.1f} "
              f"{r['gami_rate']:5.0f}% ¥{r['median_hit_ret']:>7,.0f} {r['roi_ex_top1']:7.1f}%")

    # CSV保存
    df = pd.DataFrame([{'pattern': k, **v} for k, v in all_results.items()])
    df.to_csv("data/ev_vs_prob_comparison.csv", index=False, encoding='utf-8-sig')
    print(f"\n💾 data/ev_vs_prob_comparison.csv 保存完了")


if __name__ == "__main__":
    main()
