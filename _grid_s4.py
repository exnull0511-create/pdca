"""
S4 Top-N グリッドサーチ（修正版）
S4 の use_full_permutation 行を正確に特定してから注入
"""
import subprocess, sys, re

base_src = open('hardcore_ev.py', encoding='utf-8').read()

# S4 の use_full_permutation 行を確認
lines = base_src.split('\n')
s4_targets = []
in_s4 = False
for i, line in enumerate(lines, 1):
    if '"S4"' in line and '{' in line:
        in_s4 = True
    if in_s4 and '"S_UNION"' in line:
        in_s4 = False
    if in_s4 and 'use_full_permutation' in line and 'False' in line:
        s4_targets.append((i, line))

print("S4 use_full_permutation candidates:")
for i, line in s4_targets:
    print(f"  L{i}: {repr(line)}")

if not s4_targets:
    print("ERROR: S4 target not found!")
    exit(1)

S4_TARGET = s4_targets[-1][1]  # 最後の候補を使用
print(f"\nUsing: {repr(S4_TARGET)}\n")

print("=" * 65)
print("Top-N グリッドサーチ S4 (N=1〜14)")
print("=" * 65)
print(f"  {'N':>3}  {'ROI':>9}  {'投資':>10}  {'回収':>10}  {'的中':>5}  {'対象R':>6}")
print(f"  {'-'*55}")

best_roi = 0
best_n   = None

for n in range(1, 15):
    src = base_src
    src = src.replace('STRATEGY = "S1"', 'STRATEGY = "S4"', 1)
    replacement = S4_TARGET + f'\n        "top_n_bets":           {n},'
    src = src.replace(S4_TARGET, replacement, 1)

    tmp = f'_tmp_gridS4_{n}.py'
    open(tmp, 'w', encoding='utf-8').write(src)
    proc = subprocess.run([sys.executable, tmp],
                          capture_output=True, text=True, cwd='.', timeout=120)
    out = proc.stdout

    roi_m   = re.search(r'ROI\):\s+([\d.]+)%', out)
    inv_m   = re.search(r'総投資額\s*:\s*¥([\d,]+)', out)
    ret_m   = re.search(r'総回収額\s*:\s*¥([\d,]+)', out)
    hit_m   = re.search(r'的中数\s*:\s*(\d+)', out)
    races_m = re.search(r'対象レース数\s*:\s*(\d+)', out)

    roi   = float(roi_m.group(1)) if roi_m   else 0.0
    inv   = inv_m.group(1)        if inv_m   else '-'
    ret   = ret_m.group(1)        if ret_m   else '-'
    hit   = hit_m.group(1)        if hit_m   else '-'
    races = races_m.group(1)      if races_m else '-'

    mark = ' <-- BEST' if roi > best_roi else ''
    if roi > best_roi:
        best_roi = roi
        best_n   = n

    print(f"  {n:>3}  {roi:>8.2f}%  {inv:>10}  {ret:>10}  {hit:>5}  {races:>6}{mark}")

print()
print(f"最適 N = {best_n}  ROI = {best_roi:.2f}%")
