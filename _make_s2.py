content = open('hardcore_ev.py', encoding='utf-8').read()
content2 = content.replace('STRATEGY = "S1"', 'STRATEGY = "S2"', 1)
open('_tmp_s2.py', 'w', encoding='utf-8').write(content2)
print('S2用ファイル作成完了')
