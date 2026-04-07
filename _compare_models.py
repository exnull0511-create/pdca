"""4モデル公正比較: PL単軸 vs NL多軸 × 7点/14点"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, sys
from collections import defaultdict

# === Data load ===
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
MIN_TOP_EV = 67
MIN_ODDS = 10
SIGMA = 0.90

dates = sorted(RC["date"].dropna().unique())

def get_player_scores(race_info, venue, race_dt):
    bp = BANK_DICT.get(venue, {"roi_tier": "mid", "sashi": 1.0, "makuri": 1.0})
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

    past_slim = db_slim[db_slim["開催日"] < race_dt] if not db_slim.empty else db_slim
    past_all  = db_all[db_all["開催日"] < race_dt] if not db_all.empty else db_all

    player_scores = {}
    for _, row in race_info.iterrows():
        try:
            num = int(row["車番"])
            nm = rb.norm(str(row.get("選手名", "")))
            base = float(row.get("競走得点", 80) or 80)
        except: continue
        hist = past_slim[past_slim["選手名_norm"] == nm] if not past_slim.empty else pd.DataFrame()
        use_slim = not hist.empty
        if hist.empty:
            hist = past_all[past_all["選手名_norm"] == nm] if not past_all.empty else pd.DataFrame()
        ip = ep = 4.0; dp = bp_v = 3.0; nb = sp = 2.0; is_m = is_u = False
        if not hist.empty:
            RECENT_W = 3.0
            sd = sorted(hist["開催日"].dropna().unique(), reverse=True); rd = set(sd[:2])
            def wm(series):
                v = pd.to_numeric(series, errors="coerce")
                w = np.where(hist["開催日"].isin(rd), RECENT_W, 1.0); mk = v.notna()
                return float((v[mk] * w[mk]).sum() / w[mk].sum()) if mk.any() else None
            ip = wm(hist["IP"]) or 4.0; ep = wm(hist["EP"]) or 4.0
            dp = wm(hist["DP"]) or 3.0; bp_v = wm(hist["BP"]) or 3.0
            if use_slim and "直線の伸び" in hist.columns:
                nb = wm(hist["直線の伸び"].apply(rb.nobi_score)) or 2.0
            elif nobi_col in hist.columns:
                nb = wm(hist[nobi_col].apply(rb.nobi_score)) or 2.0
            if "戦法" in hist.columns:
                sp = wm(hist["戦法"].apply(rb.senpo_lead)) or 2.0
            if use_slim:
                is_m = bool(hist.get("is_monster", pd.Series([0])).max() >= 1)
                is_u = bool(hist.get("is_unreliable", pd.Series([0])).max() >= 1)
            else:
                cmt = " ".join(hist.get("解析コメント", pd.Series([""])).astype(str))
                is_m = any(k in cmt for k in ["脚余し", "鬼脚", "別次元", "圧倒"])
                is_u = any(k in cmt for k in ["共倒れ", "位置取り失敗", "不発", "失速"])
        lno = num_to_line.get(num, 0); lbs = line_map.get(lno, [])
        pos = lbs.index(num) + 1 if num in lbs else 1
        pos_b = 0.5 if pos == 1 else -0.3 * (pos - 1)
        ev = (base * 0.4 + ip * 1.5 + ep * 1.2 + dp * bp["makuri"] + bp_v * bp["sashi"]
              + nb * 2.0 + sp * 0.5 + pos_b + (3.0 if is_m else 0) - (2.0 if is_u else 0))
        player_scores[num] = {"name": str(row.get("選手名", "")), "ev": ev,
                               "ip": ip, "is_monster": is_m, "pos_in_line": pos}
    return player_scores, num_to_line


def select_pl_single(ps, ntl, odds_dict, top_n):
    """PL単軸"""
    ranked = sorted(ps.items(), key=lambda x: x[1]["ev"], reverse=True)
    if len(ranked) < 3: return None
    all_nums = [n for n, _ in ranked]; max_e = ranked[0][1]["ev"]
    raw_s = {n: np.exp(ps[n]["ev"] - max_e) for n in all_nums}
    top_ev = ranked[0][1]["ev"]
    if top_ev < MIN_TOP_EV: return None
    def pl(f, s, t):
        d1 = sum(raw_s[n] for n in all_nums)
        d2 = sum(raw_s[n] for n in all_nums if n != f)
        d3 = sum(raw_s[n] for n in all_nums if n not in (f, s))
        return 0.0 if 0 in (d1, d2, d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)
    axis = next((n for n, d in ranked if d["is_monster"]), ranked[0][0])
    others = [n for n, _ in ranked if n != axis]
    ev_bets = sorted(
        [(pl(axis, s, t) * odds_dict.get(f"{axis}-{s}-{t}", 0),
          f"{axis}-{s}-{t}", pl(axis, s, t), odds_dict.get(f"{axis}-{s}-{t}", 0))
         for s in others for t in others if s != t and f"{axis}-{s}-{t}" in odds_dict],
        key=lambda x: x[2], reverse=True)
    sel = ev_bets[:top_n]
    sel = [(ev, c, p, o) for ev, c, p, o in sel if o >= MIN_ODDS]
    bets = [c for _, c, _, _ in sel]
    return bets if bets else None


def select_nl_multi(ps, ntl, odds_dict, top_n):
    """NL多軸"""
    ranked = sorted(ps.items(), key=lambda x: x[1]["ev"], reverse=True)
    if len(ranked) < 3: return None
    all_nums = [n for n, _ in ranked]; max_e = ranked[0][1]["ev"]
    raw_s = {n: np.exp(ps[n]["ev"] - max_e) for n in all_nums}
    top_ev = ranked[0][1]["ev"]
    if top_ev < MIN_TOP_EV: return None
    sigma = SIGMA
    def _nests(members):
        ns = {}
        for n in members:
            ln = ntl.get(n, -n)
            if ln not in ns: ns[ln] = []
            ns[ln].append(n)
        return ns
    def nmarg(tgt, rem):
        if not rem: return 0.0
        ns = _nests(rem); IV = {}
        for ln, ms in ns.items():
            inner = sum(raw_s[m] ** (1.0/sigma) for m in ms)
            IV[ln] = inner ** sigma if inner > 0 else 0.0
        tIV = sum(IV.values())
        if tIV == 0: return 0.0
        tln = ntl.get(tgt, -tgt)
        np_ = IV[tln] / tIV
        id_ = sum(raw_s[m] ** (1.0/sigma) for m in ns[tln])
        if id_ == 0: return 0.0
        return np_ * (raw_s[tgt] ** (1.0/sigma)) / id_
    def ntri(f, s, t):
        p1 = nmarg(f, all_nums)
        if p1 == 0: return 0.0
        p2 = nmarg(s, [n for n in all_nums if n != f])
        if p2 == 0: return 0.0
        p3 = nmarg(t, [n for n in all_nums if n not in (f, s)])
        return p1 * p2 * p3
    all_tri = []
    for f in all_nums:
        for s in all_nums:
            if s == f: continue
            for t in all_nums:
                if t == f or t == s: continue
                combo = f"{f}-{s}-{t}"
                if combo not in odds_dict: continue
                p = ntri(f, s, t); o = odds_dict[combo]
                all_tri.append((p * o, combo, p, o))
    sel = sorted(all_tri, key=lambda x: x[2], reverse=True)[:top_n]
    sel = [(ev, c, p, o) for ev, c, p, o in sel if o >= MIN_ODDS]
    bets = [c for _, c, _, _ in sel]
    return bets if bets else None


def select_nl_single(ps, ntl, odds_dict, top_n):
    """NL単軸: NLの確率モデルだが1着は1人に固定"""
    ranked = sorted(ps.items(), key=lambda x: x[1]["ev"], reverse=True)
    if len(ranked) < 3: return None
    all_nums = [n for n, _ in ranked]; max_e = ranked[0][1]["ev"]
    raw_s = {n: np.exp(ps[n]["ev"] - max_e) for n in all_nums}
    top_ev = ranked[0][1]["ev"]
    if top_ev < MIN_TOP_EV: return None
    sigma = SIGMA
    def _nests(members):
        ns = {}
        for n in members:
            ln = ntl.get(n, -n)
            if ln not in ns: ns[ln] = []
            ns[ln].append(n)
        return ns
    def nmarg(tgt, rem):
        if not rem: return 0.0
        ns = _nests(rem); IV = {}
        for ln, ms in ns.items():
            inner = sum(raw_s[m] ** (1.0/sigma) for m in ms)
            IV[ln] = inner ** sigma if inner > 0 else 0.0
        tIV = sum(IV.values())
        if tIV == 0: return 0.0
        tln = ntl.get(tgt, -tgt)
        np_ = IV[tln] / tIV
        id_ = sum(raw_s[m] ** (1.0/sigma) for m in ns[tln])
        if id_ == 0: return 0.0
        return np_ * (raw_s[tgt] ** (1.0/sigma)) / id_
    def ntri(f, s, t):
        p1 = nmarg(f, all_nums)
        if p1 == 0: return 0.0
        p2 = nmarg(s, [n for n in all_nums if n != f])
        if p2 == 0: return 0.0
        p3 = nmarg(t, [n for n in all_nums if n not in (f, s)])
        return p1 * p2 * p3
    axis = next((n for n, d in ranked if d["is_monster"]), ranked[0][0])
    others = [n for n, _ in ranked if n != axis]
    ev_bets = sorted(
        [(ntri(axis, s, t) * odds_dict.get(f"{axis}-{s}-{t}", 0),
          f"{axis}-{s}-{t}", ntri(axis, s, t), odds_dict.get(f"{axis}-{s}-{t}", 0))
         for s in others for t in others if s != t and f"{axis}-{s}-{t}" in odds_dict],
        key=lambda x: x[2], reverse=True)
    sel = ev_bets[:top_n]
    sel = [(ev, c, p, o) for ev, c, p, o in sel if o >= MIN_ODDS]
    bets = [c for _, c, _, _ in sel]
    return bets if bets else None


# === Strategies ===
strategies = {
    "PL単軸 7点":    lambda ps, ntl, od: select_pl_single(ps, ntl, od, 7),
    "PL単軸 14点":   lambda ps, ntl, od: select_pl_single(ps, ntl, od, 14),
    "NL単軸 7点":    lambda ps, ntl, od: select_nl_single(ps, ntl, od, 7),
    "NL単軸 14点":   lambda ps, ntl, od: select_nl_single(ps, ntl, od, 14),
    "NL多軸 7点":    lambda ps, ntl, od: select_nl_multi(ps, ntl, od, 7),
    "NL多軸 14点":   lambda ps, ntl, od: select_nl_multi(ps, ntl, od, 14),
}

res = {k: {"n": 0, "hits": 0, "invest": 0, "ret": 0, "axes": []} for k in strategies}
res_venue = {k: defaultdict(lambda: {"n": 0, "hits": 0, "invest": 0, "ret": 0}) for k in strategies}
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

        for sname, sfn in strategies.items():
            bets = sfn(ps, ntl, odds_dict)
            if bets is None: continue
            inv = len(bets) * 100
            hit = actual in bets
            ret = payout if hit else 0
            n_axes = len(set(b.split('-')[0] for b in bets))
            res[sname]["n"] += 1
            res[sname]["invest"] += inv
            res[sname]["ret"] += ret
            res[sname]["axes"].append(n_axes)
            if hit: res[sname]["hits"] += 1
            vd = res_venue[sname][venue]
            vd["n"] += 1; vd["invest"] += inv; vd["ret"] += ret
            if hit: vd["hits"] += 1

        rc += 1
        if rc % 200 == 0:
            print(f"  ... {rc} races processed", file=sys.stderr)

print(f"\n{'=' * 100}")
print(f"{'モデル':<16s}  {'R数':>5s}  {'avg点':>5s}  {'軸数':>4s}  "
      f"{'的中':>4s}  {'率':>5s}  {'投資':>12s}  {'払戻':>12s}  {'収支':>12s}  {'ROI':>6s}")
print(f"{'=' * 100}")
for sname, d in res.items():
    if d["n"] == 0: continue
    roi = d["ret"] / d["invest"] * 100 if d["invest"] else 0
    rate = d["hits"] / d["n"] * 100
    avg_bets = d["invest"] / d["n"] / 100
    avg_axes = np.mean(d["axes"])
    print(f"{sname:<16s}  {d['n']:5d}  {avg_bets:5.1f}  {avg_axes:4.1f}  "
          f"{d['hits']:4d}  {rate:4.1f}%  {d['invest']:>12,}  {d['ret']:>12,}  "
          f"{d['ret']-d['invest']:>+12,}  {roi:5.1f}%")

# === Per-venue breakdown ===
print(f"\n\n{'=' * 130}")
print("バンク別収支 (各モデル)")
print(f"{'=' * 130}")

# Collect all venues
all_venues = set()
for sname in strategies:
    all_venues |= set(res_venue[sname].keys())

# Sort venues by total race count (across all strategies)
venue_total = {}
for v in all_venues:
    venue_total[v] = max(res_venue[sname].get(v, {}).get("n", 0) for sname in strategies)

# Header
model_names = list(strategies.keys())
hdr = f"{'バンク':>8s} {'R数':>4s}"
for mn in model_names:
    short = mn.replace("点", "").replace(" ", "")
    hdr += f"  {short:>14s}"
print(hdr)
print("-" * (15 + 16 * len(model_names)))

for v in sorted(all_venues, key=lambda x: -venue_total[x]):
    if venue_total[v] < 10:
        continue
    line = f"{v:>8s} {venue_total[v]:4d}"
    for mn in model_names:
        vd = res_venue[mn].get(v)
        if vd and vd["invest"] > 0:
            roi = vd["ret"] / vd["invest"] * 100
            profit = vd["ret"] - vd["invest"]
            line += f"  {roi:5.0f}%/{profit:>+7,}"
        else:
            line += f"  {'---':>14s}"
    print(line)

# Totals row
line = f"{'合計':>8s} {'':>4s}"
for mn in model_names:
    d = res[mn]
    if d["invest"] > 0:
        roi = d["ret"] / d["invest"] * 100
        profit = d["ret"] - d["invest"]
        line += f"  {roi:5.0f}%/{profit:>+7,}"
    else:
        line += f"  {'---':>14s}"
print("-" * (15 + 16 * len(model_names)))
print(line)
