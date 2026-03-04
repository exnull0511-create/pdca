"""S4設定をhardcore_ev.pyのSTRATEGY_CONFIGSに追加するパッチスクリプト"""

src = open('hardcore_ev.py', encoding='utf-8').read()

s4_block = '''    "S4": {
        "name":            "ROI最大化版（EV80以上 / カオスはEV91orリーダー5人）",
        "skip_chaos":      False,
        "min_top_ev":      80,      # EV下限を80に引き上げ
        "require_monster": True,    # 鬼脚必須
        "s3_chaos_filter": True,    # カオス細分判定を有効化
        # EV差条件を除外し、EV91以上 or 先行役5人以上の2条件に絞る
        "chaos_buy_leaders_ge": 5,  # 先行役5人以上（超混戦）
        "chaos_buy_ev_ge":      91,  # 軸EV91以上（圧倒的強者）
        "chaos_buy_ev_gap_le":   0,  # EV差条件なし（0以下=実質無効）
    },
}'''

# S3の閉じ括弧 "}" の前にS4を差し込む
old = '''        "chaos_buy_ev_gap_le":   3,  # EV差 N以下（坡抗）
    },
}'''

if old in src:
    new_src = src.replace(old, old.rstrip('}') + s4_block, 1)
    # 末尾の } が重複してしまうので調整
    # もっとシンプルな方法：S3の末尾 "    },\n}" を S4 + "}" に置き換え
    # やり直す
    new_src = src.replace(
        '        "chaos_buy_ev_gap_le":   3,  # EV差 N以下（坡抗）\n    },\n}',
        '        "chaos_buy_ev_gap_le":   3,  # EV差 N以下（坡抗）\n    },\n' + s4_block
    )
    open('hardcore_ev.py', 'w', encoding='utf-8').write(new_src)
    print('S4追加完了')
    # 追加された部分を確認
    lines = new_src.split('\n')
    for i, l in enumerate(lines):
        if 'S4' in l or ('chaos_buy' in l and i > 40):
            print(f'  L{i+1}: {l}')
else:
    print('パターンが見つかりませんでした。手動確認が必要です。')
    # 現在の該当部分を表示
    idx = src.find('chaos_buy_ev_gap_le')
    print(repr(src[idx-10:idx+100]))
