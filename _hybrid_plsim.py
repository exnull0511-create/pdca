"""PL + 展開シミュレーション ハイブリッド
PLスコアで軸を決め、シミュ確率で買い目を補正する
"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, sys, random
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
MIN_EV = 67; MIN_ODDS = 10; N_SIM = 300

dates = sorted(RC["date"].dropna().unique())

# ── Data collection (same as _race_sim.py) ───────────────────────────────────
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
        lines = {}; num_to_line = {}
        for _, row in race_info.iterrows():
            try: num=int(row["車番"]); lno=int(row.get("line_no",0) or 0)
            except: continue
            bs=str(row.get("line_bibs",str(num)))
            if lno not in lines:
                try: lines[lno]=[int(b) for b in bs.split("-") if b.isdigit()]
                except: lines[lno]=[num]
            num_to_line[num]=lno
        players = {}
        for _, row in race_info.iterrows():
            try:
                num=int(row["車番"]); nm=rb.norm(str(row.get("選手名","")))
                base=float(row.get("競走得点",80) or 80); style=str(row.get("脚質",""))
            except: continue
            hist=past_slim[past_slim["選手名_norm"]==nm] if not past_slim.empty else pd.DataFrame()
            use_slim=not hist.empty
            if hist.empty: hist=past_all[past_all["選手名_norm"]==nm] if not past_all.empty else pd.DataFrame()
            ip=ep=4.0; dp=bp_v=3.0; nb=2.0; is_m=False; form_trend=0.0
            if not hist.empty:
                RW=3.0; sd=sorted(hist["開催日"].dropna().unique(),reverse=True); rd=set(sd[:2])
                def wm(s):
                    v=pd.to_numeric(s,errors="coerce"); w=np.where(hist["開催日"].isin(rd),RW,1.0); mk=v.notna()
                    return float((v[mk]*w[mk]).sum()/w[mk].sum()) if mk.any() else None
                ip=wm(hist["IP"]) or 4.0; ep=wm(hist["EP"]) or 4.0
                dp=wm(hist["DP"]) or 3.0; bp_v=wm(hist["BP"]) or 3.0
                if use_slim and "直線の伸び" in hist.columns: nb=wm(hist["直線の伸び"].apply(rb.nobi_score)) or 2.0
                elif nobi_col in hist.columns: nb=wm(hist[nobi_col].apply(rb.nobi_score)) or 2.0
                if use_slim: is_m=bool(hist.get("is_monster",pd.Series([0])).max()>=1)
                else:
                    cmt=" ".join(hist.get("解析コメント",pd.Series([""])).astype(str))
                    is_m=any(k in cmt for k in ["脚余し","鬼脚","別次元","圧倒"])
                if len(sd)>=3:
                    ri=pd.to_numeric(hist[hist["開催日"].isin(rd)]["IP"],errors="coerce").mean()
                    ai=pd.to_numeric(hist["IP"],errors="coerce").mean()
                    if not np.isnan(ri) and not np.isnan(ai): form_trend=ri-ai
            lno=num_to_line.get(num,0); lbs=lines.get(lno,[num])
            pos=lbs.index(num)+1 if num in lbs else 1
            players[num]={"num":num,"name":nm,"base":base,"style":style,
                          "ip":ip,"ep":ep,"dp":dp,"bp":bp_v,"nb":nb,
                          "is_m":is_m,"line":lno,"pos":pos,"form_trend":form_trend}
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


# ── Sim engine (same as _race_sim.py) ────────────────────────────────────────
def simulate_race(race, rng):
    players=race["players"]; line_info=race["lines"]; bp_d=race["bp_d"]
    front_line=line_info[0]; rear_line=line_info[-1]
    ip_diff=front_line["leader_ip"]-rear_line["leader_ip"]
    size_adv=front_line["size"]-rear_line["size"]
    style_b=1.0 if front_line["leader_style"]=="逃" else 0.0
    tup_score=ip_diff*0.3+size_adv*0.2+style_b*0.3
    tuppari=rng.random()<1.0/(1.0+np.exp(-tup_score))
    if tuppari:
        intensity=max(0,3.0-abs(ip_diff))
        fl_fat=intensity*0.4; rl_fat=intensity*0.3
    else:
        fl_fat=0.1; rl_fat=0.2
    corner4={}
    for num,p in players.items():
        sc=p["base"]*0.3
        li=next((l for l in line_info if num in l["members"]),None)
        if not li: corner4[num]=sc; continue
        is_f=(li==front_line); is_r=(li==rear_line); is_m=not is_f and not is_r
        if p["pos"]==1:
            if is_f:
                sc+=p["ip"]*(1.5 if tuppari else 0.8)-(fl_fat*2.0 if tuppari else 0)+p["dp"]*(0 if tuppari else 0.5)
            elif is_r:
                sc+=p["ip"]*(1.2 if tuppari else 1.8)-(rl_fat*2.0 if tuppari else 0)
            elif is_m:
                sc+=p["dp"]*1.5*bp_d["makuri"]
        elif p["pos"]==2:
            if is_r and not tuppari:
                if p["ep"]<4.5 and rng.random()<(4.5-p["ep"])*0.3: sc-=5.0
                sc+=p["ep"]*1.2
            elif is_f:
                sc+=p["bp"]*bp_d["sashi"]*0.8+p["ep"]*0.8
            else:
                sc+=p["ep"]*1.0+p["dp"]*0.5
        else:
            sc+=p["ep"]*0.5
        if p["is_m"]: sc+=2.0
        corner4[num]=sc
    final={}
    for num,p in players.items():
        f=corner4.get(num,0)+p["nb"]*1.5
        li=next((l for l in line_info if num in l["members"]),None)
        if li and p["pos"]==1:
            if li==front_line: f-=fl_fat
            elif li==rear_line: f-=rl_fat
        f+=rng.gauss(0,2.0)
        final[num]=f
    return [n for n,_ in sorted(final.items(),key=lambda x:x[1],reverse=True)]


# ── PL scoring ───────────────────────────────────────────────────────────────
def pl_score_players(race):
    ps=race["players"]; bp_d=race["bp_d"]
    for n,p in ps.items():
        pos_b=0.5 if p["pos"]==1 else -0.3*(p["pos"]-1)
        bsf=(bp_d["sashi"]-1.0)*p["ep"]+(bp_d["makuri"]-1.0)*p["ip"]
        p["ev"]=(p["base"]*0.4+p["ip"]*1.5+p["ep"]*1.2
                 +p["dp"]*bp_d["makuri"]+p["bp"]*bp_d["sashi"]
                 +p["nb"]*2.0+0.5*0+pos_b
                 +(3.0 if p["is_m"] else 0)
                 +p["form_trend"]*1.0+bsf*2.0)


def pl_axis_and_probs(race):
    """PLモデルで軸と3連単確率を返す"""
    ps=race["players"]; od=race["odds_dict"]
    ranked=sorted(ps.items(),key=lambda x:x[1]["ev"],reverse=True)
    top_ev=ranked[0][1]["ev"]
    sl=[nn for nn,d in ps.items() if d["ip"]>=5.5 and d["pos"]==1]
    if len(sl)>=2: return None, None, None  # chaos
    if top_ev<MIN_EV: return None, None, None
    all_nums=[nn for nn,_ in ranked]; max_e=ranked[0][1]["ev"]
    raw_s={nn:np.exp(ps[nn]["ev"]-max_e) for nn in all_nums}
    axis=next((nn for nn,d in ranked if d["is_m"]),ranked[0][0])
    others=[nn for nn in all_nums if nn!=axis]
    def pl(f,s,t):
        d1=sum(raw_s[nn] for nn in all_nums);d2=sum(raw_s[nn] for nn in all_nums if nn!=f)
        d3=sum(raw_s[nn] for nn in all_nums if nn not in(f,s))
        return 0.0 if 0 in(d1,d2,d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)
    cands={}
    for sn in others:
        for tn in others:
            if sn==tn: continue
            c=f"{axis}-{sn}-{tn}"
            if c not in od: continue
            if od[c]<MIN_ODDS: continue
            cands[c]=pl(axis,sn,tn)
    return axis, cands, top_ev


# ── Hybrid strategies ────────────────────────────────────────────────────────
def run_hybrid(races, mode="pl_only", n_sim=N_SIM, top_n=7, alpha=0.5):
    """
    mode:
      "pl_only"    = 現行PL
      "sim_only"   = シミュのみ
      "hybrid_avg" = PL確率とシミュ確率の加重平均で買い目選定
      "hybrid_filter" = PLで軸+買い目候補、シミュ確率で足切り
      "hybrid_rerank" = PLで軸決定、シミュ確率で並び替え
    """
    rng = random.Random(42)
    total_inv=total_ret=total_n=total_hits=0

    for race in races:
        pl_score_players(race)
        axis, pl_probs, top_ev = pl_axis_and_probs(race)
        if axis is None: continue

        if mode == "pl_only":
            sel = sorted(pl_probs.items(), key=lambda x:x[1], reverse=True)[:top_n]
            bets = [c for c,_ in sel]

        elif mode == "sim_only":
            tri_counts = Counter()
            for _ in range(n_sim):
                r = simulate_race(race, rng)
                if len(r)>=3: tri_counts[f"{r[0]}-{r[1]}-{r[2]}"] += 1
            axis_combos = [(c,cnt) for c,cnt in tri_counts.items()
                           if c.startswith(f"{axis}-") and c in race["odds_dict"]
                           and race["odds_dict"][c]>=MIN_ODDS]
            axis_combos.sort(key=lambda x:x[1],reverse=True)
            bets = [c for c,_ in axis_combos[:top_n]]

        elif mode == "hybrid_avg":
            # シミュ確率を計算
            tri_counts = Counter()
            for _ in range(n_sim):
                r = simulate_race(race, rng)
                if len(r)>=3: tri_counts[f"{r[0]}-{r[1]}-{r[2]}"] += 1
            sim_probs = {c: cnt/n_sim for c, cnt in tri_counts.items()}
            # PL確率の正規化
            pl_total = sum(pl_probs.values()) if pl_probs else 1
            # 加重平均
            merged = {}
            for c in set(list(pl_probs.keys()) + list(sim_probs.keys())):
                if not c.startswith(f"{axis}-"): continue
                if c not in race["odds_dict"]: continue
                if race["odds_dict"][c] < MIN_ODDS: continue
                p_pl = pl_probs.get(c, 0) / pl_total if pl_total else 0
                p_sim = sim_probs.get(c, 0)
                merged[c] = alpha * p_pl + (1-alpha) * p_sim
            bets = [c for c,_ in sorted(merged.items(), key=lambda x:x[1], reverse=True)[:top_n]]

        elif mode == "hybrid_filter":
            # PLで候補選定 → シミュで足切り
            tri_counts = Counter()
            for _ in range(n_sim):
                r = simulate_race(race, rng)
                if len(r)>=3: tri_counts[f"{r[0]}-{r[1]}-{r[2]}"] += 1
            sim_probs = {c: cnt/n_sim for c, cnt in tri_counts.items()}
            # PLのtop候補から、シミュでも出現したものだけ残す
            pl_ranked = sorted(pl_probs.items(), key=lambda x:x[1], reverse=True)
            bets = []
            for c, p in pl_ranked:
                if sim_probs.get(c, 0) > 0:  # シミュでも1回以上出現
                    bets.append(c)
                if len(bets) >= top_n: break

        elif mode == "hybrid_rerank":
            # PLで軸決定、シミュ確率で並び替え
            tri_counts = Counter()
            for _ in range(n_sim):
                r = simulate_race(race, rng)
                if len(r)>=3: tri_counts[f"{r[0]}-{r[1]}-{r[2]}"] += 1
            sim_probs = {c: cnt/n_sim for c, cnt in tri_counts.items()}
            # PL候補をシミュ確率で再ランク
            pl_candidates = [c for c in pl_probs if pl_probs[c] > 0]
            reranked = sorted(pl_candidates, key=lambda c: sim_probs.get(c, 0), reverse=True)
            bets = [c for c in reranked if c in race["odds_dict"] and race["odds_dict"][c]>=MIN_ODDS][:top_n]

        if not bets: continue
        inv=len(bets)*100; hit=race["actual"] in bets; ret=race["payout"] if hit else 0
        total_inv+=inv; total_ret+=ret; total_n+=1
        if hit: total_hits+=1

    roi=total_ret/total_inv*100 if total_inv else 0
    return {"n":total_n,"hits":total_hits,"invest":total_inv,"ret":total_ret,
            "roi":roi,"profit":total_ret-total_inv}


# ── Run all modes ────────────────────────────────────────────────────────────
all_dates=sorted(set(r["date"] for r in all_races))
mid=len(all_dates)//2
train=[r for r in all_races if r["date"]<=all_dates[mid-1]]
test=[r for r in all_races if r["date"]>all_dates[mid-1]]

configs = [
    ("PL単独(現行)", "pl_only", 0),
    ("シミュ単独", "sim_only", 0),
    ("ハイブリッド平均 a=0.3", "hybrid_avg", 0.3),
    ("ハイブリッド平均 a=0.5", "hybrid_avg", 0.5),
    ("ハイブリッド平均 a=0.7", "hybrid_avg", 0.7),
    ("ハイブリッドフィルタ", "hybrid_filter", 0),
    ("ハイブリッド再ランク", "hybrid_rerank", 0),
]

print(f"\n{'='*90}")
print(f"{'モデル':>25s}  {'全体R':>5s}  {'的中':>4s}  {'率':>5s}  {'全体ROI':>8s}  {'全体収支':>10s}  {'検証ROI':>8s}  {'検証収支':>10s}")
print(f"{'='*90}")

for name, mode, alpha in configs:
    ra = run_hybrid(all_races, mode=mode, alpha=alpha)
    rv = run_hybrid(test, mode=mode, alpha=alpha)
    hit_rate = ra['hits']/ra['n']*100 if ra['n'] else 0
    print(f"  {name:>23s}  {ra['n']:5d}  {ra['hits']:4d}  {hit_rate:4.1f}%  "
          f"{ra['roi']:7.1f}%  {ra['profit']:>+10,}  {rv['roi']:7.1f}%  {rv['profit']:>+10,}")
