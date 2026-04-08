"""アブレーション: 新特徴量を1つずつ抜いて効果を測定"""
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
MIN_ODDS = 10; MIN_EV = 67

dates = sorted(RC["date"].dropna().unique())
print("Loading...", file=sys.stderr)
all_races = []
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
        line_map={}; num_to_line={}
        for _,row in race_info.iterrows():
            try: num=int(row["車番"]); lno=int(row.get("line_no",0) or 0)
            except: continue
            bs=str(row.get("line_bibs",str(num)))
            if lno not in line_map:
                try: line_map[lno]=[int(b) for b in bs.split("-") if b.isdigit()]
                except: line_map[lno]=[num]
            num_to_line[num]=lno

        players={}
        for _,row in race_info.iterrows():
            try:
                num=int(row["車番"]); nm=rb.norm(str(row.get("選手名",""))); base=float(row.get("競走得点",80) or 80)
            except: continue
            hist=past_slim[past_slim["選手名_norm"]==nm] if not past_slim.empty else pd.DataFrame()
            use_slim=not hist.empty
            if hist.empty: hist=past_all[past_all["選手名_norm"]==nm] if not past_all.empty else pd.DataFrame()
            ip=ep=4.0; dp=bp_v=3.0; nb=sp=2.0; is_m=is_u=False; form_trend=0.0
            if not hist.empty:
                RW=3.0; sd=sorted(hist["開催日"].dropna().unique(),reverse=True); rd=set(sd[:2])
                def wm(s):
                    v=pd.to_numeric(s,errors="coerce"); w=np.where(hist["開催日"].isin(rd),RW,1.0); mk=v.notna()
                    return float((v[mk]*w[mk]).sum()/w[mk].sum()) if mk.any() else None
                ip=wm(hist["IP"]) or 4.0; ep=wm(hist["EP"]) or 4.0; dp=wm(hist["DP"]) or 3.0; bp_v=wm(hist["BP"]) or 3.0
                if use_slim and "直線の伸び" in hist.columns: nb=wm(hist["直線の伸び"].apply(rb.nobi_score)) or 2.0
                elif nobi_col in hist.columns: nb=wm(hist[nobi_col].apply(rb.nobi_score)) or 2.0
                if "戦法" in hist.columns: sp=wm(hist["戦法"].apply(rb.senpo_lead)) or 2.0
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
            lno=num_to_line.get(num,0); lbs=line_map.get(lno,[]); pos=lbs.index(num)+1 if num in lbs else 1
            pos_b=0.5 if pos==1 else -0.3*(pos-1)
            players[num]={"base":base,"ip":ip,"ep":ep,"dp":dp,"bp_v":bp_v,"nb":nb,"sp":sp,
                          "pos_b":pos_b,"is_m":is_m,"is_u":is_u,"form_trend":form_trend,
                          "pos_in_line":pos,"line":num_to_line.get(num,0)}
        if len(players)<3: continue
        # line features
        lg=defaultdict(list)
        for n,p in players.items(): lg[p["line"]].append(p)
        for n,p in players.items():
            leader=[pp for pp in lg[p["line"]] if pp["pos_in_line"]==1]
            p["bantsuke_edge"]=(leader[0]["ip"]-4.0) if p["pos_in_line"]==2 and leader else 0.0
            p["bank_style_fit"]=(bp_d["sashi"]-1.0)*p["ep"]+(bp_d["makuri"]-1.0)*p["ip"]
        all_races.append({"players":players,"actual":actual,"payout":payout,
                          "odds_dict":odds_dict,"venue":venue,"date":str(race_date.date()),"bp":bp_d})

print(f"Races: {len(all_races)}", file=sys.stderr)

def run(races, form_w, bantsuke_w, bankstyle_w):
    total_inv=total_ret=total_n=total_hits=0
    for race in races:
        bp=race["bp"]; ps=race["players"]
        # score
        for n,p in ps.items():
            p["ev"]=(p["base"]*0.4+p["ip"]*1.5+p["ep"]*1.2
                     +p["dp"]*bp["makuri"]+p["bp_v"]*bp["sashi"]
                     +p["nb"]*2.0+p["sp"]*0.5+p["pos_b"]
                     +(3.0 if p["is_m"] else 0)-(2.0 if p["is_u"] else 0)
                     +p["form_trend"]*form_w
                     +p["bantsuke_edge"]*bantsuke_w
                     +p["bank_style_fit"]*bankstyle_w)
        ranked=sorted(ps.items(),key=lambda x:x[1]["ev"],reverse=True)
        top_ev=ranked[0][1]["ev"]
        if top_ev<MIN_EV: continue
        sl=[nn for nn,d in ps.items() if d["ip"]>=5.5 and d["pos_in_line"]==1]
        if len(sl)>=2: continue  # skip chaos
        all_nums=[nn for nn,_ in ranked]; max_e=ranked[0][1]["ev"]
        raw_s={nn:np.exp(ps[nn]["ev"]-max_e) for nn in all_nums}
        axis=next((nn for nn,d in ranked if d["is_m"]),ranked[0][0])
        others=[nn for nn in all_nums if nn!=axis]; od=race["odds_dict"]
        def pl(f,s,t):
            d1=sum(raw_s[nn] for nn in all_nums); d2=sum(raw_s[nn] for nn in all_nums if nn!=f)
            d3=sum(raw_s[nn] for nn in all_nums if nn not in(f,s))
            return 0.0 if 0 in(d1,d2,d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)
        cands=[]
        for sn in others:
            for tn in others:
                if sn==tn: continue
                c=f"{axis}-{sn}-{tn}"
                if c not in od: continue
                o=od[c]
                if o<MIN_ODDS: continue
                cands.append((pl(axis,sn,tn),c,o))
        sel=sorted(cands,key=lambda x:x[0],reverse=True)[:7]
        bets=[c for _,c,_ in sel]
        if not bets: continue
        inv=len(bets)*100; hit=race["actual"] in bets; ret=race["payout"] if hit else 0
        total_inv+=inv; total_ret+=ret; total_n+=1
        if hit: total_hits+=1
    roi=total_ret/total_inv*100 if total_inv else 0
    return {"n":total_n,"hits":total_hits,"inv":total_inv,"ret":total_ret,
            "roi":roi,"profit":total_ret-total_inv}

# === Ablation ===
all_dates=sorted(set(r["date"] for r in all_races))
mid=len(all_dates)//2
train=[r for r in all_races if r["date"]<=all_dates[mid-1]]
test=[r for r in all_races if r["date"]>all_dates[mid-1]]

configs=[
    ("全部なし(ベースライン)",     0, 0, 0),
    ("調子のみ",                 1, 0, 0),
    ("番手有利のみ",              0, 2, 0),
    ("バンク×戦法のみ",           0, 0, 2),
    ("調子+番手有利",             1, 2, 0),
    ("調子+バンク×戦法",          1, 0, 2),
    ("番手有利+バンク×戦法",      0, 2, 2),
    ("★全部入り(現行)",          1, 2, 2),
    ("調子なし",                 0, 2, 2),
    ("番手有利なし",              1, 0, 2),
    ("バンク×戦法なし",           1, 2, 0),
]

print(f"\n{'='*100}")
print(f"{'設定':>25s}  {'全体R':>5s}  {'全体的中':>7s}  {'全体ROI':>8s}  {'全体収支':>10s}  "
      f"{'検証ROI':>8s}  {'検証収支':>10s}")
print(f"{'='*100}")
for name,fw,bw,bsw in configs:
    ra=run(all_races,fw,bw,bsw)
    rv=run(test,fw,bw,bsw)
    mark=" ◀" if name.startswith("★") else ""
    print(f"  {name:>23s}  {ra['n']:5d}  {ra['hits']:3d}({ra['hits']/ra['n']*100:.1f}%)  "
          f"{ra['roi']:7.1f}%  {ra['profit']:>+10,}  {rv['roi']:7.1f}%  {rv['profit']:>+10,}{mark}")
