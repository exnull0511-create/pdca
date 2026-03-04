"""keirin_app.py に load_racer_relations import と RACER_RELATIONS_PATH を追加するパッチ"""
content = open(r'c:\pdca\keirin_app.py', encoding='utf-8').read()

# import行の置換
old_import = 'from s3_predictor import run_s3_prediction, load_sclass_db'
new_import = 'from s3_predictor import run_s3_prediction, load_sclass_db, load_racer_relations'
if old_import in content:
    content = content.replace(old_import, new_import, 1)
    print('import updated')
else:
    print('import already updated or not found')

# SCLASS_DB_PATH の後に RACER_RELATIONS_PATH を追加
old_path = 'SCLASS_DB_PATH = r"C:\\pdca\\data\\S級選手究極DB (1).xlsx"'
new_path = ('SCLASS_DB_PATH       = r"C:\\pdca\\data\\S級選手究極DB (1).xlsx"\n'
            'RACER_RELATIONS_PATH = r"C:\\pdca\\data\\s_class_racers.csv"')
if 'RACER_RELATIONS_PATH' not in content:
    if old_path in content:
        content = content.replace(old_path, new_path, 1)
        print('path updated')
    else:
        print('path line not found:', repr(old_path[:50]))
else:
    print('RACER_RELATIONS_PATH already exists')

open(r'c:\pdca\keirin_app.py', 'w', encoding='utf-8').write(content)
print('Done')
