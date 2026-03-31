"""
backtest_antigami_v2.py
=======================
アンチガミ配分 v2: 固定予算方式

方針: 1レースの予算を固定（例: ¥1,400 = 14点×¥100）し、
その予算内で「的中時にガミらない最低額」を各点に配分。
予算が足りない低オッズ点は除外して残りで再配分。

アルゴリズム:
  1. 確率Top N を選択
  2. 各点に min_amt = ceil(budget * 100 / odds / 100) * 100 を計算
  3. sum(min_amt) > budget なら、最もオッズが低い点を除外
  4. 2-3を繰り返して収まるまで
  5. 余剰をEV上位に配分

ベース: Engine C σ=0.90 / ev≥70 / chaos=N / low=Y (242R)
"""

import pandas as pd
import numpy as np
from backtest_model_comparison import (
    load_db, compute_player_scores, compute_raw_strengths,
    STRATEGY, BANK_DICT,
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
                p = tri(f,s,t); o = odds_dict[c]
                res.append({'combo':c,'prob':p,'odds':o,'ev':p*o})
    return res


def alloc_ev_prop(bets, n_max=14, budget=None):
    sel = sorted(bets, key=lambda x: x['prob'], reverse=True)[:n_max]
    n = len(sel)
    if budget is None:
        budget = BET_UNIT * n
    ev_vals = np.array([max(b['ev'],0) for b in sel])
    if ev_vals.sum()==0:
        alloc = [BET_UNIT]*n
    else:
        a = (ev_vals/ev_vals.sum())*budget
        a100 = (a//BET_UNIT).astype(int)*BET_UNIT
        a100[int(np.argmax(ev_vals))] += (int(budget-a100.sum())//BET_UNIT)*BET_UNIT
        alloc = [max(int(x),BET_UNIT) for x in a100]
    return [(b['combo'],amt,b) for b,amt in zip(sel,alloc)], sum(alloc)


def alloc_antigami_fixed_budget(bets, n_max=14, budget_per_point=100):
    """固定予算内でアンチガミ配分"""
    sel = sorted(bets, key=lambda x: x['prob'], reverse=True)[:n_max]
    budget = budget_per_point * len(sel)

    # 各点の「ガミらない最低額」を計算
    # 的中時リターン = odds * bet / 100 >= budget
    # bet >= budget * 100 / odds
    candidates = []
    for b in sel:
        min_amt = max(BET_UNIT, int(np.ceil(budget * 100 / b['odds'] / BET_UNIT)) * BET_UNIT)
        candidates.append((b, min_amt))

    # 予算オーバーなら低オッズ（=高コスト）の点を除外
    while sum(m for _,m in candidates) > budget and len(candidates) > 1:
        # 最もオッズが低い（=最もコストが高い）点を除外
        worst_idx = min(range(len(candidates)), key=lambda i: candidates[i][0]['odds'])
        candidates.pop(worst_idx)
        # 予算を減らした点数に合わせて再計算
        budget = budget_per_point * (n_max)  # 元の予算は維持（除外した分が余る）
        for i, (b, _) in enumerate(candidates):
            candidates[i] = (b, max(BET_UNIT, int(np.ceil(budget * 100 / b['odds'] / BET_UNIT)) * BET_UNIT))

    # 余剰をEV上位に配分
    total_min = sum(m for _,m in candidates)
    surplus = budget - total_min
    if surplus > 0:
        ev_order = sorted(range(len(candidates)), key=lambda i: candidates[i][0]['ev'], reverse=True)
        for i in ev_order:
            add = min(surplus, BET_UNIT)
            b, cur = candidates[i]
            candidates[i] = (b, cur + add)
            surplus -= add
            if surplus <= 0: break

    result = [(b['combo'], amt, b) for b, amt in candidates]
    return result, sum(amt for _,amt,_ in result)


def alloc_antigami_smart(bets, n_max=14, budget_per_point=100):
    """スマートアンチガミ: 低オッズ除外ではなく、ガミる点は最低額(¥100)にして残りをアンチガミ配分"""
    sel = sorted(bets, key=lambda x: x['prob'], reverse=True)[:n_max]
    budget = budget_per_point * n_max  # 固定予算

    alloc = []
    for b in sel:
        # この点が的中した場合、¥100賭けで budget を回収できるか?
        ret_at_100 = int(b['odds'] * BET_UNIT / 100)
        if ret_at_100 >= budget:
            # 高オッズ: ¥100で十分ガミらない
            alloc.append((b, BET_UNIT))
        else:
            # 低オッズ: ガミらない最低額を計算
            min_amt = max(BET_UNIT, int(np.ceil(budget * 100 / b['odds'] / BET_UNIT)) * BET_UNIT)
            if min_amt > budget * 0.5:
                # 予算の半分以上を1点に使うのは危険 → 最低額(¥100)で妥協
                alloc.append((b, BET_UNIT))
            else:
                alloc.append((b, min_amt))

    # 合計が予算を超えたら高コスト点を¥100に戻す
    total = sum(a for _,a in alloc)
    while total > budget:
        # 最もコストが高い（¥100より多い）点を¥100に戻す
        reduce_candidates = [(i, a) for i, (b,a) in enumerate(alloc) if a > BET_UNIT]
        if not reduce_candidates: break
        worst = max(reduce_candidates, key=lambda x: x[1])
        b, _ = alloc[worst[0]]
        alloc[worst[0]] = (b, BET_UNIT)
        total = sum(a for _,a in alloc)

    # 余剰をEV上位に配分
    surplus = budget - sum(a for _,a in alloc)
    if surplus > 0:
        ev_order = sorted(range(len(alloc)), key=lambda i: alloc[i][0]['ev'], reverse=True)
        for i in ev_order:
            add = min(surplus, BET_UNIT)
            b, cur = alloc[i]
            alloc[i] = (b, cur + add)
            surplus -= add
            if surplus <= 0: break

    result = [(b['combo'], amt, b) for b, amt in alloc]
    return result, sum(amt for _,amt,_ in result)


def evaluate(cache, alloc_fn, label=''):
    hits=0; n=0; total_in=0; total_re=0; gami=0; hit_rets=[]; n_bets_list=[]
    for r in cache:
        result, invest = alloc_fn(r['all_tri'])
        if not result: continue
        n += 1
        combos = [c for c,_,_ in result]
        total_in += invest
        n_bets_list.append(len(result))
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
    sorted_rets = sorted(hit_rets, reverse=True)
    roi_ex1 = (total_re-sorted_rets[0])/total_in*100 if sorted_rets else 0
    return {'n':n,'hits':hits,'hr':hr,'roi':roi,'profit':total_re-total_in,
            'gami':gami,'gami_rate':gr,'roi_ex1':roi_ex1,
            'avg_bets':np.mean(n_bets_list),'avg_invest':total_in/n if n>0 else 0}


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
    except: s_race_ids = None

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
        sl = [n for n,d in ps.items() if d['ip']>=5.5 and lm.get(ntl.get(n,0),[None])[0]==n]
        if FILTER['skip_low_bank'] and bp['roi_tier']=='low': continue
        if FILTER['min_top_ev']>0 and top_ev<FILTER['min_top_ev']: continue
        if FILTER['skip_chaos'] and len(sl)>=2: continue
        all_tri = engine_c_all_tri(all_nums, raw_s, odds_dict, ntl)
        if not all_tri: continue
        cache.append({'race_id':race_id,'venue':venue,'all_tri':all_tri,'actual':actual,'payout':payout})

    print(f"  キャッシュ完了: {len(cache)}R\n")

    patterns = [
        ('A) EV比例 14点 (現行)',          lambda t: alloc_ev_prop(t, 14)),
        ('B) EV比例 7点',                 lambda t: alloc_ev_prop(t, 7)),
        ('C) EV比例 5点',                 lambda t: alloc_ev_prop(t, 5)),
        ('D) スマートアンチガミ 14点',     lambda t: alloc_antigami_smart(t, 14)),
        ('E) スマートアンチガミ 10点',     lambda t: alloc_antigami_smart(t, 10)),
        ('F) スマートアンチガミ 7点',      lambda t: alloc_antigami_smart(t, 7)),
        ('G) 固定予算アンチガミ 14点',     lambda t: alloc_antigami_fixed_budget(t, 14)),
        ('H) 固定予算アンチガミ 10点',     lambda t: alloc_antigami_fixed_budget(t, 10)),
        ('I) 固定予算アンチガミ 7点',      lambda t: alloc_antigami_fixed_budget(t, 7)),
    ]

    print(f"{'='*100}")
    print(f"  アンチガミ配分 v2 比較バックテスト (ev≥70 / chaos=N / low=Y)")
    print(f"{'='*100}\n")

    results = []
    for label, fn in patterns:
        r = evaluate(cache, fn, label)
        results.append({'label':label, **r})
        sign = "+" if r['profit']>=0 else ""
        stable = "★" if r['roi_ex1']>=100 else " "
        print(f" {stable}{label:30s}  R:{r['n']:3d}  Hit:{r['hits']:2d} ({r['hr']:.1f}%)  "
              f"ROI:{r['roi']:.1f}%  {sign}¥{r['profit']:>+8,}  "
              f"ガミ:{r['gami']}/{r['hits']} ({r['gami_rate']:.0f}%)  "
              f"Ex1:{r['roi_ex1']:.1f}%  avg:{r['avg_bets']:.1f}点 ¥{r['avg_invest']:.0f}/R")

    df = pd.DataFrame(results)
    df.to_csv("data/antigami_v2_comparison.csv", index=False, encoding='utf-8-sig')
    print(f"\n💾 data/antigami_v2_comparison.csv 保存完了")
    print(f"{'='*100}")


if __name__ == "__main__":
    main()
