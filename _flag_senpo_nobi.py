"""フラグ × 戦法 × 直線の伸び の相関分析と予測価値の調査"""
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

# 直線の伸び正規化
def nobi_grade(v):
    s = str(v).strip().upper()
    if s.startswith("S"): return "S"
    if s.startswith("A"): return "A"
    if s.startswith("B"): return "B"
    if s.startswith("C"): return "C"
    return "?"
df["nobi_grade"] = df["直線の伸び"].apply(nobi_grade)

# === 着順を取得するための準備 ===
RC = pd.read_excel("data/racecard_hist.xlsx", dtype={"race_id": str})
PY = pd.read_excel("data/payouts_hist.xlsx", dtype={"race_id": str})
RC["date"] = pd.to_datetime(RC["date"].astype(str), format="%Y%m%d", errors="coerce")
PY["result_trifecta"] = PY["result_trifecta"].astype(str).str.strip()

rc_lookup = {}
for _, row in RC.iterrows():
    key = (row["date"], row["venue"], int(row["race_no"]), int(row["車番"]))
    rc_lookup[key] = str(row["race_id"]).strip()

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

def get_finish(rec):
    """DBレコードに対する着順を返す。1-3 = 着, 0 = 着外, None = 不明"""
    try:
        date = rec["開催日"]
        venue = str(rec["開催場"]).strip()
        rno = int(rec["レース番号"])
        car = int(rec["車番"])
    except:
        return None
    key = (date, venue, rno, car)
    rid = rc_lookup.get(key)
    if not rid: return None
    result = result_lookup.get(rid)
    if not result: return None
    if car == result[0]: return 1
    if car == result[1]: return 2
    if car == result[2]: return 3
    return 0

# 各DBレコードに着順付与
print("着順取得中...", file=sys.stderr)
df["finish"] = df.apply(get_finish, axis=1)
matched = df["finish"].notna().sum()
print(f"突合成功: {matched}/{len(df)}", file=sys.stderr)

df_match = df[df["finish"].notna()].copy()
df_match["is_top1"] = (df_match["finish"]==1).astype(int)
df_match["is_top3"] = df_match["finish"].isin([1,2,3]).astype(int)

print(f"\n突合データ: {len(df_match)}レコード")
print(f"全体的中率(1着): {df_match['is_top1'].mean()*100:.1f}%")
print(f"全体的中率(3着内): {df_match['is_top3'].mean()*100:.1f}%")

# === 1. 直線の伸び×フラグ ===
print(f"\n{'='*90}")
print("=== 1. 直線の伸び × is_monster の的中率 ===")
print(f"{'='*90}")
print(f"{'伸び':>4s}  {'モンスター':>10s}  {'件数':>5s}  {'1着率':>6s}  {'3着内率':>7s}")
print("-"*55)
for grade in ["S","A","B","C","?"]:
    for is_m in [1, 0]:
        sub = df_match[(df_match["nobi_grade"]==grade) & (df_match["is_monster"]>=1 if is_m else df_match["is_monster"]<1)]
        if len(sub) < 5: continue
        label = "鬼脚" if is_m else "通常"
        print(f"  {grade:>2s}    {label:>8s}    {len(sub):5d}  {sub['is_top1'].mean()*100:5.1f}%  {sub['is_top3'].mean()*100:6.1f}%")

# === 2. 戦法×直線の伸び ===
print(f"\n{'='*90}")
print("=== 2. 戦法 × 直線の伸び の的中率 ===")
print(f"{'='*90}")
print(f"{'戦法':>8s}  {'伸び':>4s}  {'件数':>5s}  {'1着率':>6s}  {'3着内率':>7s}")
print("-"*55)
for senpo in ['逃げ','先行','捲り','差し','追走','不発系']:
    for grade in ["S","A","B","C"]:
        sub = df_match[(df_match["戦法大分類"]==senpo) & (df_match["nobi_grade"]==grade)]
        if len(sub) < 10: continue
        print(f"  {senpo:>6s}  {grade:>2s}    {len(sub):5d}  {sub['is_top1'].mean()*100:5.1f}%  {sub['is_top3'].mean()*100:6.1f}%")

# === 3. 鬼脚×戦法×伸び 三元 ===
print(f"\n{'='*90}")
print("=== 3. 鬼脚 × 戦法 × 直線の伸び (3着内率) ===")
print(f"{'='*90}")
print(f"{'is_m':>5s}  {'戦法':>8s}  {'伸び':>4s}  {'件数':>5s}  {'1着率':>6s}  {'3着内率':>7s}")
print("-"*65)
for is_m_val in [1, 0]:
    label = "鬼脚" if is_m_val else "非鬼脚"
    for senpo in ['捲り','差し','追走','逃げ','先行']:
        for grade in ["S","A","B","C"]:
            sub = df_match[
                ((df_match["is_monster"]>=1) if is_m_val else (df_match["is_monster"]<1)) &
                (df_match["戦法大分類"]==senpo) &
                (df_match["nobi_grade"]==grade)
            ]
            if len(sub) < 5: continue
            mark = ""
            if sub['is_top3'].mean() > 0.7: mark = " ★高的中"
            elif sub['is_top3'].mean() > 0.5: mark = " ◎"
            elif sub['is_top3'].mean() < 0.15: mark = " ✕低的中"
            print(f"  {label:>5s}  {senpo:>6s}  {grade:>2s}    {len(sub):5d}  "
                  f"{sub['is_top1'].mean()*100:5.1f}%  {sub['is_top3'].mean()*100:6.1f}%{mark}")

# === 4. is_unreliable × 戦法 ===
print(f"\n{'='*90}")
print("=== 4. is_unreliable × 戦法 の的中率 ===")
print(f"{'='*90}")
print(f"{'is_u':>6s}  {'戦法':>8s}  {'件数':>5s}  {'1着率':>6s}  {'3着内率':>7s}  {'差(vs通常)':>10s}")
print("-"*70)
for senpo in ['逃げ','先行','捲り','差し','追走','不発系']:
    base = df_match[(df_match["is_unreliable"]<1) & (df_match["戦法大分類"]==senpo)]
    sub = df_match[(df_match["is_unreliable"]>=1) & (df_match["戦法大分類"]==senpo)]
    if len(sub) < 5: continue
    base_t3 = base["is_top3"].mean()*100 if len(base)>0 else 0
    sub_t3 = sub["is_top3"].mean()*100
    print(f"  不発  {senpo:>6s}    {len(sub):5d}  "
          f"{sub['is_top1'].mean()*100:5.1f}%  {sub_t3:6.1f}%   {sub_t3-base_t3:+6.1f}%")

# === 5. 鬼脚 × 不発フラグ重複 ===
print(f"\n{'='*90}")
print("=== 5. 鬼脚と不発のフラグ重複パターン ===")
print(f"{'='*90}")
patterns = [
    ("鬼脚のみ", (df_match["is_monster"]>=1) & (df_match["is_unreliable"]<1)),
    ("不発のみ", (df_match["is_monster"]<1) & (df_match["is_unreliable"]>=1)),
    ("両方", (df_match["is_monster"]>=1) & (df_match["is_unreliable"]>=1)),
    ("どちらもなし", (df_match["is_monster"]<1) & (df_match["is_unreliable"]<1)),
]
print(f"{'パターン':>14s}  {'件数':>5s}  {'1着率':>6s}  {'3着内率':>7s}")
for name, mask in patterns:
    sub = df_match[mask]
    if len(sub)==0: continue
    print(f"  {name:>12s}    {len(sub):5d}  {sub['is_top1'].mean()*100:5.1f}%  {sub['is_top3'].mean()*100:6.1f}%")

# === 6. 鬼脚 + 直線S/A の威力 ===
print(f"\n{'='*90}")
print("=== 6. 鬼脚×直線S/A 組合せの予測価値 ===")
print(f"{'='*90}")
combos = [
    ("鬼脚+S", (df_match["is_monster"]>=1) & (df_match["nobi_grade"]=="S")),
    ("鬼脚+A", (df_match["is_monster"]>=1) & (df_match["nobi_grade"]=="A")),
    ("鬼脚+B", (df_match["is_monster"]>=1) & (df_match["nobi_grade"]=="B")),
    ("鬼脚+C", (df_match["is_monster"]>=1) & (df_match["nobi_grade"]=="C")),
    ("鬼脚+S/A", (df_match["is_monster"]>=1) & (df_match["nobi_grade"].isin(["S","A"]))),
    ("非鬼脚+S", (df_match["is_monster"]<1) & (df_match["nobi_grade"]=="S")),
    ("非鬼脚+A", (df_match["is_monster"]<1) & (df_match["nobi_grade"]=="A")),
]
print(f"{'組合せ':>10s}  {'件数':>5s}  {'1着率':>6s}  {'3着内率':>7s}")
for name, mask in combos:
    sub = df_match[mask]
    if len(sub)<3: continue
    print(f"  {name:>8s}    {len(sub):5d}  {sub['is_top1'].mean()*100:5.1f}%  {sub['is_top3'].mean()*100:6.1f}%")

# === 7. 不発 + 直線弱 = 完全に避けるべき選手か ===
print(f"\n{'='*90}")
print("=== 7. 不発×直線評価 (避けるべきパターンの探索) ===")
print(f"{'='*90}")
print(f"{'組合せ':>14s}  {'件数':>5s}  {'1着率':>6s}  {'3着内率':>7s}")
combos2 = [
    ("不発+S", (df_match["is_unreliable"]>=1) & (df_match["nobi_grade"]=="S")),
    ("不発+A", (df_match["is_unreliable"]>=1) & (df_match["nobi_grade"]=="A")),
    ("不発+B", (df_match["is_unreliable"]>=1) & (df_match["nobi_grade"]=="B")),
    ("不発+C", (df_match["is_unreliable"]>=1) & (df_match["nobi_grade"]=="C")),
]
for name, mask in combos2:
    sub = df_match[mask]
    if len(sub)<3: continue
    print(f"  {name:>12s}    {len(sub):5d}  {sub['is_top1'].mean()*100:5.1f}%  {sub['is_top3'].mean()*100:6.1f}%")

# === 8. ベスト/ワーストTop10の組合せを発見 ===
print(f"\n{'='*90}")
print("=== 8. 最強/最弱の(鬼脚×不発×戦法×伸び)組合せ ===")
print(f"{'='*90}")
all_combos = []
for is_m_val in [True, False]:
    for is_u_val in [True, False]:
        for senpo in ['捲り','差し','追走','逃げ','先行','不発系']:
            for grade in ["S","A","B","C"]:
                mask = (
                    ((df_match["is_monster"]>=1) if is_m_val else (df_match["is_monster"]<1)) &
                    ((df_match["is_unreliable"]>=1) if is_u_val else (df_match["is_unreliable"]<1)) &
                    (df_match["戦法大分類"]==senpo) &
                    (df_match["nobi_grade"]==grade)
                )
                sub = df_match[mask]
                if len(sub) < 5: continue
                m_str = "鬼脚" if is_m_val else "通常"
                u_str = "不発" if is_u_val else "正常"
                all_combos.append({
                    "name": f"{m_str}+{u_str}+{senpo}+伸{grade}",
                    "n": len(sub),
                    "top1": sub["is_top1"].mean()*100,
                    "top3": sub["is_top3"].mean()*100,
                })

print(f"\n--- 3着内率 上位10 (件数>=5) ---")
print(f"{'組合せ':>30s}  {'件数':>4s}  {'1着率':>6s}  {'3着内率':>7s}")
for c in sorted(all_combos, key=lambda x:-x["top3"])[:10]:
    print(f"  {c['name']:>28s}  {c['n']:4d}  {c['top1']:5.1f}%  {c['top3']:6.1f}%")

print(f"\n--- 3着内率 下位10 ---")
for c in sorted(all_combos, key=lambda x:x["top3"])[:10]:
    print(f"  {c['name']:>28s}  {c['n']:4d}  {c['top1']:5.1f}%  {c['top3']:6.1f}%")
