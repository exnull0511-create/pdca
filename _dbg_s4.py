"""S4 top_n_bets 注入デバッグ"""
src = open('hardcore_ev.py', encoding='utf-8').read()
s4_target = '        "use_full_permutation": False,  # <- 軸固定 PL'

# 注入
replacement = s4_target + '\n        "top_n_bets":           3,'
src2 = src.replace('STRATEGY = "S1"', 'STRATEGY = "S4"', 1)
src2 = src2.replace(s4_target, replacement, 1)

print('top_n_bets injected:', 'top_n_bets' in src2)

# S4 設定ブロックを表示
idx = src2.find('"S4"')
print(src2[idx:idx+400])
