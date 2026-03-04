"""
keirin_app.py の run_s3_prediction 呼び出しに
relations_df を追加するパッチスクリプト
"""
content = open(r'c:\pdca\keirin_app.py', encoding='utf-8').read()

# 1. db_all の直後に relations を追加（main関数の初期化部分）
old_init = '    db_all  = get_sclass_db()'
new_init = ('    db_all     = get_sclass_db()\n'
            '    relations  = get_racer_relations()')
if old_init in content and 'relations  = get_racer_relations()' not in content:
    content = content.replace(old_init, new_init, 1)
    print('db_all init updated')
else:
    print('db_all init: already updated or not found')

# 2. run_s3_prediction の呼び出しに relations_df= を追加
old_call = ("                pred = run_s3_prediction(\n"
            "                    race_card_df=race_card,\n"
            "                    lines=lines,\n"
            "                    \n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\nodds_df=odds,\n"
            "                    db_all=db_all,\n"
            "                    venue=sel_venue['venue_name'],\n"
            "                    race_date=st.session_state.get('disp_date', date.today())")

# より柔軟な置換：race_date= 行の後に relations_df= を追加
import re

pattern = r"(pred = run_s3_prediction\(.*?race_date=st\.session_state\.get\('disp_date', date\.today\(\)\))"
replacement_suffix = r"\1,\n                    relations_df=relations"

if 'relations_df=relations' not in content:
    new_content = re.sub(pattern, replacement_suffix, content, flags=re.DOTALL)
    if new_content != content:
        content = new_content
        print('run_s3_prediction call updated with relations_df')
    else:
        print('WARNING: pattern not matched for run_s3_prediction')
else:
    print('relations_df already in call')

open(r'c:\pdca\keirin_app.py', 'w', encoding='utf-8').write(content)
print('Done')
