src = open('hardcore_ev.py', encoding='utf-8').read()
src = src.replace('STRATEGY = "S1"', 'STRATEGY = "S4"', 1)
open('_tmp_s4.py', 'w', encoding='utf-8').write(src)
print('done')
