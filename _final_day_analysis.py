"""最終日開催の特性分析と現行ロジックでのROI比較"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, sys
from collections import defaultdict, Counter

RC = pd.read_excel("data/racecard_hist.xlsx", dtype={"race_id": str})
PY = pd.read_excel("data/payouts_hist.xlsx", dtype={"race_id": str})
OD = pd.read_excel("data/odds_hist.xlsx", dtype={"race_id": str})
RC["date"] = pd.to_datetime(RC["date"].astype(str), format="%Y%m%d", errors="coerce")
OD["オッズ"] = pd.to_numeric(OD["オッズ"], errors="coerce")
PY["payout_trifecta"] = pd.to_numeric(PY["payout_trifecta"], errors="coerce")
PY["result_trifecta"] = PY["result_trifecta"].astype(str).str.strip()

# === 開催を特定: 同じvenueで連続する日付をグループ化 ===
venue_dates = defaultdict(list)
for venue, dt in RC[["venue", "date"]].drop_duplicates().sort_values("date").values:
    venue_dates[venue].append(pd.Timestamp(dt))

# 各開催の日数を判定 (連続日 or 1日空く程度を許容)
meetings = []  # (venue, [dates])
for venue, dates in venue_dates.items():
    if not dates: continue
    cur = [dates[0]]
    for d in dates[1:]:
        gap = (d - cur[-1]).days
        if gap <= 2:  # 連続 or 1日空き
            cur.append(d)
        else:
            meetings.append({"venue": venue, "dates": cur})
            cur = [d]
    meetings.append({"venue": venue, "dates": cur})

# 各レースに「節内日数」「節最終日フラグ」を付与
race_meeting_info = {}  # race_id → (venue, day_in_meeting, is_final_day, total_days)
for m in meetings:
    venue = m["venue"]
    dates = m["dates"]
    for i, d in enumerate(dates):
        is_final = (i == len(dates) - 1)
        rids = RC[(RC["venue"]==venue)&(RC["date"]==d)]["race_id"].unique()
        for rid in rids:
            race_meeting_info[rid] = {
                "venue": venue, "day": i+1, "is_final": is_final,
                "total_days": len(dates),
            }

# 開催日数の分布
day_count_dist = Counter(len(m["dates"]) for m in meetings)
print(f"=== 開催の日数分布 ===")
print(f"全開催数: {len(meetings)}")
for k in sorted(day_count_dist):
    print(f"  {k}日開催: {day_count_dist[k]}件")

# 最終日レース数
final_day_races = sum(1 for v in race_meeting_info.values() if v["is_final"])
non_final = sum(1 for v in race_meeting_info.values() if not v["is_final"])
print(f"\n最終日レース数: {final_day_races}")
print(f"その他のレース数: {non_final}")

# === 日次別の的中率 (実績ベース、ロジックなし) ===
print(f"\n=== 日次別: 全レースの結果オッズ中央値 ===")
import importlib.util
spec = importlib.util.spec_from_file_location("rb", "run_backtest.py")
rb = importlib.util.module_from_spec(spec); sys.modules["rb"] = rb; spec.loader.exec_module(rb)
db_slim, db_all, nobi_col = rb.load_db()

odds_lookup = defaultdict(dict)
for _, r in OD.iterrows():
    if pd.notna(r["オッズ"]):
        odds_lookup[str(r["race_id"]).strip()][str(r["組み合わせ"]).strip()] = float(r["オッズ"])

# Day別の結果オッズ
by_day = defaultdict(list)
for _, py_row in PY.iterrows():
    rid = str(py_row["race_id"]).strip()
    actual = str(py_row["result_trifecta"]).strip()
    if not actual or actual=="nan": continue
    if rid not in race_meeting_info: continue
    info = race_meeting_info[rid]
    odds = odds_lookup.get(rid, {}).get(actual, 0)
    if odds > 0:
        key = f"Day{info['day']}/of{info['total_days']}"
        by_day[key].append(odds)

print(f"{'日':>15s}  {'件数':>5s}  {'結果odds中央値':>14s}  {'平均':>8s}")
for key in sorted(by_day):
    vals = by_day[key]
    if len(vals) < 5: continue
    print(f"  {key:>13s}  {len(vals):5d}  {np.median(vals):13.1f}  {np.mean(vals):7.1f}")

# === 現行ロジックで day別ROI を計算 ===
print(f"\n=== 現行ロジック(PL+シミュ閾値5+10点) で日次別ROI ===")

# Use existing _three_improvements.py framework
import random
BANK_DICT = rb.BANK_DICT
MIN_EV = 67

dates_all = sorted(RC["date"].dropna().unique())
print("Loading races...", file=sys.stderr)
all_races = []
for race_date in dates_all:
    daily_rc = RC[RC["date"] == race_date]
    for race_id in daily_rc["race_id"].unique():
        race_info = daily_rc[daily_rc["race_id"] == race_id].copy()
        if race_info.empty: continue
        venue = race_info.iloc[0]["venue"]
        bp_d = BANK_DICT.get(venue, {"roi_tier":"mid","sashi":1.0,"makuri":1.0})
        odds_dict = odds_lookup.get(race_id, {})
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
        meeting = race_meeting_info.get(race_id, {})
        all_races.append({"players":players,"lines":line_info,"actual":actual,
                          "payout":payout,"odds_dict":odds_dict,"venue":venue,
                          "date":str(race_date.date()),"bp_d":bp_d,
                          "race_id":race_id,
                          "is_final": meeting.get("is_final", False),
                          "day": meeting.get("day", 0),
                          "total_days": meeting.get("total_days", 0),
                          })

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


def run_strategy(races, sim_thresh=5, top_n=10, n_sim=500):
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


# Day別フィルタで実行
print(f"\n{'='*70}")
print(f"{'区分':>20s}  {'対象R':>5s}  {'判定R':>5s}  {'的中':>4s}  {'率':>5s}  {'ROI':>7s}  {'収支':>10s}")
print(f"{'='*70}")

# 全体
r_all = run_strategy(all_races)
print(f"  {'全レース':>18s}  {len(all_races):5d}  {r_all['n']:5d}  {r_all['hits']:4d}  {r_all['hits']/r_all['n']*100:4.1f}%  {r_all['roi']:6.1f}%  {r_all['profit']:>+10,}")

# 最終日のみ
final_races = [r for r in all_races if r["is_final"]]
r_final = run_strategy(final_races)
print(f"  {'最終日のみ':>18s}  {len(final_races):5d}  {r_final['n']:5d}  {r_final['hits']:4d}  {r_final['hits']/r_final['n']*100:4.1f}%  {r_final['roi']:6.1f}%  {r_final['profit']:>+10,}")

# 初日のみ
day1_races = [r for r in all_races if r["day"]==1]
r_d1 = run_strategy(day1_races)
print(f"  {'初日のみ':>18s}  {len(day1_races):5d}  {r_d1['n']:5d}  {r_d1['hits']:4d}  {r_d1['hits']/r_d1['n']*100:4.1f}%  {r_d1['roi']:6.1f}%  {r_d1['profit']:>+10,}")

# 2日目のみ
day2_races = [r for r in all_races if r["day"]==2]
r_d2 = run_strategy(day2_races)
print(f"  {'2日目のみ':>18s}  {len(day2_races):5d}  {r_d2['n']:5d}  {r_d2['hits']:4d}  {r_d2['hits']/r_d2['n']*100:4.1f}%  {r_d2['roi']:6.1f}%  {r_d2['profit']:>+10,}")

# 3日目以降
day3_races = [r for r in all_races if r["day"]>=3]
r_d3 = run_strategy(day3_races)
print(f"  {'3日目以降':>18s}  {len(day3_races):5d}  {r_d3['n']:5d}  {r_d3['hits']:4d}  {r_d3['hits']/r_d3['n']*100:4.1f}%  {r_d3['roi']:6.1f}%  {r_d3['profit']:>+10,}")

# レース番号別 (12R = S級決勝が多い)
print(f"\n{'='*70}")
print(f"=== レース番号別 (最終日のみ) ===")
print(f"{'='*70}")
print(f"{'R番号':>6s}  {'対象R':>5s}  {'判定R':>5s}  {'的中':>4s}  {'率':>5s}  {'ROI':>7s}  {'収支':>10s}")

for rn in [9, 10, 11, 12]:
    sub = [r for r in final_races
           if int(RC[RC["race_id"]==r["race_id"]]["race_no"].iloc[0]) == rn]
    if not sub: continue
    r = run_strategy(sub)
    if r["n"] == 0: continue
    print(f"  {rn:4d}R  {len(sub):5d}  {r['n']:5d}  {r['hits']:4d}  {r['hits']/r['n']*100:4.1f}%  {r['roi']:6.1f}%  {r['profit']:>+10,}")
