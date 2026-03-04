"""
3つの予想ロジック改善案の効果試算スクリプト
 案A: 点数 14→18点
 案B: バンク別ヒット率分析（重み調整の根拠作成）
 案C: ベットコントロール（高EV=200円 / 標準=100円）
"""
import pandas as pd
import re

# === S3ログを解析 ===
with open('iteration_1_logs_S3.txt', encoding='utf-8') as f:
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
            rm = re.search(r'【的中】 結果: ([\d\-]+)', block)
            actual = rm.group(1) if rm else ''
        elif '【ハズレ】' in block:
            outcome = 'MISS'
            payout = 0
            rm = re.search(r'【ハズレ】 結果: ([\d\-]+)', block)
            actual = rm.group(1) if rm else ''
        else:
            continue

        em  = re.search(r'1位.+?EV:([\d.]+)', block)
        top_ev = float(em.group(1)) if em else 0
        em2 = re.search(r'2位.+?EV:([\d.]+)', block)
        ev2 = float(em2.group(1)) if em2 else 0
        ev_gap = round(top_ev - ev2, 1)

        # 軸車番（推奨買い目の先頭）
        bm = re.search(r'推奨: (\d+)-', block)
        axis_num = int(bm.group(1)) if bm else 0

        # 現在の14点の買い目リスト
        bets_m = re.search(r'推奨: (.+)', block)
        bets14 = [b.strip() for b in bets_m.group(1).split(',')] if bets_m else []

        # 全出走者の車番（EVランク順から抽出）
        racer_nums = re.findall(r'車番(\d+) .+? EV:', block)
        racer_nums = [int(n) for n in racer_nums]

        is_chaos    = 'カオス展開' in block
        has_monster = '鬼脚ワード検出' in block

        records.append({
            'race_id': race_id, 'venue': venue, 'outcome': outcome,
            'payout': payout, 'actual': actual, 'top_ev': top_ev,
            'ev_gap': ev_gap, 'axis': axis_num,
            'bets14': bets14, 'racers': racer_nums,
            'is_chaos': is_chaos, 'has_monster': has_monster,
        })
    except Exception:
        continue

df = pd.DataFrame(records)
HITS = df[df['outcome'] == 'HIT']
MISSES = df[df['outcome'] == 'MISS']
print(f'S3 解析レース数: {len(df)} (的中:{len(HITS)} ハズレ:{len(MISSES)})')
print()

# =============================================
# 案A: 点数 14→18点 の効果試算
# =============================================
print('=' * 60)
print('案A: 点数 14→18点 効果試算')
print('=' * 60)

def generate_bets(axis, others, max_bets):
    """EVスコア順(others)でフォーメーション生成"""
    combos = []
    for s in others:
        for t in others:
            if s != t:
                c = f"{axis}-{s}-{t}"
                if c not in combos:
                    combos.append(c)
            if len(combos) >= max_bets:
                break
        if len(combos) >= max_bets:
            break
    return combos

hit14 = 0; hit18 = 0
add_hits = 0
for _, r in df.iterrows():
    if not r['racers'] or not r['axis']: continue
    axis = r['axis']
    others = [n for n in r['racers'] if n != axis]
    bets18 = generate_bets(axis, others, 18)

    in14 = r['actual'] in r['bets14']
    in18 = r['actual'] in bets18

    if in14:  hit14 += 1
    if in18:  hit18 += 1
    if in18 and not in14:
        add_hits += 1
        print(f'  ★追加的中候補: {r["venue"]} 結果:{r["actual"]} '
              f'払戻:¥{r["payout"]:,} EV={r["top_ev"]:.1f}')

inv14 = len(df) * 1400
inv18 = len(df) * 1800
ret14 = HITS['payout'].sum()
# 18点では追加費用がかかるが的中数は基本変わらない（14内に入ってれば当たる）
# ただし14で外れて18で入る追加的中の払戻は個別確認
print(f'\n  現行14点: 的中{hit14}件 / 投資¥{inv14:,} / 回収¥{ret14:,} / ROI={ret14/inv14*100:.1f}%')
print(f'  18点時:   的中{hit18}件（+{add_hits}件追加）/ 投資¥{inv18:,}')
print(f'  ※18点では投資が1.29倍増。追加的中の払戻額次第で判断要。')

# =============================================
# 案B: バンク別ヒット率（重み調整の根拠）
# =============================================
print()
print('=' * 60)
print('案B: バンク別ヒット率・ROI（重み調整根拠）')
print('=' * 60)
print(f'  {"会場":<8} {"R数":>4} {"的中":>4} {"的中率":>7} {"投資":>10} {"回収":>10} {"ROI":>8}')
print('  ' + '-' * 58)
for v, g in df.groupby('venue'):
    h   = (g['outcome'] == 'HIT').sum()
    inv = len(g) * 1400
    ret = g['payout'].sum()
    roi = ret / inv * 100
    flag = ' ← 高ROI' if roi > 130 else (' ← 要注意' if roi < 50 else '')
    print(f'  {v:<8} {len(g):>4} {h:>4} {h/len(g)*100:>6.1f}% '
          f'¥{inv:>8,} ¥{ret:>8,} {roi:>7.1f}%{flag}')

# =============================================
# 案C: ベットコントロール（高EV=200円）
# =============================================
print()
print('=' * 60)
print('案C: ベットコントロール（軸EV90以上=200円 / 標準=100円）')
print('=' * 60)
EV_HIGH = 90
for _, r in df.iterrows():
    pass

total_inv_bc = 0; total_ret_bc = 0
for _, r in df.iterrows():
    unit   = 200 if r['top_ev'] >= EV_HIGH else 100
    bets_n = len(r['bets14'])
    total_inv_bc += unit * bets_n
    if r['outcome'] == 'HIT':
        total_ret_bc += r['payout'] * (unit / 100)

high_ev_races = (df['top_ev'] >= EV_HIGH).sum()
std_races     = (df['top_ev'] < EV_HIGH).sum()
print(f'  EV90以上(200円): {high_ev_races}レース')
print(f'  標準(100円):     {std_races}レース')
print(f'  総投資: ¥{total_inv_bc:,}')
print(f'  総回収: ¥{total_ret_bc:,}')
print(f'  ROI:   {total_ret_bc/total_inv_bc*100:.1f}%')
print()
print(f'  ※ 参考（現行100円均等）: 投資¥{len(df)*1400:,} / 回収¥{HITS["payout"].sum():,} / ROI={HITS["payout"].sum()/(len(df)*1400)*100:.1f}%')

# EV90以上レースの的中率確認
high_df = df[df['top_ev'] >= EV_HIGH]
print(f'\n  EV90以上レースの内訳: {len(high_df)}R '
      f'的中{( high_df["outcome"]=="HIT").sum()}件 '
      f'({( high_df["outcome"]=="HIT").sum()/len(high_df)*100:.1f}%)')

# 最適EV閾値を探索
print('\n  --- ベットUP閾値の最適化 ---')
print(f'  {"EV閾値":>7} {"該当R":>6} {"的中率":>7} {"ROI(BC)":>9}')
for ev_th in [80, 85, 90, 95]:
    hi  = df[df['top_ev'] >= ev_th]
    lo  = df[df['top_ev'] <  ev_th]
    ti  = len(hi)*1800 + len(lo)*1400  # 高EVは18点に増やす案も
    ti2 = len(hi)*2800 + len(lo)*1400  # 高EV200円
    ret = (hi[hi['outcome']=='HIT']['payout'].sum() * 2
           + lo[lo['outcome']=='HIT']['payout'].sum())
    hits_hi = (hi['outcome']=='HIT').sum()
    roi = ret / ti2 * 100 if ti2 > 0 else 0
    print(f'  EV≥{ev_th}: {len(hi):3}R / 的中{hits_hi:2}件({hits_hi/len(hi)*100:.0f}%) / ROI={roi:.1f}%')
