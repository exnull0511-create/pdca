"""オッズ乖離分析: 自分の予測確率 vs 市場オッズ確率 の差が大きい時だけ買う"""
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
MIN_ODDS = 10
FEATS = ["base", "ip", "ep", "dp", "bp", "nb", "sp", "pos_b", "is_m"]

dates = sorted(RC["date"].dropna().unique())

# === Collect race data ===
print("Collecting...", file=sys.stderr)
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
                "num": num, "base": base_v, "ip": ip, "ep": ep,
                "dp": dp_v * bp["makuri"], "bp": bp_v * bp["sashi"],
                "nb": nb, "sp": sp, "pos_b": pos_b, "is_m": is_m,
            })
        if len(players) < 3: continue
        all_races.append({
            "players": players, "actual": actual, "payout": payout,
            "odds_dict": odds_dict, "num_to_line": num_to_line,
            "venue": venue, "date": str(race_date.date()),
        })
        rc += 1
        if rc % 200 == 0: print(f"  ... {rc}", file=sys.stderr)

print(f"Races: {len(all_races)}", file=sys.stderr)


def run_ev_edge_strategy(races, weights, top_n_bets=7, min_ev=67,
                          min_edge=0.0, bet_selection="prob"):
    """
    bet_selection:
      "prob" = 確率Top N (現行)
      "ev"   = EV(=確率×オッズ) Top N
      "edge" = Edge(=EV-1) Top N (市場との乖離が大きい順)

    min_edge: 買い目のEV最低値。EV>=min_edgeの買い目のみ購入。
              EV=1.0なら期待値100%(ブレークイーブン)。
    """
    total_inv = total_ret = total_n = total_hits = 0
    bets_data = []

    for race in races:
        scored = []
        for p in race["players"]:
            s = sum(p[f] * w for f, w in zip(FEATS, weights))
            scored.append((s, p["num"]))
        scored.sort(key=lambda x: x[0], reverse=True)
        top_ev_score = scored[0][0]
        if top_ev_score < min_ev: continue

        all_nums = [n for _, n in scored]
        max_e = scored[0][0]
        raw_s = {n: np.exp(s - max_e) for s, n in scored}

        # PL single axis
        axis = scored[0][1]
        for p in race["players"]:
            if p["is_m"] and p["num"] in [n for _, n in scored[:3]]:
                axis = p["num"]; break

        others = [n for n in all_nums if n != axis]
        odds_dict = race["odds_dict"]

        def pl(f, s, t):
            d1 = sum(raw_s[n] for n in all_nums)
            d2 = sum(raw_s[n] for n in all_nums if n != f)
            d3 = sum(raw_s[n] for n in all_nums if n not in (f, s))
            return 0.0 if 0 in (d1, d2, d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)

        candidates = []
        for s_n in others:
            for t_n in others:
                if s_n == t_n: continue
                combo = f"{axis}-{s_n}-{t_n}"
                if combo not in odds_dict: continue
                odds_v = odds_dict[combo]
                if odds_v < MIN_ODDS: continue
                prob = pl(axis, s_n, t_n)
                ev_val = prob * odds_v  # EV: >1.0 means +EV
                edge = ev_val - 1.0     # Edge: how much above breakeven
                candidates.append({
                    "combo": combo, "prob": prob, "odds": odds_v,
                    "ev": ev_val, "edge": edge,
                })

        if not candidates: continue

        # Filter by min_edge
        if min_edge > 0:
            candidates = [c for c in candidates if c["ev"] >= min_edge]
            if not candidates: continue

        # Select bets
        if bet_selection == "prob":
            candidates.sort(key=lambda x: x["prob"], reverse=True)
        elif bet_selection == "ev":
            candidates.sort(key=lambda x: x["ev"], reverse=True)
        elif bet_selection == "edge":
            candidates.sort(key=lambda x: x["edge"], reverse=True)

        selected = candidates[:top_n_bets]
        bets = [c["combo"] for c in selected]
        avg_ev = np.mean([c["ev"] for c in selected])
        max_ev_val = max(c["ev"] for c in selected)

        inv = len(bets) * 100
        hit = race["actual"] in bets
        ret = race["payout"] if hit else 0
        total_inv += inv; total_ret += ret; total_n += 1
        if hit: total_hits += 1

        bets_data.append({
            "avg_ev": avg_ev, "max_ev": max_ev_val,
            "hit": hit, "ret": ret, "inv": inv,
            "n_bets": len(bets),
        })

    roi = total_ret / total_inv * 100 if total_inv > 0 else 0
    hit_rate = total_hits / total_n * 100 if total_n > 0 else 0
    return {
        "n": total_n, "hits": total_hits, "invest": total_inv,
        "ret": total_ret, "roi": roi, "hit_rate": hit_rate,
        "profit": total_ret - total_inv, "bets_data": bets_data,
    }


current_w = np.array([0.4, 1.5, 1.2, 1.0, 1.0, 2.0, 0.5, 1.0, 3.0])

# === 1. 買い目選定方法の比較: 確率順 vs EV順 vs Edge順 ===
print(f"\n{'='*90}")
print("=== 1. 買い目選定方法の比較 ===")
print(f"{'='*90}")
print(f"{'方式':>20s}  {'R数':>5s}  {'的中':>4s}  {'率':>5s}  {'投資':>12s}  {'払戻':>12s}  {'収支':>12s}  {'ROI':>6s}")
print("-" * 90)
for sel, label in [("prob", "確率Top7(現行)"), ("ev", "EV Top7"), ("edge", "Edge Top7")]:
    r = run_ev_edge_strategy(all_races, current_w, top_n_bets=7, bet_selection=sel)
    print(f"  {label:>18s}  {r['n']:5d}  {r['hits']:4d}  {r['hit_rate']:4.1f}%  "
          f"{r['invest']:>12,}  {r['ret']:>12,}  {r['profit']:>+12,}  {r['roi']:5.1f}%")

# === 2. EV閾値: +EVの買い目だけに絞る ===
print(f"\n{'='*90}")
print("=== 2. 買い目のEV閾値 (EV >= X の買い目のみ購入) ===")
print(f"{'='*90}")
print(f"{'min_EV':>8s}  {'選定':>10s}  {'R数':>5s}  {'的中':>4s}  {'率':>5s}  {'投資':>12s}  {'収支':>12s}  {'ROI':>6s}")
print("-" * 85)
for min_e in [0, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0]:
    for sel in ["prob", "ev"]:
        r = run_ev_edge_strategy(all_races, current_w, top_n_bets=7,
                                  min_edge=min_e, bet_selection=sel)
        label = "確率順" if sel == "prob" else "EV順"
        print(f"  EV>={min_e:.1f}  {label:>8s}  {r['n']:5d}  {r['hits']:4d}  {r['hit_rate']:4.1f}%  "
              f"{r['invest']:>12,}  {r['profit']:>+12,}  {r['roi']:5.1f}%")

# === 3. EV分布分析: 買い目のEVはどのくらいか ===
print(f"\n{'='*90}")
print("=== 3. 買い目のEV分布 ===")
r_detail = run_ev_edge_strategy(all_races, current_w, top_n_bets=7, bet_selection="prob")
all_avg_evs = [d["avg_ev"] for d in r_detail["bets_data"]]
all_max_evs = [d["max_ev"] for d in r_detail["bets_data"]]
print(f"  買い目平均EV: mean={np.mean(all_avg_evs):.3f} med={np.median(all_avg_evs):.3f}")
print(f"  買い目最大EV: mean={np.mean(all_max_evs):.3f} med={np.median(all_max_evs):.3f}")
print(f"  平均EV >= 1.0 のレース: {sum(1 for e in all_avg_evs if e >= 1.0)} / {len(all_avg_evs)}")
print(f"  最大EV >= 1.0 のレース: {sum(1 for e in all_max_evs if e >= 1.0)} / {len(all_max_evs)}")

# Hit rate by avg EV bucket
print(f"\n  avg EV帯別の的中率:")
for lo, hi in [(0, 0.3), (0.3, 0.5), (0.5, 0.8), (0.8, 1.0), (1.0, 1.5), (1.5, 99)]:
    bucket = [d for d in r_detail["bets_data"] if lo <= d["avg_ev"] < hi]
    if not bucket: continue
    bh = sum(1 for d in bucket if d["hit"])
    bi = sum(d["inv"] for d in bucket)
    br = sum(d["ret"] for d in bucket)
    roi = br/bi*100 if bi else 0
    print(f"    EV {lo:.1f}-{hi:.1f}: {len(bucket):4d}R  的中{bh:3d} ({bh/len(bucket)*100:.1f}%)  "
          f"ROI {roi:.1f}%  profit {br-bi:+,}")

# === 4. Cross-validation ===
print(f"\n{'='*90}")
print("=== 4. クロスバリデーション (前半→後半) ===")
print(f"{'='*90}")
all_dates = sorted(set(r["date"] for r in all_races))
mid = len(all_dates) // 2
train = [r for r in all_races if r["date"] <= all_dates[mid-1]]
test = [r for r in all_races if r["date"] > all_dates[mid-1]]
print(f"学習: {len(train)}R  検証: {len(test)}R\n")

print(f"{'設定':>30s}  {'学習ROI':>8s}  {'検証ROI':>8s}  {'検証収支':>10s}")
print("-" * 70)
configs = [
    ("現行(確率Top7)", dict(bet_selection="prob", min_edge=0)),
    ("EV Top7", dict(bet_selection="ev", min_edge=0)),
    ("Edge Top7", dict(bet_selection="edge", min_edge=0)),
    ("確率Top7 + EV>=0.8", dict(bet_selection="prob", min_edge=0.8)),
    ("確率Top7 + EV>=1.0", dict(bet_selection="prob", min_edge=1.0)),
    ("確率Top7 + EV>=1.5", dict(bet_selection="prob", min_edge=1.5)),
    ("EV Top7 + EV>=0.8", dict(bet_selection="ev", min_edge=0.8)),
    ("EV Top7 + EV>=1.0", dict(bet_selection="ev", min_edge=1.0)),
    ("EV Top7 + EV>=1.5", dict(bet_selection="ev", min_edge=1.5)),
    ("EV Top7 + EV>=2.0", dict(bet_selection="ev", min_edge=2.0)),
]
for name, kw in configs:
    rt = run_ev_edge_strategy(train, current_w, top_n_bets=7, **kw)
    rv = run_ev_edge_strategy(test, current_w, top_n_bets=7, **kw)
    print(f"  {name:>28s}  {rt['roi']:7.1f}%  {rv['roi']:7.1f}%  {rv['profit']:>+10,}  ({rv['n']}R)")
