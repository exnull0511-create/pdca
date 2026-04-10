"""新特徴量(伸びS強化, 鬼脚+伸びS, 不発削除, 過去戦法)の効果検証"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, sys, random
from collections import Counter, defaultdict

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

def classify_senpo(s):
    s = str(s).strip()
    if s in ('追走','追い込み','流れ込み','マーク'): return '追走'
    if s in ('逃げ切り','逃げ粘り','逃げ','先行逃げ切り','先行逃げ粘り'): return '逃げ'
    if s in ('先行','抑え先行','カマシ先行','突っ張り先行','先行争い敗'): return '先行'
    if s in ('捲り','一発捲り','ロング捲り','カマシ捲り','番手捲り'): return '捲り'
    if s in ('差し','番手差し','捲り差し'): return '差し'
    if s in ('捲り不発','不発','先行不発','差し不発','失速','捲り追い込み'): return '不発系'
    return 'その他'

def nobi_grade(v):
    s = str(v).strip().upper()
    if s.startswith("S"): return "S"
    if s.startswith("A"): return "A"
    if s.startswith("B"): return "B"
    if s.startswith("C"): return "C"
    return "?"

# Pre-compute senpo and nobi columns on db
db_slim["戦法大分類"] = db_slim["戦法"].apply(classify_senpo) if "戦法" in db_slim.columns else "?"
db_slim["nobi_grade"] = db_slim["直線の伸び"].apply(nobi_grade) if "直線の伸び" in db_slim.columns else "?"
if "戦法" in db_all.columns:
    db_all["戦法大分類"] = db_all["戦法"].apply(classify_senpo)
else:
    db_all["戦法大分類"] = "?"
if nobi_col in db_all.columns:
    db_all["nobi_grade"] = db_all[nobi_col].apply(nobi_grade)
else:
    db_all["nobi_grade"] = "?"

dates = sorted(RC["date"].dropna().unique())

print("Loading races with extended features...", file=sys.stderr)
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
        lines={}; num_to_line={}
        for _,row in race_info.iterrows():
            try: num=int(row["車番"]); lno=int(row.get("line_no",0) or 0)
            except: continue
            bs=str(row.get("line_bibs",str(num)))
            if lno not in lines:
                try: lines[lno]=[int(b) for b in bs.split("-") if b.isdigit()]
                except: lines[lno]=[num]
            num_to_line[num]=lno
        players={}
        for _,row in race_info.iterrows():
            try:
                num=int(row["車番"]); nm=rb.norm(str(row.get("選手名","")))
                base=float(row.get("競走得点",80) or 80); style=str(row.get("脚質",""))
            except: continue
            hist=past_slim[past_slim["選手名_norm"]==nm] if not past_slim.empty else pd.DataFrame()
            use_slim=not hist.empty
            if hist.empty: hist=past_all[past_all["選手名_norm"]==nm] if not past_all.empty else pd.DataFrame()
            ip=ep=4.0; dp=bp_v=3.0; nb=2.0; is_m=is_u=False; form_trend=0.0
            past_senpo_main = "?"; past_nobi_main = "?"
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
                # 過去最頻戦法
                if "戦法大分類" in hist.columns:
                    sm = hist["戦法大分類"].value_counts()
                    if len(sm) > 0: past_senpo_main = sm.index[0]
                # 過去最頻 直線の伸び
                if "nobi_grade" in hist.columns:
                    nm_v = hist["nobi_grade"].value_counts()
                    if len(nm_v) > 0: past_nobi_main = nm_v.index[0]
            lno=num_to_line.get(num,0); lbs=lines.get(lno,[num])
            pos=lbs.index(num)+1 if num in lbs else 1
            players[num]={"num":num,"name":nm,"base":base,"style":style,
                          "ip":ip,"ep":ep,"dp":dp,"bp":bp_v,"nb":nb,
                          "is_m":is_m,"is_u":is_u,"line":lno,"pos":pos,"form_trend":form_trend,
                          "past_senpo": past_senpo_main, "past_nobi": past_nobi_main}
        if len(players)<3: continue
        line_info=[]
        for lno,members in sorted(lines.items()):
            ms=[m for m in members if m in players]
            if not ms: continue
            leader=players[ms[0]]
            line_info.append({"lno":lno,"members":ms,"size":len(ms),
                              "leader":ms[0],"leader_ip":leader["ip"],
                              "leader_dp":leader["dp"],"leader_style":leader["style"]})
        if len(line_info)<2: continue
        all_races.append({"players":players,"lines":line_info,"actual":actual,
                          "payout":payout,"odds_dict":odds_dict,"venue":venue,
                          "date":str(race_date.date()),"bp_d":bp_d})

print(f"Races: {len(all_races)}", file=sys.stderr)

SIM_PARAMS = {
    "fat_front":0.6,"fat_rear":0.5,"w_base":0.3,"w_fatigue":2.0,
    "w_dp_mid":1.5,"ep_thresh":4.5,"chigire_rate":0.3,"chigire_penalty":5.0,
    "w_bp_front":0.8,"w_monster":2.0,"w_nb":1.5,"w_fat_straight":1.0,"noise":2.0,
}

def simulate_race(race, rng, params):
    players=race["players"]; line_info=race["lines"]; bp_d=race["bp_d"]
    front=line_info[0]; rear=line_info[-1]
    ip_diff=front["leader_ip"]-rear["leader_ip"]
    size_adv=front["size"]-rear["size"]
    style_b=1.0 if front["leader_style"]=="逃" else 0.0
    tup_score=ip_diff*0.3+size_adv*0.2+style_b*0.3
    tuppari=rng.random()<1.0/(1.0+np.exp(-tup_score))
    if tuppari:
        intensity=max(0,3.0-abs(ip_diff))
        fl_fat=intensity*params["fat_front"]; rl_fat=intensity*params["fat_rear"]
    else:
        fl_fat=0.1; rl_fat=0.2
    c4={}
    for num,p in players.items():
        sc=p["base"]*params["w_base"]
        li=next((l for l in line_info if num in l["members"]),None)
        if not li: c4[num]=sc; continue
        is_f=(li==front); is_r=(li==rear); is_mid=not is_f and not is_r
        if p["pos"]==1:
            if is_f:
                sc+=p["ip"]*(1.5 if tuppari else 0.8)
                sc-=fl_fat*params["w_fatigue"] if tuppari else 0
                if not tuppari: sc+=p["dp"]*0.5
            elif is_r:
                sc+=p["ip"]*(1.2 if tuppari else 1.8)
                sc-=rl_fat*params["w_fatigue"] if tuppari else 0
            elif is_mid:
                sc+=p["dp"]*params["w_dp_mid"]*bp_d["makuri"]
        elif p["pos"]==2:
            if is_r and not tuppari:
                if p["ep"]<params["ep_thresh"] and rng.random()<(params["ep_thresh"]-p["ep"])*params["chigire_rate"]:
                    sc-=params["chigire_penalty"]
                sc+=p["ep"]*1.2
            elif is_f:
                sc+=p["bp"]*bp_d["sashi"]*params["w_bp_front"]+p["ep"]*0.8
            else:
                sc+=p["ep"]*1.0+p["dp"]*0.5
        else:
            sc+=p["ep"]*0.5
        if p["is_m"]: sc+=params["w_monster"]
        c4[num]=sc
    final={}
    for num,p in players.items():
        f=c4.get(num,0)+p["nb"]*params["w_nb"]
        li=next((l for l in line_info if num in l["members"]),None)
        if li and p["pos"]==1:
            if li==front: f-=fl_fat*params["w_fat_straight"]
            elif li==rear: f-=rl_fat*params["w_fat_straight"]
        f+=rng.gauss(0,params["noise"])
        final[num]=f
    return [n for n,_ in sorted(final.items(),key=lambda x:x[1],reverse=True)]


def run_strategy(races, ev_fn, sim_thresh=5, top_n=10, n_sim=500):
    rng=random.Random(42)
    total_inv=total_ret=total_n=total_hits=0
    for race in races:
        ps=race["players"]; bp_d=race["bp_d"]; od=race["odds_dict"]
        for n,p in ps.items():
            p["ev"] = ev_fn(p, bp_d)
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
        cands=[]
        for sn in others:
            for tn in others:
                if sn==tn: continue
                c=f"{axis}-{sn}-{tn}"
                if c not in od or od[c]<10: continue
                cands.append((pl(axis,sn,tn),c))
        cands.sort(key=lambda x:x[0], reverse=True)
        tri_counts=Counter()
        for _ in range(n_sim):
            r=simulate_race(race,rng,SIM_PARAMS)
            if len(r)>=3: tri_counts[f"{r[0]}-{r[1]}-{r[2]}"]+=1
        bets=[]
        for _,c in cands:
            if tri_counts.get(c,0)>=sim_thresh:
                bets.append(c)
            if len(bets)>=top_n: break
        if not bets: continue
        inv=len(bets)*100; hit=race["actual"] in bets; ret=race["payout"] if hit else 0
        total_inv+=inv; total_ret+=ret; total_n+=1
        if hit: total_hits+=1
    roi=total_ret/total_inv*100 if total_inv else 0
    return {"n":total_n,"hits":total_hits,"invest":total_inv,"ret":total_ret,
            "roi":roi,"profit":total_ret-total_inv}


# === EV scoring functions ===

def ev_baseline(p, bp_d):
    pos_b = 0.5 if p["pos"]==1 else -0.3*(p["pos"]-1)
    bsf = (bp_d["sashi"]-1.0)*p["ep"] + (bp_d["makuri"]-1.0)*p["ip"]
    return (p["base"]*0.4 + p["ip"]*1.5 + p["ep"]*1.2
            + p["dp"]*bp_d["makuri"] + p["bp"]*bp_d["sashi"]
            + p["nb"]*2.0 + pos_b
            + (3.0 if p["is_m"] else 0)
            - (2.0 if p["is_u"] else 0)
            + p["form_trend"]*1.0 + bsf*2.0)

def ev_no_unreliable(p, bp_d):
    """C: 不発ペナルティ削除"""
    pos_b = 0.5 if p["pos"]==1 else -0.3*(p["pos"]-1)
    bsf = (bp_d["sashi"]-1.0)*p["ep"] + (bp_d["makuri"]-1.0)*p["ip"]
    return (p["base"]*0.4 + p["ip"]*1.5 + p["ep"]*1.2
            + p["dp"]*bp_d["makuri"] + p["bp"]*bp_d["sashi"]
            + p["nb"]*2.0 + pos_b
            + (3.0 if p["is_m"] else 0)
            + p["form_trend"]*1.0 + bsf*2.0)

def ev_half_unreliable(p, bp_d):
    """C': 不発ペナルティ -2.0 → -0.5"""
    pos_b = 0.5 if p["pos"]==1 else -0.3*(p["pos"]-1)
    bsf = (bp_d["sashi"]-1.0)*p["ep"] + (bp_d["makuri"]-1.0)*p["ip"]
    return (p["base"]*0.4 + p["ip"]*1.5 + p["ep"]*1.2
            + p["dp"]*bp_d["makuri"] + p["bp"]*bp_d["sashi"]
            + p["nb"]*2.0 + pos_b
            + (3.0 if p["is_m"] else 0)
            - (0.5 if p["is_u"] else 0)
            + p["form_trend"]*1.0 + bsf*2.0)

def ev_nobi_s_bonus(p, bp_d):
    """A: 直線伸びS追加ボーナス +3.0"""
    pos_b = 0.5 if p["pos"]==1 else -0.3*(p["pos"]-1)
    bsf = (bp_d["sashi"]-1.0)*p["ep"] + (bp_d["makuri"]-1.0)*p["ip"]
    nobi_s_bonus = 3.0 if p["past_nobi"] == "S" else 0
    return (p["base"]*0.4 + p["ip"]*1.5 + p["ep"]*1.2
            + p["dp"]*bp_d["makuri"] + p["bp"]*bp_d["sashi"]
            + p["nb"]*2.0 + pos_b
            + (3.0 if p["is_m"] else 0)
            - (2.0 if p["is_u"] else 0)
            + p["form_trend"]*1.0 + bsf*2.0
            + nobi_s_bonus)

def ev_monster_nobi_s(p, bp_d):
    """B: 鬼脚+伸びSコンボボーナス +2.0"""
    pos_b = 0.5 if p["pos"]==1 else -0.3*(p["pos"]-1)
    bsf = (bp_d["sashi"]-1.0)*p["ep"] + (bp_d["makuri"]-1.0)*p["ip"]
    combo = 2.0 if p["is_m"] and p["past_nobi"] == "S" else 0
    return (p["base"]*0.4 + p["ip"]*1.5 + p["ep"]*1.2
            + p["dp"]*bp_d["makuri"] + p["bp"]*bp_d["sashi"]
            + p["nb"]*2.0 + pos_b
            + (3.0 if p["is_m"] else 0)
            - (2.0 if p["is_u"] else 0)
            + p["form_trend"]*1.0 + bsf*2.0
            + combo)

def ev_past_senpo(p, bp_d):
    """D: 過去最頻=捲り or 先行 ボーナス +1.5"""
    pos_b = 0.5 if p["pos"]==1 else -0.3*(p["pos"]-1)
    bsf = (bp_d["sashi"]-1.0)*p["ep"] + (bp_d["makuri"]-1.0)*p["ip"]
    senpo_bonus = 1.5 if p["past_senpo"] in ["捲り","先行"] else 0
    return (p["base"]*0.4 + p["ip"]*1.5 + p["ep"]*1.2
            + p["dp"]*bp_d["makuri"] + p["bp"]*bp_d["sashi"]
            + p["nb"]*2.0 + pos_b
            + (3.0 if p["is_m"] else 0)
            - (2.0 if p["is_u"] else 0)
            + p["form_trend"]*1.0 + bsf*2.0
            + senpo_bonus)

def ev_all_combined(p, bp_d):
    """全部入り: A+B+C+D"""
    pos_b = 0.5 if p["pos"]==1 else -0.3*(p["pos"]-1)
    bsf = (bp_d["sashi"]-1.0)*p["ep"] + (bp_d["makuri"]-1.0)*p["ip"]
    nobi_s_bonus = 3.0 if p["past_nobi"] == "S" else 0
    combo = 2.0 if p["is_m"] and p["past_nobi"] == "S" else 0
    senpo_bonus = 1.5 if p["past_senpo"] in ["捲り","先行"] else 0
    return (p["base"]*0.4 + p["ip"]*1.5 + p["ep"]*1.2
            + p["dp"]*bp_d["makuri"] + p["bp"]*bp_d["sashi"]
            + p["nb"]*2.0 + pos_b
            + (3.0 if p["is_m"] else 0)
            + p["form_trend"]*1.0 + bsf*2.0
            + nobi_s_bonus + combo + senpo_bonus)

def ev_a_plus_c(p, bp_d):
    """A + C: 伸びS強化 + 不発削除"""
    pos_b = 0.5 if p["pos"]==1 else -0.3*(p["pos"]-1)
    bsf = (bp_d["sashi"]-1.0)*p["ep"] + (bp_d["makuri"]-1.0)*p["ip"]
    nobi_s_bonus = 3.0 if p["past_nobi"] == "S" else 0
    return (p["base"]*0.4 + p["ip"]*1.5 + p["ep"]*1.2
            + p["dp"]*bp_d["makuri"] + p["bp"]*bp_d["sashi"]
            + p["nb"]*2.0 + pos_b
            + (3.0 if p["is_m"] else 0)
            + p["form_trend"]*1.0 + bsf*2.0
            + nobi_s_bonus)

def ev_a_plus_b(p, bp_d):
    """A + B: 伸びS + 鬼脚×伸びS"""
    pos_b = 0.5 if p["pos"]==1 else -0.3*(p["pos"]-1)
    bsf = (bp_d["sashi"]-1.0)*p["ep"] + (bp_d["makuri"]-1.0)*p["ip"]
    nobi_s_bonus = 3.0 if p["past_nobi"] == "S" else 0
    combo = 2.0 if p["is_m"] and p["past_nobi"] == "S" else 0
    return (p["base"]*0.4 + p["ip"]*1.5 + p["ep"]*1.2
            + p["dp"]*bp_d["makuri"] + p["bp"]*bp_d["sashi"]
            + p["nb"]*2.0 + pos_b
            + (3.0 if p["is_m"] else 0)
            - (2.0 if p["is_u"] else 0)
            + p["form_trend"]*1.0 + bsf*2.0
            + nobi_s_bonus + combo)

def ev_abc_no_d(p, bp_d):
    """A+B+C (Dなし): 伸びS+鬼脚×伸びS+不発削除"""
    pos_b = 0.5 if p["pos"]==1 else -0.3*(p["pos"]-1)
    bsf = (bp_d["sashi"]-1.0)*p["ep"] + (bp_d["makuri"]-1.0)*p["ip"]
    nobi_s_bonus = 3.0 if p["past_nobi"] == "S" else 0
    combo = 2.0 if p["is_m"] and p["past_nobi"] == "S" else 0
    return (p["base"]*0.4 + p["ip"]*1.5 + p["ep"]*1.2
            + p["dp"]*bp_d["makuri"] + p["bp"]*bp_d["sashi"]
            + p["nb"]*2.0 + pos_b
            + (3.0 if p["is_m"] else 0)
            + p["form_trend"]*1.0 + bsf*2.0
            + nobi_s_bonus + combo)

def ev_abc_half_d(p, bp_d):
    """A+B+C' (不発半減版)"""
    pos_b = 0.5 if p["pos"]==1 else -0.3*(p["pos"]-1)
    bsf = (bp_d["sashi"]-1.0)*p["ep"] + (bp_d["makuri"]-1.0)*p["ip"]
    nobi_s_bonus = 3.0 if p["past_nobi"] == "S" else 0
    combo = 2.0 if p["is_m"] and p["past_nobi"] == "S" else 0
    return (p["base"]*0.4 + p["ip"]*1.5 + p["ep"]*1.2
            + p["dp"]*bp_d["makuri"] + p["bp"]*bp_d["sashi"]
            + p["nb"]*2.0 + pos_b
            + (3.0 if p["is_m"] else 0)
            - (0.5 if p["is_u"] else 0)
            + p["form_trend"]*1.0 + bsf*2.0
            + nobi_s_bonus + combo)

def ev_b_plus_c(p, bp_d):
    """B+C: 鬼脚×伸びS+不発削除 (Aなし)"""
    pos_b = 0.5 if p["pos"]==1 else -0.3*(p["pos"]-1)
    bsf = (bp_d["sashi"]-1.0)*p["ep"] + (bp_d["makuri"]-1.0)*p["ip"]
    combo = 2.0 if p["is_m"] and p["past_nobi"] == "S" else 0
    return (p["base"]*0.4 + p["ip"]*1.5 + p["ep"]*1.2
            + p["dp"]*bp_d["makuri"] + p["bp"]*bp_d["sashi"]
            + p["nb"]*2.0 + pos_b
            + (3.0 if p["is_m"] else 0)
            + p["form_trend"]*1.0 + bsf*2.0
            + combo)


# CV
all_dates=sorted(set(r["date"] for r in all_races))
mid=len(all_dates)//2
test=[r for r in all_races if r["date"]>all_dates[mid-1]]
folds=[[],[],[]]
for i,d in enumerate(all_dates):
    for r in all_races:
        if r["date"]==d: folds[i%3].append(r)


def cv_eval(name, ev_fn):
    ra = run_strategy(all_races, ev_fn)
    rv = run_strategy(test, ev_fn)
    fr = [run_strategy(folds[fi], ev_fn) for fi in range(3)]
    cv = np.mean([f["roi"] for f in fr])
    return name, ra, rv, fr, cv


print(f"\n{'='*120}")
print(f"{'設定':>30s}  {'対象R':>4s}  {'avg':>4s}  {'的中':>4s}  {'率':>5s}  "
      f"{'全ROI':>7s}  {'全収支':>10s}  {'検ROI':>7s}  {'検収支':>10s}  "
      f"{'F1':>5s} {'F2':>5s} {'F3':>5s}  {'CV':>5s}")
print(f"{'='*120}")

configs = [
    ("ベースライン", ev_baseline),
    ("C: 不発削除", ev_no_unreliable),
    ("C': 不発-2→-0.5", ev_half_unreliable),
    ("A+C", ev_a_plus_c),
    ("A+B+C+D全部入り", ev_all_combined),
    ("A+B+C (Dなし)", ev_abc_no_d),
    ("A+B+C' (不発半減)", ev_abc_half_d),
    ("B+C (Aなし)", ev_b_plus_c),
]

for name, fn in configs:
    n, ra, rv, fr, cv = cv_eval(name, fn)
    if ra["n"]==0:
        print(f"  {name:>28s}  対象0件")
        continue
    avg_b = ra["invest"]/ra["n"]/100
    hr = ra["hits"]/ra["n"]*100
    print(f"  {name:>28s}  {ra['n']:4d}  {avg_b:4.1f}  {ra['hits']:4d}  {hr:4.1f}%  "
          f"{ra['roi']:6.1f}%  {ra['profit']:>+10,}  "
          f"{rv['roi']:6.1f}%  {rv['profit']:>+10,}  "
          f"{fr[0]['roi']:4.0f}% {fr[1]['roi']:4.0f}% {fr[2]['roi']:4.0f}%  {cv:5.1f}%")
