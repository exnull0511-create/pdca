"""展開シミュレーション予想エンジン v0.1
並び順→前取り争い→捲りvsブロック→直線 の分岐をモンテカルロで確率化
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

dates = sorted(RC["date"].dropna().unique())
MIN_EV = 67; MIN_ODDS = 10; N_SIM = 500

# ── Data collection ──────────────────────────────────────────────────────────
print("Loading race data...", file=sys.stderr)
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

        # Build line structure
        lines = {}  # line_no -> [list of bibs in order]
        num_to_line = {}
        for _, row in race_info.iterrows():
            try: num=int(row["車番"]); lno=int(row.get("line_no",0) or 0)
            except: continue
            bs = str(row.get("line_bibs",str(num)))
            if lno not in lines:
                try: lines[lno] = [int(b) for b in bs.split("-") if b.isdigit()]
                except: lines[lno] = [num]
            num_to_line[num] = lno

        # Build player data
        players = {}
        for _, row in race_info.iterrows():
            try:
                num=int(row["車番"]); nm=rb.norm(str(row.get("選手名","")))
                base=float(row.get("競走得点",80) or 80)
                style=str(row.get("脚質",""))
            except: continue
            hist=past_slim[past_slim["選手名_norm"]==nm] if not past_slim.empty else pd.DataFrame()
            use_slim=not hist.empty
            if hist.empty: hist=past_all[past_all["選手名_norm"]==nm] if not past_all.empty else pd.DataFrame()
            ip=ep=4.0; dp=bp_v=3.0; nb=2.0; is_m=False
            if not hist.empty:
                RW=3.0; sd=sorted(hist["開催日"].dropna().unique(),reverse=True); rd=set(sd[:2])
                def wm(s):
                    v=pd.to_numeric(s,errors="coerce"); w=np.where(hist["開催日"].isin(rd),RW,1.0); mk=v.notna()
                    return float((v[mk]*w[mk]).sum()/w[mk].sum()) if mk.any() else None
                ip=wm(hist["IP"]) or 4.0; ep=wm(hist["EP"]) or 4.0
                dp=wm(hist["DP"]) or 3.0; bp_v=wm(hist["BP"]) or 3.0
                if use_slim and "直線の伸び" in hist.columns:
                    nb=wm(hist["直線の伸び"].apply(rb.nobi_score)) or 2.0
                elif nobi_col in hist.columns:
                    nb=wm(hist[nobi_col].apply(rb.nobi_score)) or 2.0
                if use_slim:
                    is_m=bool(hist.get("is_monster",pd.Series([0])).max()>=1)
                else:
                    cmt=" ".join(hist.get("解析コメント",pd.Series([""])).astype(str))
                    is_m=any(k in cmt for k in ["脚余し","鬼脚","別次元","圧倒"])

            lno = num_to_line.get(num, 0)
            line_members = lines.get(lno, [num])
            pos = line_members.index(num) + 1 if num in line_members else 1

            players[num] = {
                "num": num, "name": nm, "base": base, "style": style,
                "ip": ip, "ep": ep, "dp": dp, "bp": bp_v, "nb": nb,
                "is_m": is_m, "line": lno, "pos": pos,
            }

        if len(players) < 3: continue

        # Organize lines with leader info
        line_info = []  # sorted by S本数 (front to back)
        for lno, members in sorted(lines.items()):
            leader_num = members[0] if members else None
            if leader_num not in players: continue
            leader = players[leader_num]
            line_info.append({
                "lno": lno, "members": [m for m in members if m in players],
                "size": len([m for m in members if m in players]),
                "leader": leader_num,
                "leader_ip": leader["ip"],
                "leader_dp": leader["dp"],
                "leader_style": leader["style"],
            })

        if len(line_info) < 2: continue

        all_races.append({
            "players": players, "lines": line_info, "actual": actual,
            "payout": payout, "odds_dict": odds_dict, "venue": venue,
            "date": str(race_date.date()), "bp_d": bp_d,
        })

print(f"Races: {len(all_races)}", file=sys.stderr)


# ── Simulation Engine ────────────────────────────────────────────────────────
def simulate_race(race, rng):
    """1回のレースシミュレーション。着順を返す。"""
    players = race["players"]
    line_info = race["lines"]
    bp_d = race["bp_d"]

    # === Phase 1: 並び順（line_infoの順序 = 前から後ろ） ===
    # line_info[0] = 最前ライン, line_info[-1] = 最後方ライン
    n_lines = len(line_info)

    # === Phase 2: 前取り争い ===
    # 最後方ラインが仕掛ける。前ラインが突っ張るか引くかを判定。
    front_line = line_info[0]
    rear_line = line_info[-1]
    mid_lines = line_info[1:-1] if n_lines > 2 else []

    # 突っ張り確率: 前ラインの先頭IPが後方より高い & ライン長い → 突っ張りやすい
    ip_diff = front_line["leader_ip"] - rear_line["leader_ip"]
    size_advantage = front_line["size"] - rear_line["size"]
    # 逃げ脚質なら突っ張りやすい
    style_bonus = 1.0 if front_line["leader_style"] == "逃" else 0.0

    tuppari_score = ip_diff * 0.3 + size_advantage * 0.2 + style_bonus * 0.3
    tuppari_prob = 1.0 / (1.0 + np.exp(-tuppari_score))  # sigmoid

    tuppari = rng.random() < tuppari_prob

    # === Phase 2.5: 消耗度計算 ===
    # 前取り争いの激しさ → 先頭選手の消耗
    if tuppari:
        # 突っ張り → 両先頭が消耗。IP差が小さいほど消耗大。
        intensity = max(0, 3.0 - abs(ip_diff))  # IP差が小さいほど激しい
        front_leader_fatigue = intensity * 0.4
        rear_leader_fatigue = intensity * 0.3
    else:
        # 前ラインが引く → 前は消耗少、後方が逃げ確定
        front_leader_fatigue = 0.1
        rear_leader_fatigue = 0.2  # 仕掛けた分の消耗

    # === Phase 3: 捲り判定 ===
    # 中段ラインが捲りに行く。前ラインの番手がブロックするか。
    # 4コーナーの位置取りを決める

    # 各選手のスコア（4コーナー時点の有利度）
    corner4_scores = {}
    for num, p in players.items():
        score = p["base"] * 0.3  # ベース能力

        line_of_player = next((li for li in line_info if num in li["members"]), None)
        if not line_of_player:
            corner4_scores[num] = score
            continue

        is_front_line = (line_of_player == front_line)
        is_rear_line = (line_of_player == rear_line)
        is_mid_line = not is_front_line and not is_rear_line

        if p["pos"] == 1:  # ライン先頭
            if is_front_line:
                if tuppari:
                    # 突っ張り成功 → 前にいるが消耗
                    score += p["ip"] * 1.5 - front_leader_fatigue * 2.0
                else:
                    # 引いた → 中段、脚は残ってる
                    score += p["ip"] * 0.8 + p["dp"] * 0.5
            elif is_rear_line:
                if tuppari:
                    # 前が突っ張った → 消耗戦
                    score += p["ip"] * 1.2 - rear_leader_fatigue * 2.0
                else:
                    # 前が引いた → 逃げ確定、有利
                    score += p["ip"] * 1.8
            elif is_mid_line:
                # 中段 → 捲りのチャンス
                score += p["dp"] * 1.5 * bp_d["makuri"]

        elif p["pos"] == 2:  # 番手
            leader_num = line_of_player["members"][0]
            leader_p = players.get(leader_num, p)

            if is_rear_line and not tuppari:
                # 後方仕掛けの番手 → EP必須（千切れリスク）
                ep_threshold = 4.5
                if p["ep"] < ep_threshold:
                    # 千切れリスク
                    chigire_prob = (ep_threshold - p["ep"]) * 0.3
                    if rng.random() < chigire_prob:
                        score -= 5.0  # 大きなペナルティ
                score += p["ep"] * 1.2
            elif is_rear_line and tuppari:
                # 消耗戦の番手 → 追走は楽、EP普通でOK
                score += p["ep"] * 0.8 + p["bp"] * 0.5
            elif is_front_line:
                # 前ラインの番手 → ブロック力 + 差し力
                score += p["bp"] * bp_d["sashi"] * 0.8 + p["ep"] * 0.8
            elif is_mid_line:
                # 中段番手 → 先頭の捲りに付いていく
                score += p["ep"] * 1.0 + p["dp"] * 0.5

        else:  # 3番手以降
            score += p["ep"] * 0.5  # 追走のみ

        # 鬼脚ボーナス
        if p["is_m"]:
            score += 2.0

        corner4_scores[num] = score

    # === Phase 4: 直線（個人の伸び + 残脚） ===
    final_scores = {}
    for num, p in players.items():
        c4 = corner4_scores.get(num, 0)
        # 直線の伸び（nb: 1-5, 5=S級）
        straight = p["nb"] * 1.5

        # 消耗が大きいほど直線で伸びない
        line_of_player = next((li for li in line_info if num in li["members"]), None)
        fatigue = 0
        if line_of_player and p["pos"] == 1:
            if line_of_player == front_line:
                fatigue = front_leader_fatigue
            elif line_of_player == rear_line:
                fatigue = rear_leader_fatigue

        final = c4 + straight - fatigue * 1.0

        # ランダム要素（レースの不確実性）
        final += rng.gauss(0, 2.0)

        final_scores[num] = final

    # 着順
    ranking = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
    return [num for num, _ in ranking]


def run_simulation_backtest(races, n_sim=500, top_n=7):
    """モンテカルロシミュレーションで各選手の1着確率を算出し、
    PL単軸と同様に軸+買い目を決定してバックテスト"""
    rng = random.Random(42)
    total_inv = total_ret = total_n = total_hits = 0

    for race in races:
        players = race["players"]
        odds_dict = race["odds_dict"]

        # N_SIM回シミュレーション
        first_counts = Counter()  # num -> 1着回数
        trifecta_counts = Counter()  # "f-s-t" -> 出現回数

        for _ in range(n_sim):
            ranking = simulate_race(race, rng)
            if len(ranking) >= 3:
                first_counts[ranking[0]] += 1
                combo = f"{ranking[0]}-{ranking[1]}-{ranking[2]}"
                trifecta_counts[combo] += 1

        # 軸 = 1着最多の選手
        if not first_counts:
            continue
        axis = first_counts.most_common(1)[0][0]
        axis_rate = first_counts[axis] / n_sim

        # EV的なフィルタ: 軸の1着確率が低すぎるレースはスキップ
        if axis_rate < 0.15:
            continue

        # 軸固定の3連単をシミュレーション確率順で選択
        axis_combos = [(combo, cnt) for combo, cnt in trifecta_counts.items()
                       if combo.startswith(f"{axis}-")]
        axis_combos.sort(key=lambda x: x[1], reverse=True)

        # ガミカット + 上位N点
        selected = []
        for combo, cnt in axis_combos:
            if combo not in odds_dict: continue
            if odds_dict[combo] < MIN_ODDS: continue
            selected.append(combo)
            if len(selected) >= top_n:
                break

        if not selected:
            continue

        inv = len(selected) * 100
        hit = race["actual"] in selected
        ret = race["payout"] if hit else 0
        total_inv += inv; total_ret += ret; total_n += 1
        if hit: total_hits += 1

    roi = total_ret / total_inv * 100 if total_inv > 0 else 0
    return {"n": total_n, "hits": total_hits, "invest": total_inv,
            "ret": total_ret, "roi": roi, "profit": total_ret - total_inv}


# ── Run backtest ─────────────────────────────────────────────────────────────
print("\n=== 展開シミュレーション バックテスト ===", flush=True)

# Full dataset
r_all = run_simulation_backtest(all_races, n_sim=N_SIM)
print(f"\n全期間: {r_all['n']}R  的中{r_all['hits']}({r_all['hits']/r_all['n']*100:.1f}%)  "
      f"ROI {r_all['roi']:.1f}%  収支{r_all['profit']:+,}")

# CV: 前半→後半
all_dates = sorted(set(r["date"] for r in all_races))
mid = len(all_dates) // 2
train = [r for r in all_races if r["date"] <= all_dates[mid-1]]
test = [r for r in all_races if r["date"] > all_dates[mid-1]]

r_train = run_simulation_backtest(train, n_sim=N_SIM)
r_test = run_simulation_backtest(test, n_sim=N_SIM)
print(f"学習期間: {r_train['n']}R  ROI {r_train['roi']:.1f}%  収支{r_train['profit']:+,}")
print(f"検証期間: {r_test['n']}R  ROI {r_test['roi']:.1f}%  収支{r_test['profit']:+,}")

# Compare with current PL model
print("\n=== 比較: 現行PLモデル (同一データ) ===")

# Run current PL model for comparison
def run_pl_backtest(races):
    total_inv=total_ret=total_n=total_hits=0
    for race in races:
        ps = race["players"]; bp_d = race["bp_d"]; od = race["odds_dict"]
        # Current scoring
        for n, p in ps.items():
            li = next((l for l in race["lines"] if n in l["members"]), None)
            pos = p["pos"]; pos_b = 0.5 if pos==1 else -0.3*(pos-1)
            bsf = (bp_d["sashi"]-1.0)*p["ep"]+(bp_d["makuri"]-1.0)*p["ip"]
            p["ev"] = (p["base"]*0.4+p["ip"]*1.5+p["ep"]*1.2
                       +p["dp"]*bp_d["makuri"]+p["bp"]*bp_d["sashi"]
                       +p["nb"]*2.0+pos_b
                       +(3.0 if p["is_m"] else 0)+bsf*2.0)
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
                if c not in od: continue
                o=od[c]
                if o<MIN_ODDS: continue
                cands.append((pl(axis,sn,tn),c))
        sel=sorted(cands,key=lambda x:x[0],reverse=True)[:7]
        bets=[c for _,c in sel]
        if not bets: continue
        inv=len(bets)*100; hit=race["actual"] in bets; ret=race["payout"] if hit else 0
        total_inv+=inv;total_ret+=ret;total_n+=1
        if hit: total_hits+=1
    roi=total_ret/total_inv*100 if total_inv else 0
    return {"n":total_n,"hits":total_hits,"invest":total_inv,"ret":total_ret,
            "roi":roi,"profit":total_ret-total_inv}

rp_all = run_pl_backtest(all_races)
rp_test = run_pl_backtest(test)
print(f"PL全期間: {rp_all['n']}R  的中{rp_all['hits']}({rp_all['hits']/rp_all['n']*100:.1f}%)  "
      f"ROI {rp_all['roi']:.1f}%  収支{rp_all['profit']:+,}")
print(f"PL検証:   {rp_test['n']}R  ROI {rp_test['roi']:.1f}%  収支{rp_test['profit']:+,}")

print("\n=== まとめ ===")
print(f"  {'モデル':>15s}  {'全体ROI':>8s}  {'全体収支':>10s}  {'検証ROI':>8s}  {'検証収支':>10s}")
print(f"  {'展開シミュ':>15s}  {r_all['roi']:7.1f}%  {r_all['profit']:>+10,}  {r_test['roi']:7.1f}%  {r_test['profit']:>+10,}")
print(f"  {'現行PL':>15s}  {rp_all['roi']:7.1f}%  {rp_all['profit']:>+10,}  {rp_test['roi']:7.1f}%  {rp_test['profit']:>+10,}")
