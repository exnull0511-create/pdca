"""
Top-N グリッドサーチ（修正版）: N=1〜14 で S3/S4 の ROI を比較
"""
import subprocess, sys, re

# S3/S4 それぞれの use_full_permutation 行（実際のターゲット文字列）
# _debug_inject.py で確認した正確な値
S3_TARGET = '        "use_full_permutation": False,  # \u2190 \u8ef8\u56fa\u5b9a PL\uff08\u30ab\u30aa\u30b9\u30ec\u30fc\u30b9\u3067\u5168\u9806\u5217\u306f\u6563\u3089\u304b\u308b\uff09'
S4_TARGET = '        "use_full_permutation": False,  # \u2190 \u8ef8\u56fa\u5b9a PL'

base_src = open('hardcore_ev.py', encoding='utf-8').read()

# 注入ターゲットを確認
print(f'S3 target found: {S3_TARGET in base_src}')
print(f'S4 target found: {S4_TARGET in base_src}')

print("=" * 65)
print("Top-N グリッドサーチ (S3/S4 \u00d7 N=1〜14)")
print("=" * 65)

best = {}

for strategy, target in [('S3', S3_TARGET), ('S4', S4_TARGET)]:
    print(f"\n■ {strategy}")
    print(f"  {'N':>3}  {'ROI':>9}  {'投資':>10}  {'回収':>10}  {'的中':>5}  {'対象R':>6}")
    print(f"  {'-'*55}")
    best[strategy] = (0, None)

    for n in range(1, 15):
        src = base_src
        # STRATEGY を変更
        src = src.replace('STRATEGY = "S1"', f'STRATEGY = "{strategy}"', 1)
        # top_n_bets を注入（該当行を top_n_bets 付きに置換）
        replacement = target + f'\n        "top_n_bets":           {n},'
        src = src.replace(target, replacement, 1)

        tmp = f'_tmp_grid_{strategy}_{n}.py'
        open(tmp, 'w', encoding='utf-8').write(src)
        proc = subprocess.run(
            [sys.executable, tmp],
            capture_output=True, text=True, cwd='.',
            timeout=120
        )
        out = proc.stdout

        roi_m   = re.search(r'ROI\):\s+([\d.]+)%', out)
        inv_m   = re.search(r'\u7dcf\u6295\u8cc7\u984d\s*:\s*¥([\d,]+)', out)
        ret_m   = re.search(r'\u7dcf\u56de\u53ce\u984d\s*:\s*¥([\d,]+)', out)
        hit_m   = re.search(r'\u7684\u4e2d\u6570\s*:\s*(\d+)', out)
        races_m = re.search(r'\u5bfe\u8c61\u30ec\u30fc\u30b9\u6570\s*:\s*(\d+)', out)

        roi   = float(roi_m.group(1)) if roi_m   else 0.0
        inv   = inv_m.group(1)        if inv_m   else '-'
        ret   = ret_m.group(1)        if ret_m   else '-'
        hit   = hit_m.group(1)        if hit_m   else '-'
        races = races_m.group(1)      if races_m else '-'

        mark = ' <-- BEST' if roi > best[strategy][0] else ''
        if roi > best[strategy][0]:
            best[strategy] = (roi, n)

        print(f"  {n:>3}  {roi:>8.2f}%  {inv:>10}  {ret:>10}  {hit:>5}  {races:>6}{mark}")

print()
print("=" * 65)
print("最適 N まとめ")
print("=" * 65)
for s, (roi, n) in best.items():
    print(f"  {s}: N = {n:>2}  ROI = {roi:.2f}%")
