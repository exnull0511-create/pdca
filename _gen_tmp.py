"""S1〜S4の一時実行ファイルを生成する"""
for s in ['S1', 'S2', 'S3', 'S4']:
    src = open('hardcore_ev.py', encoding='utf-8').read()
    src = src.replace('STRATEGY = "S1"', f'STRATEGY = "{s}"', 1)
    open(f'_tmp_{s}.py', 'w', encoding='utf-8').write(src)
print('S1〜S4 生成完了')
