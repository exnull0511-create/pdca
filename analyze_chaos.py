"""
カオス展開322Rの深掘り分析スクリプト
的中/ハズレを多軸で細分化して「読めるカオス」を特定する
"""
import pandas as pd
import re

with open('iteration_1_logs_S1.txt', encoding='utf-8') as f:
    content = f.read()

blocks = re.split(r'={50,}\n🔥 【Hardcore EV 推論レポート】', content)
records = []

for block in blocks[1:]:
    try:
        vm = re.search(r'^(.+?)バンク Race ID: (\S+)', block)
        if not vm: continue
        venue   = vm.group(1).strip()
        race_id = vm.group(2).strip()

        if '【的中】' in block:
            outcome = 'HIT'
            pm = re.search(r'払戻: ¥([\d,]+)', block)
            payout = int(pm.group(1).replace(',','')) if pm else 0
        elif '【ハズレ】' in block:
            outcome = 'MISS'; payout = 0
        else:
            outcome = 'OTHER'; payout = 0

        is_chaos    = 'カオス展開' in block
        has_monster = '鬼脚ワード検出' in block

        # 先行役人数
        chaos_names_m = re.search(r'対象選手: (.+)', block)
        chaos_count = len(chaos_names_m.group(1).split(',')) if chaos_names_m else 0

        # EV1位スコア
        em = re.search(r'1位.+?EV:([\d.]+)', block)
        top_ev = float(em.group(1)) if em else 0

        # 2位のEVスコア
        em2 = re.search(r'2位.+?EV:([\d.]+)', block)
        ev2 = float(em2.group(1)) if em2 else 0

        # EV差（1位と2位の差）
        ev_gap = top_ev - ev2

        # 軸のライン位置
        line_m = re.search(r'1位 車番(\d).+?ライン(\d)-(\d)番手', block)
        axis_line_pos = int(line_m.group(3)) if line_m else 0  # 1=先頭, 2=番手...

        records.append({
            'venue': venue, 'race_id': race_id, 'outcome': outcome, 'payout': payout,
            'is_chaos': is_chaos, 'has_monster': has_monster,
            'chaos_count': chaos_count, 'top_ev': top_ev, 'ev2': ev2,
            'ev_gap': ev_gap, 'axis_line_pos': axis_line_pos,
        })
    except Exception:
        continue

df = pd.DataFrame(records)
df_bet = df[df['outcome'].isin(['HIT','MISS'])].copy()
df_chaos = df_bet[df_bet['is_chaos'] == True].copy()
UNIT = 1400

print(f'カオス展開レース: {len(df_chaos)}R  的中: {(df_chaos["outcome"]=="HIT").sum()}件')
print(f'回収: ¥{df_chaos["payout"].sum():,}  ROI: {df_chaos["payout"].sum()/(len(df_chaos)*UNIT)*100:.1f}%')
print()

# =========================================
# 1. 鬼脚 × カオス
# =========================================
print('=== 鬼脚 × カオス展開 ===')
for m_flag, m_lbl in [(True,'鬼脚あり'),(False,'鬼脚なし')]:
    g = df_chaos[df_chaos['has_monster']==m_flag]
    if not len(g): continue
    h = (g['outcome']=='HIT').sum()
    roi = g['payout'].sum()/(len(g)*UNIT)*100
    print(f'  {m_lbl}: {len(g):3}R  的中{h:2}件({h/len(g)*100:5.1f}%)  ROI={roi:7.1f}%')

print()
# =========================================
# 2. カオス先行役人数別
# =========================================
print('=== カオス先行役 人数別 ===')
for cnt in sorted(df_chaos['chaos_count'].unique()):
    g = df_chaos[df_chaos['chaos_count']==cnt]
    h = (g['outcome']=='HIT').sum()
    roi = g['payout'].sum()/(len(g)*UNIT)*100
    print(f'  先行役{int(cnt)}人: {len(g):3}R  的中{h:2}件({h/len(g)*100:5.1f}%)  ROI={roi:7.1f}%')

print()
# =========================================
# 3. 軸EV帯 × カオス
# =========================================
print('=== EV帯ごと（カオス内） ===')
bins = [0,70,80,90,9999]; lbls=['~70','71~80','81~90','91~']
df_chaos['EV帯'] = pd.cut(df_chaos['top_ev'],bins=bins,labels=lbls)
for band, g in df_chaos.groupby('EV帯', observed=True):
    h = (g['outcome']=='HIT').sum()
    roi = g['payout'].sum()/(len(g)*UNIT)*100
    print(f'  EV{band}: {len(g):3}R  的中{h:2}件({h/len(g)*100:5.1f}%)  ROI={roi:7.1f}%')

print()
# =========================================
# 4. EVギャップ（1位-2位の差）別
# =========================================
print('=== EV差（1位-2位）別（カオス内） ===')
bins2=[0,3,6,10,9999]; lbls2=['~3','3~6','6~10','10~']
df_chaos['EV差帯'] = pd.cut(df_chaos['ev_gap'],bins=bins2,labels=lbls2)
for band, g in df_chaos.groupby('EV差帯', observed=True):
    h = (g['outcome']=='HIT').sum()
    roi = g['payout'].sum()/(len(g)*UNIT)*100
    print(f'  EV差{band}: {len(g):3}R  的中{h:2}件({h/len(g)*100:5.1f}%)  ROI={roi:7.1f}%')

print()
# =========================================
# 5. 軸のライン位置別
# =========================================
print('=== 軸のライン内ポジション別（カオス内） ===')
for pos in sorted(df_chaos['axis_line_pos'].unique()):
    g = df_chaos[df_chaos['axis_line_pos']==pos]
    if not len(g): continue
    h = (g['outcome']=='HIT').sum()
    roi = g['payout'].sum()/(len(g)*UNIT)*100
    lbl = {1:'先頭(逃げ役)',2:'2番手',3:'3番手',4:'4番手~'}.get(pos, f'{pos}番手')
    print(f'  {lbl}: {len(g):3}R  的中{h:2}件({h/len(g)*100:5.1f}%)  ROI={roi:7.1f}%')

print()
# =========================================
# 6. カオス内の高配当的中TOP
# =========================================
print('=== カオス内 高配当的中 TOP10 ===')
chaos_hits = df_chaos[df_chaos['outcome']=='HIT'].nlargest(10,'payout')
for _, r in chaos_hits.iterrows():
    print(f'  {r["venue"]:6} ¥{r["payout"]:>8,}  EV={r["top_ev"]:.1f}  先行役{int(r["chaos_count"])}人  EV差={r["ev_gap"]:.1f}  鬼脚={r["has_monster"]}  軸{int(r["axis_line_pos"])}番手')

print()
# =========================================
# 7. 組み合わせ: 鬼脚あり × EV80以上 のカオスのみ残したら？
# =========================================
print('=== 試算: 鬼脚あり & EV≥80 のカオスのみ対象 ===')
cond = df_chaos[(df_chaos['has_monster']==True) & (df_chaos['top_ev']>=80)]
if len(cond):
    h   = (cond['outcome']=='HIT').sum()
    roi = cond['payout'].sum()/(len(cond)*UNIT)*100
    print(f'  {len(cond)}R  的中{h}件({h/len(cond)*100:.1f}%)  ROI={roi:.1f}%')
else:
    print('  該当なし')

print()
print('=== 試算: EV差10以上のカオス（圧倒的な1強）===')
cond2 = df_chaos[df_chaos['ev_gap'] >= 10]
if len(cond2):
    h   = (cond2['outcome']=='HIT').sum()
    roi = cond2['payout'].sum()/(len(cond2)*UNIT)*100
    print(f'  {len(cond2)}R  的中{h}件({h/len(cond2)*100:.1f}%)  ROI={roi:.1f}%')
else:
    print('  該当なし')
