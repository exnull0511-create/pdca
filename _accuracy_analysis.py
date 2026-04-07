"""予想精度の深掘り分析: 何が当たって何が外れているか"""
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

dates = sorted(RC["date"].dropna().unique())
results = []

for race_date in dates:
    daily_rc = RC[RC["date"] == race_date]
    for race_id in daily_rc["race_id"].unique():
        race_info = daily_rc[daily_rc["race_id"] == race_id].copy()
        if race_info.empty: continue
        venue = race_info.iloc[0]["venue"]
        bp = BANK_DICT.get(venue, {"roi_tier": "mid", "sashi": 1.0, "makuri": 1.0})

        py_race = PY[PY["race_id"] == race_id]
        if py_race.empty: continue
        actual = str(py_race.iloc[0]["result_trifecta"]).strip()
        if not actual or actual == "nan": continue
        actual_parts = actual.split("-")
        if len(actual_parts) != 3: continue
        a1, a2, a3 = [int(x) for x in actual_parts]

        # Build player scores
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

        scores = {}
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
                else:
                    cmt = " ".join(hist.get("解析コメント", pd.Series([""])).astype(str))
                    is_m = any(k in cmt for k in ["脚余し", "鬼脚", "別次元", "圧倒"])

            lno = num_to_line.get(num, 0); lbs = line_map.get(lno, [])
            pos = lbs.index(num) + 1 if num in lbs else 1
            pos_b = 0.5 if pos == 1 else -0.3 * (pos - 1)
            ev = (base * 0.4 + ip * 1.5 + ep * 1.2 + dp * bp["makuri"] + bp_v * bp["sashi"]
                  + nb * 2.0 + sp * 0.5 + pos_b + (3.0 if is_m else 0))
            scores[num] = {"ev": ev, "ip": ip, "ep": ep, "dp": dp, "bp": bp_v,
                           "nb": nb, "sp": sp, "is_m": is_m, "base": base, "pos": pos,
                           "line": num_to_line.get(num, -1)}

        if len(scores) < 3: continue
        ranked = sorted(scores.items(), key=lambda x: x[1]["ev"], reverse=True)
        top_ev = ranked[0][1]["ev"]
        if top_ev < 67: continue

        rank_map = {n: i+1 for i, (n, _) in enumerate(ranked)}
        our_top = ranked[0][0]
        actual_finish = [0, 0, 0]  # where our top3 finished
        for i in range(min(3, len(ranked))):
            pn = ranked[i][0]
            if pn == a1: actual_finish[i] = 1
            elif pn == a2: actual_finish[i] = 2
            elif pn == a3: actual_finish[i] = 3

        # Line analysis: did a whole line come in?
        a1_line = num_to_line.get(a1, -1)
        a2_line = num_to_line.get(a2, -2)
        a3_line = num_to_line.get(a3, -3)
        line_sweep = a1_line == a2_line  # 1-2 same line

        # Our top's line members
        our_line = scores[our_top]["line"]
        our_line_members = [n for n, ln in num_to_line.items() if ln == our_line and n in scores]
        line_size = len(our_line_members)

        results.append({
            "venue": venue,
            "pred_rank_a1": rank_map.get(a1, 99),
            "pred_rank_a2": rank_map.get(a2, 99),
            "pred_rank_a3": rank_map.get(a3, 99),
            "our_top_finish": 1 if our_top == a1 else (2 if our_top == a2 else (3 if our_top == a3 else 0)),
            "top_ev": top_ev, "ev_gap": ranked[0][1]["ev"] - scores.get(a1, {"ev": 0})["ev"],
            "winner_base": scores[a1]["base"] if a1 in scores else 0,
            "winner_ip": scores[a1]["ip"] if a1 in scores else 0,
            "winner_ep": scores[a1]["ep"] if a1 in scores else 0,
            "winner_sp": scores[a1]["sp"] if a1 in scores else 0,
            "winner_nb": scores[a1]["nb"] if a1 in scores else 0,
            "winner_pos": scores[a1]["pos"] if a1 in scores else 0,
            "winner_is_m": scores[a1]["is_m"] if a1 in scores else False,
            "winner_line": a1_line,
            "line_sweep_12": line_sweep,
            "our_line_size": line_size,
            "n_players": len(scores),
        })

print(f"Analyzed {len(results)} races")
df = pd.DataFrame(results)

print("\n=== 1. 予想1位は実際何着か ===")
for f in [1, 2, 3, 0]:
    label = f"{f}着" if f > 0 else "着外"
    cnt = (df["our_top_finish"] == f).sum()
    print(f"  {label}: {cnt} ({cnt/len(df)*100:.1f}%)")

print("\n=== 2. 実際の1着は予想何位か ===")
for r in range(1, 10):
    cnt = (df["pred_rank_a1"] == r).sum()
    print(f"  予想{r}位: {cnt} ({cnt/len(df)*100:.1f}%)")

print("\n=== 3. 予想1位が外れた時の特徴 ===")
correct = df[df["pred_rank_a1"] == 1]
wrong = df[df["pred_rank_a1"] > 1]
for feat in ["winner_base", "winner_ip", "winner_ep", "winner_sp", "winner_nb"]:
    short = feat.replace("winner_", "")
    cm = correct[feat].mean()
    wm = wrong[feat].mean()
    print(f"  {short:>6s}: 的中{cm:.2f}  外れ{wm:.2f}  差{cm-wm:+.2f}")

print("\n=== 4. EVギャップ(予想1位と実際1着のEV差) ===")
print(f"  外れ時 平均: {wrong['ev_gap'].mean():.2f}")
for lo, hi, label in [(0,2,"僅差0-2"),(2,5,"小差2-5"),(5,10,"中差5-10"),(10,99,"大差10+")]:
    cnt = ((wrong["ev_gap"]>=lo)&(wrong["ev_gap"]<hi)).sum()
    pct = cnt/len(wrong)*100
    print(f"    {label}: {cnt} ({pct:.1f}%)")

print("\n=== 5. 実1着のライン位置 (全レース) ===")
for p in [1, 2, 3, 4]:
    cnt = (df["winner_pos"] == p).sum()
    print(f"  {p}番手: {cnt} ({cnt/len(df)*100:.1f}%)")

print("\n=== 6. ライン決着(1-2着が同ライン) ===")
ls = df["line_sweep_12"].sum()
print(f"  同ライン1-2着: {ls} ({ls/len(df)*100:.1f}%)")
print(f"  異ライン1-2着: {len(df)-ls} ({(len(df)-ls)/len(df)*100:.1f}%)")

# When line sweep, how often do we predict correctly?
ls_correct = df[df["line_sweep_12"] & (df["pred_rank_a1"] == 1)].shape[0]
ls_total = df[df["line_sweep_12"]].shape[0]
nls_correct = df[~df["line_sweep_12"] & (df["pred_rank_a1"] == 1)].shape[0]
nls_total = df[~df["line_sweep_12"]].shape[0]
print(f"  ライン決着時の1着的中: {ls_correct}/{ls_total} ({ls_correct/ls_total*100:.1f}%)")
print(f"  異ライン時の1着的中:   {nls_correct}/{nls_total} ({nls_correct/nls_total*100:.1f}%)")

print("\n=== 7. 鬼脚フラグの有効性 ===")
m_total = df[df["winner_is_m"]].shape[0]
m_correct = df[df["winner_is_m"] & (df["pred_rank_a1"]==1)].shape[0]
nm_total = df[~df["winner_is_m"]].shape[0]
nm_correct = df[~df["winner_is_m"] & (df["pred_rank_a1"]==1)].shape[0]
if m_total: print(f"  鬼脚1着: {m_total}R 予想的中{m_correct} ({m_correct/m_total*100:.1f}%)")
if nm_total: print(f"  非鬼脚1着: {nm_total}R 予想的中{nm_correct} ({nm_correct/nm_total*100:.1f}%)")

print("\n=== 8. 各特徴量の単独予測力(1着との相関) ===")
# For each feature, rank players by that feature alone and check top1 accuracy
# We need per-race per-player data... approximate with winner stats
feats = ["base", "ip", "ep", "sp", "nb"]
print("  (1着選手のその特徴値が全選手中1位だった割合)")
# This is stored differently - let me use winner stats relative to the field
# We only have winner stats, not all player stats. Skip for now.
print("  (別途要実装)")

print("\n=== 9. 現行スコアの各項目ウェイト vs 的中への貢献 ===")
print("  現行ウェイト:")
print("    競走得点×0.4  IP×1.5  EP×1.2  DP×bank  BP×bank  伸び×2.0  戦法×0.5  ライン位置±0.5  鬼脚+3.0")
print()
print("  問題の仮説:")
print("    1) IPウェイト(1.5)が高すぎ? → 先行有利を過大評価してる可能性")
print("    2) 競走得点(0.4)が低すぎ? → 公式の強さ指標を軽視してる")
print("    3) 伸び(2.0)が高すぎ? → 直線の伸びは条件依存で安定しない")
print("    4) ライン構造の反映が不十分 → 番手差し/捲りの展開が読めてない")
