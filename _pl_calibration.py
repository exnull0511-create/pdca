"""PL確率のキャリブレーション分析
予測確率 vs 実際の的中率を比較
"""
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
MIN_EV = 67

dates = sorted(RC["date"].dropna().unique())
print("Loading...", file=sys.stderr)

# === Collect all (combo, predicted_prob, market_implied_prob, actually_won) tuples ===
all_combo_data = []  # for calibration analysis

for race_date in dates:
    daily_rc = RC[RC["date"] == race_date]
    for race_id in daily_rc["race_id"].unique():
        race_info = daily_rc[daily_rc["race_id"] == race_id].copy()
        if race_info.empty: continue
        venue = race_info.iloc[0]["venue"]
        bp_d = BANK_DICT.get(venue, {"roi_tier":"mid","sashi":1.0,"makuri":1.0})
        od_race = OD[OD["race_id"] == race_id]
        odds_dict = {str(r["組み合わせ"]).strip(): float(r["オッズ"])
                     for _, r in od_race.iterrows() if pd.notna(r["オッズ"])}
        py_race = PY[PY["race_id"] == race_id]
        if py_race.empty: continue
        actual = str(py_race.iloc[0]["result_trifecta"]).strip()
        if not actual or actual == "nan": continue

        past_slim = db_slim[db_slim["開催日"]<race_date] if not db_slim.empty else db_slim
        past_all = db_all[db_all["開催日"]<race_date] if not db_all.empty else db_all
        lines={}; num_to_line={}
        for _,row in race_info.iterrows():
            try: num=int(row["車番"]); lno=int(row.get("line_no",0) or 0)
            except: continue
            bs=str(row.get("line_bibs",str(num)))
            if lno not in lines:
                try: lines[lno]=[int(b) for b in bs.split("-") if b.isdigit()]
                except: lines[lno]=[num]
            num_to_line[num]=lno

        ps={}
        for _,row in race_info.iterrows():
            try:
                num=int(row["車番"]); nm=rb.norm(str(row.get("選手名","")))
                base=float(row.get("競走得点",80) or 80)
            except: continue
            hist=past_slim[past_slim["選手名_norm"]==nm] if not past_slim.empty else pd.DataFrame()
            use_slim=not hist.empty
            if hist.empty: hist=past_all[past_all["選手名_norm"]==nm] if not past_all.empty else pd.DataFrame()
            ip=ep=4.0; dp=bp_v=3.0; nb=2.0; is_m=is_u=False; form_trend=0.0
            if not hist.empty:
                RW=3.0; sd=sorted(hist["開催日"].dropna().unique(),reverse=True); rd=set(sd[:2])
                def wm(s):
                    v=pd.to_numeric(s,errors="coerce"); w=np.where(hist["開催日"].isin(rd),RW,1.0); mk=v.notna()
                    return float((v[mk]*w[mk]).sum()/w[mk].sum()) if mk.any() else None
                ip=wm(hist["IP"]) or 4.0; ep=wm(hist["EP"]) or 4.0
                dp=wm(hist["DP"]) or 3.0; bp_v=wm(hist["BP"]) or 3.0
                if use_slim and "直線の伸び" in hist.columns: nb=wm(hist["直線の伸び"].apply(rb.nobi_score)) or 2.0
                elif nobi_col in hist.columns: nb=wm(hist[nobi_col].apply(rb.nobi_score)) or 2.0
                if use_slim:
                    is_m=bool(hist.get("is_monster",pd.Series([0])).max()>=1)
                    is_u=bool(hist.get("is_unreliable",pd.Series([0])).max()>=1)
                else:
                    cmt=" ".join(hist.get("解析コメント",pd.Series([""])).astype(str))
                    is_m=any(k in cmt for k in ["脚余し","鬼脚","別次元","圧倒"])
                    is_u=any(k in cmt for k in ["共倒れ","位置取り失敗","不発","失速"])
                if len(sd)>=3:
                    ri=pd.to_numeric(hist[hist["開催日"].isin(rd)]["IP"],errors="coerce").mean()
                    ai=pd.to_numeric(hist["IP"],errors="coerce").mean()
                    if not np.isnan(ri) and not np.isnan(ai): form_trend=ri-ai
            lno=num_to_line.get(num,0); lbs=lines.get(lno,[num])
            pos=lbs.index(num)+1 if num in lbs else 1
            pos_b=0.5 if pos==1 else -0.3*(pos-1)
            bsf=(bp_d["sashi"]-1.0)*ep+(bp_d["makuri"]-1.0)*ip
            ev=(base*0.4+ip*1.5+ep*1.2+dp*bp_d["makuri"]+bp_v*bp_d["sashi"]
                +nb*2.0+pos_b+(3.0 if is_m else 0)-(2.0 if is_u else 0)
                +form_trend*1.0+bsf*2.0)
            ps[num]={"ev":ev,"is_m":is_m,"ip":ip,"pos":pos}

        if len(ps)<3: continue
        ranked=sorted(ps.items(),key=lambda x:x[1]["ev"],reverse=True)
        top_ev=ranked[0][1]["ev"]
        if top_ev<MIN_EV: continue
        sl=[nn for nn,d in ps.items() if d["ip"]>=5.5 and d["pos"]==1]
        if len(sl)>=2: continue

        all_nums=[nn for nn,_ in ranked]; max_e=ranked[0][1]["ev"]
        raw_s={nn:np.exp(ps[nn]["ev"]-max_e) for nn in all_nums}
        axis=next((nn for nn,d in ranked if d["is_m"]),ranked[0][0])
        others=[nn for nn in all_nums if nn!=axis]

        def pl(f,s,t):
            d1=sum(raw_s[nn] for nn in all_nums);d2=sum(raw_s[nn] for nn in all_nums if nn!=f)
            d3=sum(raw_s[nn] for nn in all_nums if nn not in(f,s))
            return 0.0 if 0 in(d1,d2,d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)

        # All single-axis trifectas
        for sn in others:
            for tn in others:
                if sn==tn: continue
                c=f"{axis}-{sn}-{tn}"
                if c not in odds_dict: continue
                o=odds_dict[c]
                p_pl=pl(axis,sn,tn)
                # Market implied (very rough: 1/odds, doesn't normalize)
                p_market=1.0/o if o>0 else 0
                won = (c == actual)
                all_combo_data.append({
                    "combo":c, "p_pl":p_pl, "p_market":p_market,
                    "odds":o, "won":won, "venue":venue,
                })

print(f"Total combos analyzed: {len(all_combo_data)}", file=sys.stderr)

df = pd.DataFrame(all_combo_data)
print(f"\nN combos: {len(df)}, N wins: {df['won'].sum()}")
print(f"Predicted prob sum (axis fixed) per race avg: {df.groupby('venue')['p_pl'].sum().mean():.3f}")

# === 1. Calibration by predicted probability bins ===
print(f"\n{'='*85}")
print("=== 1. PL予測確率 vs 実際的中率 ===")
print(f"{'='*85}")
print(f"{'予測確率帯':>14s}  {'件数':>6s}  {'平均予測%':>10s}  {'実際的中%':>10s}  {'乖離':>8s}  {'評価':>10s}")
print("-"*70)

bins = [(0,0.001),(0.001,0.005),(0.005,0.01),(0.01,0.02),(0.02,0.03),
        (0.03,0.05),(0.05,0.08),(0.08,0.12),(0.12,0.20),(0.20,1.0)]
for lo, hi in bins:
    sub = df[(df["p_pl"]>=lo)&(df["p_pl"]<hi)]
    if len(sub)==0: continue
    avg_pred = sub["p_pl"].mean() * 100
    actual = sub["won"].mean() * 100
    diff = actual - avg_pred
    if abs(diff) < 0.3:
        eval_str = "○"
    elif diff > 0:
        eval_str = "↑過小"
    else:
        eval_str = "↓過大"
    print(f"  {lo*100:5.1f}%-{hi*100:5.1f}%  {len(sub):6d}  {avg_pred:9.2f}%  {actual:9.2f}%  {diff:+7.2f}%  {eval_str:>10s}")

# === 2. Calibration by market implied probability ===
print(f"\n{'='*85}")
print("=== 2. 市場確率(1/odds) vs 実際的中率 ===")
print(f"{'='*85}")
print(f"{'市場確率帯':>14s}  {'件数':>6s}  {'平均市場%':>10s}  {'実際的中%':>10s}  {'乖離':>8s}")
print("-"*65)

for lo, hi in bins:
    sub = df[(df["p_market"]>=lo)&(df["p_market"]<hi)]
    if len(sub)==0: continue
    avg_pred = sub["p_market"].mean() * 100
    actual = sub["won"].mean() * 100
    diff = actual - avg_pred
    print(f"  {lo*100:5.1f}%-{hi*100:5.1f}%  {len(sub):6d}  {avg_pred:9.2f}%  {actual:9.2f}%  {diff:+7.2f}%")

# === 3. 市場 vs PL: 同じオッズ帯で予測確率が違うか ===
print(f"\n{'='*85}")
print("=== 3. オッズ帯別: PL予測 vs 市場確率 vs 実績 ===")
print(f"{'='*85}")
print(f"{'オッズ帯':>14s}  {'件数':>6s}  {'PL予測%':>9s}  {'市場%':>8s}  {'実際%':>8s}  {'PL乖離':>8s}  {'市場乖離':>8s}")
print("-"*80)

odds_bins = [(0,5),(5,10),(10,20),(20,50),(50,100),(100,300),(300,1000),(1000,99999)]
for lo, hi in odds_bins:
    sub = df[(df["odds"]>=lo)&(df["odds"]<hi)]
    if len(sub)==0: continue
    pl_pred = sub["p_pl"].mean() * 100
    market = sub["p_market"].mean() * 100
    actual = sub["won"].mean() * 100
    print(f"  {lo:5.0f}-{hi:5.0f}倍  {len(sub):6d}  {pl_pred:8.2f}%  {market:7.2f}%  {actual:7.2f}%  "
          f"{actual-pl_pred:+7.2f}%  {actual-market:+7.2f}%")

# === 4. PL vs Market: どっちが当てるか ===
print(f"\n{'='*85}")
print("=== 4. PL Top1 vs 市場Top1 (オッズ最低 = 1番人気) の的中精度 ===")
print(f"{'='*85}")

# Group by race
race_groups = df.groupby([df["combo"].str.split("-").str[0], df["venue"]])
# Better: group by combination of all features that identify a race
# Actually we need race_id - let me use a hash

# Simpler: for each unique axis-venue combination, find the top PL prob and top market prob
# But actually each axis already has up to ~56 combos. Let me restructure.

# Let me re-aggregate by (race_id-like)
# We have venue, but not race_id. Add race_id earlier.
print("(再構成: race_id情報がないため代替集計)")

pl_top_correct = 0
market_top_correct = 0
n_groups = 0

# Group by axis (first num) - same axis means same race
for (axis_str, venue), grp in df.groupby([df["combo"].str.split("-").str[0], df["venue"]]):
    if grp["won"].sum() == 0: continue  # no winner in this group (probably partial)
    pl_top = grp.loc[grp["p_pl"].idxmax()]
    market_top = grp.loc[grp["p_market"].idxmax()]
    n_groups += 1
    if pl_top["won"]: pl_top_correct += 1
    if market_top["won"]: market_top_correct += 1

if n_groups > 0:
    print(f"  PL Top1 的中: {pl_top_correct}/{n_groups} ({pl_top_correct/n_groups*100:.1f}%)")
    print(f"  市場Top1 的中: {market_top_correct}/{n_groups} ({market_top_correct/n_groups*100:.1f}%)")

# === 5. PL vs Market のスケール係数（線形回帰っぽく） ===
print(f"\n{'='*85}")
print("=== 5. キャリブレーション補正係数 ===")
print(f"{'='*85}")

# Logistic-style: log(actual) vs log(predicted)
# But simpler: calculate average ratio actual/predicted per bin
print("各確率帯での 実際/予測 の比率:")
for lo, hi in [(0,0.005),(0.005,0.02),(0.02,0.05),(0.05,0.10),(0.10,0.20),(0.20,1.0)]:
    sub = df[(df["p_pl"]>=lo)&(df["p_pl"]<hi)]
    if len(sub)<10: continue
    pred = sub["p_pl"].mean()
    actual = sub["won"].mean()
    ratio = actual/pred if pred>0 else 0
    print(f"  PL{lo*100:.1f}%-{hi*100:.1f}%: pred={pred:.4f} actual={actual:.4f} ratio={ratio:.2f}")
