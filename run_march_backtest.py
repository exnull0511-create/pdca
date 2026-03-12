"""
run_march_backtest.py
=====================
3月分（racecard_march.xlsx / odds_march.xlsx / payouts_march.xlsx）を使って
現在の check_and_notify.py と同一ロジックでバックテストを実行する。

_verify_stats.py の S_MAXHIT_14_EV_LOOSE_B 設定をベースにしており、
バンクROI/カオスフィルタ/EV閾値も本番と同一。

使い方:
  python run_march_backtest.py
  python run_march_backtest.py --strategy CURRENT   # min_ev=60 版
  python run_march_backtest.py --no-bank-filter     # バンクフィルタなし
"""

import argparse
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from pathlib import Path

# ── ファイルパス ──────────────────────────────────────────────────────────────
RC_PATH  = Path("data/racecard_march.xlsx")
OD_PATH  = Path("data/odds_march.xlsx")
PY_PATH  = Path("data/payouts_march.xlsx")
OUT_CSV  = Path("data/backtest_march_result.csv")

DB_OLD   = "data/S級選手究極DB(1).xlsx"
DB_SLIM  = "data/S級DB_slim.xlsx"

# ── ストラテジー設定 ──────────────────────────────────────────────────────────
STRATEGY_CONFIGS = {
    # 本番採用設定（check_and_notify.py と同一: skip_chaos=True / min_ev=60）
    "CURRENT": {
        "name":             "[本番] skip_chaos=True / min_top_ev=60 / EV傾斜14点",
        "skip_chaos":       True,
        "min_top_ev":       60,
        "require_monster":  False,
        "skip_low_bank":    True,
        "top_n_prob_bets":  14,
        "bet_base":         100,
    },
    # 過去バックテスト最良設定（LOOSE-B）
    "LOOSE_B": {
        "name":             "[LOOSE-B] skip_chaos=True / min_top_ev=70 / EV傾斜14点",
        "skip_chaos":       True,
        "min_top_ev":       70,
        "require_monster":  False,
        "skip_low_bank":    True,
        "top_n_prob_bets":  14,
        "bet_base":         100,
    },
    # LOOSE-A（EV75）
    "LOOSE_A": {
        "name":             "[LOOSE-A] skip_chaos=True / min_top_ev=75 / EV傾斜14点",
        "skip_chaos":       True,
        "min_top_ev":       75,
        "require_monster":  False,
        "skip_low_bank":    True,
        "top_n_prob_bets":  14,
        "bet_base":         100,
    },
}

BANK_DICT = {
    "前橋":   {"roi_tier": "mid",  "sashi": 0.8, "makuri": 1.2},
    "宇都宮": {"roi_tier": "high", "sashi": 1.5, "makuri": 1.1},
    "豊橋":   {"roi_tier": "high", "sashi": 1.3, "makuri": 1.2},
    "岸和田": {"roi_tier": "low",  "sashi": 1.1, "makuri": 1.3},
    "熊本":   {"roi_tier": "high", "sashi": 1.2, "makuri": 1.1},
    "いわき平": {"roi_tier": "mid","sashi": 0.9, "makuri": 1.3},
    "広島":   {"roi_tier": "mid",  "sashi": 1.2, "makuri": 1.0},
    "別府":   {"roi_tier": "mid",  "sashi": 1.1, "makuri": 1.1},
    "松山":   {"roi_tier": "mid",  "sashi": 1.0, "makuri": 1.2},
    "小倉":   {"roi_tier": "low",  "sashi": 1.1, "makuri": 1.1},
    "京王閣": {"roi_tier": "high", "sashi": 1.0, "makuri": 1.1},
    "立川":   {"roi_tier": "high", "sashi": 1.1, "makuri": 1.0},
    "取手":   {"roi_tier": "mid",  "sashi": 1.1, "makuri": 1.1},
    "伊東":   {"roi_tier": "mid",  "sashi": 1.0, "makuri": 1.2},
    "久留米": {"roi_tier": "low",  "sashi": 1.1, "makuri": 1.1},
    "奈良":   {"roi_tier": "low",  "sashi": 1.2, "makuri": 1.0},
    "岐阜":   {"roi_tier": "low",  "sashi": 1.1, "makuri": 1.1},
    "小松島": {"roi_tier": "low",  "sashi": 1.1, "makuri": 1.0},
    "防府":   {"roi_tier": "low",  "sashi": 1.1, "makuri": 1.1},
    "静岡":   {"roi_tier": "low",  "sashi": 1.2, "makuri": 1.0},
    "松阪":   {"roi_tier": "mid",  "sashi": 1.1, "makuri": 1.1},
    "高知":   {"roi_tier": "mid",  "sashi": 1.0, "makuri": 1.2},
    "松戸":   {"roi_tier": "mid",  "sashi": 1.1, "makuri": 1.0},
    "平塚":   {"roi_tier": "mid",  "sashi": 1.2, "makuri": 1.1},
    "西武園": {"roi_tier": "mid",  "sashi": 1.0, "makuri": 1.1},
    "大垣":   {"roi_tier": "mid",  "sashi": 1.1, "makuri": 1.1},
    "名古屋": {"roi_tier": "mid",  "sashi": 1.0, "makuri": 1.1},
}

SENPO_LEAD = {
    "逃げ切り": 5, "逃げ粘り": 4, "突っ張り先行": 4, "抑え先行": 4,
    "カマシ先行": 5, "先行逃げ切り": 5, "先行": 4, "逃げ": 5,
    "先行争い敗北": 3, "一発捲り": 3, "ロング捲り": 3, "捲り": 3,
    "番手捲り": 3, "カマシ捲り": 4, "捲り差し": 3, "捲り不発": 2,
    "番手差し": 2, "差し": 2, "追い込み": 2, "流れ込み": 1, "追走": 1, "マーク": 1,
}


def norm(s): return str(s).replace(" ", "").replace("\u3000", "").strip()

def nobi_score(v):
    s = str(v).strip().upper()
    if s.startswith("S"): return 5
    elif s.startswith("A"): return 4
    elif s.startswith("B"): return 3
    elif s.startswith("C"): return 1
    return 2

def senpo_lead(v): return SENPO_LEAD.get(str(v).strip(), 1)


def load_db():
    """選手過去成績DBをロード（_verify_stats.py と同一）"""
    db_slim = pd.DataFrame()
    db_all  = pd.DataFrame()
    nobi_col = "直線の伸び"

    try:
        sl = pd.ExcelFile(DB_SLIM)
        dfs = [sl.parse(s) for s in ["F1", "G3~1"] if s in sl.sheet_names]
        if dfs:
            db_slim = pd.concat(dfs, ignore_index=True)
            db_slim["開催日"] = pd.to_datetime(db_slim["開催日"], errors="coerce")
            for c in ["IP", "EP", "DP", "BP"]:
                if c in db_slim.columns:
                    db_slim[c] = pd.to_numeric(db_slim[c], errors="coerce")
            db_slim["選手名_norm"] = db_slim["選手名"].apply(norm)
    except Exception as e:
        print(f"slimDB失敗: {e}")

    try:
        xl = pd.ExcelFile(DB_OLD)
        dfs = [xl.parse(s) for s in ["F1", "G3~1"] if s in xl.sheet_names]
        if dfs:
            db_all = pd.concat(dfs, ignore_index=True)
            db_all["開催日"] = pd.to_datetime(db_all["開催日"], errors="coerce")
            for c in ["IP", "EP", "DP", "BP"]:
                db_all[c] = pd.to_numeric(db_all[c], errors="coerce")
            db_all["選手名_norm"] = db_all["選手名"].apply(norm)
            nb_cols = [c for c in db_all.columns if "直線" in c]
            if nb_cols:
                nobi_col = nb_cols[0]
    except Exception as e:
        print(f"oldDB失敗: {e}")

    print(f"slimDB:{len(db_slim)}件  oldDB:{len(db_all)}件  伸び列:{nobi_col}")
    return db_slim, db_all, nobi_col


def analyze_race(race_id, venue, race_dt, race_info, odds_dict,
                 db_slim, db_all, nobi_col, cfg):
    """
    check_and_notify.py の run_prediction() と完全同一ロジック。
    """
    bp = BANK_DICT.get(venue, {"roi_tier": "mid", "sashi": 1.0, "makuri": 1.0})

    # ライン辞書構築
    line_map    = {}
    num_to_line = {}
    for _, row in race_info.iterrows():
        try:
            lno = int(row.get("line_no", 0) or 0)
            num = int(row["車番"])
        except Exception:
            continue
        bibs_str = str(row.get("line_bibs", str(num)))
        if lno not in line_map:
            try:
                bibs_list = [int(b) for b in bibs_str.split("-") if b.isdigit()]
            except Exception:
                bibs_list = [num]
            line_map[lno] = bibs_list
        num_to_line[num] = lno

    past_slim = db_slim[db_slim["開催日"] < race_dt] if not db_slim.empty else db_slim
    past_all  = db_all[db_all["開催日"]  < race_dt] if not db_all.empty  else db_all

    player_scores = {}
    for _, row in race_info.iterrows():
        try:
            num  = int(row["車番"])
            nm   = norm(str(row.get("選手名", "")))
            base = float(row.get("競走得点", 80) or 80)
        except Exception:
            continue

        hist      = past_slim[past_slim["選手名_norm"] == nm] if not past_slim.empty else pd.DataFrame()
        use_slim  = not hist.empty
        if hist.empty:
            hist = past_all[past_all["選手名_norm"] == nm] if not past_all.empty else pd.DataFrame()

        ip = ep = 4.0; dp = bp_v = 3.0; nb = sp = 2.0; is_m = is_u = False
        if not hist.empty:
            RECENT_W = 3.0
            sd = sorted(hist["開催日"].dropna().unique(), reverse=True)
            rd = set(sd[:2])
            def wm(series):
                v = pd.to_numeric(series, errors="coerce")
                w = np.where(hist["開催日"].isin(rd), RECENT_W, 1.0)
                mk = v.notna()
                return float((v[mk] * w[mk]).sum() / w[mk].sum()) if mk.any() else None

            ip   = wm(hist["IP"])   or 4.0
            ep   = wm(hist["EP"])   or 4.0
            dp   = wm(hist["DP"])   or 3.0
            bp_v = wm(hist["BP"])   or 3.0
            if use_slim and "直線の伸び" in hist.columns:
                nb = wm(hist["直線の伸び"].apply(nobi_score)) or 2.0
            elif nobi_col in hist.columns:
                nb = wm(hist[nobi_col].apply(nobi_score)) or 2.0
            if "戦法" in hist.columns:
                sp = wm(hist["戦法"].apply(senpo_lead)) or 2.0
            if use_slim:
                is_m = bool(hist.get("is_monster",   pd.Series([0])).max() >= 1)
                is_u = bool(hist.get("is_unreliable", pd.Series([0])).max() >= 1)
            else:
                cmt = " ".join(hist.get("解析コメント", pd.Series([""])).astype(str))
                is_m = any(k in cmt for k in ["脚余し", "鬼脚", "別次元", "圧倒"])
                is_u = any(k in cmt for k in ["共倒れ", "位置取り失敗", "不発", "失速"])

        lno   = num_to_line.get(num, 0)
        lbs   = line_map.get(lno, [])
        pos   = lbs.index(num) + 1 if num in lbs else 1
        pos_b = 0.5 if pos == 1 else -0.3 * (pos - 1)

        ev = (base * 0.4 + ip * 1.5 + ep * 1.2 + dp * bp["makuri"] + bp_v * bp["sashi"]
              + nb * 2.0 + sp * 0.5 + pos_b + (3.0 if is_m else 0) - (2.0 if is_u else 0))
        player_scores[num] = {"name": str(row.get("選手名", "")), "ev": ev,
                               "ip": ip, "is_monster": is_m, "pos_in_line": pos}

    ranked = sorted(player_scores.items(), key=lambda x: x[1]["ev"], reverse=True)
    if len(ranked) < 3:
        return None, "選手不足"

    strong_leaders = [n for n, d in player_scores.items()
                      if d["ip"] >= 5.5 and d["pos_in_line"] == 1]
    is_chaos = len(strong_leaders) >= 2
    top_ev   = ranked[0][1]["ev"]

    if top_ev < cfg["min_top_ev"]:
        return None, f"EV不足({top_ev:.1f})"
    if is_chaos and cfg["skip_chaos"]:
        return None, f"カオス(先行×{len(strong_leaders)})"

    all_nums = [n for n, _ in ranked]
    max_e    = ranked[0][1]["ev"]
    raw_s    = {n: np.exp(player_scores[n]["ev"] - max_e) for n in all_nums}

    def pl(f, s, t):
        d1 = sum(raw_s[n] for n in all_nums)
        d2 = sum(raw_s[n] for n in all_nums if n != f)
        d3 = sum(raw_s[n] for n in all_nums if n not in (f, s))
        return 0.0 if 0 in (d1, d2, d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)

    axis_num = next((n for n, d in ranked if d["is_monster"]), ranked[0][0])
    others   = [n for n, _ in ranked if n != axis_num]

    ev_bets = sorted(
        [(pl(axis_num, s, t) * odds_dict.get(f"{axis_num}-{s}-{t}", 0),
          f"{axis_num}-{s}-{t}", pl(axis_num, s, t), odds_dict.get(f"{axis_num}-{s}-{t}", 0))
         for s in others for t in others if s != t and f"{axis_num}-{s}-{t}" in odds_dict],
        key=lambda x: x[2], reverse=True
    )
    bets = [c for _, c, _, _ in ev_bets[:cfg["top_n_prob_bets"]]]
    if not bets:
        return None, "買い目なし"

    ev_lookup = {c: ev for ev, c, p, o in sorted(ev_bets, key=lambda x: x[0], reverse=True)}
    bet_ev    = [(c, ev_lookup.get(c, 0.0)) for c in bets]
    ev_vals   = np.array([max(e, 0.0) for _, e in bet_ev])
    bet_base  = cfg["bet_base"]
    total_p   = bet_base * len(bets)
    if ev_vals.sum() == 0:
        alloc = [bet_base] * len(bets)
    else:
        a     = (ev_vals / ev_vals.sum()) * total_p
        a100  = (a // 100).astype(int) * 100
        a100[int(np.argmax(ev_vals))] += (int(total_p - a100.sum()) // 100) * 100
        alloc = [max(int(x), 100) for x in a100]

    return {
        "axis":       axis_num,
        "axis_name":  player_scores[axis_num]["name"],
        "axis_ev":    player_scores[axis_num]["ev"],
        "top_ev":     top_ev,
        "bets":       list(zip(bets, alloc)),
        "total":      sum(alloc),
        "is_chaos":   is_chaos,
    }, None


def run_backtest(strategy: str, use_bank_filter: bool):
    cfg = STRATEGY_CONFIGS[strategy]
    print(f"\n🎮 ストラテジー: {strategy} — {cfg['name']}")
    print(f"   バンクフィルタ: {'有効' if use_bank_filter else '無効'}")

    # データロード
    for path in [RC_PATH, OD_PATH, PY_PATH]:
        if not path.exists():
            print(f"❌ {path} が見つかりません。先に collect_march_data.py を実行してください。")
            return

    rc_df = pd.read_excel(RC_PATH, dtype={"race_id": str})
    od_df = pd.read_excel(OD_PATH, dtype={"race_id": str})
    py_df = pd.read_excel(PY_PATH, dtype={"race_id": str})

    # 型整備
    rc_df["date"] = pd.to_datetime(rc_df["date"].astype(str), format="%Y%m%d", errors="coerce")
    od_df["オッズ"] = pd.to_numeric(od_df["オッズ"], errors="coerce")
    py_df["payout_trifecta"] = pd.to_numeric(py_df["payout_trifecta"], errors="coerce")
    py_df["result_trifecta"] = py_df["result_trifecta"].astype(str).str.strip()

    db_slim, db_all, nobi_col = load_db()

    dates = sorted(rc_df["date"].dropna().unique())
    print(f"\n📅 バックテスト期間: {dates[0].date()} 〜 {dates[-1].date()}  ({len(dates)}日間)")

    results  = []
    skipped  = []
    total_invest = total_return = hit_count = bet_races = 0

    for race_date in dates:
        past_slim = db_slim[db_slim["開催日"] < race_date] if not db_slim.empty else db_slim
        past_all  = db_all[db_all["開催日"]  < race_date] if not db_all.empty  else db_all
        # ※ analyze_race内部で改めてフィルタするが、DBはここで渡す
        daily_rc  = rc_df[rc_df["date"] == race_date]

        for race_id in daily_rc["race_id"].unique():
            race_info = daily_rc[daily_rc["race_id"] == race_id].copy()
            if race_info.empty:
                continue

            venue = race_info.iloc[0]["venue"]

            # バンクROIフィルタ
            if use_bank_filter and cfg.get("skip_low_bank", True):
                bp = BANK_DICT.get(venue, {"roi_tier": "mid"})
                if bp.get("roi_tier") == "low":
                    skipped.append({"reason": "低bankスキップ", "venue": venue})
                    continue

            # オッズ辞書
            od_race   = od_df[od_df["race_id"] == race_id]
            odds_dict = {str(r["組み合わせ"]).strip(): float(r["オッズ"])
                         for _, r in od_race.iterrows() if pd.notna(r["オッズ"])}

            pred, reason = analyze_race(
                race_id, venue, race_date, race_info, odds_dict,
                db_slim, db_all, nobi_col, cfg
            )

            if pred is None:
                skipped.append({"reason": reason, "venue": venue})
                continue

            # 払戻取得
            py_race = py_df[py_df["race_id"] == race_id]
            if py_race.empty:
                skipped.append({"reason": "払戻データなし", "venue": venue})
                continue

            actual  = str(py_race.iloc[0]["result_trifecta"]).strip()
            payout  = py_race.iloc[0]["payout_trifecta"]
            try:
                payout = int(float(str(payout).replace(",", "")))
            except Exception:
                payout = 0

            if not actual or actual in ("nan", ""):
                skipped.append({"reason": "結果未確定", "venue": venue})
                continue

            # 的中判定
            bet_combos = [c for c, _ in pred["bets"]]
            bet_amts   = {c: a for c, a in pred["bets"]}
            hit        = actual in bet_combos
            bet_amt    = bet_amts.get(actual, 0) if hit else 0
            ret        = int(payout * bet_amt / 100) if hit else 0
            invest     = pred["total"]

            bet_races    += 1
            total_invest += invest
            total_return += ret
            if hit:
                hit_count += 1

            status = "✅ 的中" if hit else "❌ 外れ"
            print(f"  {str(race_date.date())} {venue:6s} {int(race_info.iloc[0]['race_no']):>2d}R"
                  f"  軸:{pred['axis']}({pred['axis_ev']:.1f})"
                  f"  topEV:{pred['top_ev']:.1f}"
                  f"  {status}  {actual}({payout//10}倍)")

            results.append({
                "race_id":   race_id,
                "date":      str(race_date.date()),
                "venue":     venue,
                "race_no":   int(race_info.iloc[0]["race_no"]),
                "axis":      pred["axis"],
                "axis_name": pred["axis_name"],
                "axis_ev":   round(pred["axis_ev"], 1),
                "top_ev":    round(pred["top_ev"], 1),
                "invest":    invest,
                "return":    ret,
                "payout_100": payout,
                "hit":       hit,
                "actual":    actual,
                "bets":      ",".join(bet_combos[:7]),
            })

    # ── サマリー ──────────────────────────────────────────────────────────────
    roi      = total_return  / total_invest * 100  if total_invest > 0  else 0
    hit_rate = hit_count     / bet_races     * 100  if bet_races    > 0  else 0
    profit   = total_return  - total_invest

    skip_reasons = {}
    for s in skipped:
        skip_reasons[s["reason"]] = skip_reasons.get(s["reason"], 0) + 1

    print(f"\n{'='*60}")
    print(f"🏁 【3月バックテスト結果】 {strategy}")
    print(f"   {cfg['name']}")
    print(f"{'='*60}")
    print(f"  全レース数     : {bet_races + len(skipped):>5} R")
    print(f"  スキップ       : {len(skipped):>5} R  {dict(sorted(skip_reasons.items()))}")
    print(f"  ─────────────────────────────────────────────────────")
    print(f"  買い判定       : {bet_races:>5} R")
    print(f"  的中           : {hit_count:>5} R  ({hit_rate:.1f}%)")
    print(f"  ─────────────────────────────────────────────────────")
    print(f"  投資           : ¥{total_invest:>10,}")
    print(f"  払戻           : ¥{total_return:>10,}")
    print(f"  収支           : {'+'if profit>=0 else ''}¥{profit:>8,}")
    print(f"  ROI            : {roi:>7.1f}%")
    print(f"{'='*60}")

    # CSV保存
    if results:
        df_res = pd.DataFrame(results)
        out_path = Path(f"data/backtest_march_{strategy.lower()}.csv")
        df_res.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"\n  → {out_path} 保存完了")


def main():
    parser = argparse.ArgumentParser(description="3月分バックテスト実行")
    parser.add_argument("--strategy",       default="CURRENT",
                        choices=list(STRATEGY_CONFIGS.keys()),
                        help="バックテスト戦略")
    parser.add_argument("--no-bank-filter", action="store_true",
                        help="バンクROIフィルタを無効化")
    parser.add_argument("--all-strategies", action="store_true",
                        help="全戦略を一括実行")
    args = parser.parse_args()

    if args.all_strategies:
        for s in STRATEGY_CONFIGS:
            run_backtest(s, not args.no_bank_filter)
    else:
        run_backtest(args.strategy, not args.no_bank_filter)


if __name__ == "__main__":
    main()
