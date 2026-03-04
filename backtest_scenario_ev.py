#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_scenario_ev.py
EV = P(的中) × オッズ - 1 > 0 の条件でのみ購入するシナリオEVバックテスト

モード:
  EV_MODE=True  : EV>0 の組み合わせのみ購入（実運用想定）
  EV_MODE=False : 確率上位14点を購入（フォールバック）
"""
import sys
sys.path.insert(0, r'C:\keirinbusines')
sys.path.insert(0, r'C:\pdca')

import pandas as pd
import numpy as np
from datetime import date
import warnings
warnings.filterwarnings('ignore')

from s3_predictor import (
    load_sclass_db, load_racer_relations,
    load_rescored_db, normalize_name, BANK_DICT
)
try:
    from s3_predictor import _get_bank_detail
except ImportError:
    def _get_bank_detail(v): return {}

from scenario_ev import run_scenario_ev

# =========================================================
# パス設定
# =========================================================
RACECARD_PATH  = r'C:\pdca\data\racecard.xlsx'
PAYOUTS_PATH   = r'C:\pdca\data\payouts.xlsx'
ODDS_PATH      = r'C:\pdca\data\odds.xlsx'
SCLASS_DB_PATH = r'C:\pdca\data\S級選手究極DB(1).xlsx'
RELATIONS_PATH = r'C:\pdca\data\s_class_racers.csv'
RESCORED_PATH  = r'C:\pdca\data\top30_rescored_rank_change.csv'
OUTPUT_CSV     = r'C:\pdca\data\backtest_ev_filter.csv'

EV_MODE        = True   # True: EV>0 フィルタ ON  / False: 確率上位14点
EV_THRESHOLD   = 0.0   # EV > この値の組み合わせを購入 (0=損益分岐以上)
MAX_BETS       = 30    # EV>0 でも最大N点まで

# =========================================================
# データ読み込み
# =========================================================
print("データ読み込み中...")
rc_all   = pd.read_excel(RACECARD_PATH)
pay_all  = pd.read_excel(PAYOUTS_PATH)
odds_all = pd.read_excel(ODDS_PATH)
db_all   = load_sclass_db(SCLASS_DB_PATH)
rels     = load_racer_relations(RELATIONS_PATH)
rescored = load_rescored_db(RESCORED_PATH)
print(f"オッズデータ: {len(odds_all)}行, 展開データ: {len(rescored)}選手分")

rc_all['date_dt']   = pd.to_datetime(rc_all['date'].astype(str),   format='%Y%m%d').dt.date
pay_all['date_dt']  = pd.to_datetime(pay_all['date'].astype(str),  format='%Y%m%d').dt.date

FEB_START = date(2026, 2, 1)
FEB_END   = date(2026, 2, 28)
rc_feb   = rc_all[ (rc_all['date_dt']  >= FEB_START) & (rc_all['date_dt']  <= FEB_END)]
pay_feb  = pay_all[(pay_all['date_dt'] >= FEB_START) & (pay_all['date_dt'] <= FEB_END)]
race_ids = pay_feb['race_id'].unique()
print(f"対象レース数: {len(race_ids)}R")

# =========================================================
# バックテスト本体
# =========================================================
results      = []
hit_count    = 0
total_invest = 0
total_return = 0
skipped      = 0   # EV>0 の組み合わせが0だったレース

for i, race_id in enumerate(race_ids, 1):
    rc_df = rc_feb[rc_feb['race_id'] == race_id].copy()
    if rc_df.empty:
        continue

    pay_row = pay_feb[pay_feb['race_id'] == race_id].iloc[0]
    venue   = str(pay_row['venue'])
    rd      = pay_row['date_dt']

    # ラインデータ再構築
    line_map = {}
    if 'line_no' in rc_df.columns and 'line_bibs' in rc_df.columns:
        for lno in sorted(rc_df['line_no'].dropna().unique()):
            lno = int(lno)
            bibs_rows = rc_df[rc_df['line_no'] == lno]
            if not bibs_rows.empty:
                try:
                    bs = str(bibs_rows.iloc[0]['line_bibs'])
                    bibs = [int(x) for x in bs.replace('-', ' ').split() if x.strip().isdigit()]
                except Exception:
                    bibs = list(bibs_rows['車番'].astype(int))
                if bibs:
                    line_map[lno] = bibs

    # player_scores 構築
    player_scores = {}
    for _, row in rc_df.iterrows():
        try:
            num  = int(row['車番'])
            name = str(row['選手名'])
            norm = normalize_name(name)
            hist = db_all[db_all['選手名_norm'] == norm]
            def _avg(col, d):
                v = hist[col].mean() if not hist.empty and col in hist.columns else d
                return d if pd.isna(v) else float(v)
            player_scores[num] = {
                'name': name, 'ip': _avg('IP', 4.0), 'ep': _avg('EP', 4.0),
                'dp': _avg('DP', 3.0), 'bp': _avg('BP', 3.0),
                'style': str(row.get('脚質', '')),
                'line_no': 0, 'pos_in_line': 1,
                'hidden_monster': 0.0, 'chigire': 0.0, 'loyalty': 0.0, 'totsu': 0.0,
            }
            for lno, bibs in line_map.items():
                if num in bibs:
                    player_scores[num]['line_no']     = lno
                    player_scores[num]['pos_in_line'] = bibs.index(num) + 1
                    break
        except Exception:
            continue

    if not player_scores or not line_map:
        continue

    # このレースのオッズ辞書を構築 {組み合わせ: 倍率}
    race_odds_df = odds_all[odds_all['race_id'] == race_id]
    odds_dict = {}
    if not race_odds_df.empty:
        for _, orow in race_odds_df.iterrows():
            combo = str(orow['組み合わせ']).strip()
            try:
                odds_dict[combo] = float(orow['オッズ'])
            except Exception:
                pass

    bk = _get_bank_detail(venue)

    # シナリオEV実行
    try:
        sev = run_scenario_ev(
            player_scores=player_scores,
            line_map=line_map,
            venue=venue,
            bank_detail=bk,
            rescored_df=rescored,
            odds_dict=odds_dict if (EV_MODE and odds_dict) else None,
            ev_threshold=EV_THRESHOLD,
            max_bets=MAX_BETS,
        )
    except Exception as e:
        print(f"  [{i}] {race_id} ERROR: {e}")
        continue

    bets     = sev.get('bets', [])
    top_scen = sev.get('top_scenario')
    phase1   = sev.get('phase1', '')

    r1 = int(pay_row['1着車番'])
    r2 = int(pay_row['2着車番'])
    r3 = int(pay_row['3着車番'])
    actual = f"{r1}-{r2}-{r3}"
    payout = int(pay_row['payout_trifecta'])

    invest = 0
    ret    = 0
    hit    = False

    if not bets:
        skipped += 1
    else:
        invest = len(bets) * 100
        total_invest += invest
        if actual in bets:
            hit = True
            hit_count += 1
            ret = payout
            total_return += ret

    # EVスコア（的中組み合わせのEV）
    theo_prob = sev['combo_probs'].get(actual, 0.0)
    actual_odds_val = odds_dict.get(actual, 0)
    ev_actual = theo_prob * actual_odds_val - 1.0

    results.append({
        'race_id':    race_id,
        'venue':      venue,
        'date':       rd,
        'race_no':    int(pay_row['race_no']),
        'bets':       len(bets),
        'invest':     invest,
        'actual':     actual,
        'payout':     payout,
        'hit':        hit,
        'return':     ret,
        'top_phase':  phase1,
        'theo_prob':  round(theo_prob, 5),
        'ev_actual':  round(ev_actual, 3),
        'actual_odds': actual_odds_val,
    })

    if i % 20 == 0:
        print(f"  進捗: {i}/{len(race_ids)} R処理済")

# =========================================================
# 集計
# =========================================================
mode_label = "EV>0フィルタ" if EV_MODE else "確率上位14点"
print("\n" + "="*60)
print(f"[シナリオEV / {mode_label}] バックテスト結果 2026年2月")
print("="*60)
bought = [r for r in results if r['bets'] > 0]
print(f"総レース数       : {len(race_ids)} R")
print(f"購入レース       : {len(bought)} R  (スキップ: {skipped} R)")
print(f"平均購入点       : {sum(r['bets'] for r in bought)/max(1,len(bought)):.1f}点/R")
print(f"的中レース       : {hit_count} R  ({hit_count/max(1,len(bought))*100:.1f}% / 購入ベース)")
print(f"総投資額         : {total_invest:,}円")
print(f"総回収額         : {total_return:,}円")
roi    = total_return / max(1, total_invest) * 100
profit = total_return - total_invest
print(f"回収率           : {roi:.1f}%")
print(f"損益             : {profit:+,}円")

hits = [r for r in results if r['hit']]
if hits:
    pays = [r['payout'] for r in hits]
    print(f"的中配当 min={min(pays):,} avg={int(sum(pays)/len(pays)):,} max={max(pays):,}")

# EV>0 の組み合わせが的中した場合の詳細
if EV_MODE:
    ev_hits = [r for r in hits if r['ev_actual'] > 0]
    print(f"\nEV>0組み合わせの的中: {len(ev_hits)}R / 的中{len(hits)}R")

df_result = pd.DataFrame(results)
df_result.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')
print(f"\n詳細結果: {OUTPUT_CSV}")
print("="*60)

# バンク別ROI
bought_df = df_result[df_result['bets'] > 0]
bv = bought_df.groupby('venue').agg(
    n=('hit','count'), hits=('hit','sum'),
    ret=('return','sum'), inv=('invest','sum')
).reset_index()
bv['ROI'] = (bv['ret'] / bv['inv'].clip(lower=1) * 100).round(1)
bv = bv.sort_values('ROI', ascending=False)
print("\n=== バンク別ROI（購入レースのみ） ===")
for _, r in bv.iterrows():
    print(r['venue'] + ': ' + str(r['n']) + 'R  的中' + str(int(r['hits'])) + 'R  ROI=' + str(r['ROI']) + '%')
