#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""keirin_app.py の配線修正スクリプト"""
import re

path = r'c:\pdca\keirin_app.py'
with open(path, encoding='utf-8') as f:
    txt = f.read()

# 1. import行を更新
old_imp = 'from s3_predictor import run_s3_prediction, load_sclass_db'
new_imp = 'from s3_predictor import run_s3_prediction, load_sclass_db, load_racer_relations'
if old_imp in txt:
    txt = txt.replace(old_imp, new_imp, 1)
    print('✅ import更新済み')
else:
    print('⚠ import行が見つかりません')

# 2. パス定数を追加（SCLASS_DB_PATHの行の直後にRACER_RELATIONS_PATHを追加）
old_path = "SCLASS_DB_PATH = r\"C:\\pdca\\data\\S級選手究極DB (1).xlsx\""
new_path = ("SCLASS_DB_PATH       = r\"C:\\pdca\\data\\S級選手究極DB (1).xlsx\"\n"
            "RACER_RELATIONS_PATH = r\"C:\\pdca\\data\\s_class_racers.csv\"")
if old_path in txt:
    txt = txt.replace(old_path, new_path, 1)
    print('✅ パス定数更新済み')
elif 'RACER_RELATIONS_PATH' in txt:
    print('ℹ パス定数は既に追加済み')
else:
    print('⚠ SCLASS_DB_PATHが見つかりません')

# 3. get_sclass_db の後に get_racer_relations キャッシュ関数を追加
if 'get_racer_relations' not in txt:
    old_fn = ('@st.cache_resource\n'
              'def get_sclass_db():\n'
              '    if os.path.exists(SCLASS_DB_PATH):\n'
              '        return load_sclass_db(SCLASS_DB_PATH)\n'
              '    return None')
    new_fn = (old_fn + '\n\n\n'
              '@st.cache_resource\n'
              'def get_racer_relations():\n'
              '    """s_class_racers.csv をロードしキャッシュする"""\n'
              '    if os.path.exists(RACER_RELATIONS_PATH):\n'
              '        return load_racer_relations(RACER_RELATIONS_PATH)\n'
              '    return None')
    if old_fn in txt:
        txt = txt.replace(old_fn, new_fn, 1)
        print('✅ get_racer_relations関数追加済み')
    else:
        print('⚠ get_sclass_db関数が見つかりません')
else:
    print('ℹ get_racer_relations関数は既に存在する')

# 4. main()内で db_all のすぐ後に relations_df をロード
if 'relations_df' not in txt:
    old_load = 'db_all  = get_sclass_db()'
    new_load = ('db_all       = get_sclass_db()\n'
                '    relations_df = get_racer_relations()')
    if old_load in txt:
        txt = txt.replace(old_load, new_load, 1)
        print('✅ relations_dfロード追加済み')
    else:
        print('⚠ db_all = get_sclass_db()が見つかりません')
else:
    print('ℹ relations_dfは既に存在する')

# 5. run_s3_prediction の呼び出しに relations_df= を追加
old_call = (
    'run_s3_prediction(\n'
    '                race_card=d[\'race_card\'],\n'
)
# 引数パターンを柔軟に探す
for pattern in [
    "run_s3_prediction(\n                race_card_df=",
    "run_s3_prediction(\n                    race_card_df=",
]:
    if pattern in txt:
        # race_dateの行の後にrelations_dfを挿入
        txt = txt.replace(
            "race_date=st.session_state.selected_date,\n",
            "race_date=st.session_state.selected_date,\n                    relations_df=relations_df,\n",
            1
        )
        print('✅ run_s3_prediction呼び出しにrelations_df追加済み')
        break
else:
    # race_dateで直接探す
    if 'race_date=st.session_state.selected_date,' in txt and 'relations_df=relations_df' not in txt:
        txt = txt.replace(
            'race_date=st.session_state.selected_date,',
            'race_date=st.session_state.selected_date,\n                    relations_df=relations_df,',
            1
        )
        print('✅ run_s3_prediction呼び出しにrelations_df追加済み（パターン2）')
    else:
        print('ℹ relations_dfは既に追加済みかrun_s3_prediction呼び出しが見つかりません')

with open(path, 'w', encoding='utf-8') as f:
    f.write(txt)

print('\n🏁 修正完了')
