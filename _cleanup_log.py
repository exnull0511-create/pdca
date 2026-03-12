import csv

with open('data/bets_log.csv', 'r', encoding='utf-8') as f:
    rows = list(csv.reader(f))

keep = [rows[0]]
for r in rows[1:]:
    if r and r[0] != '2026-03-12':
        keep.append(r)

print(f'クリーン後: {len(keep)-1}件')
for r in keep[1:]:
    print(f'  {r[0]} {r[2]} {r[4]}R')

with open('data/bets_log.csv', 'w', newline='', encoding='utf-8') as f:
    csv.writer(f).writerows(keep)

print('保存完了')
