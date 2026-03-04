"""S_UNION を STRATEGY_CONFIGS に追加するパッチ"""
txt = open('hardcore_ev.py', encoding='utf-8').read()

# S4 の末尾（closing brace の直前）を探す
old = '        "use_full_permutation": False,'
# 最後の occurrence を S_UNION 挿入ポイントとする
idx = txt.rfind(old)
if idx == -1:
    print("ERROR: target not found")
    exit(1)

# "},\n}" の部分（S4 設定末尾 + STRATEGY_CONFIGS 末尾）を置換
target_section = txt[idx: idx + 200]
print("FOUND:", repr(target_section[:80]))

union_block = '''        "use_full_permutation": False,  # ← 軸固定 PL
    },
    "S_UNION": {
        # 実戦用ユニオン: S2∨S3∨S4いずれか通過でベット、クロス数で増額
        "name":               "S234ユニオン（S2∨S3∨S4通過 + クロス増額）",
        "skip_chaos":         False,
        "min_top_ev":         0,
        "require_monster":    False,
        "s3_chaos_filter":    False,
        "use_union_filter":   True,    # S2∨S3∨S4 判定モード
        "use_full_permutation": False, # 軸固定-PL
        "bet_base":           100,
        "skip_low_bank":      False,
    },
}'''

# 最後の use_full_permutation 行から "}\n}" までを置換
end_idx = txt.find('\n}', idx)
if end_idx == -1:
    print("ERROR: closing brace not found")
    exit(1)

new_txt = txt[:idx] + union_block + txt[end_idx + 2:]
open('hardcore_ev.py', 'w', encoding='utf-8').write(new_txt)
print("OK: S_UNION added")
