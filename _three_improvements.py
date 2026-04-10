"""3つの改善案を並列検証
1. シミュ閾値緩和
2. 動的買い目数（軸確信度ベース）
3. PL温度スケーリング
"""
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

dates = sorted(RC["date"].dropna().unique())
print("Loading races...", file=sys.stderr)
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


# === Pre-compute per-race signals (one-time) ===
print("Pre-computing per-race signals...", file=sys.stderr)
race_signals = []
rng_global = random.Random(42)

for race in all_races:
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
    if top_ev<MIN_EV:
        race_signals.append(None); continue
    sl=[nn for nn,d in ps.items() if d["ip"]>=5.5 and d["pos"]==1]
    if len(sl)>=2:
        race_signals.append(None); continue

    # Run simulation 500 times once (max we'll need)
    tri_counts = Counter()
    first_counts = Counter()
    for _ in range(500):
        r = simulate_race(race, rng_global, SIM_PARAMS)
        if len(r)>=3:
            tri_counts[f"{r[0]}-{r[1]}-{r[2]}"]+=1
            first_counts[r[0]]+=1

    race_signals.append({
        "ranked": ranked,
        "top_ev": top_ev,
        "tri_counts": tri_counts,
        "first_counts": first_counts,
    })
    if len([s for s in race_signals if s is not None]) % 200 == 0:
        print(f"  ... {len([s for s in race_signals if s is not None])} valid races processed", file=sys.stderr)

valid_races = [(r, s) for r, s in zip(all_races, race_signals) if s is not None]
print(f"Valid races: {len(valid_races)}", file=sys.stderr)


def build_pl_candidates(race, ranked, T=1.0):
    """温度T付きでPL候補生成。axis-X-X all combos with prob, odds."""
    ps=race["players"]; od=race["odds_dict"]
    all_nums=[nn for nn,_ in ranked]; max_e=ranked[0][1]["ev"]
    raw_s={nn:np.exp((ps[nn]["ev"]-max_e)/T) for nn in all_nums}
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
            if c not in od: continue
            o=od[c]
            if o<10: continue
            cands.append({"combo":c,"prob":pl(axis,sn,tn),"odds":o})
    cands.sort(key=lambda x:x["prob"], reverse=True)
    # Axis 1着 prob (signal A)
    axis_prob = raw_s[axis] / sum(raw_s.values())
    return cands, axis, axis_prob


def evaluate(races_signals, top_n_fn, sim_thresh, T=1.0, n_sim=500):
    """評価実行。
    top_n_fn(signal) -> top_n: 動的買い目数を返す関数
    """
    total_inv=total_ret=total_n=total_hits=0
    bet_count_dist=[]
    for race, sig in races_signals:
        if sig is None: continue
        cands, axis, axis_prob = build_pl_candidates(race, sig["ranked"], T)
        if not cands: continue
        # シミュフィルタ (n_simでスケーリング)
        # tri_counts is for 500 sims, scale threshold appropriately
        scale = n_sim / 500.0
        adj_thresh = max(1, int(sim_thresh * scale + 0.5))

        # Determine top_n for this race
        top_n = top_n_fn({"axis_prob": axis_prob,
                          "ranked": sig["ranked"],
                          "first_counts": sig["first_counts"],
                          "n_sim": 500})

        bets=[]
        for c in cands:
            if sig["tri_counts"].get(c["combo"],0)>=adj_thresh:
                bets.append(c["combo"])
            if len(bets)>=top_n: break
        if not bets: continue
        bet_count_dist.append(len(bets))
        inv=len(bets)*100; hit=race["actual"] in bets; ret=race["payout"] if hit else 0
        total_inv+=inv; total_ret+=ret; total_n+=1
        if hit: total_hits+=1
    roi=total_ret/total_inv*100 if total_inv else 0
    avg_bets = np.mean(bet_count_dist) if bet_count_dist else 0
    return {"n":total_n,"hits":total_hits,"invest":total_inv,"ret":total_ret,
            "roi":roi,"profit":total_ret-total_inv,"avg_bets":avg_bets}


# CV splits
all_dates_set=sorted(set(r["date"] for r,_ in valid_races))
mid=len(all_dates_set)//2
train_set = set(all_dates_set[:mid])
test_set = set(all_dates_set[mid:])

train_races = [(r,s) for r,s in valid_races if r["date"] in train_set]
test_races = [(r,s) for r,s in valid_races if r["date"] in test_set]

folds=[[],[],[]]
for i,d in enumerate(all_dates_set):
    for r,s in valid_races:
        if r["date"]==d: folds[i%3].append((r,s))


def full_eval(name, top_n_fn, sim_thresh, T=1.0):
    ra = evaluate(valid_races, top_n_fn, sim_thresh, T)
    rv = evaluate(test_races, top_n_fn, sim_thresh, T)
    fr = [evaluate(folds[fi], top_n_fn, sim_thresh, T) for fi in range(3)]
    cv_avg = np.mean([f["roi"] for f in fr])
    return name, ra, rv, fr, cv_avg


def fixed_top_n(n):
    return lambda sig: n


print("\n" + "="*120)
print("=== ベースライン (現行: T=1.0, シミュ閾値3, 上限10) ===")
print("="*120)
n, ra, rv, fr, cv = full_eval("ベースライン", fixed_top_n(10), 3, 1.0)
print(f"  全体ROI: {ra['roi']:.1f}%  検証ROI: {rv['roi']:.1f}%  CV平均: {cv:.1f}% (F1:{fr[0]['roi']:.0f}% F2:{fr[1]['roi']:.0f}% F3:{fr[2]['roi']:.0f}%)")
print(f"  全体収支: {ra['profit']:+,}  検証収支: {rv['profit']:+,}  平均点: {ra['avg_bets']:.1f}")

# === 1. シミュ閾値の感度 ===
print("\n" + "="*120)
print("=== 改善1: シミュ閾値の緩和/強化 ===")
print("="*120)
print(f"{'設定':>30s}  {'R':>4s} {'avg':>4s} {'全ROI':>7s} {'全収支':>10s} {'検ROI':>7s} {'検収支':>10s} {'F1':>4s} {'F2':>4s} {'F3':>4s} {'CV':>5s}")
print("-"*120)

for thresh in [1, 2, 3, 4, 5]:
    for top_n in [7, 10, 12, 15]:
        n, ra, rv, fr, cv = full_eval(f"閾値{thresh}+{top_n}点",
                                      fixed_top_n(top_n), thresh, 1.0)
        print(f"  シミュ閾値={thresh} 上限{top_n}点  {ra['n']:4d} {ra['avg_bets']:4.1f} "
              f"{ra['roi']:6.1f}% {ra['profit']:>+10,} "
              f"{rv['roi']:6.1f}% {rv['profit']:>+10,} "
              f"{fr[0]['roi']:3.0f}% {fr[1]['roi']:3.0f}% {fr[2]['roi']:3.0f}% {cv:4.1f}%")


# === 2. 動的買い目数 ===
print("\n" + "="*120)
print("=== 改善2: 動的買い目数（軸確信度ベース）===")
print("="*120)

# 確信度指標A: PL確率での軸の1着確率
def make_axis_prob_fn(low_thresh, high_thresh, low_n, mid_n, high_n):
    def fn(sig):
        ap = sig["axis_prob"]
        if ap >= high_thresh: return high_n
        elif ap >= low_thresh: return mid_n
        else: return low_n
    return fn

# 確信度指標C: シミュ軸1着頻度
def make_sim_axis_fn(low_thresh, high_thresh, low_n, mid_n, high_n):
    def fn(sig):
        axis = next((nn for nn,d in sig["ranked"] if d["is_m"]), sig["ranked"][0][0])
        sim_freq = sig["first_counts"][axis] / sig["n_sim"]
        if sim_freq >= high_thresh: return high_n
        elif sim_freq >= low_thresh: return mid_n
        else: return low_n
    return fn

# 確信度指標B: Top1-Top2 EV差
def make_ev_gap_fn(low_thresh, high_thresh, low_n, mid_n, high_n):
    def fn(sig):
        if len(sig["ranked"])<2: return mid_n
        gap = sig["ranked"][0][1]["ev"] - sig["ranked"][1][1]["ev"]
        if gap >= high_thresh: return high_n
        elif gap >= low_thresh: return mid_n
        else: return low_n
    return fn

print(f"{'設定':>40s}  {'avg':>4s} {'全ROI':>7s} {'全収支':>10s} {'検ROI':>7s} {'検収支':>10s} {'F1':>4s} {'F2':>4s} {'F3':>4s} {'CV':>5s}")
print("-"*120)

# 集中型: 高確信度で点数絞る
configs_dynamic = [
    # (name, top_n_fn)
    ("[A:axis_prob]集中 0.3/0.5 → 15/10/5", make_axis_prob_fn(0.3, 0.5, 15, 10, 5)),
    ("[A:axis_prob]集中 0.35/0.55 → 13/10/7", make_axis_prob_fn(0.35, 0.55, 13, 10, 7)),
    ("[A:axis_prob]集中 0.4/0.6 → 12/8/5", make_axis_prob_fn(0.4, 0.6, 12, 8, 5)),
    ("[A:axis_prob]強気 0.3/0.5 → 5/10/15", make_axis_prob_fn(0.3, 0.5, 5, 10, 15)),
    ("[A:axis_prob]強気 0.35/0.55 → 7/10/13", make_axis_prob_fn(0.35, 0.55, 7, 10, 13)),
    ("[C:sim_freq]集中 0.2/0.4 → 15/10/5", make_sim_axis_fn(0.2, 0.4, 15, 10, 5)),
    ("[C:sim_freq]集中 0.25/0.45 → 13/10/7", make_sim_axis_fn(0.25, 0.45, 13, 10, 7)),
    ("[C:sim_freq]強気 0.2/0.4 → 5/10/15", make_sim_axis_fn(0.2, 0.4, 5, 10, 15)),
    ("[B:ev_gap]集中 1.5/3.0 → 15/10/5", make_ev_gap_fn(1.5, 3.0, 15, 10, 5)),
    ("[B:ev_gap]集中 1.0/2.5 → 13/10/7", make_ev_gap_fn(1.0, 2.5, 13, 10, 7)),
    ("[B:ev_gap]強気 1.5/3.0 → 5/10/15", make_ev_gap_fn(1.5, 3.0, 5, 10, 15)),
]

for name, fn in configs_dynamic:
    n, ra, rv, fr, cv = full_eval(name, fn, 3, 1.0)
    print(f"  {name:>38s}  {ra['avg_bets']:4.1f} "
          f"{ra['roi']:6.1f}% {ra['profit']:>+10,} "
          f"{rv['roi']:6.1f}% {rv['profit']:>+10,} "
          f"{fr[0]['roi']:3.0f}% {fr[1]['roi']:3.0f}% {fr[2]['roi']:3.0f}% {cv:4.1f}%")


# === 3. PL温度スケーリング ===
print("\n" + "="*120)
print("=== 改善3: PL温度スケーリング ===")
print("="*120)
print(f"{'温度T':>8s}  {'シミュ閾':>6s}  {'avg':>4s} {'全ROI':>7s} {'全収支':>10s} {'検ROI':>7s} {'検収支':>10s} {'F1':>4s} {'F2':>4s} {'F3':>4s} {'CV':>5s}")
print("-"*100)

for T in [1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 12.0]:
    for thresh in [3]:  # ベースラインと同じ
        n, ra, rv, fr, cv = full_eval(f"T={T}", fixed_top_n(10), thresh, T)
        print(f"  T={T:5.1f}     {thresh}       {ra['avg_bets']:4.1f} "
              f"{ra['roi']:6.1f}% {ra['profit']:>+10,} "
              f"{rv['roi']:6.1f}% {rv['profit']:>+10,} "
              f"{fr[0]['roi']:3.0f}% {fr[1]['roi']:3.0f}% {fr[2]['roi']:3.0f}% {cv:4.1f}%")

# 温度+EV閾値は省略 (確率変わるのでEV閾値の意味も変わる)
