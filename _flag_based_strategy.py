"""鬼脚/不発フラグベースの単純戦略の検証
A) 鬼脚を含む3連単
B) 不発を除外した3連単
C) 鬼脚を含み、かつ不発を除外
D) 鬼脚が1着の3連単
E) 鬼脚が1-2着の3連単
"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, sys
from collections import defaultdict, Counter
from itertools import permutations

RC = pd.read_excel("data/racecard_hist.xlsx", dtype={"race_id": str})
OD = pd.read_excel("data/odds_hist.xlsx", dtype={"race_id": str})
PY = pd.read_excel("data/payouts_hist.xlsx", dtype={"race_id": str})
RC["date"] = pd.to_datetime(RC["date"].astype(str), format="%Y%m%d", errors="coerce")
OD["オッズ"] = pd.to_numeric(OD["オッズ"], errors="coerce")
PY["payout_trifecta"] = pd.to_numeric(PY["payout_trifecta"], errors="coerce")
PY["result_trifecta"] = PY["result_trifecta"].astype(str).str.strip()

import importlib.util
spec = importlib.util.spec_from_file_location("rb", "run_backtest.py")
rb = importlib.util.module_from_spec(spec); sys.modules["rb"] = rb; spec.loader.exec_module(rb)
db_slim, db_all, nobi_col = rb.load_db()

# === Build race data with monster/unreliable flags ===
print("Loading...", file=sys.stderr)
races = []
for race_date in sorted(RC["date"].dropna().unique()):
    daily = RC[RC["date"] == race_date]
    for race_id in daily["race_id"].unique():
        ri = daily[daily["race_id"] == race_id]
        if ri.empty: continue
        venue = ri.iloc[0]["venue"]
        od = OD[OD["race_id"] == race_id]
        odds = {str(r["組み合わせ"]).strip(): float(r["オッズ"])
                for _, r in od.iterrows() if pd.notna(r["オッズ"])}
        py = PY[PY["race_id"] == race_id]
        if py.empty: continue
        actual = str(py.iloc[0]["result_trifecta"]).strip()
        if not actual or actual == "nan": continue
        payout = int(float(str(py.iloc[0]["payout_trifecta"]).replace(",",""))) \
            if pd.notna(py.iloc[0]["payout_trifecta"]) else 0

        past_slim = db_slim[db_slim["開催日"]<race_date] if not db_slim.empty else db_slim
        past_all = db_all[db_all["開催日"]<race_date] if not db_all.empty else db_all

        riders = {}
        for _, row in ri.iterrows():
            try:
                num = int(row["車番"])
                nm = rb.norm(str(row.get("選手名", "")))
            except: continue
            hist = past_slim[past_slim["選手名_norm"]==nm] if not past_slim.empty else pd.DataFrame()
            use_slim = not hist.empty
            if hist.empty:
                hist = past_all[past_all["選手名_norm"]==nm] if not past_all.empty else pd.DataFrame()
            is_m = is_u = False
            if not hist.empty:
                if use_slim:
                    is_m = bool(hist.get("is_monster",pd.Series([0])).max()>=1)
                    is_u = bool(hist.get("is_unreliable",pd.Series([0])).max()>=1)
                else:
                    cmt = " ".join(hist.get("解析コメント",pd.Series([""])).astype(str))
                    is_m = any(k in cmt for k in ["脚余し","鬼脚","別次元","圧倒"])
                    is_u = any(k in cmt for k in ["共倒れ","位置取り失敗","不発","失速"])
            riders[num] = {"is_m": is_m, "is_u": is_u}
        if len(riders) < 3: continue
        races.append({"riders":riders,"actual":actual,"payout":payout,
                      "odds_dict":odds,"venue":venue,
                      "date":str(race_date.date())})

print(f"Races: {len(races)}", file=sys.stderr)


# === Strategy evaluators ===
def evaluate(strategy_fn, races, min_odds=10, max_bets=None):
    """各レースで戦略関数が選んだ買い目を集計"""
    total_inv = total_ret = total_n = total_hits = 0
    bet_counts = []
    for race in races:
        bets = strategy_fn(race)
        # Filter: in odds dict, odds >= min_odds
        bets = [b for b in bets if b in race["odds_dict"] and race["odds_dict"][b] >= min_odds]
        if max_bets:
            bets = bets[:max_bets]
        if not bets: continue
        inv = len(bets) * 100
        hit = race["actual"] in bets
        ret = race["payout"] if hit else 0
        total_inv += inv; total_ret += ret; total_n += 1
        if hit: total_hits += 1
        bet_counts.append(len(bets))
    roi = total_ret/total_inv*100 if total_inv else 0
    avg = np.mean(bet_counts) if bet_counts else 0
    return {"n":total_n,"hits":total_hits,"invest":total_inv,"ret":total_ret,
            "roi":roi,"profit":total_ret-total_inv,"avg_bets":avg}


# Strategy A: 鬼脚を含む3連単
def strat_contains_monster(race):
    riders = race["riders"]
    monsters = [n for n,r in riders.items() if r["is_m"]]
    if not monsters: return []
    nums = list(riders.keys())
    bets = []
    for f, s, t in permutations(nums, 3):
        if any(m in (f,s,t) for m in monsters):
            bets.append(f"{f}-{s}-{t}")
    return bets

# Strategy B: 不発を除外した3連単
def strat_exclude_unreliable(race):
    riders = race["riders"]
    excluded = {n for n,r in riders.items() if r["is_u"]}
    valid = [n for n in riders.keys() if n not in excluded]
    if len(valid) < 3: return []
    return [f"{f}-{s}-{t}" for f,s,t in permutations(valid, 3)]

# Strategy C: 鬼脚を含み、かつ不発を除外
def strat_monster_no_unreliable(race):
    riders = race["riders"]
    monsters = {n for n,r in riders.items() if r["is_m"]}
    excluded = {n for n,r in riders.items() if r["is_u"]}
    valid = [n for n in riders.keys() if n not in excluded]
    if not monsters or len(valid) < 3: return []
    bets = []
    for f, s, t in permutations(valid, 3):
        if any(m in (f,s,t) for m in monsters):
            bets.append(f"{f}-{s}-{t}")
    return bets

# Strategy D: 鬼脚が1着の3連単
def strat_monster_first(race):
    riders = race["riders"]
    monsters = [n for n,r in riders.items() if r["is_m"]]
    if not monsters: return []
    nums = list(riders.keys())
    bets = []
    for f in monsters:
        for s, t in permutations([n for n in nums if n != f], 2):
            bets.append(f"{f}-{s}-{t}")
    return bets

# Strategy E: 鬼脚が1-2着の3連単
def strat_monster_top2(race):
    riders = race["riders"]
    monsters = [n for n,r in riders.items() if r["is_m"]]
    if not monsters: return []
    nums = list(riders.keys())
    bets = []
    for f, s, t in permutations(nums, 3):
        if f in monsters or s in monsters:
            bets.append(f"{f}-{s}-{t}")
    return bets

# Strategy F: 鬼脚が1着 + 不発を除外
def strat_monster_first_no_u(race):
    riders = race["riders"]
    monsters = [n for n,r in riders.items() if r["is_m"]]
    excluded = {n for n,r in riders.items() if r["is_u"]}
    valid = [n for n in riders.keys() if n not in excluded]
    if not monsters or len(valid) < 3: return []
    valid_monsters = [m for m in monsters if m in valid]
    if not valid_monsters: return []
    bets = []
    for f in valid_monsters:
        for s, t in permutations([n for n in valid if n != f], 2):
            bets.append(f"{f}-{s}-{t}")
    return bets

# Strategy G: 鬼脚2人以上いるレースで、鬼脚同士の3連単 (1-2着が鬼脚)
def strat_double_monster(race):
    riders = race["riders"]
    monsters = [n for n,r in riders.items() if r["is_m"]]
    if len(monsters) < 2: return []
    nums = list(riders.keys())
    bets = []
    for f, s in permutations(monsters, 2):
        for t in nums:
            if t in (f,s): continue
            bets.append(f"{f}-{s}-{t}")
    return bets


# === Run all strategies ===
print(f"\n{'='*100}")
print("=== フラグベース戦略の検証 ===")
print(f"{'='*100}")

strategies = [
    ("A: 鬼脚を含む", strat_contains_monster),
    ("B: 不発を除外", strat_exclude_unreliable),
    ("C: 鬼脚含+不発除", strat_monster_no_unreliable),
    ("D: 鬼脚=1着", strat_monster_first),
    ("E: 鬼脚=1or2着", strat_monster_top2),
    ("F: 鬼脚=1着+不発除", strat_monster_first_no_u),
    ("G: 鬼脚2人=1-2着", strat_double_monster),
]

print(f"\n--- 1) フィルタなし(全買い目, ガミカットodds<10のみ) ---")
print(f"{'戦略':>22s}  {'対象R':>5s}  {'avg点':>6s}  {'的中':>4s}  {'率':>5s}  {'投資':>11s}  {'払戻':>11s}  {'収支':>11s}  {'ROI':>6s}")
for name, fn in strategies:
    r = evaluate(fn, races)
    if r["n"]==0: continue
    hr = r["hits"]/r["n"]*100
    print(f"  {name:>20s}  {r['n']:5d}  {r['avg_bets']:6.1f}  {r['hits']:4d}  {hr:4.1f}%  "
          f"{r['invest']:>11,}  {r['ret']:>11,}  {r['profit']:>+11,}  {r['roi']:5.1f}%")

print(f"\n--- 2) 上限7点制限 (オッズ高い順) ---")
def topn_by_odds(strategy_fn, n=7):
    def wrapper(race):
        bets = strategy_fn(race)
        bets = [b for b in bets if b in race["odds_dict"]]
        bets.sort(key=lambda b: race["odds_dict"][b])
        return bets[:n]  # オッズ低い順 (本命寄り)
    return wrapper

for name, fn in strategies:
    r = evaluate(topn_by_odds(fn, 7), races)
    if r["n"]==0: continue
    hr = r["hits"]/r["n"]*100
    print(f"  {name:>20s}  {r['n']:5d}  {r['avg_bets']:6.1f}  {r['hits']:4d}  {hr:4.1f}%  "
          f"{r['invest']:>11,}  {r['ret']:>11,}  {r['profit']:>+11,}  {r['roi']:5.1f}%")

print(f"\n--- 3) オッズ帯フィルタ: 10-100倍のみ ---")
def odds_band(strategy_fn, low=10, high=100):
    def wrapper(race):
        bets = strategy_fn(race)
        return [b for b in bets if b in race["odds_dict"]
                and low <= race["odds_dict"][b] <= high]
    return wrapper

for name, fn in strategies:
    r = evaluate(odds_band(fn, 10, 100), races)
    if r["n"]==0: continue
    hr = r["hits"]/r["n"]*100
    print(f"  {name:>20s}  {r['n']:5d}  {r['avg_bets']:6.1f}  {r['hits']:4d}  {hr:4.1f}%  "
          f"{r['invest']:>11,}  {r['ret']:>11,}  {r['profit']:>+11,}  {r['roi']:5.1f}%")

print(f"\n--- 4) オッズ帯フィルタ: 20-200倍のみ ---")
for name, fn in strategies:
    r = evaluate(odds_band(fn, 20, 200), races)
    if r["n"]==0: continue
    hr = r["hits"]/r["n"]*100
    print(f"  {name:>20s}  {r['n']:5d}  {r['avg_bets']:6.1f}  {r['hits']:4d}  {hr:4.1f}%  "
          f"{r['invest']:>11,}  {r['ret']:>11,}  {r['profit']:>+11,}  {r['roi']:5.1f}%")

# Check overall stats
print(f"\n--- 統計 ---")
n_with_monster = sum(1 for r in races if any(rd["is_m"] for rd in r["riders"].values()))
n_with_unreliable = sum(1 for r in races if any(rd["is_u"] for rd in r["riders"].values()))
n_with_2plus_monster = sum(1 for r in races if sum(1 for rd in r["riders"].values() if rd["is_m"]) >= 2)
print(f"鬼脚>=1人のレース: {n_with_monster}/{len(races)} ({n_with_monster/len(races)*100:.1f}%)")
print(f"鬼脚>=2人のレース: {n_with_2plus_monster}/{len(races)} ({n_with_2plus_monster/len(races)*100:.1f}%)")
print(f"不発>=1人のレース: {n_with_unreliable}/{len(races)} ({n_with_unreliable/len(races)*100:.1f}%)")
