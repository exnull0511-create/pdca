"""baseウェイト変更による的中率+ROI同時検証 (CV付き)"""
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
SIGMA = 0.90
MIN_ODDS = 10

dates = sorted(RC["date"].dropna().unique())
FEATS = ["base", "ip", "ep", "dp", "bp", "nb", "sp", "pos_b", "is_m"]

# === Collect all race data with raw features ===
print("Collecting race data...", file=sys.stderr)
all_races = []
rc = 0
for race_date in dates:
    daily_rc = RC[RC["date"] == race_date]
    for race_id in daily_rc["race_id"].unique():
        race_info = daily_rc[daily_rc["race_id"] == race_id].copy()
        if race_info.empty: continue
        venue = race_info.iloc[0]["venue"]
        bp = BANK_DICT.get(venue, {"roi_tier": "mid", "sashi": 1.0, "makuri": 1.0})
        od_race = OD[OD["race_id"] == race_id]
        odds_dict = {str(r["組み合わせ"]).strip(): float(r["オッズ"])
                     for _, r in od_race.iterrows() if pd.notna(r["オッズ"])}
        py_race = PY[PY["race_id"] == race_id]
        if py_race.empty: continue
        actual = str(py_race.iloc[0]["result_trifecta"]).strip()
        payout = int(float(str(py_race.iloc[0]["payout_trifecta"]).replace(",", ""))) \
            if pd.notna(py_race.iloc[0]["payout_trifecta"]) else 0
        if not actual or actual == "nan": continue

        past_slim = db_slim[db_slim["開催日"] < race_date] if not db_slim.empty else db_slim
        past_all = db_all[db_all["開催日"] < race_date] if not db_all.empty else db_all
        line_map = {}; num_to_line = {}
        for _, row in race_info.iterrows():
            try:
                num = int(row["車番"]); lno = int(row.get("line_no", 0) or 0)
            except: continue
            bibs_str = str(row.get("line_bibs", str(num)))
            if lno not in line_map:
                try: bibs_list = [int(b) for b in bibs_str.split("-") if b.isdigit()]
                except: bibs_list = [num]
                line_map[lno] = bibs_list
            num_to_line[num] = lno

        players = []
        for _, row in race_info.iterrows():
            try:
                num = int(row["車番"])
                nm = rb.norm(str(row.get("選手名", "")))
                base_v = float(row.get("競走得点", 80) or 80)
            except: continue
            hist = past_slim[past_slim["選手名_norm"] == nm] if not past_slim.empty else pd.DataFrame()
            use_slim = not hist.empty
            if hist.empty:
                hist = past_all[past_all["選手名_norm"] == nm] if not past_all.empty else pd.DataFrame()
            ip = ep = 4.0; dp_v = bp_v = 3.0; nb = sp = 2.0; is_m = 0
            if not hist.empty:
                RECENT_W = 3.0
                sd = sorted(hist["開催日"].dropna().unique(), reverse=True); rd = set(sd[:2])
                def wm(series):
                    v = pd.to_numeric(series, errors="coerce")
                    w = np.where(hist["開催日"].isin(rd), RECENT_W, 1.0); mk = v.notna()
                    return float((v[mk] * w[mk]).sum() / w[mk].sum()) if mk.any() else None
                ip = wm(hist["IP"]) or 4.0; ep = wm(hist["EP"]) or 4.0
                dp_v = wm(hist["DP"]) or 3.0; bp_v = wm(hist["BP"]) or 3.0
                if use_slim and "直線の伸び" in hist.columns:
                    nb = wm(hist["直線の伸び"].apply(rb.nobi_score)) or 2.0
                elif nobi_col in hist.columns:
                    nb = wm(hist[nobi_col].apply(rb.nobi_score)) or 2.0
                if "戦法" in hist.columns:
                    sp = wm(hist["戦法"].apply(rb.senpo_lead)) or 2.0
                if use_slim:
                    is_m = 1 if hist.get("is_monster", pd.Series([0])).max() >= 1 else 0
                else:
                    cmt = " ".join(hist.get("解析コメント", pd.Series([""])).astype(str))
                    is_m = 1 if any(k in cmt for k in ["脚余し", "鬼脚", "別次元", "圧倒"]) else 0
            lno = num_to_line.get(num, 0); lbs = line_map.get(lno, [])
            pos = lbs.index(num) + 1 if num in lbs else 1
            pos_b = 0.5 if pos == 1 else -0.3 * (pos - 1)
            players.append({
                "num": num,
                "base": base_v, "ip": ip, "ep": ep,
                "dp": dp_v * bp["makuri"], "bp": bp_v * bp["sashi"],
                "nb": nb, "sp": sp, "pos_b": pos_b, "is_m": is_m,
                "line": num_to_line.get(num, -num),
            })
        if len(players) < 3: continue
        all_races.append({
            "players": players, "actual": actual, "payout": payout,
            "odds_dict": odds_dict, "num_to_line": num_to_line,
            "venue": venue, "date": str(race_date.date()),
        })
        rc += 1
        if rc % 200 == 0: print(f"  ... {rc} races", file=sys.stderr)

print(f"Total races: {len(all_races)}", file=sys.stderr)


def simulate_strategy(races, weights, top_n=7, min_ev=67):
    """Given weights, simulate PL single-axis strategy and return stats"""
    total_inv = total_ret = total_n = total_hits = 0
    top1_correct = 0
    for race in races:
        # Score players
        scored = []
        for p in race["players"]:
            s = sum(p[f] * w for f, w in zip(FEATS, weights))
            scored.append((s, p["num"], p))
        scored.sort(key=lambda x: x[0], reverse=True)
        top_ev = scored[0][0]
        if top_ev < min_ev: continue

        # Check top1 accuracy
        actual_parts = race["actual"].split("-")
        if len(actual_parts) == 3:
            a1 = int(actual_parts[0])
            if scored[0][1] == a1:
                top1_correct += 1

        # PL single-axis bets
        all_nums = [n for _, n, _ in scored]
        max_e = scored[0][0]
        raw_s = {n: np.exp(s - max_e) for s, n, _ in scored}

        # Axis = monster or top
        axis = None
        for s, n, p in scored:
            if p["is_m"]: axis = n; break
        if axis is None: axis = scored[0][1]

        others = [n for n in all_nums if n != axis]
        odds_dict = race["odds_dict"]

        def pl(f, s, t):
            d1 = sum(raw_s[n] for n in all_nums)
            d2 = sum(raw_s[n] for n in all_nums if n != f)
            d3 = sum(raw_s[n] for n in all_nums if n not in (f, s))
            return 0.0 if 0 in (d1, d2, d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)

        ev_bets = []
        for s_n in others:
            for t_n in others:
                if s_n == t_n: continue
                combo = f"{axis}-{s_n}-{t_n}"
                if combo not in odds_dict: continue
                p = pl(axis, s_n, t_n)
                o = odds_dict[combo]
                ev_bets.append((p * o, combo, p, o))
        ev_bets.sort(key=lambda x: x[2], reverse=True)
        selected = ev_bets[:top_n]
        selected = [(ev, c, p, o) for ev, c, p, o in selected if o >= MIN_ODDS]
        bets = [c for _, c, _, _ in selected]
        if not bets: continue

        inv = len(bets) * 100
        hit = race["actual"] in bets
        ret = race["payout"] if hit else 0
        total_inv += inv; total_ret += ret; total_n += 1
        if hit: total_hits += 1

    roi = total_ret / total_inv * 100 if total_inv > 0 else 0
    hit_rate = total_hits / total_n * 100 if total_n > 0 else 0
    top1_rate = top1_correct / total_n * 100 if total_n > 0 else 0
    return {
        "n": total_n, "hits": total_hits, "invest": total_inv,
        "ret": total_ret, "roi": roi, "hit_rate": hit_rate,
        "profit": total_ret - total_inv, "top1_rate": top1_rate,
    }


# === Test: sweep base weight ===
print(f"\n{'='*95}")
print("=== baseウェイト感度分析 (PL単軸7点, EV>=67, ガミカット, フラット) ===")
print(f"{'='*95}")
print(f"{'base_w':>7s}  {'R数':>5s}  {'1着率':>6s}  {'3連的中':>7s}  {'率':>5s}  {'投資':>12s}  {'払戻':>12s}  {'収支':>12s}  {'ROI':>6s}")
print("-" * 95)

current_w = np.array([0.4, 1.5, 1.2, 1.0, 1.0, 2.0, 0.5, 1.0, 3.0])
for base_w in [0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
    w = current_w.copy()
    w[0] = base_w
    r = simulate_strategy(all_races, w, top_n=7)
    mark = " ◀ 現行" if base_w == 0.4 else ""
    print(f"  {base_w:5.1f}  {r['n']:5d}  {r['top1_rate']:5.1f}%  {r['hits']:5d}  {r['hit_rate']:4.1f}%  "
          f"{r['invest']:>12,}  {r['ret']:>12,}  {r['profit']:>+12,}  {r['roi']:5.1f}%{mark}")

# === Also test: base + reduce other weights ===
print(f"\n{'='*95}")
print("=== base引き上げ + 他ウェイト調整 組み合わせ ===")
print(f"{'='*95}")
print(f"{'設定':>30s}  {'R数':>5s}  {'1着率':>6s}  {'的中':>5s}  {'率':>5s}  {'収支':>12s}  {'ROI':>6s}")
print("-" * 95)

configs = [
    ("現行", [0.4, 1.5, 1.2, 1.0, 1.0, 2.0, 0.5, 1.0, 3.0]),
    ("base2.0のみ", [2.0, 1.5, 1.2, 1.0, 1.0, 2.0, 0.5, 1.0, 3.0]),
    ("base2.5のみ", [2.5, 1.5, 1.2, 1.0, 1.0, 2.0, 0.5, 1.0, 3.0]),
    ("base3.0のみ", [3.0, 1.5, 1.2, 1.0, 1.0, 2.0, 0.5, 1.0, 3.0]),
    ("base2.5+IP0.5", [2.5, 0.5, 1.2, 1.0, 1.0, 2.0, 0.5, 1.0, 3.0]),
    ("base2.5+IP0+nb1", [2.5, 0.0, 1.2, 1.0, 1.0, 1.0, 0.5, 1.0, 3.0]),
    ("base2.5+posb0", [2.5, 1.5, 1.2, 1.0, 1.0, 2.0, 0.5, 0.0, 3.0]),
    ("base2.5+EP2.0", [2.5, 1.5, 2.0, 1.0, 1.0, 2.0, 0.5, 1.0, 3.0]),
    ("base3.0+IP0.5+nb1", [3.0, 0.5, 1.2, 1.0, 1.0, 1.0, 0.5, 1.0, 3.0]),
    ("base3.0+IP0+posb0", [3.0, 0.0, 1.2, 1.0, 1.0, 2.0, 0.5, 0.0, 3.0]),
    ("base重視型", [3.0, 0.5, 1.0, 0.5, 1.0, 1.0, 0.3, 0.5, 2.0]),
    ("得点特化", [5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 3.0]),
]
for name, w in configs:
    r = simulate_strategy(all_races, w, top_n=7)
    print(f"  {name:>28s}  {r['n']:5d}  {r['top1_rate']:5.1f}%  {r['hits']:5d}  {r['hit_rate']:4.1f}%  "
          f"{r['profit']:>+12,}  {r['roi']:5.1f}%")

# === Cross-validation for top configs ===
print(f"\n{'='*95}")
print("=== クロスバリデーション (前半学習→後半検証) ===")
print(f"{'='*95}")
all_dates = sorted(set(r["date"] for r in all_races))
mid = len(all_dates) // 2
train = [r for r in all_races if r["date"] <= all_dates[mid-1]]
test = [r for r in all_races if r["date"] > all_dates[mid-1]]
print(f"学習: ~{all_dates[mid-1]} ({len(train)}R)  検証: {all_dates[mid]}~ ({len(test)}R)\n")

print(f"{'設定':>30s}  {'学習ROI':>8s}  {'検証ROI':>8s}  {'検証収支':>12s}  {'検証的中率':>8s}")
print("-" * 85)
for name, w in configs:
    r_train = simulate_strategy(train, w, top_n=7)
    r_test = simulate_strategy(test, w, top_n=7)
    print(f"  {name:>28s}  {r_train['roi']:7.1f}%  {r_test['roi']:7.1f}%  "
          f"{r_test['profit']:>+12,}  {r_test['hit_rate']:7.1f}%")
