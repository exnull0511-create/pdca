"""新特徴量検証: 調子/ライン構成/バンク×戦法 で市場均衡帯のエッジを探す"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, sys
from collections import defaultdict, Counter

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
FEATS = ["base", "ip", "ep", "dp", "bp", "nb", "sp", "pos_b", "is_m"]

dates = sorted(RC["date"].dropna().unique())

# === Collect enriched race data ===
print("Collecting enriched features...", file=sys.stderr)
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

        players = {}
        for _, row in race_info.iterrows():
            try:
                num = int(row["車番"])
                nm = rb.norm(str(row.get("選手名", "")))
                base_v = float(row.get("競走得点", 80) or 80)
                style = str(row.get("脚質", ""))
            except: continue
            hist = past_slim[past_slim["選手名_norm"] == nm] if not past_slim.empty else pd.DataFrame()
            use_slim = not hist.empty
            if hist.empty:
                hist = past_all[past_all["選手名_norm"] == nm] if not past_all.empty else pd.DataFrame()
            ip = ep = 4.0; dp_v = bp_v = 3.0; nb = sp = 2.0; is_m = 0
            # --- 新特徴量: 調子(直近の得点変動) ---
            form_trend = 0.0  # 直近2開催の平均得点 - 全期間平均得点
            n_hist = 0
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

                # 調子: 直近2開催IP vs 全期間IP
                n_hist = len(hist)
                if len(sd) >= 3:
                    recent_ip = pd.to_numeric(hist[hist["開催日"].isin(rd)]["IP"], errors="coerce").mean()
                    all_ip = pd.to_numeric(hist["IP"], errors="coerce").mean()
                    if not np.isnan(recent_ip) and not np.isnan(all_ip):
                        form_trend = recent_ip - all_ip

            lno = num_to_line.get(num, 0); lbs = line_map.get(lno, [])
            pos = lbs.index(num) + 1 if num in lbs else 1
            pos_b = 0.5 if pos == 1 else -0.3 * (pos - 1)

            # 戦法分類
            is_senko = 1 if style in ("逃", "追込") or sp >= 3.5 else 0  # 先行系
            is_oikomi = 1 if style in ("追", "追込") or sp <= 1.5 else 0  # 追込系

            players[num] = {
                "num": num, "base": base_v, "ip": ip, "ep": ep,
                "dp": dp_v * bp["makuri"], "bp": bp_v * bp["sashi"],
                "nb": nb, "sp": sp, "pos_b": pos_b, "is_m": is_m,
                "form_trend": form_trend, "n_hist": n_hist,
                "is_senko": is_senko, "is_oikomi": is_oikomi,
                "line": num_to_line.get(num, -num), "pos": pos,
                "raw_base": base_v, "raw_ip": ip,
            }

        if len(players) < 3: continue

        # --- ライン構成の特徴量 ---
        line_groups = defaultdict(list)
        for num, p in players.items():
            line_groups[p["line"]].append(p)

        for num, p in players.items():
            lg = line_groups[p["line"]]
            p["line_size"] = len(lg)
            p["line_total_base"] = sum(pp["raw_base"] for pp in lg)
            p["line_avg_base"] = p["line_total_base"] / len(lg)
            # ラインの先頭(1番手)のIP
            leader = [pp for pp in lg if pp["pos"] == 1]
            p["line_leader_ip"] = leader[0]["raw_ip"] if leader else p["raw_ip"]
            # ライン内の自分の位置の優位性(番手が2番手で先頭が強い→有利)
            if p["pos"] == 2 and leader:
                p["bantsuke_edge"] = leader[0]["raw_ip"] - 4.0  # 先頭IPが高いほど番手有利
            else:
                p["bantsuke_edge"] = 0.0

        # --- バンク×戦法 ---
        sashi_coef = bp["sashi"]
        makuri_coef = bp["makuri"]
        for num, p in players.items():
            # 差しバンクで追込系 or 捲りバンクで先行系 → 相性ボーナス
            p["bank_style_fit"] = (sashi_coef - 1.0) * p["ep"] + (makuri_coef - 1.0) * p["ip"]

        all_races.append({
            "players": players, "actual": actual, "payout": payout,
            "odds_dict": odds_dict, "venue": venue, "date": str(race_date.date()),
        })
        rc += 1
        if rc % 200 == 0: print(f"  ... {rc}", file=sys.stderr)

print(f"Races: {len(all_races)}", file=sys.stderr)

# === Scoring function with new features ===
BASE_FEATS = ["base", "ip", "ep", "dp", "bp", "nb", "sp", "pos_b", "is_m"]
NEW_FEATS = ["form_trend", "line_size", "line_avg_base", "bantsuke_edge", "bank_style_fit"]
ALL_FEATS = BASE_FEATS + NEW_FEATS

def simulate(races, weights, feat_names, top_n=7, min_ev=67, min_odds=10):
    total_inv = total_ret = total_n = total_hits = 0
    for race in races:
        scored = []
        for num, p in race["players"].items():
            s = sum(p.get(f, 0) * w for f, w in zip(feat_names, weights))
            scored.append((s, num))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored[0][0] < min_ev: continue

        all_nums = [n for _, n in scored]; max_e = scored[0][0]
        raw_s = {n: np.exp(s - max_e) for s, n in scored}
        axis = scored[0][1]
        for s, n in scored[:3]:
            if race["players"][n]["is_m"]: axis = n; break
        others = [n for n in all_nums if n != axis]
        od = race["odds_dict"]

        def pl(f, s, t):
            d1 = sum(raw_s[n] for n in all_nums)
            d2 = sum(raw_s[n] for n in all_nums if n != f)
            d3 = sum(raw_s[n] for n in all_nums if n not in (f, s))
            return 0.0 if 0 in (d1, d2, d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)

        cands = []
        for sn in others:
            for tn in others:
                if sn == tn: continue
                c = f"{axis}-{sn}-{tn}"
                if c not in od: continue
                o = od[c]
                if o < min_odds: continue
                p = pl(axis, sn, tn)
                cands.append((p, c, o))
        cands.sort(key=lambda x: x[0], reverse=True)
        bets = [c for _, c, _ in cands[:top_n]]
        if not bets: continue

        inv = len(bets) * 100
        hit = race["actual"] in bets
        ret = race["payout"] if hit else 0
        total_inv += inv; total_ret += ret; total_n += 1
        if hit: total_hits += 1

    roi = total_ret / total_inv * 100 if total_inv > 0 else 0
    return {"n": total_n, "hits": total_hits, "roi": roi,
            "profit": total_ret - total_inv, "invest": total_inv, "ret": total_ret}


# === 1. 新特徴量の単独効果 ===
print(f"\n{'='*90}")
print("=== 1. 新特徴量の単独効果 (既存ウェイト + 新特徴量1つ追加) ===")
print(f"{'='*90}")

current_w = [0.4, 1.5, 1.2, 1.0, 1.0, 2.0, 0.5, 1.0, 3.0]
r_base = simulate(all_races, current_w, BASE_FEATS)
print(f"{'設定':>35s}  {'R数':>5s}  {'的中':>4s}  {'率':>5s}  {'収支':>12s}  {'ROI':>6s}")
print("-" * 80)
print(f"  {'現行(追加なし)':>33s}  {r_base['n']:5d}  {r_base['hits']:4d}  "
      f"{r_base['hits']/r_base['n']*100:4.1f}%  {r_base['profit']:>+12,}  {r_base['roi']:5.1f}%")

for feat_name, candidates in [
    ("form_trend(調子)", [0.5, 1.0, 1.5, 2.0, 3.0, 5.0]),
    ("line_size(ライン人数)", [0.5, 1.0, 2.0, 3.0, 5.0]),
    ("line_avg_base(ライン平均得点)", [0.01, 0.02, 0.05, 0.1, 0.2]),
    ("bantsuke_edge(番手有利度)", [0.5, 1.0, 2.0, 3.0, 5.0]),
    ("bank_style_fit(バンク×戦法)", [0.5, 1.0, 2.0, 3.0, 5.0]),
]:
    raw_name = feat_name.split("(")[0]
    best_w = 0; best_roi = r_base["roi"]; best_r = None
    for w in candidates:
        test_w = current_w + [0] * len(NEW_FEATS)
        idx = ALL_FEATS.index(raw_name)
        test_w[idx] = w
        r = simulate(all_races, test_w, ALL_FEATS)
        if r["roi"] > best_roi:
            best_roi = r["roi"]; best_w = w; best_r = r
    if best_r:
        diff = best_r["roi"] - r_base["roi"]
        print(f"  +{feat_name:>31s}={best_w:<4}  {best_r['n']:5d}  {best_r['hits']:4d}  "
              f"{best_r['hits']/best_r['n']*100:4.1f}%  {best_r['profit']:>+12,}  {best_r['roi']:5.1f}% ({diff:+.1f}%)")
    else:
        print(f"  +{feat_name:>31s}  改善なし")


# === 2. 組み合わせ最適化 ===
print(f"\n{'='*90}")
print("=== 2. 新特徴量組み合わせ ===")
print(f"{'='*90}")
combos = [
    ("現行", current_w + [0]*5),
    ("調子1.0", current_w + [1.0, 0, 0, 0, 0]),
    ("調子2.0", current_w + [2.0, 0, 0, 0, 0]),
    ("ライン人数2.0", current_w + [0, 2.0, 0, 0, 0]),
    ("番手有利2.0", current_w + [0, 0, 0, 2.0, 0]),
    ("バンク戦法2.0", current_w + [0, 0, 0, 0, 2.0]),
    ("調子1+番手2", current_w + [1.0, 0, 0, 2.0, 0]),
    ("調子1+ライン2+番手2", current_w + [1.0, 2.0, 0, 2.0, 0]),
    ("調子2+番手3+バンク戦法2", current_w + [2.0, 0, 0, 3.0, 2.0]),
    ("全部入り(1,2,0,2,2)", current_w + [1.0, 2.0, 0, 2.0, 2.0]),
    ("全部入り(2,3,0,3,2)", current_w + [2.0, 3.0, 0, 3.0, 2.0]),
]
print(f"{'設定':>35s}  {'R数':>5s}  {'的中':>4s}  {'率':>5s}  {'収支':>12s}  {'ROI':>6s}")
print("-" * 80)
for name, w in combos:
    r = simulate(all_races, w, ALL_FEATS)
    print(f"  {name:>33s}  {r['n']:5d}  {r['hits']:4d}  "
          f"{r['hits']/r['n']*100:4.1f}%  {r['profit']:>+12,}  {r['roi']:5.1f}%")


# === 3. CV検証 ===
print(f"\n{'='*90}")
print("=== 3. クロスバリデーション ===")
print(f"{'='*90}")
all_dates = sorted(set(r["date"] for r in all_races))
mid = len(all_dates) // 2
train = [r for r in all_races if r["date"] <= all_dates[mid-1]]
test = [r for r in all_races if r["date"] > all_dates[mid-1]]
print(f"学習: {len(train)}R  検証: {len(test)}R\n")

print(f"{'設定':>35s}  {'学習ROI':>8s}  {'検証ROI':>8s}  {'検証収支':>10s}  {'検証R':>5s}")
print("-" * 80)
for name, w in combos:
    rt = simulate(train, w, ALL_FEATS)
    rv = simulate(test, w, ALL_FEATS)
    print(f"  {name:>33s}  {rt['roi']:7.1f}%  {rv['roi']:7.1f}%  {rv['profit']:>+10,}  {rv['n']:5d}")


# === 4. 新特徴量が1着予測に与える影響分析 ===
print(f"\n{'='*90}")
print("=== 4. 新特徴量の1着選手 vs 非1着選手の差 ===")
print(f"{'='*90}")
winner_feats = defaultdict(list)
loser_feats = defaultdict(list)
for race in all_races:
    actual_parts = race["actual"].split("-")
    if len(actual_parts) != 3: continue
    a1 = int(actual_parts[0])
    for num, p in race["players"].items():
        target = winner_feats if num == a1 else loser_feats
        for f in NEW_FEATS:
            target[f].append(p.get(f, 0))

print(f"{'特徴量':>20s}  {'1着平均':>10s}  {'非1着平均':>10s}  {'差':>10s}  {'効果':>6s}")
print("-" * 65)
for f in NEW_FEATS:
    wm = np.mean(winner_feats[f])
    lm = np.mean(loser_feats[f])
    diff = wm - lm
    effect = "◎" if abs(diff) > 0.1 else ("○" if abs(diff) > 0.05 else "△")
    print(f"  {f:>18s}  {wm:10.3f}  {lm:10.3f}  {diff:+10.3f}  {effect}")
