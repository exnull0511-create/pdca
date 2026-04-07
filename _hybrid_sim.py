"""ハイブリッド戦略シミュレーション: バンク別モデル切替 + クロスバリデーション"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, sys
from collections import defaultdict

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
BANK_DICT = rb.BANK_DICT
MIN_TOP_EV = 67; MIN_ODDS = 10; SIGMA = 0.90
dates = sorted(RC["date"].dropna().unique())

# Load model functions from _compare_models.py
src = open("_compare_models.py", encoding="utf-8").read()
exec(src.split("# === Strategies ===")[0])

strats = {
    "PL単軸7":  lambda ps, ntl, od: select_pl_single(ps, ntl, od, 7),
    "PL単軸14": lambda ps, ntl, od: select_pl_single(ps, ntl, od, 14),
    "NL単軸7":  lambda ps, ntl, od: select_nl_single(ps, ntl, od, 7),
    "NL単軸14": lambda ps, ntl, od: select_nl_single(ps, ntl, od, 14),
    "NL多軸7":  lambda ps, ntl, od: select_nl_multi(ps, ntl, od, 7),
    "NL多軸14": lambda ps, ntl, od: select_nl_multi(ps, ntl, od, 14),
}

# === Collect per-race, per-strategy results ===
race_results = []
rc = 0
for race_date in dates:
    daily_rc = RC[RC["date"] == race_date]
    for race_id in daily_rc["race_id"].unique():
        race_info = daily_rc[daily_rc["race_id"] == race_id].copy()
        if race_info.empty: continue
        venue = race_info.iloc[0]["venue"]
        od_race = OD[OD["race_id"] == race_id]
        odds_dict = {str(r["組み合わせ"]).strip(): float(r["オッズ"])
                     for _, r in od_race.iterrows() if pd.notna(r["オッズ"])}
        py_race = PY[PY["race_id"] == race_id]
        if py_race.empty: continue
        actual = str(py_race.iloc[0]["result_trifecta"]).strip()
        payout = int(float(str(py_race.iloc[0]["payout_trifecta"]).replace(",", ""))) \
            if pd.notna(py_race.iloc[0]["payout_trifecta"]) else 0
        ps, ntl = get_player_scores(race_info, venue, race_date)
        if len(ps) < 3: continue

        entry = {"race_id": race_id, "venue": venue, "date": str(race_date.date()), "strats": {}}
        for sn, sfn in strats.items():
            bets = sfn(ps, ntl, odds_dict)
            if bets is None: continue
            inv = len(bets) * 100
            hit = actual in bets
            ret = payout if hit else 0
            entry["strats"][sn] = {"inv": inv, "ret": ret, "hit": hit}
        if entry["strats"]:
            race_results.append(entry)
        rc += 1
        if rc % 200 == 0:
            print(f"  ... {rc} races", file=sys.stderr)

print(f"Total races: {len(race_results)}")

# === In-sample: best model per venue ===
venue_stats = defaultdict(lambda: {s: {"inv": 0, "ret": 0, "n": 0} for s in strats})
for r in race_results:
    for sn, sd in r["strats"].items():
        venue_stats[r["venue"]][sn]["inv"] += sd["inv"]
        venue_stats[r["venue"]][sn]["ret"] += sd["ret"]
        venue_stats[r["venue"]][sn]["n"] += 1

venue_best = {}
for v, ss in venue_stats.items():
    best_sn = max(ss.keys(), key=lambda s: ss[s]["ret"]/ss[s]["inv"]*100 if ss[s]["inv"] > 0 else -999)
    venue_best[v] = best_sn

print("\n=== バンク別最適モデル (in-sample) ===")
for v in sorted(venue_best, key=lambda x: -max(venue_stats[x][s]["n"] for s in strats)):
    sn = venue_best[v]
    d = venue_stats[v][sn]
    if d["n"] < 5: continue
    roi = d["ret"]/d["inv"]*100 if d["inv"] else 0
    print(f"  {v:>8s}: {sn:<10s}  {d['n']:3d}R  ROI {roi:5.0f}%  profit {d['ret']-d['inv']:>+8,}")

# === Hybrid in-sample ===
print("\n=== 戦略比較 ===")
hyb_inv = hyb_ret = hyb_n = 0
for r in race_results:
    sn = venue_best.get(r["venue"])
    if sn and sn in r["strats"]:
        sd = r["strats"][sn]
        hyb_inv += sd["inv"]; hyb_ret += sd["ret"]; hyb_n += 1
print(f"  ハイブリッド(IS): {hyb_n}R  ROI {hyb_ret/hyb_inv*100:.1f}%  profit {hyb_ret-hyb_inv:+,}")

for sn in strats:
    inv = ret = n = 0
    for r in race_results:
        if sn in r["strats"]:
            sd = r["strats"][sn]; inv += sd["inv"]; ret += sd["ret"]; n += 1
    if inv > 0:
        print(f"  {sn:<16s}: {n}R  ROI {ret/inv*100:.1f}%  profit {ret-inv:+,}")

# === Cross-validation: 前半→後半 ===
print("\n=== クロスバリデーション (前半学習→後半検証) ===")
all_dates = sorted(set(r["date"] for r in race_results))
mid = len(all_dates) // 2
train_dates = set(all_dates[:mid])
test_dates = set(all_dates[mid:])
print(f"  学習: {all_dates[0]}~{all_dates[mid-1]} ({mid}日)  検証: {all_dates[mid]}~{all_dates[-1]} ({len(all_dates)-mid}日)")

# Train best per venue
tv = defaultdict(lambda: {s: {"inv": 0, "ret": 0} for s in strats})
for r in race_results:
    if r["date"] not in train_dates: continue
    for sn, sd in r["strats"].items():
        tv[r["venue"]][sn]["inv"] += sd["inv"]
        tv[r["venue"]][sn]["ret"] += sd["ret"]

train_best = {}
for v, ss in tv.items():
    train_best[v] = max(ss.keys(), key=lambda s: ss[s]["ret"]/ss[s]["inv"]*100 if ss[s]["inv"] > 0 else -999)

# Default model
ai = {sn: 0 for sn in strats}; ar = {sn: 0 for sn in strats}
for r in race_results:
    if r["date"] not in train_dates: continue
    for sn, sd in r["strats"].items():
        ai[sn] += sd["inv"]; ar[sn] += sd["ret"]
dm = max(strats.keys(), key=lambda s: ar[s]/ai[s]*100 if ai[s] > 0 else 0)
print(f"  デフォルトモデル(学習最良): {dm}")

# Test hybrid
ti = tr = tn = 0
for r in race_results:
    if r["date"] not in test_dates: continue
    sn = train_best.get(r["venue"], dm)
    if sn and sn in r["strats"]:
        sd = r["strats"][sn]; ti += sd["inv"]; tr += sd["ret"]; tn += 1
if ti > 0:
    print(f"  ハイブリッド(OOS): {tn}R  ROI {tr/ti*100:.1f}%  profit {tr-ti:+,}")

for sn in strats:
    inv = ret = n = 0
    for r in race_results:
        if r["date"] not in test_dates: continue
        if sn in r["strats"]:
            sd = r["strats"][sn]; inv += sd["inv"]; ret += sd["ret"]; n += 1
    if inv > 0:
        print(f"  {sn:<16s}: {n}R  ROI {ret/inv*100:.1f}%  profit {ret-inv:+,}")

# === 3-fold CV ===
print("\n=== 3分割クロスバリデーション ===")
folds = [set(all_dates[i::3]) for i in range(3)]
fold_rois = []
for fi in range(3):
    test_d = folds[fi]; train_d = set(all_dates) - test_d
    tv2 = defaultdict(lambda: {s: {"inv": 0, "ret": 0} for s in strats})
    for r in race_results:
        if r["date"] not in train_d: continue
        for sn, sd in r["strats"].items():
            tv2[r["venue"]][sn]["inv"] += sd["inv"]; tv2[r["venue"]][sn]["ret"] += sd["ret"]
    tb2 = {}
    for v, ss in tv2.items():
        tb2[v] = max(ss.keys(), key=lambda s: ss[s]["ret"]/ss[s]["inv"]*100 if ss[s]["inv"] > 0 else -999)
    ai2 = {s: 0 for s in strats}; ar2 = {s: 0 for s in strats}
    for r in race_results:
        if r["date"] not in train_d: continue
        for sn, sd in r["strats"].items():
            ai2[sn] += sd["inv"]; ar2[sn] += sd["ret"]
    dm2 = max(strats.keys(), key=lambda s: ar2[s]/ai2[s]*100 if ai2[s] > 0 else 0)
    ti2 = tr2 = tn2 = 0
    for r in race_results:
        if r["date"] not in test_d: continue
        sn = tb2.get(r["venue"], dm2)
        if sn and sn in r["strats"]:
            sd = r["strats"][sn]; ti2 += sd["inv"]; tr2 += sd["ret"]; tn2 += 1
    roi2 = tr2/ti2*100 if ti2 > 0 else 0
    fold_rois.append(roi2)
    print(f"  Fold{fi+1}: {tn2}R  ROI {roi2:.1f}%  profit {tr2-ti2:+,}")

print(f"  平均ROI: {np.mean(fold_rois):.1f}%")
