"""ハイブリッドフィルタのチューニング
1. シミュフィルタ閾値 (何%以上で通過させるか)
2. シミュレーション係数 (消耗度・ノイズ・各フェーズの重み)
3. 買い目数
全てCV検証付き
"""
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

dates = sorted(RC["date"].dropna().unique())

# ── Data load (reuse from _hybrid_plsim) ─────────────────────────────────────
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

# ── Parameterized simulation ─────────────────────────────────────────────────
def simulate_race(race, rng, params):
    """パラメータ化されたレースシミュレーション"""
    players=race["players"]; line_info=race["lines"]; bp_d=race["bp_d"]
    front=line_info[0]; rear=line_info[-1]

    # 突っ張り判定
    ip_diff = front["leader_ip"] - rear["leader_ip"]
    size_adv = front["size"] - rear["size"]
    style_b = 1.0 if front["leader_style"] == "逃" else 0.0
    tup_score = ip_diff * params["tup_ip"] + size_adv * params["tup_size"] + style_b * params["tup_style"]
    tuppari = rng.random() < 1.0 / (1.0 + np.exp(-tup_score))

    # 消耗
    if tuppari:
        intensity = max(0, 3.0 - abs(ip_diff))
        fl_fat = intensity * params["fat_front"]; rl_fat = intensity * params["fat_rear"]
    else:
        fl_fat = 0.1; rl_fat = 0.2

    # 4コーナー
    c4 = {}
    for num, p in players.items():
        sc = p["base"] * params["w_base"]
        li = next((l for l in line_info if num in l["members"]), None)
        if not li: c4[num] = sc; continue
        is_f = (li == front); is_r = (li == rear); is_mid = not is_f and not is_r
        if p["pos"] == 1:
            if is_f:
                sc += p["ip"] * (params["w_ip_front_tup"] if tuppari else params["w_ip_front_pull"])
                sc -= fl_fat * params["w_fatigue"] if tuppari else 0
                if not tuppari: sc += p["dp"] * params["w_dp_pull"]
            elif is_r:
                sc += p["ip"] * (params["w_ip_rear_tup"] if tuppari else params["w_ip_rear_free"])
                sc -= rl_fat * params["w_fatigue"] if tuppari else 0
            elif is_mid:
                sc += p["dp"] * params["w_dp_mid"] * bp_d["makuri"]
        elif p["pos"] == 2:
            if is_r and not tuppari:
                if p["ep"] < params["ep_thresh"] and rng.random() < (params["ep_thresh"] - p["ep"]) * params["chigire_rate"]:
                    sc -= params["chigire_penalty"]
                sc += p["ep"] * params["w_ep_rear"]
            elif is_f:
                sc += p["bp"] * bp_d["sashi"] * params["w_bp_front"] + p["ep"] * params["w_ep_front"]
            else:
                sc += p["ep"] * params["w_ep_mid"] + p["dp"] * params["w_dp_mid_bante"]
        else:
            sc += p["ep"] * params["w_ep_3rd"]
        if p["is_m"]: sc += params["w_monster"]
        c4[num] = sc

    # 直線
    final = {}
    for num, p in players.items():
        f = c4.get(num, 0) + p["nb"] * params["w_nb"]
        li = next((l for l in line_info if num in l["members"]), None)
        if li and p["pos"] == 1:
            if li == front: f -= fl_fat * params["w_fat_straight"]
            elif li == rear: f -= rl_fat * params["w_fat_straight"]
        f += rng.gauss(0, params["noise"])
        final[num] = f
    return [n for n, _ in sorted(final.items(), key=lambda x: x[1], reverse=True)]


DEFAULT_PARAMS = {
    "tup_ip": 0.3, "tup_size": 0.2, "tup_style": 0.3,
    "fat_front": 0.4, "fat_rear": 0.3,
    "w_base": 0.3, "w_fatigue": 2.0,
    "w_ip_front_tup": 1.5, "w_ip_front_pull": 0.8,
    "w_ip_rear_tup": 1.2, "w_ip_rear_free": 1.8,
    "w_dp_pull": 0.5, "w_dp_mid": 1.5,
    "ep_thresh": 4.5, "chigire_rate": 0.3, "chigire_penalty": 5.0,
    "w_ep_rear": 1.2, "w_bp_front": 0.8, "w_ep_front": 0.8,
    "w_ep_mid": 1.0, "w_dp_mid_bante": 0.5, "w_ep_3rd": 0.5,
    "w_monster": 2.0, "w_nb": 1.5, "w_fat_straight": 1.0,
    "noise": 2.0,
}


def run_hybrid_filter(races, n_sim=300, top_n=7, sim_threshold=1, params=DEFAULT_PARAMS):
    """ハイブリッドフィルタ: PL候補 × シミュ出現回数 >= threshold"""
    rng = random.Random(42)
    total_inv=total_ret=total_n=total_hits=0
    for race in races:
        ps=race["players"]; bp_d=race["bp_d"]; od=race["odds_dict"]
        # PL scoring
        for n,p in ps.items():
            pos_b=0.5 if p["pos"]==1 else -0.3*(p["pos"]-1)
            bsf=(bp_d["sashi"]-1.0)*p["ep"]+(bp_d["makuri"]-1.0)*p["ip"]
            p["ev"]=(p["base"]*0.4+p["ip"]*1.5+p["ep"]*1.2
                     +p["dp"]*bp_d["makuri"]+p["bp"]*bp_d["sashi"]
                     +p["nb"]*2.0+pos_b+(3.0 if p["is_m"] else 0)
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
        # PLの上位候補（多めに取る）
        pl_pool = [c for _,c in pl_cands[:top_n*3]]

        # シミュレーション
        tri_counts = Counter()
        for _ in range(n_sim):
            r = simulate_race(race, rng, params)
            if len(r)>=3: tri_counts[f"{r[0]}-{r[1]}-{r[2]}"] += 1

        # フィルタ: PL候補 & シミュ出現 >= threshold
        bets = []
        for c in [cc for _,cc in pl_cands]:  # PL確率順
            if tri_counts.get(c, 0) >= sim_threshold:
                bets.append(c)
            if len(bets) >= top_n: break

        if not bets: continue
        inv=len(bets)*100; hit=race["actual"] in bets; ret=race["payout"] if hit else 0
        total_inv+=inv; total_ret+=ret; total_n+=1
        if hit: total_hits+=1
    roi=total_ret/total_inv*100 if total_inv else 0
    return {"n":total_n,"hits":total_hits,"invest":total_inv,"ret":total_ret,
            "roi":roi,"profit":total_ret-total_inv}


# ── Test suites ──────────────────────────────────────────────────────────────
all_dates = sorted(set(r["date"] for r in all_races))
mid = len(all_dates) // 2
train = [r for r in all_races if r["date"] <= all_dates[mid-1]]
test = [r for r in all_races if r["date"] > all_dates[mid-1]]

# === 1. フィルタ閾値 + 買い目数 ===
print(f"\n{'='*85}")
print("=== 1. フィルタ閾値 × 買い目数 ===")
print(f"{'='*85}")
print(f"{'閾値':>4s} {'N点':>3s}  {'全R':>4s} {'的中':>4s} {'率':>5s} {'全ROI':>7s} {'全収支':>10s} {'検ROI':>7s} {'検収支':>10s}")
print("-"*75)
for thresh in [1, 2, 3, 5]:
    for top_n in [5, 7, 10]:
        ra = run_hybrid_filter(all_races, n_sim=300, top_n=top_n, sim_threshold=thresh)
        rv = run_hybrid_filter(test, n_sim=300, top_n=top_n, sim_threshold=thresh)
        if ra["n"] == 0: continue
        hr = ra["hits"]/ra["n"]*100
        print(f"  {thresh:2d}  {top_n:3d}  {ra['n']:4d} {ra['hits']:4d} {hr:4.1f}% "
              f"{ra['roi']:6.1f}% {ra['profit']:>+10,} {rv['roi']:6.1f}% {rv['profit']:>+10,}")

# === 2. シミュレーション係数チューニング ===
print(f"\n{'='*85}")
print("=== 2. シミュ係数チューニング (閾値=1, 7点固定) ===")
print(f"{'='*85}")
print(f"{'パラメータ':>25s}  {'全ROI':>7s}  {'全収支':>10s}  {'検ROI':>7s}  {'検収支':>10s}")
print("-"*70)

# デフォルト
ra = run_hybrid_filter(all_races, params=DEFAULT_PARAMS)
rv = run_hybrid_filter(test, params=DEFAULT_PARAMS)
print(f"  {'デフォルト':>23s}  {ra['roi']:6.1f}%  {ra['profit']:>+10,}  {rv['roi']:6.1f}%  {rv['profit']:>+10,}")

# 個別パラメータ変動テスト
tweaks = [
    ("noise=1.0(小)", {"noise": 1.0}),
    ("noise=1.5", {"noise": 1.5}),
    ("noise=3.0(大)", {"noise": 3.0}),
    ("w_base=0.5", {"w_base": 0.5}),
    ("w_base=0.1", {"w_base": 0.1}),
    ("消耗大 fat=0.6/0.5", {"fat_front": 0.6, "fat_rear": 0.5}),
    ("消耗小 fat=0.2/0.15", {"fat_front": 0.2, "fat_rear": 0.15}),
    ("捲り強 dp_mid=2.0", {"w_dp_mid": 2.0}),
    ("捲り弱 dp_mid=1.0", {"w_dp_mid": 1.0}),
    ("直線重視 nb=2.5", {"w_nb": 2.5}),
    ("直線軽視 nb=0.8", {"w_nb": 0.8}),
    ("鬼脚大 monster=3.0", {"w_monster": 3.0}),
    ("鬼脚小 monster=1.0", {"w_monster": 1.0}),
    ("千切り厳 ep_th=5.0", {"ep_thresh": 5.0}),
    ("千切り緩 ep_th=4.0", {"ep_thresh": 4.0}),
    ("逃げ有利 rear_free=2.2", {"w_ip_rear_free": 2.2}),
    ("逃げ不利 rear_free=1.4", {"w_ip_rear_free": 1.4}),
    ("BP重要 bp_front=1.2", {"w_bp_front": 1.2}),
]

for name, changes in tweaks:
    p = {**DEFAULT_PARAMS, **changes}
    ra = run_hybrid_filter(all_races, params=p)
    rv = run_hybrid_filter(test, params=p)
    if ra["n"] == 0: continue
    print(f"  {name:>23s}  {ra['roi']:6.1f}%  {ra['profit']:>+10,}  {rv['roi']:6.1f}%  {rv['profit']:>+10,}")

# === 3. ベストパラメータ組み合わせ ===
print(f"\n{'='*85}")
print("=== 3. ベスト組み合わせ候補 ===")
print(f"{'='*85}")
combos = [
    ("デフォルト", {}),
    ("noise1.5+nb2.5", {"noise":1.5,"w_nb":2.5}),
    ("noise1.5+捲り2.0+nb2.5", {"noise":1.5,"w_dp_mid":2.0,"w_nb":2.5}),
    ("noise1.5+消耗大+nb2.5", {"noise":1.5,"fat_front":0.6,"fat_rear":0.5,"w_nb":2.5}),
    ("noise1.5+BP1.2+nb2.5", {"noise":1.5,"w_bp_front":1.2,"w_nb":2.5}),
    ("noise1.0+base0.5+nb2.5", {"noise":1.0,"w_base":0.5,"w_nb":2.5}),
    ("全盛り", {"noise":1.5,"w_nb":2.5,"w_dp_mid":2.0,"w_bp_front":1.2,"fat_front":0.6,"fat_rear":0.5}),
]
print(f"{'設定':>30s}  {'全R':>4s} {'全ROI':>7s} {'全収支':>10s} {'検R':>4s} {'検ROI':>7s} {'検収支':>10s}")
print("-"*80)
for name, changes in combos:
    p = {**DEFAULT_PARAMS, **changes}
    ra = run_hybrid_filter(all_races, params=p)
    rv = run_hybrid_filter(test, params=p)
    if ra["n"]==0: continue
    print(f"  {name:>28s}  {ra['n']:4d} {ra['roi']:6.1f}% {ra['profit']:>+10,} "
          f"{rv['n']:4d} {rv['roi']:6.1f}% {rv['profit']:>+10,}")
