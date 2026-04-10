"""PL温度パラメータ検証: exp((EV-max)/T) でキャリブレーション改善"""
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

# Collect race data once
all_races_data = []
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
        payout = int(float(str(py_race.iloc[0]["payout_trifecta"]).replace(",",""))) \
            if pd.notna(py_race.iloc[0]["payout_trifecta"]) else 0
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
        all_races_data.append({"ps":ps,"actual":actual,"payout":payout,
                               "odds_dict":odds_dict,"venue":venue,
                               "date":str(race_date.date())})

print(f"Races: {len(all_races_data)}", file=sys.stderr)


def calc_pl_probs(ps, ranked, T):
    """温度パラメータT付きPL確率を返す。axis-s-tの全組み合わせ"""
    all_nums=[nn for nn,_ in ranked]; max_e=ranked[0][1]["ev"]
    raw_s={nn:np.exp((ps[nn]["ev"]-max_e)/T) for nn in all_nums}
    axis=next((nn for nn,d in ranked if d["is_m"]),ranked[0][0])
    others=[nn for nn in all_nums if nn!=axis]
    def pl(f,s,t):
        d1=sum(raw_s[nn] for nn in all_nums);d2=sum(raw_s[nn] for nn in all_nums if nn!=f)
        d3=sum(raw_s[nn] for nn in all_nums if nn not in(f,s))
        return 0.0 if 0 in(d1,d2,d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)
    probs={}
    for sn in others:
        for tn in others:
            if sn==tn: continue
            c=f"{axis}-{sn}-{tn}"
            probs[c]=pl(axis,sn,tn)
    return axis, probs


def calibration_analysis(T):
    """指定温度でのキャリブレーション分析"""
    combo_data = []
    for race in all_races_data:
        ps=race["ps"]
        ranked=sorted(ps.items(),key=lambda x:x[1]["ev"],reverse=True)
        axis, probs = calc_pl_probs(ps, ranked, T)
        for c, p in probs.items():
            if c not in race["odds_dict"]: continue
            o=race["odds_dict"][c]
            combo_data.append({"p":p,"odds":o,"won":(c==race["actual"]),"ev":p*o})
    return pd.DataFrame(combo_data)


print(f"\n{'='*90}")
print(f"温度パラメータ別キャリブレーション (件数=対象3連単買い目)")
print(f"{'='*90}")

bins = [(0,0.005),(0.005,0.02),(0.02,0.05),(0.05,0.10),(0.10,0.20),(0.20,1.0)]

for T in [1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 12.0]:
    df = calibration_analysis(T)
    print(f"\n--- T = {T} ---")
    print(f"{'予測確率帯':>14s}  {'件数':>5s}  {'平均予測%':>9s}  {'実際%':>8s}  {'比率(実/予)':>12s}")
    for lo, hi in bins:
        sub = df[(df["p"]>=lo)&(df["p"]<hi)]
        if len(sub)<10: continue
        pred = sub["p"].mean()*100
        actual = sub["won"].mean()*100
        ratio = (sub["won"].mean()/sub["p"].mean()) if sub["p"].mean()>0 else 0
        flag = " ✓" if 0.7 <= ratio <= 1.3 else ""
        print(f"  {lo*100:5.1f}%-{hi*100:5.1f}%  {len(sub):5d}  {pred:8.2f}%  {actual:7.2f}%  {ratio:11.2f}{flag}")


# === 各温度での「+EV買い目」の的中率と収支 ===
print(f"\n{'='*90}")
print("=== 温度別: PL確率×オッズ で+EV判定した買い目の収支 ===")
print(f"{'='*90}")
print(f"{'T':>5s}  {'EV>1.0買い目':>12s}  {'的中':>4s}  {'率':>5s}  {'投資':>10s}  {'払戻':>10s}  {'収支':>10s}  {'ROI':>6s}")
print("-"*80)

for T in [1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0]:
    df = calibration_analysis(T)
    df_pos = df[df["ev"] > 1.0]
    if len(df_pos)==0: continue
    inv = len(df_pos)*100
    ret = sum(int(o*100) if w else 0 for o,w in zip(df_pos["odds"], df_pos["won"]))
    hits = df_pos["won"].sum()
    roi = ret/inv*100
    print(f"  {T:4.1f}  {len(df_pos):11d}  {hits:4d}  {hits/len(df_pos)*100:4.1f}%  "
          f"{inv:>10,}  {ret:>10,}  {ret-inv:>+10,}  {roi:5.1f}%")

# === 各温度でのEV>1.5, EV>2.0 ===
print(f"\n{'='*90}")
print("=== 温度別: EV閾値別収支 ===")
print(f"{'='*90}")
print(f"{'T':>5s}  {'EV閾値':>7s}  {'件数':>5s}  {'的中':>4s}  {'率':>5s}  {'ROI':>6s}  {'収支':>10s}")
print("-"*70)

for T in [3.0, 5.0, 8.0, 12.0, 20.0]:
    df = calibration_analysis(T)
    for ev_th in [1.0, 1.2, 1.5, 2.0, 3.0]:
        sub = df[df["ev"] >= ev_th]
        if len(sub)<10: continue
        inv = len(sub)*100
        ret = sum(int(o*100) if w else 0 for o,w in zip(sub["odds"], sub["won"]))
        hits = sub["won"].sum()
        roi = ret/inv*100
        print(f"  {T:4.1f}  EV>={ev_th:.1f}  {len(sub):5d}  {hits:4d}  {hits/len(sub)*100:4.1f}%  {roi:5.1f}%  {ret-inv:>+10,}")
