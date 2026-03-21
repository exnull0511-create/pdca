"""
backtest_grid_search.py
=======================
Engine B / Engine C / A+Bハイブリッドのパラメータグリッドサーチ

・Engine B: LINE_CORR を 0.05〜0.50 で探索
・Engine C: NEST_SIGMA を 0.50〜1.00 で探索
・Hybrid A+B: マルチ軸 + ライン相関（LINE_CORR 0.05〜0.50 で探索）

使い方:
  python backtest_grid_search.py
"""

import sys, os
import pandas as pd
import numpy as np
from datetime import datetime, date
from pathlib import Path

# ── 共通設定をインポート ─────────────────────────────────────────────────
from backtest_model_comparison import (
    load_db, compute_player_scores, common_filter, compute_raw_strengths,
    allocate_bets, STRATEGY, BET_BASE, LOW_BANK, BANK_DICT,
)


# ═══════════════════════════════════════════════════════════════════════
#  Engine A: マルチ軸PL（パラメータなし、固定参照用）
# ═══════════════════════════════════════════════════════════════════════
def run_engine_a(all_nums, raw_s, odds_dict, **_kw):
    def pl(f, s, t):
        d1 = sum(raw_s[n] for n in all_nums)
        d2 = sum(raw_s[n] for n in all_nums if n != f)
        d3 = sum(raw_s[n] for n in all_nums if n not in (f, s))
        return 0.0 if 0 in (d1, d2, d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)

    bets_data = []
    for f in all_nums:
        for s in all_nums:
            if s == f: continue
            for t in all_nums:
                if t == f or t == s: continue
                combo = f"{f}-{s}-{t}"
                if combo not in odds_dict: continue
                p = pl(f, s, t)
                bets_data.append((p * odds_dict[combo], combo, p, odds_dict[combo]))

    sel = sorted(bets_data, key=lambda x: x[2], reverse=True)[:STRATEGY['top_n_prob_bets']]
    if not sel: return None
    ev_lk = {c: ev for ev, c, p, o in bets_data}
    bets, total = allocate_bets(sel, ev_lk)
    return {'bets': bets, 'total': total}


# ═══════════════════════════════════════════════════════════════════════
#  Engine B: ライン相関PL（LINE_CORRパラメータ化）
# ═══════════════════════════════════════════════════════════════════════
def run_engine_b(all_nums, raw_s, odds_dict, num_to_line, line_map, line_corr=0.3, **_kw):
    def pl(f, s, t):
        d1 = sum(raw_s[n] for n in all_nums)
        d2 = sum(raw_s[n] for n in all_nums if n != f)
        d3 = sum(raw_s[n] for n in all_nums if n not in (f, s))
        return 0.0 if 0 in (d1, d2, d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)

    def pl_lc(f, s, t):
        base = pl(f, s, t)
        lines = [num_to_line.get(x, -x) for x in [f, s, t]]
        same_pairs = sum(1 for i in range(3) for j in range(i+1, 3) if lines[i] == lines[j])
        if same_pairs >= 3:
            return base * (1 - line_corr)
        elif same_pairs >= 1:
            for pair_line in set(lines):
                if pair_line < 0: continue
                members_in_top = [x for x in [f, s, t] if num_to_line.get(x, -x) == pair_line]
                if len(members_in_top) >= 2:
                    lm = line_map.get(pair_line, [])
                    leader = lm[0] if lm else None
                    if leader and leader not in [f, s, t]:
                        return base * (1 - line_corr)
                    elif leader and leader == f:
                        return base * (1 - line_corr * 0.15)
            return base * (1 - line_corr * 0.3)
        return base

    # マルチ軸展開
    bets_data = []
    for f in all_nums:
        for s in all_nums:
            if s == f: continue
            for t in all_nums:
                if t == f or t == s: continue
                combo = f"{f}-{s}-{t}"
                if combo not in odds_dict: continue
                p = pl_lc(f, s, t)
                bets_data.append((p * odds_dict[combo], combo, p, odds_dict[combo]))

    total_p = sum(p for _, _, p, _ in bets_data) or 1.0
    bets_norm = [(ev, c, p/total_p, o) for ev, c, p, o in bets_data]
    sel = sorted(bets_norm, key=lambda x: x[2], reverse=True)[:STRATEGY['top_n_prob_bets']]
    if not sel: return None
    ev_lk = {c: (p * o) for _, c, p, o in bets_norm}
    bets, total = allocate_bets(sel, ev_lk)
    return {'bets': bets, 'total': total}


# ═══════════════════════════════════════════════════════════════════════
#  Engine C: Nested Logit（NEST_SIGMAパラメータ化）
# ═══════════════════════════════════════════════════════════════════════
def run_engine_c(all_nums, raw_s, odds_dict, num_to_line, sigma=0.7, **_kw):
    def nested_marginal(target, remaining):
        if not remaining: return 0.0
        nests = {}
        for n in remaining:
            ln = num_to_line.get(n, -n)
            if ln not in nests: nests[ln] = []
            nests[ln].append(n)
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

    bets_data = []
    for f in all_nums:
        for s in all_nums:
            if s == f: continue
            for t in all_nums:
                if t == f or t == s: continue
                combo = f"{f}-{s}-{t}"
                if combo not in odds_dict: continue
                p = nested_tri(f, s, t)
                bets_data.append((p * odds_dict[combo], combo, p, odds_dict[combo]))

    sel = sorted(bets_data, key=lambda x: x[2], reverse=True)[:STRATEGY['top_n_prob_bets']]
    if not sel: return None
    ev_lk = {c: ev for ev, c, p, o in bets_data}
    bets, total = allocate_bets(sel, ev_lk)
    return {'bets': bets, 'total': total}


# ═══════════════════════════════════════════════════════════════════════
#  Hybrid A+B: マルチ軸 + ライン相関（LINE_CORRパラメータ化）
# ═══════════════════════════════════════════════════════════════════════
def run_hybrid_ab(all_nums, raw_s, odds_dict, num_to_line, line_map, line_corr=0.3, **_kw):
    """Engine Aのマルチ軸展開 + Engine Bのライン相関ペナルティ（再正規化なし版）"""
    def pl(f, s, t):
        d1 = sum(raw_s[n] for n in all_nums)
        d2 = sum(raw_s[n] for n in all_nums if n != f)
        d3 = sum(raw_s[n] for n in all_nums if n not in (f, s))
        return 0.0 if 0 in (d1, d2, d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)

    def pl_hybrid(f, s, t):
        base = pl(f, s, t)
        lines = [num_to_line.get(x, -x) for x in [f, s, t]]
        same_pairs = sum(1 for i in range(3) for j in range(i+1, 3) if lines[i] == lines[j])
        if same_pairs >= 3:
            return base * (1 - line_corr)
        elif same_pairs >= 1:
            for pair_line in set(lines):
                if pair_line < 0: continue
                members_in_top = [x for x in [f, s, t] if num_to_line.get(x, -x) == pair_line]
                if len(members_in_top) >= 2:
                    lm = line_map.get(pair_line, [])
                    leader = lm[0] if lm else None
                    if leader and leader not in [f, s, t]:
                        return base * (1 - line_corr)
                    elif leader and leader == f:
                        return base * (1 - line_corr * 0.15)
            return base * (1 - line_corr * 0.3)
        return base

    # マルチ軸（全選手×全選手）+ ペナルティ（再正規化なし）
    bets_data = []
    for f in all_nums:
        for s in all_nums:
            if s == f: continue
            for t in all_nums:
                if t == f or t == s: continue
                combo = f"{f}-{s}-{t}"
                if combo not in odds_dict: continue
                p = pl_hybrid(f, s, t)
                bets_data.append((p * odds_dict[combo], combo, p, odds_dict[combo]))

    # 再正規化せずPL確率順でTop14（Engine Aと同じセレクション方式）
    sel = sorted(bets_data, key=lambda x: x[2], reverse=True)[:STRATEGY['top_n_prob_bets']]
    if not sel: return None
    ev_lk = {c: ev for ev, c, p, o in bets_data}
    bets, total = allocate_bets(sel, ev_lk)
    return {'bets': bets, 'total': total}


# ═══════════════════════════════════════════════════════════════════════
#  データ準備（キャッシュ）
# ═══════════════════════════════════════════════════════════════════════
def prepare_races(db_slim, db_all, nobi_col):
    """全レースの共通データを事前計算してキャッシュ"""
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
    groups = rc_df.groupby('race_id')
    for race_id, rc_group in groups:
        if s_race_ids and race_id not in s_race_ids:
            continue
        venue   = rc_group.iloc[0]['venue']
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

        cache.append({
            'race_id': race_id, 'venue': venue, 'race_dt': race_dt,
            'race_no': int(rc_group.iloc[0]['race_no']),
            'all_nums': all_nums, 'raw_s': raw_s, 'odds_dict': odds_dict,
            'num_to_line': ntl, 'line_map': lm,
            'actual': actual, 'payout': payout,
        })

    print(f"  キャッシュ完了: {len(cache)}レース")
    return cache


def evaluate(cache, engine_fn, **params):
    """キャッシュされたレースデータにエンジンを適用し、結果を集計"""
    hits = 0; n = 0; total_in = 0; total_re = 0
    for r in cache:
        pred = engine_fn(
            all_nums=r['all_nums'], raw_s=r['raw_s'], odds_dict=r['odds_dict'],
            num_to_line=r['num_to_line'], line_map=r['line_map'], **params,
        )
        if pred is None: continue
        n += 1
        combos = [c for c, _ in pred['bets']]
        hit = r['actual'] in combos
        bet_amt = dict(pred['bets']).get(r['actual'], 0) if hit else 0
        ret = int(r['payout'] * bet_amt / 100) if hit else 0
        if hit: hits += 1
        total_in += pred['total']
        total_re += ret
    roi = total_re / total_in * 100 if total_in > 0 else 0
    hr  = hits / n * 100 if n > 0 else 0
    return {'n': n, 'hits': hits, 'hr': hr, 'invest': total_in,
            'ret': total_re, 'profit': total_re - total_in, 'roi': roi}


# ═══════════════════════════════════════════════════════════════════════
#  メイン
# ═══════════════════════════════════════════════════════════════════════
def main():
    db_slim, db_all, nobi_col = load_db()
    print("\n🔄 レースデータ事前計算中...")
    cache = prepare_races(db_slim, db_all, nobi_col)

    # ── ① Engine A（参照基準） ──────────────────────────────────────────
    print("\n" + "="*75)
    print("  ① Engine A（マルチ軸PL）参照基準")
    print("="*75)
    res_a = evaluate(cache, run_engine_a)
    print(f"  Races:{res_a['n']}  Hits:{res_a['hits']}  HR:{res_a['hr']:.1f}%  "
          f"Invest:¥{res_a['invest']:,}  Return:¥{res_a['ret']:,}  ROI:{res_a['roi']:.1f}%")

    results = [{'engine': 'EngineA', 'param': '-', **res_a}]

    # ── ② Engine B グリッドサーチ ──────────────────────────────────────
    print("\n" + "="*75)
    print("  ② Engine B（ライン相関PL）LINE_CORR グリッドサーチ")
    print("="*75)
    lc_values = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
    best_b = None
    for lc in lc_values:
        res = evaluate(cache, run_engine_b, line_corr=lc)
        tag = " 🏆" if best_b is None or res['roi'] > best_b['roi'] else ""
        if best_b is None or res['roi'] > best_b['roi']:
            best_b = {**res, 'lc': lc}
        print(f"  LC={lc:.2f}  Races:{res['n']}  Hits:{res['hits']}  HR:{res['hr']:.1f}%  "
              f"ROI:{res['roi']:.1f}%  Profit:{'+'if res['profit']>=0 else ''}¥{res['profit']:,}{tag}")
        results.append({'engine': f'EngineB(LC={lc:.2f})', 'param': f'LINE_CORR={lc:.2f}', **res})

    print(f"\n  ★ Engine B 最適: LINE_CORR={best_b['lc']:.2f}  ROI={best_b['roi']:.1f}%  HR={best_b['hr']:.1f}%")

    # ── ③ Engine C グリッドサーチ ──────────────────────────────────────
    print("\n" + "="*75)
    print("  ③ Engine C（Nested Logit）NEST_SIGMA グリッドサーチ")
    print("="*75)
    sigma_values = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00]
    best_c = None
    for sg in sigma_values:
        res = evaluate(cache, run_engine_c, sigma=sg)
        tag = " 🏆" if best_c is None or res['roi'] > best_c['roi'] else ""
        if best_c is None or res['roi'] > best_c['roi']:
            best_c = {**res, 'sg': sg}
        print(f"  σ={sg:.2f}  Races:{res['n']}  Hits:{res['hits']}  HR:{res['hr']:.1f}%  "
              f"ROI:{res['roi']:.1f}%  Profit:{'+'if res['profit']>=0 else ''}¥{res['profit']:,}{tag}")
        results.append({'engine': f'EngineC(σ={sg:.2f})', 'param': f'SIGMA={sg:.2f}', **res})

    print(f"\n  ★ Engine C 最適: SIGMA={best_c['sg']:.2f}  ROI={best_c['roi']:.1f}%  HR={best_c['hr']:.1f}%")

    # ── ④ Hybrid A+B グリッドサーチ ────────────────────────────────────
    print("\n" + "="*75)
    print("  ④ Hybrid A+B（マルチ軸＋ライン相関）LINE_CORR グリッドサーチ")
    print("="*75)
    best_h = None
    for lc in lc_values:
        res = evaluate(cache, run_hybrid_ab, line_corr=lc)
        tag = " 🏆" if best_h is None or res['roi'] > best_h['roi'] else ""
        if best_h is None or res['roi'] > best_h['roi']:
            best_h = {**res, 'lc': lc}
        print(f"  LC={lc:.2f}  Races:{res['n']}  Hits:{res['hits']}  HR:{res['hr']:.1f}%  "
              f"ROI:{res['roi']:.1f}%  Profit:{'+'if res['profit']>=0 else ''}¥{res['profit']:,}{tag}")
        results.append({'engine': f'HybridAB(LC={lc:.2f})', 'param': f'LINE_CORR={lc:.2f}', **res})

    print(f"\n  ★ Hybrid A+B 最適: LINE_CORR={best_h['lc']:.2f}  ROI={best_h['roi']:.1f}%  HR={best_h['hr']:.1f}%")

    # ── 最終ランキング ────────────────────────────────────────────────
    print("\n" + "="*75)
    print("  【最終ランキング】 全候補の最適パラメータ比較")
    print("="*75 + "\n")

    finalists = [
        {'engine': 'Engine A (マルチ軸PL)',           'param': '-',                     **res_a},
        {'engine': f'Engine B (LC={best_b["lc"]:.2f})',  'param': f'LC={best_b["lc"]:.2f}',  **best_b},
        {'engine': f'Engine C (σ={best_c["sg"]:.2f})',   'param': f'σ={best_c["sg"]:.2f}',   **best_c},
        {'engine': f'Hybrid A+B (LC={best_h["lc"]:.2f})','param': f'LC={best_h["lc"]:.2f}',  **best_h},
    ]
    finalists.sort(key=lambda x: x['roi'], reverse=True)

    for i, f in enumerate(finalists, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "  "
        print(f"  {medal} {i}. {f['engine']:30s}  Hits:{f['hits']:2d}  HR:{f['hr']:.1f}%  "
              f"ROI:{f['roi']:.1f}%  Profit:{'+'if f['profit']>=0 else ''}¥{f['profit']:,}")

    # CSV保存
    df = pd.DataFrame(results)
    df.to_csv("data/grid_search_models.csv", index=False, encoding='utf-8-sig')
    print(f"\n💾 data/grid_search_models.csv 保存完了")
    print("="*75)


if __name__ == "__main__":
    main()
