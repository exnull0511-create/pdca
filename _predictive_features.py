"""予測価値のある特徴量を探す
過去データから計算した特徴 → 当日の着順
"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, sys
from collections import defaultdict, Counter

sl = pd.ExcelFile("data/S級DB_slim.xlsx")
db = pd.concat([sl.parse(s) for s in ["F1","G3~1"] if s in sl.sheet_names], ignore_index=True)

def norm(s): return str(s).replace(" ","").replace("\u3000","").strip()
db["選手名_norm"] = db["選手名"].apply(norm)
db["開催日"] = pd.to_datetime(db["開催日"], errors="coerce")

def classify_senpo(s):
    s = str(s).strip()
    if s in ('追走','追い込み','流れ込み','マーク'): return '追走'
    if s in ('逃げ切り','逃げ粘り','逃げ','先行逃げ切り','先行逃げ粘り'): return '逃げ'
    if s in ('先行','抑え先行','カマシ先行','突っ張り先行','先行争い敗'): return '先行'
    if s in ('捲り','一発捲り','ロング捲り','カマシ捲り','番手捲り'): return '捲り'
    if s in ('差し','番手差し','捲り差し'): return '差し'
    if s in ('捲り不発','不発','先行不発','差し不発','失速','捲り追い込み'): return '不発系'
    return 'その他'
db["戦法大分類"] = db["戦法"].apply(classify_senpo)

def nobi_grade(v):
    s = str(v).strip().upper()
    if s.startswith("S"): return "S"
    if s.startswith("A"): return "A"
    if s.startswith("B"): return "B"
    if s.startswith("C"): return "C"
    return "?"
db["nobi_grade"] = db["直線の伸び"].apply(nobi_grade)

# === Racecard + payouts ===
RC = pd.read_excel("data/racecard_hist.xlsx", dtype={"race_id": str})
PY = pd.read_excel("data/payouts_hist.xlsx", dtype={"race_id": str})
RC["date"] = pd.to_datetime(RC["date"].astype(str), format="%Y%m%d", errors="coerce")
RC["選手名_norm"] = RC["選手名"].apply(norm)
PY["result_trifecta"] = PY["result_trifecta"].astype(str).str.strip()

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

print(f"Racecard rows: {len(RC)}", file=sys.stderr)
print(f"DB rows: {len(db)}", file=sys.stderr)

# === 各レーサー×レースに対して過去の特徴量を計算 ===
print("Computing past features for each rider-race...", file=sys.stderr)
records = []
for _, row in RC.iterrows():
    rid = str(row["race_id"]).strip()
    if rid not in result_lookup: continue
    result = result_lookup[rid]

    nm = row["選手名_norm"]
    car = int(row["車番"])
    race_date = row["date"]

    # 過去レコード
    past = db[(db["選手名_norm"]==nm) & (db["開催日"]<race_date)]
    if past.empty: continue

    # 過去フラグ (any記録に1があれば true)
    is_m = (past["is_monster"]>=1).any()
    is_u = (past["is_unreliable"]>=1).any()

    # 過去の直線の伸び (最頻 or 最高)
    nobi_modes = past["nobi_grade"].value_counts()
    if len(nobi_modes)==0: continue
    nobi_top = nobi_modes.index[0]  # 最頻

    # 過去の戦法分布 (最頻)
    senpo_modes = past["戦法大分類"].value_counts()
    senpo_top = senpo_modes.index[0] if len(senpo_modes) else "?"

    # 着順
    finish = 0
    if car == result[0]: finish = 1
    elif car == result[1]: finish = 2
    elif car == result[2]: finish = 3

    records.append({
        "is_m": is_m, "is_u": is_u,
        "nobi": nobi_top, "senpo_main": senpo_top,
        "finish": finish, "is_top1": finish==1, "is_top3": finish in [1,2,3],
    })

dfr = pd.DataFrame(records)
print(f"\nValid records: {len(dfr)}")
print(f"全体1着率: {dfr['is_top1'].mean()*100:.1f}%")
print(f"全体3着内率: {dfr['is_top3'].mean()*100:.1f}%")

# === 1. 過去フラグの効果 ===
print(f"\n{'='*80}")
print("=== 1. 過去フラグ別の的中率 (予測価値) ===")
print(f"{'='*80}")
print(f"{'フラグ':>15s}  {'件数':>6s}  {'1着率':>6s}  {'3着内率':>7s}")
print("-"*60)
for name, mask in [
    ("過去鬼脚あり", dfr["is_m"]),
    ("過去鬼脚なし", ~dfr["is_m"]),
    ("過去不発あり", dfr["is_u"]),
    ("過去不発なし", ~dfr["is_u"]),
    ("鬼脚かつ不発", dfr["is_m"] & dfr["is_u"]),
    ("鬼脚のみ", dfr["is_m"] & ~dfr["is_u"]),
    ("不発のみ", ~dfr["is_m"] & dfr["is_u"]),
    ("どちらもなし", ~dfr["is_m"] & ~dfr["is_u"]),
]:
    sub = dfr[mask]
    if len(sub)<5: continue
    print(f"  {name:>13s}    {len(sub):6d}  {sub['is_top1'].mean()*100:5.1f}%  {sub['is_top3'].mean()*100:6.1f}%")

# === 2. 過去最頻 直線の伸び ===
print(f"\n{'='*80}")
print("=== 2. 過去の最頻 直線の伸び別 ===")
print(f"{'='*80}")
print(f"{'伸び':>4s}  {'件数':>6s}  {'1着率':>6s}  {'3着内率':>7s}")
print("-"*50)
for grade in ["S","A","B","C","?"]:
    sub = dfr[dfr["nobi"]==grade]
    if len(sub)<10: continue
    print(f"  {grade:>2s}    {len(sub):6d}  {sub['is_top1'].mean()*100:5.1f}%  {sub['is_top3'].mean()*100:6.1f}%")

# === 3. 過去最頻戦法 ===
print(f"\n{'='*80}")
print("=== 3. 過去の最頻戦法別 ===")
print(f"{'='*80}")
print(f"{'戦法':>8s}  {'件数':>6s}  {'1着率':>6s}  {'3着内率':>7s}")
print("-"*55)
for senpo in ['逃げ','先行','捲り','差し','追走','不発系']:
    sub = dfr[dfr["senpo_main"]==senpo]
    if len(sub)<10: continue
    print(f"  {senpo:>6s}    {len(sub):6d}  {sub['is_top1'].mean()*100:5.1f}%  {sub['is_top3'].mean()*100:6.1f}%")

# === 4. 鬼脚 × 過去最頻戦法 ===
print(f"\n{'='*80}")
print("=== 4. 過去鬼脚 × 過去最頻戦法 ===")
print(f"{'='*80}")
print(f"{'鬼脚':>6s}  {'戦法':>8s}  {'件数':>6s}  {'1着率':>6s}  {'3着内率':>7s}")
print("-"*65)
for is_m_val in [True, False]:
    for senpo in ['逃げ','先行','捲り','差し','追走','不発系']:
        sub = dfr[(dfr["is_m"]==is_m_val) & (dfr["senpo_main"]==senpo)]
        if len(sub)<10: continue
        label = "鬼脚" if is_m_val else "通常"
        print(f"  {label:>4s}  {senpo:>6s}    {len(sub):6d}  {sub['is_top1'].mean()*100:5.1f}%  {sub['is_top3'].mean()*100:6.1f}%")

# === 5. 鬼脚 × 直線伸び ===
print(f"\n{'='*80}")
print("=== 5. 過去鬼脚 × 過去最頻 直線の伸び ===")
print(f"{'='*80}")
print(f"{'鬼脚':>6s}  {'伸び':>4s}  {'件数':>6s}  {'1着率':>6s}  {'3着内率':>7s}")
print("-"*55)
for is_m_val in [True, False]:
    for grade in ["S","A","B","C"]:
        sub = dfr[(dfr["is_m"]==is_m_val) & (dfr["nobi"]==grade)]
        if len(sub)<10: continue
        label = "鬼脚" if is_m_val else "通常"
        print(f"  {label:>4s}  {grade:>2s}    {len(sub):6d}  {sub['is_top1'].mean()*100:5.1f}%  {sub['is_top3'].mean()*100:6.1f}%")

# === 6. 4次元組合せから「使える」パターンを洗い出し ===
print(f"\n{'='*80}")
print("=== 6. 4次元組合せ Top10/Bottom10 ===")
print(f"{'='*80}")
combos = []
for is_m_val in [True, False]:
    for is_u_val in [True, False]:
        for senpo in ['逃げ','先行','捲り','差し','追走','不発系']:
            for grade in ["S","A","B","C"]:
                mask = ((dfr["is_m"]==is_m_val) & (dfr["is_u"]==is_u_val) &
                        (dfr["senpo_main"]==senpo) & (dfr["nobi"]==grade))
                sub = dfr[mask]
                if len(sub)<10: continue
                combos.append({
                    "name": f"{'鬼脚' if is_m_val else '通常'}+{'不発' if is_u_val else '正常'}+{senpo}+伸{grade}",
                    "n": len(sub),
                    "top1": sub["is_top1"].mean()*100,
                    "top3": sub["is_top3"].mean()*100,
                })

print(f"\n--- 3着内率 上位10 (n>=10) ---")
print(f"{'組合せ':>30s}  {'件数':>5s}  {'1着率':>6s}  {'3着内率':>7s}")
for c in sorted(combos, key=lambda x:-x["top3"])[:10]:
    print(f"  {c['name']:>28s}  {c['n']:5d}  {c['top1']:5.1f}%  {c['top3']:6.1f}%")

print(f"\n--- 3着内率 下位10 ---")
for c in sorted(combos, key=lambda x:x["top3"])[:10]:
    print(f"  {c['name']:>28s}  {c['n']:5d}  {c['top1']:5.1f}%  {c['top3']:6.1f}%")

# === 7. リフト分析: ベースラインとの差で重要な特徴を発見 ===
print(f"\n{'='*80}")
print("=== 7. 単一特徴のリフト (vs ベースライン3着内率) ===")
print(f"{'='*80}")
baseline_t3 = dfr["is_top3"].mean()*100
print(f"ベースライン: {baseline_t3:.1f}%\n")
print(f"{'特徴':>20s}  {'件数':>6s}  {'3着内率':>7s}  {'リフト':>7s}")
print("-"*55)

# 単一特徴のリフト
features = [
    ("過去鬼脚", dfr["is_m"]),
    ("過去不発", dfr["is_u"]),
    ("伸びS", dfr["nobi"]=="S"),
    ("伸びA", dfr["nobi"]=="A"),
    ("伸びB", dfr["nobi"]=="B"),
    ("伸びC", dfr["nobi"]=="C"),
    ("最頻=逃げ", dfr["senpo_main"]=="逃げ"),
    ("最頻=捲り", dfr["senpo_main"]=="捲り"),
    ("最頻=差し", dfr["senpo_main"]=="差し"),
    ("最頻=追走", dfr["senpo_main"]=="追走"),
]
for name, mask in features:
    sub = dfr[mask]
    if len(sub)<10: continue
    t3 = sub["is_top3"].mean()*100
    lift = t3 - baseline_t3
    print(f"  {name:>18s}    {len(sub):6d}  {t3:6.1f}%  {lift:+6.1f}%")
