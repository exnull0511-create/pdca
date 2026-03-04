"""S_MAXHIT 追加パッチ"""
import re

txt = open('hardcore_ev.py', encoding='utf-8').read()

# S_UNION ブロックの後に S_MAXHIT を追加
insert_after = '"S_UNION": {'
# 対応する } を探して、その後に S_MAXHIT を追加

# STRATEGY_CONFIGS の最後の閉じ } を探す
# `},\n}` の最後の出現を見つける
s_union_start = txt.rfind('"S_UNION"')
closing = txt.find('\n}', s_union_start)  # S_UNION ブロック末尾の },

maxhit_block = '''
    "S_MAXHIT_3": {
        # 的中最大化モード: PL確率上位3点 (EV/オッズ完全無視)
        # 軸固定-PL → モデル最有力1着に集中
        "name":               "的中最大化×3点（PL確率Top3・EVなし）",
        "skip_chaos":         False,
        "min_top_ev":         0,
        "require_monster":    False,
        "s3_chaos_filter":    False,
        "use_full_permutation": False,
        "top_n_prob_bets":    3,
    },
    "S_MAXHIT_7": {
        # 的中最大化モード: PL確率上位7点
        "name":               "的中最大化×7点（PL確率Top7・EVなし）",
        "skip_chaos":         False,
        "min_top_ev":         0,
        "require_monster":    False,
        "s3_chaos_filter":    False,
        "use_full_permutation": False,
        "top_n_prob_bets":    7,
    },
    "S_MAXHIT_14": {
        # 的中最大化モード: PL確率上位14点（フル）
        "name":               "的中最大化×14点（PL確率Top14・EVなし）",
        "skip_chaos":         False,
        "min_top_ev":         0,
        "require_monster":    False,
        "s3_chaos_filter":    False,
        "use_full_permutation": False,
        "top_n_prob_bets":    14,
    },
}'''

# }\n} の最後を S_MAXHIT + } に置換
old_end = txt[closing:]  # \n} から末尾
# 最初の \n} だけを置換(S_UNION の閉じ),
new_txt = txt[:closing] + ''',
    },''' + maxhit_block + txt[closing + 2:]

# ただし closing は `\n}` の位置なので、そこを `},\n    S_MAXHIT...\n}` に置換
# より安全に: 末尾の `\n}` (STRATEGY_CONFIGSの閉じブレース) を見つけて置換
last_closing = txt.rfind('\n}')
new_txt2 = txt[:last_closing] + '\n' + maxhit_block.lstrip('\n')
open('hardcore_ev.py', 'w', encoding='utf-8').write(new_txt2)
print("OK")
