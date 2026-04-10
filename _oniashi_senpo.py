"""鬼脚フラグ選手と戦法の関係性分析"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, sys
from collections import defaultdict, Counter

# DB全件
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

# === 1. 鬼脚フラグ別の戦法分布 ===
print("="*70)
print("=== 1. 鬼脚フラグ選手の戦法分布 (DB全レコード) ===")
print("="*70)

monster_df = df[df["is_monster"] >= 1] if "is_monster" in df.columns else pd.DataFrame()
non_m_df = df[df["is_monster"] < 1] if "is_monster" in df.columns else df

print(f"\n鬼脚レコード数: {len(monster_df)}")
print(f"非鬼脚レコード数: {len(non_m_df)}")

print(f"\n{'戦法':>10s}  {'鬼脚件数':>8s}  {'鬼脚%':>6s}  {'非鬼脚%':>7s}  {'差':>6s}")
print("-"*55)
total_m = len(monster_df); total_n = len(non_m_df)
for senpo in ['逃げ','先行','捲り','差し','追走','不発系','その他']:
    m_n = (monster_df["戦法大分類"]==senpo).sum()
    n_n = (non_m_df["戦法大分類"]==senpo).sum()
    m_pct = m_n/total_m*100 if total_m else 0
    n_pct = n_n/total_n*100 if total_n else 0
    diff = m_pct - n_pct
    mark = " ★" if abs(diff) >= 3 else ""
    print(f"  {senpo:>8s}  {m_n:8d}  {m_pct:5.1f}%  {n_pct:6.1f}%  {diff:+5.1f}%{mark}")


# === 2. 鬼脚選手の脚質分布 ===
print(f"\n{'='*70}")
print("=== 2. 鬼脚選手のホーム脚質分布（出走表脚質との照合）===")
print("="*70)

import csv
racers = {}
with open("data/s_class_racers.csv", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        racers[norm(row["選手名"])] = row.get("脚質", "")

monster_riders = monster_df["選手名_norm"].unique() if not monster_df.empty else []
non_m_riders = non_m_df["選手名_norm"].unique()

m_styles = Counter()
n_styles = Counter()
for r in monster_riders:
    s = racers.get(r, "?")
    m_styles[s] += 1
for r in non_m_riders:
    if r in monster_riders: continue
    s = racers.get(r, "?")
    n_styles[s] += 1

print(f"\n{'脚質':>6s}  {'鬼脚選手数':>8s}  {'鬼脚%':>6s}  {'非鬼脚選手数':>10s}  {'非鬼脚%':>7s}")
total_mr = sum(m_styles.values()); total_nr = sum(n_styles.values())
for s in ['逃','追','両','?','-']:
    if m_styles.get(s,0)==0 and n_styles.get(s,0)==0: continue
    m_pct = m_styles.get(s,0)/total_mr*100 if total_mr else 0
    n_pct = n_styles.get(s,0)/total_nr*100 if total_nr else 0
    print(f"  {s:>4s}  {m_styles.get(s,0):8d}  {m_pct:5.1f}%  {n_styles.get(s,0):10d}  {n_pct:6.1f}%")


# === 3. 鬼脚×戦法×実成績 (DBの各レコードで実際の戦法とis_monsterの両方を持つ) ===
print(f"\n{'='*70}")
print("=== 3. is_monster=1の時の戦法分布(同時記録) ===")
print("="*70)
print("(同じレコードで鬼脚フラグが立っていた時、その日の実戦法は何か)")

if "is_monster" in df.columns:
    same_day = df[df["is_monster"]>=1]
    if len(same_day) > 0:
        sd_dist = same_day["戦法大分類"].value_counts()
        total = len(same_day)
        print(f"\n総数: {total}")
        for s, c in sd_dist.items():
            print(f"  {s}: {c} ({c/total*100:.1f}%)")


# === 4. 鬼脚フラグの付与基準を逆算 ===
print(f"\n{'='*70}")
print("=== 4. 鬼脚フラグ選手の能力値分布 ===")
print("="*70)

if not monster_df.empty:
    print(f"\n{'指標':>8s}  {'鬼脚平均':>10s}  {'非鬼脚平均':>10s}  {'差':>6s}")
    for col in ['IP','EP','DP','BP']:
        m_val = pd.to_numeric(monster_df[col], errors='coerce').mean()
        n_val = pd.to_numeric(non_m_df[col], errors='coerce').mean()
        print(f"  {col:>6s}  {m_val:10.2f}  {n_val:10.2f}  {m_val-n_val:+5.2f}")


# === 5. 実戦データでの鬼脚×戦法×順位 ===
print(f"\n{'='*70}")
print("=== 5. 鬼脚選手の戦法別パフォーマンス (DB内) ===")
print("="*70)

# 各鬼脚レコードで, その日の戦法と着順を確認
# DBのレコードに「順位」「着」のような列があるかチェック
print(f"\nDBカラム: {list(df.columns)}")

# 戦法別に過去の鬼脚記録を集計
print(f"\n{'戦法':>10s}  {'鬼脚件数':>8s}  {'平均IP':>8s}  {'平均DP':>8s}")
for senpo in ['逃げ','先行','捲り','差し','追走','不発系']:
    sub = monster_df[monster_df["戦法大分類"]==senpo] if not monster_df.empty else pd.DataFrame()
    if len(sub)<5: continue
    avg_ip = pd.to_numeric(sub["IP"], errors='coerce').mean()
    avg_dp = pd.to_numeric(sub["DP"], errors='coerce').mean()
    print(f"  {senpo:>8s}  {len(sub):8d}  {avg_ip:8.2f}  {avg_dp:8.2f}")


# === 6. 鬼脚×レース番号 (開催種別プロキシ) ===
print(f"\n{'='*70}")
print("=== 6. 鬼脚レコードのレース番号別分布 ===")
print("="*70)

if "レース番号" in df.columns and not monster_df.empty:
    print(f"\n{'R番号':>5s}  {'鬼脚件数':>8s}  {'非鬼脚件数':>10s}  {'鬼脚出現率':>10s}")
    for rno in sorted(df["レース番号"].dropna().unique()):
        try: rno_int = int(rno)
        except: continue
        if rno_int < 5 or rno_int > 12: continue
        m_count = (monster_df["レース番号"] == rno).sum()
        n_count = (non_m_df["レース番号"] == rno).sum()
        total = m_count + n_count
        rate = m_count/total*100 if total else 0
        print(f"  {rno_int:3d}R  {m_count:8d}  {n_count:10d}  {rate:9.1f}%")


# === 7. 鬼脚 → 翌レースで逃げ/捲り/差しのどれを選ぶか ===
print(f"\n{'='*70}")
print("=== 7. 鬼脚レコードの実際の戦法（再集計） ===")
print("="*70)

if "is_monster" in df.columns:
    print(f"\n--- 鬼脚=1のレコードでの戦法 ---")
    m_only = df[df["is_monster"]>=1]
    senpo_dist = m_only["戦法大分類"].value_counts()
    total = len(m_only)
    for s in ['逃げ','先行','捲り','差し','追走','不発系','その他']:
        cnt = senpo_dist.get(s, 0)
        print(f"  {s:>6s}: {cnt:5d} ({cnt/total*100:5.1f}%)")

    # 細かい戦法
    print(f"\n--- 鬼脚=1の細かい戦法 (Top15) ---")
    fine = m_only["戦法"].value_counts().head(15)
    for s, c in fine.items():
        print(f"  {s:>10s}: {c}")
