"""
backtest_s3.py
2月過去レースデータ（racecard.xlsx + payouts.xlsx）を使って
S3予想ロジック（展開EV強化版）のバックテストを実行する。

出力: 的中率・回収率・投資額・利益 をコンソールとCSVに出力
"""
import sys, os
sys.path.insert(0, r'C:\keirinbusines')
sys.path.insert(0, r'C:\pdca')

import pandas as pd
import numpy as np
from datetime import date, datetime
import warnings
warnings.filterwarnings('ignore')

from s3_predictor import (
    run_s3_prediction, load_sclass_db, load_racer_relations,
    load_rescored_db, normalize_name
)

# =========================================================
# パス設定
# =========================================================
RACECARD_PATH   = r'C:\pdca\data\racecard.xlsx'
PAYOUTS_PATH    = r'C:\pdca\data\payouts.xlsx'
SCLASS_DB_PATH  = r'C:\pdca\data\S級選手究極DB(1).xlsx'
RELATIONS_PATH  = r'C:\pdca\data\s_class_racers.csv'
RESCORED_PATH   = r'C:\pdca\data\top30_rescored_rank_change.csv'
OUTPUT_CSV      = r'C:\pdca\data\backtest_result_v2.csv'

# =========================================================
# データ読み込み
# =========================================================
print("データ読み込み中...")
rc_all   = pd.read_excel(RACECARD_PATH)
pay_all  = pd.read_excel(PAYOUTS_PATH)
db_all   = load_sclass_db(SCLASS_DB_PATH)
rels     = load_racer_relations(RELATIONS_PATH)
rescored = load_rescored_db(RESCORED_PATH)
print(f"展開データ: {len(rescored)}選手分 ロード完了")

# 日付を整数→date変換
rc_all['date_dt']  = pd.to_datetime(rc_all['date'].astype(str), format='%Y%m%d').dt.date
pay_all['date_dt'] = pd.to_datetime(pay_all['date'].astype(str), format='%Y%m%d').dt.date

# 2月データのみ絞り込み
FEB_START = date(2026, 2, 1)
FEB_END   = date(2026, 2, 28)
rc_feb   = rc_all[(rc_all['date_dt'] >= FEB_START) & (rc_all['date_dt'] <= FEB_END)]
pay_feb  = pay_all[(pay_all['date_dt'] >= FEB_START) & (pay_all['date_dt'] <= FEB_END)]

race_ids = pay_feb['race_id'].unique()
print(f"対象レース数: {len(race_ids)}R")

# =========================================================
# バックテスト本体
# =========================================================
results = []
s3_pass_count = 0
hit_count     = 0
total_invest  = 0
total_return  = 0

for i, race_id in enumerate(race_ids, 1):
    # 出走表
    rc_df = rc_feb[rc_feb['race_id'] == race_id].copy()
    if rc_df.empty:
        continue

    # 払戻データ
    pay_row = pay_feb[pay_feb['race_id'] == race_id].iloc[0]
    venue   = str(pay_row['venue'])
    rd      = pay_row['date_dt']

    # ラインデータを再構築（racecard.xlsxのline_no/line_bibs列から）
    lines = []
    if 'line_no' in rc_df.columns and 'line_bibs' in rc_df.columns:
        for lno in sorted(rc_df['line_no'].dropna().unique()):
            lno = int(lno)
            bibs_rows = rc_df[rc_df['line_no'] == lno]
            # line_bibs文字列から車番順に並び替え
            if not bibs_rows.empty and 'line_bibs' in bibs_rows.columns:
                bibs_str = str(bibs_rows.iloc[0]['line_bibs'])
                try:
                    bibs = [int(x) for x in bibs_str.replace('-', ' ').split() if x.strip().isdigit()]
                except Exception:
                    bibs = list(bibs_rows['車番'].astype(int))
            else:
                bibs = list(bibs_rows['車番'].astype(int))
            if bibs:
                lines.append({'line': lno, 'bibs': bibs})

    # S3予想実行
    try:
        pred = run_s3_prediction(
            race_card_df=rc_df.rename(columns={'date': '開催日'}) if '開催日' not in rc_df.columns else rc_df,
            lines=lines,
            odds_df=None,
            db_all=db_all,
            venue=venue,
            race_date=rd,
            relations_df=rels,
            rescored_df=rescored,
        )
    except Exception as e:
        print(f"  [{i}/{len(race_ids)}] {race_id} ERROR: {e}")
        continue

    s3_pass   = pred.get('s3_pass', False)
    bets      = pred.get('bets', [])
    bet_unit  = pred.get('bet_unit', 100)
    skip_rsn  = pred.get('s3_skip_reason', '')

    # 実際の結果
    r1 = int(pay_row['1着車番'])
    r2 = int(pay_row['2着車番'])
    r3 = int(pay_row['3着車番'])
    actual = f"{r1}-{r2}-{r3}"
    payout = int(pay_row['payout_trifecta'])

    # S3通過レースのみ投資
    invest = 0
    ret    = 0
    hit    = False
    # S3フィルタ廃止 --- 全レース購入
    if bets:
        s3_pass_count += 1
        invest = len(bets) * bet_unit
        total_invest += invest
        if actual in bets:
            hit = True
            hit_count += 1
            ret = payout * bet_unit // 100   # 払戻（100円単位）
            total_return += ret

    ranked = pred.get('ranked', [])
    top_ev = ranked[0][1]['ev_score'] if ranked else 0

    results.append({
        'race_id':   race_id,
        'venue':     venue,
        'date':      rd,
        'race_no':   int(pay_row['race_no']),
        's3_pass':   s3_pass,
        'skip_rsn':  skip_rsn,
        'bets':      len(bets),
        'bet_unit':  bet_unit,
        'invest':    invest,
        'actual':    actual,
        'payout':    payout,
        'hit':       hit,
        'return':    ret,
        'top_ev':    round(top_ev, 1),
        'axis':      pred.get('axis_num', ''),
        'is_chaos':  pred.get('is_chaos', False),
        'has_monster': pred.get('has_monster', False),
    })

    if i % 20 == 0:
        print(f"  進捗: {i}/{len(race_ids)} R処理済")

# =========================================================
# 集計
# =========================================================
print("\n" + "="*60)
print("【バックテスト結果】2026年2月")
print("="*60)
print(f"総レース数      : {len(race_ids)} R")
print(f"S3通過レース    : {s3_pass_count} R  ({s3_pass_count/max(1,len(race_ids))*100:.1f}%)")
print(f"的中レース      : {hit_count} R  ({hit_count/max(1,s3_pass_count)*100:.1f}% / S3通過ベース)")
print(f"総投資額        : YEN{total_invest:,}")
print(f"総回収額        : YEN{total_return:,}")
roi = total_return / max(1, total_invest) * 100
profit = total_return - total_invest
print(f"回収率          : {roi:.1f}%")
print(f"損益            : YEN{profit:+,}")

# 払戻分布（的中レースのみ）
hits = [r for r in results if r['hit']]
if hits:
    pays = [r['payout'] for r in hits]
    print(f"\n的中払戻 min={min(pays):,} / avg={int(sum(pays)/len(pays)):,} / max={max(pays):,}")

# スキップ理由集計
from collections import Counter
skip_reasons = Counter(r['skip_rsn'] for r in results if not r['s3_pass'] and r['skip_rsn'])
print(f"\n【S3スキップ理由 TOP5】")
for rsn, cnt in skip_reasons.most_common(5):
    print(f"  {cnt}R : {rsn}")

# CSV出力
df_result = pd.DataFrame(results)
df_result.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')
print(f"\n詳細結果: {OUTPUT_CSV}")
print("="*60)
