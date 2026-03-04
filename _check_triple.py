"""
S2∩S3∩S4 通過レースの的中状況を確認する
ログファイルを行単位で読み込み（大きなDOTALL regexを避ける）
"""
import re

TRIPLE_IDS = {
    '2320260217010007','2420260131030008','2420260214010009','2420260214030006',
    '2720260203020009','2820260209010011','2820260209010012','3120260204010011',
    '3720260220010006','3720260220010011','4520260223010006','4520260223010009',
    '4720260201030009','7420260210010008','8620260212010009','8620260212010012',
    '8720260220010012','8720260220030001',
}

id_pat  = re.compile(r'Race ID: (\S+)')
hit_pat = re.compile(r'(的中|ハズレ|払戻未集計|結果データなし)')
pay_pat = re.compile(r'払戻: ¥([\d,]+)')

def parse_log(fname):
    """行単位でログを読み、triple_ids に該当するレースの結果を返す"""
    results = {}
    cur_id  = None
    try:
        with open(fname, encoding='utf-8') as f:
            for line in f:
                m = id_pat.search(line)
                if m:
                    cur_id = m.group(1)
                    continue
                if cur_id and cur_id in TRIPLE_IDS:
                    h = hit_pat.search(line)
                    if h:
                        tag = h.group(1)
                        if tag == '的中':
                            p = pay_pat.search(line)
                            results[cur_id] = f'的中 ¥{p.group(1)}' if p else '的中'
                        elif cur_id not in results:
                            results[cur_id] = tag
    except FileNotFoundError:
        pass
    return results

data = {s: parse_log(f'iteration_1_logs_{s}.txt') for s in ['S2','S3','S4']}

# 集計
print(f"{'race_id':22}  {'S2':20}  {'S3':20}  {'S4':20}")
print('-' * 88)

hit_all = 0
for rid in sorted(TRIPLE_IDS):
    s2 = data['S2'].get(rid, '?')
    s3 = data['S3'].get(rid, '?')
    s4 = data['S4'].get(rid, '?')
    mark = ' ★' if '的中' in s2 or '的中' in s3 or '的中' in s4 else ''
    print(f"{rid:22}  {s2:20}  {s3:20}  {s4:20}{mark}")
    if '的中' in s2 or '的中' in s3 or '的中' in s4:
        hit_all += 1

print()
print(f'18 レース中 {hit_all} レースで少なくとも1ストラテジーが的中')
hit3 = sum(1 for rid in TRIPLE_IDS
           if '的中' in data['S2'].get(rid,'')
           and '的中' in data['S3'].get(rid,'')
           and '的中' in data['S4'].get(rid,''))
print(f'S2∩S3∩S4 全部的中: {hit3} レース')
