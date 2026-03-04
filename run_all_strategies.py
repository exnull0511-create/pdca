"""S1〜S4を順番に実行してROIを比較するバッチランナー"""
import subprocess, sys, re

results = {}
for strategy in ['S_MAXHIT_3', 'S_MAXHIT_7', 'S_MAXHIT_14']:
    src = open('hardcore_ev.py', encoding='utf-8').read()
    src = src.replace('STRATEGY = "S1"', f'STRATEGY = "{strategy}"', 1)
    open(f'_tmp_{strategy}.py', 'w', encoding='utf-8').write(src)
    proc = subprocess.run([sys.executable, f'_tmp_{strategy}.py'],
                          capture_output=True, text=True, cwd='.')
    results[strategy] = proc.stdout

# サマリー行だけ抽出して表示
print('=' * 60)
print('全ストラテジー ROI比較（修正後payoutsデータ）')
print('=' * 60)
for s, out in results.items():
    print(f'\n■ {s}')
    for line in out.splitlines():
        if any(k in line for k in ['Strategy','全レース数','スキップ','対象レース数',
                                    '的中数','的中率','総投資','総回収','ROI']):
            print(f'  {line.strip()}')
print('=' * 60)
