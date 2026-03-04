"""
スキップレース分析：S3フィルタを通過しなかったレースで
「もし14点投資していたら」の的中率・回収率を再計算する
"""
import sys
sys.path.insert(0, r'C:\keirinbusines')
sys.path.insert(0, r'C:\pdca')

import pandas as pd
import warnings
warnings.filterwarnings('ignore')

from datetime import date
from s3_predictor import run_s3_prediction, load_sclass_db, load_racer_relations

RACECARD_PATH  = r'C:\pdca\data\racecard.xlsx'
PAYOUTS_PATH   = r'C:\pdca\data\payouts.xlsx'
SCLASS_DB_PATH = r'C:\pdca\data\S級選手究極DB (1).xlsx'
RELATIONS_PATH = r'C:\pdca\data\s_class_racers.csv'

print("データ読み込み中...")
rc_all  = pd.read_excel(RACECARD_PATH)
pay_all = pd.read_excel(PAYOUTS_PATH)
db_all  = load_sclass_db(SCLASS_DB_PATH)
rels    = load_racer_relations(RELATIONS_PATH)

rc_all['date_dt']  = pd.to_datetime(rc_all['date'].astype(str), format='%Y%m%d').dt.date
pay_all['date_dt'] = pd.to_datetime(pay_all['date'].astype(str), format='%Y%m%d').dt.date

FEB_START = date(2026, 2, 1)
FEB_END   = date(2026, 2, 28)
rc_feb  = rc_all[(rc_all['date_dt'] >= FEB_START) & (rc_all['date_dt'] <= FEB_END)]
pay_feb = pay_all[(pay_all['date_dt'] >= FEB_START) & (pay_all['date_dt'] <= FEB_END)]

race_ids = pay_feb['race_id'].unique()
print(f"対象: {len(race_ids)}R")

BET_UNIT = 100
N_BETS   = 14

s3_pass_invest = s3_pass_ret = s3_pass_hit = s3_pass_total = 0
skip_invest    = skip_ret    = skip_hit    = skip_total    = 0

for i, race_id in enumerate(race_ids, 1):
    rc_df = rc_feb[rc_feb['race_id'] == race_id].copy()
    if rc_df.empty:
        continue
    pay_row = pay_feb[pay_feb['race_id'] == race_id].iloc[0]
    venue   = str(pay_row['venue'])
    rd      = pay_row['date_dt']

    # ライン再構築
    lines = []
    if 'line_no' in rc_df.columns and 'line_bibs' in rc_df.columns:
        for lno in sorted(rc_df['line_no'].dropna().unique()):
            lno = int(lno)
            bibs_rows = rc_df[rc_df['line_no'] == lno]
            if not bibs_rows.empty:
                bibs_str = str(bibs_rows.iloc[0]['line_bibs'])
                try:
                    bibs = [int(x) for x in bibs_str.replace('-', ' ').split() if x.strip().isdigit()]
                except Exception:
                    bibs = list(bibs_rows['車番'].astype(int))
            else:
                bibs = list(bibs_rows['車番'].astype(int))
            if bibs:
                lines.append({'line': lno, 'bibs': bibs})

    try:
        try:
            pred = run_s3_prediction(
                race_card_df=rc_df,
                lines=lines,
                odds_df=None,
                db_all=db_all,
                venue=venue,
                race_date=rd,
                relations_df=rels,
            )
        except Exception as e:
            continue

        s3_pass  = pred.get('s3_pass', False)
        bets     = pred.get('bets', [])
        bet_unit = pred.get('bet_unit', BET_UNIT)

        r1 = int(pay_row['1着車番'])
        r2 = int(pay_row['2着車番'])
        r3 = int(pay_row['3着車番'])
        actual = f"{r1}-{r2}-{r3}"
        payout = int(pay_row['payout_trifecta'])

        n_bets = len(bets)
        invest = n_bets * bet_unit
        hit    = actual in bets
        ret    = payout * bet_unit // 100 if hit else 0

        if s3_pass:
            s3_pass_total  += 1
            s3_pass_invest += invest
            s3_pass_ret    += ret
            s3_pass_hit    += int(hit)
        else:
            skip_total  += 1
            skip_invest += invest
            skip_ret    += ret
            skip_hit    += int(hit)

    except Exception:
        continue

    if i % 50 == 0:
        print(f"  {i}/{len(race_ids)}")

print("\n" + "="*55)
print("【S3通過レース】")
print(f"  レース数  : {s3_pass_total}R")
print(f"  的中      : {s3_pass_hit}R  ({s3_pass_hit/max(1,s3_pass_total)*100:.1f}%)")
print(f"  投資額    : ¥{s3_pass_invest:,}")
print(f"  回収額    : ¥{s3_pass_ret:,}")
print(f"  回収率    : {s3_pass_ret/max(1,s3_pass_invest)*100:.1f}%")
print(f"  損益      : ¥{s3_pass_ret-s3_pass_invest:+,}")

print("\n【S3スキップレース（もし投資していたら）】")
print(f"  レース数  : {skip_total}R")
print(f"  的中      : {skip_hit}R  ({skip_hit/max(1,skip_total)*100:.1f}%)")
print(f"  投資額    : ¥{skip_invest:,}")
print(f"  回収額    : ¥{skip_ret:,}")
print(f"  回収率    : {skip_ret/max(1,skip_invest)*100:.1f}%")
print(f"  損益      : ¥{skip_ret-skip_invest:+,}")

print("\n【全レース（フィルタなし）】")
all_invest = s3_pass_invest + skip_invest
all_ret    = s3_pass_ret    + skip_ret
all_hit    = s3_pass_hit    + skip_hit
all_total  = s3_pass_total  + skip_total
print(f"  レース数  : {all_total}R")
print(f"  的中      : {all_hit}R  ({all_hit/max(1,all_total)*100:.1f}%)")
print(f"  投資額    : ¥{all_invest:,}")
print(f"  回収額    : ¥{all_ret:,}")
print(f"  回収率    : {all_ret/max(1,all_invest)*100:.1f}%")
print(f"  損益      : ¥{all_ret-all_invest:+,}")
print("="*55)
