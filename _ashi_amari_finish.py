"""追走鬼脚選手の自走着順を payouts データから突合"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, sys
from collections import defaultdict, Counter

sl = pd.ExcelFile("data/S級DB_slim.xlsx")
df = pd.concat([sl.parse(s) for s in ["F1","G3~1"] if s in sl.sheet_names], ignore_index=True)

def norm(s): return str(s).replace(" ","").replace("\u3000","").strip()
df["選手名_norm"] = df["選手名"].apply(norm)
df["開催日"] = pd.to_datetime(df["開催日"], errors="coerce")

def classify_senpo(s):
    s = str(s).strip()
    if s in ('追走','追い込み','流れ込み','マーク'): return '追走'
    if s in ('逃げ切り','逃げ粘り','逃げ','先行逃げ切り','先行逃げ粘り'): return '逃げ'
    if s in ('先行','抑え先行','カマシ先行','突っ張り先行','先行争い敗'): return '先行'
    if s in ('捲り','一発捲り','ロング捲り','カマシ捲り','番手捲り'): return '捲り'
    if s in ('差し','番手差し','捲り差し'): return '差し'
    if s in ('捲り不発','不発','先行不発','差し不発','失速','捲り追い込み'): return '不発系'
    return 'その他'
df["戦法大分類"] = df["戦法"].apply(classify_senpo)

# 脚余し鬼脚レコード
ashi_amari = df[(df["is_monster"]>=1) & (df["戦法大分類"]=="追走")].copy()
print(f"脚余し鬼脚レコード: {len(ashi_amari)}")

# === payouts_hist と racecard_hist で着順を取得 ===
RC = pd.read_excel("data/racecard_hist.xlsx", dtype={"race_id": str})
PY = pd.read_excel("data/payouts_hist.xlsx", dtype={"race_id": str})
RC["date"] = pd.to_datetime(RC["date"].astype(str), format="%Y%m%d", errors="coerce")
RC["選手名_norm"] = RC["選手名"].apply(norm)
PY["result_trifecta"] = PY["result_trifecta"].astype(str).str.strip()

# (date, venue, race_no, 車番) → race_idマップ
rc_lookup = {}
for _, row in RC.iterrows():
    key = (row["date"], row["venue"], int(row["race_no"]), int(row["車番"]))
    rc_lookup[key] = str(row["race_id"]).strip()

# race_id → result(着順list)
result_lookup = {}
for _, row in PY.iterrows():
    rid = str(row["race_id"]).strip()
    actual = str(row["result_trifecta"]).strip()
    if not actual or actual=="nan": continue
    parts = actual.split("-")
    if len(parts) != 3: continue
    try:
        result_lookup[rid] = [int(p) for p in parts]
    except:
        continue

# 各脚余し鬼脚レコードに対応する着順を取得
finish_positions = []
not_found = 0
for _, rec in ashi_amari.iterrows():
    try:
        date = rec["開催日"]
        venue = str(rec["開催場"]).strip()
        rno = int(rec["レース番号"])
        car = int(rec["車番"])
    except:
        not_found += 1; continue
    key = (date, venue, rno, car)
    rid = rc_lookup.get(key)
    if not rid:
        not_found += 1; continue
    result = result_lookup.get(rid)
    if not result:
        not_found += 1; continue
    if car == result[0]: finish_positions.append(1)
    elif car == result[1]: finish_positions.append(2)
    elif car == result[2]: finish_positions.append(3)
    else: finish_positions.append(0)  # 着外

found = len(finish_positions)
print(f"突合成功: {found}件 / 突合失敗: {not_found}件")

if found == 0:
    print("\n[!] 突合データなし。DB日付とracecard日付の重複を確認:")
    db_dates = set(ashi_amari["開催日"].dt.date)
    rc_dates = set(RC["date"].dt.date)
    overlap = db_dates & rc_dates
    print(f"  DB日付数: {len(db_dates)}")
    print(f"  racecard日付数: {len(rc_dates)}")
    print(f"  重複日付: {len(overlap)}")
    sys.exit(0)

print(f"\n=== 脚余し鬼脚 (追走戦法) の自走着順 ===")
counts = Counter(finish_positions)
for pos in [1, 2, 3, 0]:
    label = f"{pos}着" if pos > 0 else "着外"
    cnt = counts.get(pos, 0)
    print(f"  {label}: {cnt} ({cnt/found*100:.1f}%)")

top3 = sum(counts.get(p,0) for p in [1,2,3])
print(f"\n  3着以内: {top3}/{found} ({top3/found*100:.1f}%)")

# === 比較: 通常鬼脚(捲り) と 通常鬼脚(差し) の着順 ===
print(f"\n=== 比較: 各カテゴリの着順分布 ===")
print(f"{'カテゴリ':>20s}  {'対象数':>6s}  {'1着':>5s}  {'2着':>5s}  {'3着':>5s}  {'着外':>5s}  {'3着内%':>7s}")
print("-"*80)

categories = [
    ("脚余し鬼脚(追走)", df[(df["is_monster"]>=1) & (df["戦法大分類"]=="追走")]),
    ("通常鬼脚(捲り)", df[(df["is_monster"]>=1) & (df["戦法大分類"]=="捲り")]),
    ("通常鬼脚(差し)", df[(df["is_monster"]>=1) & (df["戦法大分類"]=="差し")]),
    ("通常鬼脚(逃げ)", df[(df["is_monster"]>=1) & (df["戦法大分類"]=="逃げ")]),
    ("非鬼脚追走", df[(df["is_monster"]<1) & (df["戦法大分類"]=="追走")]),
    ("非鬼脚捲り", df[(df["is_monster"]<1) & (df["戦法大分類"]=="捲り")]),
]

for name, sub in categories:
    pos_dist = Counter()
    nf = 0
    for _, rec in sub.iterrows():
        try:
            date = rec["開催日"]
            venue = str(rec["開催場"]).strip()
            rno = int(rec["レース番号"])
            car = int(rec["車番"])
        except:
            continue
        key = (date, venue, rno, car)
        rid = rc_lookup.get(key)
        if not rid: continue
        result = result_lookup.get(rid)
        if not result: continue
        nf += 1
        if car == result[0]: pos_dist[1] += 1
        elif car == result[1]: pos_dist[2] += 1
        elif car == result[2]: pos_dist[3] += 1
        else: pos_dist[0] += 1
    if nf == 0: continue
    top3_n = pos_dist[1]+pos_dist[2]+pos_dist[3]
    print(f"  {name:>18s}  {nf:6d}  "
          f"{pos_dist[1]:3d}({pos_dist[1]/nf*100:4.1f}%)  "
          f"{pos_dist[2]:3d}({pos_dist[2]/nf*100:4.1f}%)  "
          f"{pos_dist[3]:3d}({pos_dist[3]/nf*100:4.1f}%)  "
          f"{pos_dist[0]:3d}({pos_dist[0]/nf*100:4.1f}%)  "
          f"{top3_n/nf*100:5.1f}%")
