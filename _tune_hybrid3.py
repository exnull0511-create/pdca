"""is_unreliable + バンク直線×戦法相性 の追加検証"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, sys, random
from collections import Counter

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
MIN_EV = 67; MIN_ODDS = 10

# バンク直線距離
BANK_STRAIGHT = {
    "前橋":46.0,"宇都宮":63.3,"豊橋":60.3,"岸和田":56.2,"熊本":56.0,
    "いわき平":62.7,"広島":57.9,"別府":59.9,"松山":58.6,"小倉":56.9,
    "京王閣":51.5,"立川":58.0,"取手":54.8,"伊東":46.6,"久留米":50.7,
    "奈良":38.2,"岐阜":56.0,"小松島":55.5,"防府":42.5,"静岡":56.4,
    "松阪":61.5,"高知":52.0,"松戸":38.2,"平塚":54.2,"西武園":47.6,
    "小田原":36.0,"大垣":56.0,"名古屋":58.8,"川崎":58.0,"大宮":46.7,
    "和歌山":59.9,"玉野":47.9,"武雄":64.4,"四日市":62.4,
}
# バンクのカント(傾斜角)の目安 - 捲りやすさに影響
# 333m: カントきつい(捲り有利), 400m: 標準, 500m: カント緩い(逃げ有利)
BANK_CIRC = {
    "前橋":335,"宇都宮":500,"豊橋":400,"岸和田":400,"熊本":400,
    "いわき平":500,"広島":400,"別府":400,"松山":400,"小倉":400,
    "京王閣":400,"立川":400,"取手":400,"伊東":333,"久留米":400,
    "奈良":333,"岐阜":400,"小松島":400,"防府":333,"静岡":400,
    "松阪":400,"高知":333,"松戸":333,"平塚":400,"西武園":400,
    "小田原":333,"大垣":400,"名古屋":400,"川崎":400,"大宮":335,
    "和歌山":400,"玉野":400,"武雄":400,"四日市":400,
}

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
            players[num]={"num":num,"name":nm,"base":base,"style":style,
                          "ip":ip,"ep":ep,"dp":dp,"bp":bp_v,"nb":nb,
                          "is_m":is_m,"is_u":is_u,"line":lno,"pos":pos,"form_trend":form_trend}
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
        straight_len = BANK_STRAIGHT.get(venue, 54.0)
        circ = BANK_CIRC.get(venue, 400)
        all_races.append({"players":players,"lines":line_info,"actual":actual,
                          "payout":payout,"odds_dict":odds_dict,"venue":venue,
                          "date":str(race_date.date()),"bp_d":bp_d,
                          "straight_len":straight_len,"circ":circ})

print(f"Races: {len(all_races)}", file=sys.stderr)


def simulate_race(race, rng, params):
    players=race["players"]; line_info=race["lines"]; bp_d=race["bp_d"]
    straight_len=race["straight_len"]; circ=race["circ"]
    straight_f = straight_len / 54.0  # 54m基準
    # 333mバンク: カントきつい→捲り有利、500m: 逃げ有利
    makuri_bank_bonus = 1.15 if circ <= 335 else (0.9 if circ >= 500 else 1.0)

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

        # is_unreliable: 不発・失速リスク
        if p["is_u"]:
            # 不発選手はランダムに大失速する可能性
            if rng.random() < params["unreliable_prob"]:
                sc -= params["unreliable_penalty"]
                c4[num] = sc
                continue

        if p["pos"]==1:
            if is_f:
                sc+=p["ip"]*(1.5 if tuppari else 0.8)
                sc-=fl_fat*params["w_fatigue"] if tuppari else 0
                if not tuppari: sc+=p["dp"]*0.5
            elif is_r:
                sc+=p["ip"]*(1.2 if tuppari else 1.8)
                sc-=rl_fat*params["w_fatigue"] if tuppari else 0
            elif is_mid:
                sc+=p["dp"]*params["w_dp_mid"]*bp_d["makuri"]*makuri_bank_bonus
        elif p["pos"]==2:
            if is_r and not tuppari:
                if p["ep"]<params["ep_thresh"] and rng.random()<(params["ep_thresh"]-p["ep"])*params["chigire_rate"]:
                    sc-=params["chigire_penalty"]
                sc+=p["ep"]*1.2
            elif is_f:
                sc+=p["bp"]*bp_d["sashi"]*params["w_bp_front"]+p["ep"]*0.8
            else:
                sc+=p["ep"]*1.0+p["dp"]*0.5
        else:  # 3番手
            sc+=p["ep"]*0.5 - params["pos3_penalty"]*(p["pos"]-2)
        if p["is_m"]: sc+=params["w_monster"]
        c4[num]=sc

    final={}
    for num,p in players.items():
        f=c4.get(num,0)
        # 直線: バンク直線距離が長いほど後方有利
        if p["pos"]>=3:
            f+=p["nb"]*params["w_nb"]*straight_f*params["pos3_nb_straight"]
        else:
            f+=p["nb"]*params["w_nb"]
        # 先頭の残脚
        li=next((l for l in line_info if num in l["members"]),None)
        if li and p["pos"]==1:
            fat = fl_fat if li==front else (rl_fat if li==rear else 0)
            remaining = 1.0 - fat * params["w_fat_straight"]
            f += (remaining - 0.5) * params["w_remaining"]
        f+=rng.gauss(0, params["noise"])
        final[num]=f
    return [n for n,_ in sorted(final.items(),key=lambda x:x[1],reverse=True)]


def run_hybrid_filter(races, n_sim=300, top_n=10, sim_threshold=3, params=None):
    rng=random.Random(42)
    total_inv=total_ret=total_n=total_hits=0
    for race in races:
        ps=race["players"]; bp_d=race["bp_d"]; od=race["odds_dict"]
        for n,p in ps.items():
            pos_b=0.5 if p["pos"]==1 else -0.3*(p["pos"]-1)
            bsf=(bp_d["sashi"]-1.0)*p["ep"]+(bp_d["makuri"]-1.0)*p["ip"]
            p["ev"]=(p["base"]*0.4+p["ip"]*1.5+p["ep"]*1.2
                     +p["dp"]*bp_d["makuri"]+p["bp"]*bp_d["sashi"]
                     +p["nb"]*2.0+pos_b+(3.0 if p["is_m"] else 0)-(2.0 if p["is_u"] else 0)
                     +p["form_trend"]*1.0+bsf*2.0)
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
        pl_cands=[]
        for sn in others:
            for tn in others:
                if sn==tn: continue
                c=f"{axis}-{sn}-{tn}"
                if c not in od or od[c]<MIN_ODDS: continue
                pl_cands.append((pl(axis,sn,tn),c))
        pl_cands.sort(key=lambda x:x[0],reverse=True)
        tri_counts=Counter()
        for _ in range(n_sim):
            r=simulate_race(race,rng,params)
            if len(r)>=3: tri_counts[f"{r[0]}-{r[1]}-{r[2]}"]+=1
        bets=[]
        for _,c in pl_cands:
            if tri_counts.get(c,0)>=sim_threshold:
                bets.append(c)
            if len(bets)>=top_n: break
        if not bets: continue
        inv=len(bets)*100; hit=race["actual"] in bets; ret=race["payout"] if hit else 0
        total_inv+=inv; total_ret+=ret; total_n+=1
        if hit: total_hits+=1
    roi=total_ret/total_inv*100 if total_inv else 0
    return {"n":total_n,"hits":total_hits,"invest":total_inv,"ret":total_ret,
            "roi":roi,"profit":total_ret-total_inv}


# ── Params ───────────────────────────────────────────────────────────────────
BASE = {
    "fat_front":0.6,"fat_rear":0.5,"w_base":0.3,"w_fatigue":2.0,
    "w_dp_mid":1.5,"ep_thresh":4.5,"chigire_rate":0.3,"chigire_penalty":5.0,
    "w_bp_front":0.8,"w_monster":2.0,"w_nb":1.5,"w_fat_straight":1.0,
    "noise":2.0,"pos3_penalty":1.0,"pos3_nb_straight":1.0,"w_remaining":2.0,
    "unreliable_prob":0.0,"unreliable_penalty":0.0,  # 現行: 無効
}

all_dates=sorted(set(r["date"] for r in all_races))
mid=len(all_dates)//2
train=[r for r in all_races if r["date"]<=all_dates[mid-1]]
test=[r for r in all_races if r["date"]>all_dates[mid-1]]

folds=[[],[],[]]
for i,d in enumerate(sorted(set(r["date"] for r in all_races))):
    for r in all_races:
        if r["date"]==d: folds[i%3].append(r)

def eval_config(name, changes):
    p={**BASE,**changes}
    ra=run_hybrid_filter(all_races,params=p)
    rv=run_hybrid_filter(test,params=p)
    fold_rois=[]
    for fi in range(3):
        rf=run_hybrid_filter(folds[fi],params=p)
        fold_rois.append(rf["roi"])
    avg_cv=np.mean(fold_rois)
    return name, ra, rv, fold_rois, avg_cv

print(f"\n{'='*100}")
print(f"{'設定':>35s}  {'全ROI':>7s} {'全収支':>10s} {'検ROI':>7s} {'検収支':>10s} {'F1':>5s} {'F2':>5s} {'F3':>5s} {'CV平均':>6s}")
print(f"{'='*100}")

configs = [
    ("ベースライン(unreliable無効)", {}),
    # is_unreliable
    ("unreliable 20%/-3.0", {"unreliable_prob":0.2,"unreliable_penalty":3.0}),
    ("unreliable 30%/-3.0", {"unreliable_prob":0.3,"unreliable_penalty":3.0}),
    ("unreliable 30%/-5.0", {"unreliable_prob":0.3,"unreliable_penalty":5.0}),
    ("unreliable 40%/-4.0", {"unreliable_prob":0.4,"unreliable_penalty":4.0}),
    # バンク周長(捲り補正)は既に入ってるので直線距離効果をテスト
    ("3番手直線ブースト1.3", {"pos3_nb_straight":1.3}),
    ("3番手直線ブースト1.5", {"pos3_nb_straight":1.5}),
    # 組み合わせ
    ("unrel30/-3 + 直線1.3", {"unreliable_prob":0.3,"unreliable_penalty":3.0,"pos3_nb_straight":1.3}),
    ("unrel30/-3 + 残脚2.5", {"unreliable_prob":0.3,"unreliable_penalty":3.0,"w_remaining":2.5}),
    ("unrel30/-3 + 残脚2.5 + 直線1.3", {"unreliable_prob":0.3,"unreliable_penalty":3.0,"w_remaining":2.5,"pos3_nb_straight":1.3}),
    ("unrel40/-4 + 残脚2.5 + 直線1.3", {"unreliable_prob":0.4,"unreliable_penalty":4.0,"w_remaining":2.5,"pos3_nb_straight":1.3}),
]

for name, changes in configs:
    n, ra, rv, fr, avg = eval_config(name, changes)
    print(f"  {n:>33s}  {ra['roi']:6.1f}% {ra['profit']:>+10,} "
          f"{rv['roi']:6.1f}% {rv['profit']:>+10,} "
          f"{fr[0]:4.0f}% {fr[1]:4.0f}% {fr[2]:4.0f}% {avg:5.1f}%")
