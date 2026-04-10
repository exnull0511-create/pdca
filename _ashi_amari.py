"""脚余し鬼脚(鬼脚+追走)の次走パフォーマンス検証"""
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
    if s in ('逃げ切り','逃げ粘り','逃げ','先行逃げ切り','先行逃げ粘り'): return '逃げ'
    if s in ('先行','抑え先行','カマシ先行','突っ張り先行','先行争い敗'): return '先行'
    if s in ('捲り','一発捲り','ロング捲り','カマシ捲り','番手捲り'): return '捲り'
    if s in ('差し','番手差し','捲り差し'): return '差し'
    if s in ('追走','追い込み','流れ込み','マーク'): return '追走'
    if s in ('捲り不発','不発','先行不発','差し不発','失速','捲り追い込み'): return '不発系'
    return 'その他'
df["戦法大分類"] = df["戦法"].apply(classify_senpo)

# === 1. 鬼脚+追走 (脚余し疑い) の選手リスト ===
ashi_amari = df[(df["is_monster"]>=1) & (df["戦法大分類"]=="追走")]
print(f"=== 鬼脚+追走 (脚余し) のレコード: {len(ashi_amari)} ===")

# === 2. 各脚余しレコードの「次走」を追跡 ===
# 同じ選手の次のレコード(時系列)を取得
df_sorted = df.sort_values(["選手名_norm","開催日"]).reset_index(drop=True)
df_sorted["next_idx"] = df_sorted.index + 1

# 同じ選手の次レコードのみ次走として扱う
def get_next_record(idx, name_norm):
    next_idx = idx + 1
    if next_idx >= len(df_sorted): return None
    if df_sorted.iloc[next_idx]["選手名_norm"] != name_norm: return None
    return df_sorted.iloc[next_idx]

# 全体の次走戦法分布のベースライン
all_next_dist = Counter()
for idx in range(len(df_sorted)-1):
    nm = df_sorted.iloc[idx]["選手名_norm"]
    next_rec = get_next_record(idx, nm)
    if next_rec is not None:
        all_next_dist[next_rec["戦法大分類"]] += 1
total_all_next = sum(all_next_dist.values())

# 脚余し鬼脚レコードの次走を追跡
ashi_indices = df_sorted[(df_sorted["is_monster"]>=1) & (df_sorted["戦法大分類"]=="追走")].index
ashi_next_dist = Counter()
ashi_next_records = []
for idx in ashi_indices:
    nm = df_sorted.iloc[idx]["選手名_norm"]
    next_rec = get_next_record(idx, nm)
    if next_rec is not None:
        ashi_next_dist[next_rec["戦法大分類"]] += 1
        ashi_next_records.append(next_rec)
total_ashi_next = sum(ashi_next_dist.values())

# 普通の鬼脚(追走以外)の次走分布も取得
normal_monster_indices = df_sorted[(df_sorted["is_monster"]>=1) & (df_sorted["戦法大分類"]!="追走")].index
normal_next_dist = Counter()
for idx in normal_monster_indices:
    nm = df_sorted.iloc[idx]["選手名_norm"]
    next_rec = get_next_record(idx, nm)
    if next_rec is not None:
        normal_next_dist[next_rec["戦法大分類"]] += 1
total_normal_next = sum(normal_next_dist.values())

# 非鬼脚の次走分布
non_monster_indices = df_sorted[df_sorted["is_monster"]<1].index
non_m_next_dist = Counter()
for idx in non_monster_indices[:5000]:  # サンプリング
    nm = df_sorted.iloc[idx]["選手名_norm"]
    next_rec = get_next_record(idx, nm)
    if next_rec is not None:
        non_m_next_dist[next_rec["戦法大分類"]] += 1
total_non_m_next = sum(non_m_next_dist.values())

print(f"\n{'='*80}")
print(f"=== 次走の戦法分布比較 ===")
print(f"{'='*80}")
print(f"{'戦法':>8s}  {'脚余し鬼脚→次走':>16s}  {'通常鬼脚→次走':>14s}  {'非鬼脚→次走':>13s}  {'全体':>8s}")
print("-"*80)
for s in ['逃げ','先行','捲り','差し','追走','不発系']:
    a_pct = ashi_next_dist.get(s,0)/total_ashi_next*100 if total_ashi_next else 0
    n_pct = normal_next_dist.get(s,0)/total_normal_next*100 if total_normal_next else 0
    nm_pct = non_m_next_dist.get(s,0)/total_non_m_next*100 if total_non_m_next else 0
    all_pct = all_next_dist.get(s,0)/total_all_next*100 if total_all_next else 0
    print(f"  {s:>6s}  {ashi_next_dist.get(s,0):8d} ({a_pct:4.1f}%)  "
          f"{normal_next_dist.get(s,0):6d} ({n_pct:4.1f}%)  "
          f"{non_m_next_dist.get(s,0):5d} ({nm_pct:4.1f}%)  "
          f"{all_pct:5.1f}%")
print(f"\n  N      {total_ashi_next:8d}             {total_normal_next:6d}             {total_non_m_next:5d}")


# === 3. 脚余し鬼脚 → 次走で再度is_monsterフラグが付いた率 ===
print(f"\n{'='*80}")
print(f"=== 脚余し鬼脚の継続性 (次走で再度鬼脚フラグ) ===")
print(f"{'='*80}")

ashi_next_monster = sum(1 for r in ashi_next_records if r["is_monster"]>=1)
print(f"\n脚余し鬼脚の次走で再度鬼脚: {ashi_next_monster}/{total_ashi_next} ({ashi_next_monster/total_ashi_next*100:.1f}%)")

# 通常鬼脚の次走で再度鬼脚率
normal_next_records = []
for idx in normal_monster_indices:
    nm = df_sorted.iloc[idx]["選手名_norm"]
    nr = get_next_record(idx, nm)
    if nr is not None: normal_next_records.append(nr)
normal_next_monster = sum(1 for r in normal_next_records if r["is_monster"]>=1)
print(f"通常鬼脚の次走で再度鬼脚:   {normal_next_monster}/{len(normal_next_records)} ({normal_next_monster/len(normal_next_records)*100:.1f}%)")

# 非鬼脚の次走で鬼脚になる率(ベースライン)
non_m_next_records = []
for idx in non_monster_indices[:5000]:
    nm = df_sorted.iloc[idx]["選手名_norm"]
    nr = get_next_record(idx, nm)
    if nr is not None: non_m_next_records.append(nr)
non_m_next_monster = sum(1 for r in non_m_next_records if r["is_monster"]>=1)
print(f"非鬼脚の次走で鬼脚:         {non_m_next_monster}/{len(non_m_next_records)} ({non_m_next_monster/len(non_m_next_records)*100:.1f}%)")


# === 4. 「鬼脚+追走」と「鬼脚+捲り」と「非鬼脚」の能力値比較 ===
print(f"\n{'='*80}")
print(f"=== 各パターンの能力値 ===")
print(f"{'='*80}")
print(f"{'パターン':>20s}  {'IP':>6s}  {'EP':>6s}  {'DP':>6s}  {'BP':>6s}  {'件数':>5s}")
print("-"*70)

categories = [
    ("脚余し鬼脚(鬼脚+追走)", df[(df["is_monster"]>=1) & (df["戦法大分類"]=="追走")]),
    ("通常鬼脚(鬼脚+捲り)", df[(df["is_monster"]>=1) & (df["戦法大分類"]=="捲り")]),
    ("通常鬼脚(鬼脚+差し)", df[(df["is_monster"]>=1) & (df["戦法大分類"]=="差し")]),
    ("非鬼脚追走", df[(df["is_monster"]<1) & (df["戦法大分類"]=="追走")]),
    ("非鬼脚捲り", df[(df["is_monster"]<1) & (df["戦法大分類"]=="捲り")]),
]
for name, sub in categories:
    if len(sub)==0: continue
    print(f"  {name:>18s}  "
          f"{pd.to_numeric(sub['IP'],errors='coerce').mean():6.2f}  "
          f"{pd.to_numeric(sub['EP'],errors='coerce').mean():6.2f}  "
          f"{pd.to_numeric(sub['DP'],errors='coerce').mean():6.2f}  "
          f"{pd.to_numeric(sub['BP'],errors='coerce').mean():6.2f}  "
          f"{len(sub):5d}")


# === 5. 直近2レースのフラグから「次走鬼脚予測」の精度 ===
print(f"\n{'='*80}")
print(f"=== 直近2走の脚余し鬼脚 → 次走鬼脚率 ===")
print(f"{'='*80}")

# 連続2走で脚余し鬼脚 → 3走目の鬼脚率を計算
double_ashi_next = []
for idx in range(len(df_sorted)-2):
    cur = df_sorted.iloc[idx]
    nxt = df_sorted.iloc[idx+1]
    if (cur["選手名_norm"] != nxt["選手名_norm"]): continue
    if cur["is_monster"]>=1 and cur["戦法大分類"]=="追走" and \
       nxt["is_monster"]>=1 and nxt["戦法大分類"]=="追走":
        # 3走目を取得
        if idx+2 >= len(df_sorted): continue
        third = df_sorted.iloc[idx+2]
        if third["選手名_norm"] != cur["選手名_norm"]: continue
        double_ashi_next.append(third)

print(f"\n2走連続脚余し鬼脚: {len(double_ashi_next)}件")
if double_ashi_next:
    next_monster = sum(1 for r in double_ashi_next if r["is_monster"]>=1)
    next_kuri = sum(1 for r in double_ashi_next if r["戦法大分類"]=="捲り")
    next_sashi = sum(1 for r in double_ashi_next if r["戦法大分類"]=="差し")
    print(f"  → 3走目で鬼脚継続: {next_monster}/{len(double_ashi_next)} ({next_monster/len(double_ashi_next)*100:.1f}%)")
    print(f"  → 3走目で捲り発動: {next_kuri}/{len(double_ashi_next)} ({next_kuri/len(double_ashi_next)*100:.1f}%)")
    print(f"  → 3走目で差し発動: {next_sashi}/{len(double_ashi_next)} ({next_sashi/len(double_ashi_next)*100:.1f}%)")
