import pandas as pd
import re

with open('iteration_1_logs.txt', encoding='utf-8') as f:
    content = f.read()

blocks = re.split(r'={50,}\n🔥 【Hardcore EV 推論レポート】', content)
records = []
for block in blocks[1:]:
    try:
        vm = re.search(r'^(.+?)バンク Race ID: (\S+)', block)
        if not vm:
            continue
        venue = vm.group(1).strip()
        if '【的中】' in block:
            outcome = 'HIT'
            pm = re.search(r'払戻: ¥([\d,]+)', block)
            payout = int(pm.group(1).replace(',', '')) if pm else 0
        elif '【ハズレ】' in block:
            outcome = 'MISS'
            payout = 0
        else:
            outcome = 'OTHER'
            payout = 0
        is_chaos    = 'カオス展開' in block
        has_monster = '鬼脚ワード検出' in block
        em = re.search(r'1位.+?EV:([\d.]+)', block)
        top_ev = float(em.group(1)) if em else 0
        records.append({
            'venue': venue, 'outcome': outcome, 'payout': payout,
            'is_chaos': is_chaos, 'has_monster': has_monster, 'top_ev': top_ev
        })
    except Exception:
        continue

df = pd.DataFrame(records)
df_bet = df[df['outcome'].isin(['HIT', 'MISS'])].copy()
UNIT = 1400
print('解析レース数:', len(df_bet))
print()

# 1. 会場別ROI
print('=== 会場別 ROI ===')
for v, g in df_bet.groupby('venue'):
    hits = (g['outcome'] == 'HIT').sum()
    ret  = g['payout'].sum()
    roi  = ret / (len(g) * UNIT) * 100
    print(f'{v:8} {len(g):3}R  的中{hits:2}件  的中率{hits/len(g)*100:5.1f}%  ROI{roi:7.1f}%')

print()
print('=== 展開タイプ別 ===')
for flag, label in [(True, 'カオス展開'), (False, '安定展開')]:
    g    = df_bet[df_bet['is_chaos'] == flag]
    h    = (g['outcome'] == 'HIT').sum()
    roi  = g['payout'].sum() / (len(g) * UNIT) * 100
    print(f'{label}: {len(g)}R  的中{h}件({h/len(g)*100:.1f}%)  ROI={roi:.1f}%')

print()
print('=== Hidden Monster有無 ===')
for flag, label in [(True, '鬼脚あり'), (False, '鬼脚なし')]:
    g = df_bet[df_bet['has_monster'] == flag]
    if not len(g):
        continue
    h   = (g['outcome'] == 'HIT').sum()
    roi = g['payout'].sum() / (len(g) * UNIT) * 100
    print(f'{label}: {len(g)}R  的中{h}件({h/len(g)*100:.1f}%)  ROI={roi:.1f}%')

print()
print('=== 軸EVスコア帯 ===')
bins = [0, 60, 70, 80, 90, 9999]
lbls = ['~60', '61~70', '71~80', '81~90', '91~']
df_bet['EV帯'] = pd.cut(df_bet['top_ev'], bins=bins, labels=lbls)
for band, g in df_bet.groupby('EV帯', observed=True):
    h   = (g['outcome'] == 'HIT').sum()
    roi = g['payout'].sum() / (len(g) * UNIT) * 100
    print(f'EV{band}: {len(g):3}R  的中{h:2}件({h/len(g)*100:5.1f}%)  ROI={roi:7.1f}%')

print()
print('=== 払戻分布（的中レース） ===')
hd = df_bet[df_bet['outcome'] == 'HIT']
for lo, hi, lbl in [
    (0,     2001,    '~2000'),
    (2001,  5001,    '2001~5000'),
    (5001,  10001,   '5001~10000'),
    (10001, 30001,   '10001~30000'),
    (30001, 9999999, '30001~'),
]:
    g = hd[(hd['payout'] >= lo) & (hd['payout'] < hi)]
    if len(g):
        tot = g['payout'].sum()
        avg = int(g['payout'].mean())
        print(f'{lbl:14} {len(g):2}件  合計¥{tot:>10,}  平均¥{avg:>8,}')

print()
print('=== 高配当的中 TOP10 ===')
top = hd.nlargest(10, 'payout')[['venue', 'payout', 'top_ev', 'is_chaos', 'has_monster']]
for _, r in top.iterrows():
    print(f'{r["venue"]:6} ¥{r["payout"]:>8,}  EV={r["top_ev"]:.1f}  カオス={r["is_chaos"]}  鬼脚={r["has_monster"]}')
