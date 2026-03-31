"""
backtest_antigami_alloc.py
==========================
ガミらない配分（アンチガミ配分）の検証

各買い目に「的中時にレース投資総額を回収できる最低金額」を配分する。
低オッズ（ガミりやすい）買い目ほど多く賭け、
高オッズ（穴目）は最低¥100で良い。

方式:
  A) 現行 EV比例 14点
  B) アンチガミ 14点: 全点がガミらない最低配分
  C) アンチガミ 7点: 上位7点のみ
  D) アンチガミ + EV余剰配分: 最低保障後の余りをEV順で上乗せ
  E) ガミ点除外 + アンチガミ: EV<1.0の点を除外し、残りにアンチガミ配分

ベース: Engine C σ=0.90 / ev≥70 / chaos=N / low=Y (242R)
"""

import pandas as pd
import numpy as np
from backtest_model_comparison import (
    load_db, compute_player_scores, compute_raw_strengths,
    STRATEGY, BANK_DICT, BET_BASE,
)

NEST_SIGMA = 0.90
BET_UNIT = 100
FILTER = {'min_top_ev': 70, 'skip_chaos': False, 'skip_low_bank': True}


def engine_c_all_tri(all_nums, raw_s, odds_dict, num_to_line):
    sigma = NEST_SIGMA
    def _nests(members):
        nests = {}
        for n in members:
            ln = num_to_line.get(n, -n)
            if ln not in nests: nests[ln] = []
            nests[ln].append(n)
        return nests
    def nm(target, remaining):
        if not remaining: return 0.0
        nests = _nests(remaining)
        IV = {}
        for ln, ms in nests.items():
            inner = sum(raw_s[m]**(1.0/sigma) for m in ms)
            IV[ln] = inner**sigma if inner > 0 else 0.0
        total_IV = sum(IV.values())
        if total_IV == 0: return 0.0
        t_ln = num_to_line.get(target, -target)
        inner_d = sum(raw_s[m]**(1.0/sigma) for m in nests[t_ln])
        if inner_d == 0: return 0.0
        return (IV[t_ln]/total_IV) * (raw_s[target]**(1.0/sigma)) / inner_d
    def tri(f, s, t):
        p1 = nm(f, all_nums)
        if p1==0: return 0.0
        p2 = nm(s, [n for n in all_nums if n!=f])
        if p2==0: return 0.0
        p3 = nm(t, [n for n in all_nums if n not in (f,s)])
        return p1*p2*p3
    res = []
    for f in all_nums:
        for s in all_nums:
            if s==f: continue
            for t in all_nums:
                if t==f or t==s: continue
                c = f"{f}-{s}-{t}"
                if c not in odds_dict: continue
                p = tri(f,s,t)
                o = odds_dict[c]
                res.append({'combo':c,'prob':p,'odds':o,'ev':p*o})
    return res


def alloc_ev_prop(bets, n_max=14):
    sel = sorted(bets, key=lambda x: x['prob'], reverse=True)[:n_max]
    ev_vals = np.array([max(b['ev'],0) for b in sel])
    n = len(sel)
    total = BET_UNIT * n
    if ev_vals.sum()==0:
        alloc = [BET_UNIT]*n
    else:
        a = (ev_vals/ev_vals.sum())*total
        a100 = (a//BET_UNIT).astype(int)*BET_UNIT
        a100[int(np.argmax(ev_vals))] += (int(total-a100.sum())//BET_UNIT)*BET_UNIT
        alloc = [max(int(x),BET_UNIT) for x in a100]
    return [(b['combo'], amt, b) for b, amt in zip(sel, alloc)]


def alloc_antigami(bets, n_max=14):
    """アンチガミ配分: 各点の的中時にレース総投資以上のリターンを保障"""
    sel = sorted(bets, key=lambda x: x['prob'], reverse=True)[:n_max]
    n = len(sel)
    if n == 0: return []

    # 反復法: 総投資Iを仮定 → 各点の最低額を計算 → 合計がIになるまで反復
    for iteration in range(20):
        if iteration == 0:
            total_est = BET_UNIT * n  # 初期推定: 均等
        alloc = []
        for b in sel:
            # 的中時リターン = odds * bet_amt / 100 >= total_est
            # → bet_amt >= total_est * 100 / odds
            if b['odds'] > 0:
                min_amt = max(BET_UNIT, int(np.ceil(total_est * 100 / b['odds'] / BET_UNIT)) * BET_UNIT)
            else:
                min_amt = BET_UNIT
            alloc.append(min_amt)
        new_total = sum(alloc)
        if new_total == total_est:
            break
        total_est = new_total

    return [(b['combo'], amt, b) for b, amt in zip(sel, alloc)]


def alloc_antigami_ev_surplus(bets, n_max=14, surplus_budget=0):
    """アンチガミ最低保障 + EV順で余剰配分"""
    sel = sorted(bets, key=lambda x: x['prob'], reverse=True)[:n_max]
    n = len(sel)
    if n == 0: return []

    # まずアンチガミ最低額を計算
    total_est = BET_UNIT * n
    for _ in range(20):
        alloc = []
        for b in sel:
            if b['odds'] > 0:
                min_amt = max(BET_UNIT, int(np.ceil(total_est * 100 / b['odds'] / BET_UNIT)) * BET_UNIT)
            else:
                min_amt = BET_UNIT
            alloc.append(min_amt)
        new_total = sum(alloc)
        if new_total == total_est: break
        total_est = new_total

    # 余剰をEV上位に配分（任意の追加予算）
    if surplus_budget > 0:
        ev_order = sorted(range(n), key=lambda i: sel[i]['ev'], reverse=True)
        remaining = surplus_budget
        for i in ev_order:
            add = min(remaining, BET_UNIT * 3)  # 1点に最大300円追加
            alloc[i] += add
            remaining -= add
            if remaining <= 0: break

    return [(b['combo'], amt, b) for b, amt in zip(sel, alloc)]


def alloc_antigami_filtered(bets, n_max=14, min_ev=1.0):
    """EV<閾値の点を除外してからアンチガミ配分"""
    filtered = [b for b in bets if b['ev'] >= min_ev]
    if not filtered: filtered = bets[:3]  # 最低3点は残す
    return alloc_antigami(filtered, n_max)


def evaluate(cache, alloc_fn, label=''):
    hits=0; n=0; total_in=0; total_re=0; gami=0; hit_rets=[]
    per_race_invest = []

    for r in cache:
        result = alloc_fn(r['all_tri'])
        if not result: continue
        n += 1
        combos = [c for c,_,_ in result]
        invest = sum(a for _,a,_ in result)
        total_in += invest
        per_race_invest.append(invest)

        if r['actual'] in combos:
            idx = combos.index(r['actual'])
            bet_amt = result[idx][1]
            ret = int(r['payout'] * bet_amt / 100)
            total_re += ret
            hits += 1
            hit_rets.append(ret)
            if ret < invest: gami += 1

    roi = total_re/total_in*100 if total_in>0 else 0
    hr = hits/n*100 if n>0 else 0
    gr = gami/hits*100 if hits>0 else 0
    profit = total_re - total_in
    avg_invest = np.mean(per_race_invest) if per_race_invest else 0

    sorted_rets = sorted(hit_rets, reverse=True)
    roi_ex1 = (total_re - sorted_rets[0])/total_in*100 if sorted_rets else 0

    return {'n':n, 'hits':hits, 'hr':hr, 'roi':roi, 'profit':profit,
            'gami':gami, 'gami_rate':gr, 'roi_ex1':roi_ex1,
            'avg_invest':avg_invest, 'avg_bets':len(result) if result else 0}


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

    print("🔄 全レース事前計算中...")
    cache = []
    for race_id, rc_group in rc_df.groupby('race_id'):
        if s_race_ids and race_id not in s_race_ids: continue
        venue = rc_group.iloc[0]['venue']
        race_dt = rc_group.iloc[0]['date']
        if pd.isna(race_dt): continue
        lines_df = rc_group[['line_no','車番']].dropna()
        if lines_df.empty: continue
        od_race = od_df[od_df['race_id']==race_id]
        odds_dict = {str(r['組み合わせ']).strip(): float(r['オッズ']) for _,r in od_race.iterrows() if pd.notna(r['オッズ'])}
        py_race = py_df[py_df['race_id']==race_id]
        if py_race.empty: continue
        actual = str(py_race.iloc[0].get('result_trifecta','')).strip().replace('="','').replace('"','')
        payout = py_race.iloc[0].get('payout_trifecta',0)
        try: payout = int(str(payout).replace(',',''))
        except: payout = 0

        ps, ntl, lm = compute_player_scores(venue, rc_group, lines_df, db_slim, db_all, nobi_col, race_dt)
        ranked = sorted(ps.items(), key=lambda x: x[1]['ev'], reverse=True)
        if len(ranked)<3: continue
        all_nums, raw_s = compute_raw_strengths(ps, ranked)
        bp = BANK_DICT.get(venue, {'roi_tier':'mid','sashi':1.0,'makuri':1.0})
        top_ev = ranked[0][1]['ev']
        strong_leaders = [n for n,d in ps.items() if d['ip']>=5.5 and lm.get(ntl.get(n,0),[None])[0]==n]
        is_chaos = len(strong_leaders)>=2
        if FILTER['skip_low_bank'] and bp['roi_tier']=='low': continue
        if FILTER['min_top_ev']>0 and top_ev<FILTER['min_top_ev']: continue
        if FILTER['skip_chaos'] and is_chaos: continue

        all_tri = engine_c_all_tri(all_nums, raw_s, odds_dict, ntl)
        if not all_tri: continue

        cache.append({'race_id':race_id, 'venue':venue, 'all_tri':all_tri,
                       'actual':actual, 'payout':payout})

    print(f"  キャッシュ完了: {len(cache)}R\n")

    # テストパターン
    patterns = [
        ('A) EV比例 14点 (現行)',       lambda tri: alloc_ev_prop(tri, 14)),
        ('B) EV比例 7点',              lambda tri: alloc_ev_prop(tri, 7)),
        ('C) アンチガミ 14点',         lambda tri: alloc_antigami(tri, 14)),
        ('D) アンチガミ 10点',         lambda tri: alloc_antigami(tri, 10)),
        ('E) アンチガミ 7点',          lambda tri: alloc_antigami(tri, 7)),
        ('F) アンチガミ 5点',          lambda tri: alloc_antigami(tri, 5)),
        ('G) アンチガミ+EV余剰 7点',   lambda tri: alloc_antigami_ev_surplus(tri, 7, 300)),
        ('H) EV≥1.0除外+アンチガミ',   lambda tri: alloc_antigami_filtered(tri, 14, 1.0)),
        ('I) EV≥0.5除外+アンチガミ',   lambda tri: alloc_antigami_filtered(tri, 14, 0.5)),
    ]

    print(f"{'='*95}")
    print(f"  アンチガミ配分 比較バックテスト")
    print(f"{'='*95}\n")

    results = []
    for label, fn in patterns:
        r = evaluate(cache, fn, label)
        results.append({'label': label, **r})
        sign = "+" if r['profit']>=0 else ""
        stable = "★" if r['roi_ex1']>=100 else " "
        print(f" {stable}{label:30s}  R:{r['n']:3d}  Hit:{r['hits']:2d} ({r['hr']:.1f}%)  "
              f"ROI:{r['roi']:.1f}%  {sign}¥{r['profit']:>+8,}  "
              f"ガミ:{r['gami_rate']:.0f}% ({r['gami']}/{r['hits']})  "
              f"Ex1:{r['roi_ex1']:.1f}%  1R平均:¥{r['avg_invest']:.0f}")

    # CSV保存
    df = pd.DataFrame(results)
    df.to_csv("data/antigami_comparison.csv", index=False, encoding='utf-8-sig')
    print(f"\n💾 data/antigami_comparison.csv 保存完了")
    print(f"{'='*95}")


if __name__ == "__main__":
    main()
