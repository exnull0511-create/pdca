"""
S2・S4の的中レース適正チェックレポート生成スクリプト
- 全的中レースの詳細一覧
- 配当帯別の分類
- 疑わしい高額配当（落車偶発）フラグ付き
"""
import pandas as pd
import re

def parse_hits(log_path, strategy):
    """ログから的中ブロックを構造化して返す"""
    with open(log_path, encoding='utf-8') as f:
        content = f.read()

    blocks = re.split(r'={50,}\n🔥 【Hardcore EV 推論レポート】', content)
    hits = []

    for block in blocks[1:]:
        if '【的中】' not in block:
            continue
        try:
            vm = re.search(r'^(.+?)バンク Race ID: (\S+)', block)
            venue   = vm.group(1).strip()
            race_id = vm.group(2).strip()

            pm = re.search(r'払戻: ¥([\d,]+)', block)
            payout = int(pm.group(1).replace(',','')) if pm else 0

            # 結果（的中した組み合わせ）
            rm = re.search(r'【的中】 結果: ([\d\-]+)', block)
            result = rm.group(1) if rm else '?'

            # EVスコア
            em = re.search(r'1位.+?EV:([\d.]+)', block)
            top_ev = float(em.group(1)) if em else 0

            em2 = re.search(r'2位.+?EV:([\d.]+)', block)
            ev2 = float(em2.group(1)) if em2 else 0
            ev_gap = round(top_ev - ev2, 1)

            # カオス・鬼脚
            is_chaos = 'カオス展開' in block
            has_monster = '鬼脚ワード検出' in block

            # 先行役人数
            cm = re.search(r'対象選手: (.+)', block)
            chaos_count = len(cm.group(1).split(',')) if cm else 0

            # 軸選手名と車番
            ax_m = re.search(r'1位 車番(\d+) (.+?) \(', block)
            axis_num  = ax_m.group(1) if ax_m else '?'
            axis_name = ax_m.group(2).strip() if ax_m else '?'

            hits.append({
                'strategy':    strategy,
                'race_id':     race_id,
                'venue':       venue,
                'result':      result,
                'payout':      payout,
                'top_ev':      top_ev,
                'ev_gap':      ev_gap,
                'is_chaos':    is_chaos,
                'chaos_count': chaos_count,
                'has_monster': has_monster,
                'axis':        f"車番{axis_num} {axis_name}",
            })
        except Exception:
            continue
    return hits

# S2・S4のログを解析
all_hits = []
for strategy, logfile in [('S2','iteration_1_logs_S2.txt'), ('S4','iteration_1_logs_S4.txt')]:
    all_hits.extend(parse_hits(logfile, strategy))

df = pd.DataFrame(all_hits).sort_values('payout', ascending=False)

# 高額疑わしいフラグ（配当50倍=¥7000以上かつカオス展開で偶発的な可能性）
df['疑わしい'] = (df['payout'] >= 30000) & (df['is_chaos'] == True)
df['配当倍率'] = (df['payout'] / 100).round(1).astype(str) + '倍'

UNIT = 1400

print('=' * 80)
print(f'S2・S4 的中レース全件リスト（合計{len(df)}件）')
print('=' * 80)
print()

for strategy in ['S2', 'S4']:
    sub = df[df['strategy'] == strategy]
    total_inv  = len(set(sub['race_id'])) * UNIT  # 近似
    total_ret  = sub['payout'].sum()
    print(f'■ {strategy} 的中 {len(sub)}件  回収合計: ¥{total_ret:,}')
    print(f'  {"No":<3} {"会場":<6} {"結果":<8} {"払戻":>9} {"配当倍率":>7} {"軸選手":<16} {"EV":>5} {"EV差":>5} {"カオス":<5} {"先行役":>5} {"鬼脚":<5} {"疑い"}')
    print('  ' + '-'*100)
    for i, (_, r) in enumerate(sub.sort_values('payout', ascending=False).iterrows(), 1):
        flag = '⚠️ ' if r['疑わしい'] else '  '
        print(f'  {i:<3} {r["venue"]:<6} {r["result"]:<8} ¥{r["payout"]:>8,} {r["配当倍率"]:>8} '
              f'{r["axis"][:15]:<16} {r["top_ev"]:5.1f} {r["ev_gap"]:5.1f} '
              f'{"YES" if r["is_chaos"] else "no":<5} {r["chaos_count"]:>5}人 '
              f'{"YES" if r["has_monster"] else "no":<5} {flag}')
    print()

# 配当帯サマリー
print('=' * 80)
print('配当帯別サマリー（S2+S4合計）')
print('=' * 80)
bins   = [0, 2000, 5000, 10000, 30000, 9999999]
labels = ['~2000（低）', '~5000（中）', '~10000（高）', '~30000（超高）', '30001~（爆裂）']
df['配当帯'] = pd.cut(df['payout'], bins=bins, labels=labels)
for band, g in df.groupby('配当帯', observed=True):
    suspicious = g['疑わしい'].sum()
    print(f'  {str(band):<14} {len(g):2}件  合計¥{g["payout"].sum():>9,}  '
          f'平均¥{int(g["payout"].mean()):>7,}  疑わしい:{suspicious}件')

print()
print('⚠️ 疑わしいレース（高額配当×カオス展開）:')
suspicious_df = df[df['疑わしい']]
if not suspicious_df.empty:
    for _, r in suspicious_df.iterrows():
        print(f'  [{r["strategy"]}] {r["venue"]} {r["result"]} ¥{r["payout"]:,}  '
              f'カオス先行役{r["chaos_count"]}人 EV={r["top_ev"]:.1f}')
else:
    print('  なし')
