import pandas as pd

df = pd.read_csv('data/model_comparison_result.csv')
eng_c = df[df['engine']=='EngineC'].copy()
eng_c['profit'] = eng_c['return'] - eng_c['invest']

hits = eng_c[eng_c['hit']==True].sort_values('return', ascending=False)

print('=== Engine C 的中レース (払戻額順) ===')
for i, (_, r) in enumerate(hits.iterrows(), 1):
    v = r['venue']
    rn = int(r['race_no'])
    ret = int(r['return'])
    inv = int(r['invest'])
    p100 = int(r['payout_100'])
    prf = ret - inv
    print(f"  {i:2d}. {v} {rn:2d}R  払戻:{ret:>8,}  投資:{inv:>5,}  損益:{prf:>+8,}  ({p100//10}倍)")

total_in = int(eng_c['invest'].sum())
total_re = int(eng_c['return'].sum())
print(f"\n全{len(eng_c)}R: 投資{total_in:,}  払戻{total_re:,}  ROI {total_re/total_in*100:.1f}%  収支+{total_re-total_in:,}")

print("\n=== 大穴除外シミュレーション ===")
sorted_c = eng_c.sort_values('return', ascending=False)
for exclude in [1, 2, 3, 5]:
    remaining = sorted_c.iloc[exclude:]
    t_in = int(remaining['invest'].sum())
    t_re = int(remaining['return'].sum())
    n_hit = int(remaining['hit'].sum())
    roi = t_re / t_in * 100 if t_in > 0 else 0
    prf = t_re - t_in
    sign = "+" if prf >= 0 else ""
    print(f"  Top{exclude}除外: {len(remaining)}R  的中{n_hit}件  投資{t_in:,}  払戻{t_re:,}  ROI {roi:.1f}%  収支{sign}{prf:,}")
