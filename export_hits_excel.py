"""S2・S4の的中レースをExcelに出力する"""
import pandas as pd
import re

def parse_hits(log_path, strategy):
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

            rm = re.search(r'【的中】 結果: ([\d\-]+)', block)
            result = rm.group(1) if rm else '?'

            em = re.search(r'1位.+?EV:([\d.]+)', block)
            top_ev = float(em.group(1)) if em else 0
            em2 = re.search(r'2位.+?EV:([\d.]+)', block)
            ev2   = float(em2.group(1)) if em2 else 0
            ev_gap = round(top_ev - ev2, 1)

            is_chaos    = 'カオス展開' in block
            has_monster = '鬼脚ワード検出' in block

            cm = re.search(r'対象選手: (.+)', block)
            chaos_count = len(cm.group(1).split(',')) if cm else 0

            ax_m = re.search(r'1位 車番(\d+) (.+?) \(', block)
            axis_num  = ax_m.group(1) if ax_m else '?'
            axis_name = ax_m.group(2).strip() if ax_m else '?'

            bm = re.search(r'推奨: (.+)', block)
            bets = bm.group(1).strip() if bm else ''

            hits.append({
                'Strategy':   strategy,
                'Race ID':    race_id,
                '会場':       venue,
                '結果':       result,
                '払戻金額':   payout,
                '配当倍率':   round(payout / 100, 1),
                '軸車番':     axis_num,
                '軸選手名':   axis_name,
                '軸EVスコア': top_ev,
                'EV差(1-2位)': ev_gap,
                'カオス展開': 'YES' if is_chaos else 'no',
                '先行役人数': chaos_count,
                '鬼脚あり':   'YES' if has_monster else 'no',
                '⚠疑わしい':  '⚠️ 要確認' if (payout >= 30000 and is_chaos) else '',
                '投資額(円)': 1400,
                '損益(円)':   payout - 1400,
                '推奨買い目': bets,
            })
        except Exception:
            continue
    return hits

rows = []
for strategy, logfile in [('S2','iteration_1_logs_S2.txt'),('S4','iteration_1_logs_S4.txt')]:
    rows.extend(parse_hits(logfile, strategy))

df = pd.DataFrame(rows).sort_values(['Strategy','払戻金額'], ascending=[True, False])

# Excel出力（シート分け）
outfile = 'S2_S4_的中レース一覧.xlsx'
with pd.ExcelWriter(outfile, engine='openpyxl') as writer:
    # シート1: S2+S4合算
    df.to_excel(writer, sheet_name='S2+S4合算', index=False)

    # シート2: S2のみ
    df[df['Strategy']=='S2'].to_excel(writer, sheet_name='S2', index=False)

    # シート3: S4のみ
    df[df['Strategy']=='S4'].to_excel(writer, sheet_name='S4', index=False)

    # シート4: サマリー
    summary_rows = []
    for strategy in ['S2', 'S4']:
        g = df[df['Strategy'] == strategy]
        summary_rows.append({
            'Strategy':  strategy,
            '的中件数':  len(g),
            '総回収':    g['払戻金額'].sum(),
            '総投資':    len(g) * 1400,
            '損益合計':  g['損益(円)'].sum(),
            '平均払戻':  round(g['払戻金額'].mean()),
            '最高払戻':  g['払戻金額'].max(),
            '疑わしい件数': (g['⚠疑わしい'] != '').sum(),
        })
    pd.DataFrame(summary_rows).to_excel(writer, sheet_name='サマリー', index=False)

    # 列幅の自動調整
    from openpyxl.utils import get_column_letter
    for sheet in writer.sheets.values():
        for col in sheet.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            sheet.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 3, 40)

print(f'✅ Excel出力完了: {outfile}')
print(f'   シート: S2+S4合算 / S2 / S4 / サマリー')
print(f'   合計{len(df)}件')
