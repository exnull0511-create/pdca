"""スコアウェイト最適化: 1700Rの実績から最適ウェイトを回帰で探索"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, sys
from collections import defaultdict
from scipy.optimize import minimize

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

# === Step 1: Collect per-player raw features for all races ===
print("Collecting player features...")
all_races = []  # [{race_id, venue, actual_1st, players: [{num, features...}]}]
rc = 0

for race_date in dates:
    daily_rc = RC[RC["date"] == race_date]
    for race_id in daily_rc["race_id"].unique():
        race_info = daily_rc[daily_rc["race_id"] == race_id].copy()
        if race_info.empty: continue
        venue = race_info.iloc[0]["venue"]
        bp = BANK_DICT.get(venue, {"roi_tier": "mid", "sashi": 1.0, "makuri": 1.0})

        py_race = PY[PY["race_id"] == race_id]
        if py_race.empty: continue
        actual = str(py_race.iloc[0]["result_trifecta"]).strip()
        if not actual or actual == "nan": continue
        actual_parts = actual.split("-")
        if len(actual_parts) != 3: continue
        a1 = int(actual_parts[0])

        past_slim = db_slim[db_slim["開催日"] < race_date] if not db_slim.empty else db_slim
        past_all = db_all[db_all["開催日"] < race_date] if not db_all.empty else db_all

        line_map = {}; num_to_line = {}
        for _, row in race_info.iterrows():
            try:
                num = int(row["車番"]); lno = int(row.get("line_no", 0) or 0)
            except: continue
            bibs_str = str(row.get("line_bibs", str(num)))
            if lno not in line_map:
                try: bibs_list = [int(b) for b in bibs_str.split("-") if b.isdigit()]
                except: bibs_list = [num]
                line_map[lno] = bibs_list
            num_to_line[num] = lno

        players = []
        for _, row in race_info.iterrows():
            try:
                num = int(row["車番"])
                nm = rb.norm(str(row.get("選手名", "")))
                base = float(row.get("競走得点", 80) or 80)
            except: continue
            hist = past_slim[past_slim["選手名_norm"] == nm] if not past_slim.empty else pd.DataFrame()
            use_slim = not hist.empty
            if hist.empty:
                hist = past_all[past_all["選手名_norm"] == nm] if not past_all.empty else pd.DataFrame()
            ip = ep = 4.0; dp = bp_v = 3.0; nb = sp = 2.0; is_m = 0
            if not hist.empty:
                RECENT_W = 3.0
                sd = sorted(hist["開催日"].dropna().unique(), reverse=True); rd = set(sd[:2])
                def wm(series):
                    v = pd.to_numeric(series, errors="coerce")
                    w = np.where(hist["開催日"].isin(rd), RECENT_W, 1.0); mk = v.notna()
                    return float((v[mk] * w[mk]).sum() / w[mk].sum()) if mk.any() else None
                ip = wm(hist["IP"]) or 4.0; ep = wm(hist["EP"]) or 4.0
                dp = wm(hist["DP"]) or 3.0; bp_v = wm(hist["BP"]) or 3.0
                if use_slim and "直線の伸び" in hist.columns:
                    nb = wm(hist["直線の伸び"].apply(rb.nobi_score)) or 2.0
                elif nobi_col in hist.columns:
                    nb = wm(hist[nobi_col].apply(rb.nobi_score)) or 2.0
                if "戦法" in hist.columns:
                    sp = wm(hist["戦法"].apply(rb.senpo_lead)) or 2.0
                if use_slim:
                    is_m = 1 if hist.get("is_monster", pd.Series([0])).max() >= 1 else 0
                else:
                    cmt = " ".join(hist.get("解析コメント", pd.Series([""])).astype(str))
                    is_m = 1 if any(k in cmt for k in ["脚余し", "鬼脚", "別次元", "圧倒"]) else 0

            lno = num_to_line.get(num, 0); lbs = line_map.get(lno, [])
            pos = lbs.index(num) + 1 if num in lbs else 1
            pos_b = 0.5 if pos == 1 else -0.3 * (pos - 1)

            # DP/BP にバンク係数を掛けた値を特徴量にする
            dp_adj = dp * bp["makuri"]
            bp_adj = bp_v * bp["sashi"]

            players.append({
                "num": num,
                "base": base, "ip": ip, "ep": ep, "dp": dp_adj, "bp": bp_adj,
                "nb": nb, "sp": sp, "pos_b": pos_b, "is_m": is_m,
                "is_winner": 1 if num == a1 else 0,
            })

        if len(players) < 3: continue

        # Check top_ev with current weights
        current_w = [0.4, 1.5, 1.2, 1.0, 1.0, 2.0, 0.5, 1.0, 3.0]
        feats = ["base", "ip", "ep", "dp", "bp", "nb", "sp", "pos_b", "is_m"]
        top_ev = max(sum(p[f] * w for f, w in zip(feats, current_w)) for p in players)
        if top_ev < 67: continue

        all_races.append({"players": players, "a1": a1, "venue": venue,
                          "race_id": race_id, "date": str(race_date.date())})
        rc += 1
        if rc % 200 == 0:
            print(f"  ... {rc} races", file=sys.stderr)

print(f"Total races: {len(all_races)}")

# === Step 2: Define scoring function and optimize ===
FEATS = ["base", "ip", "ep", "dp", "bp", "nb", "sp", "pos_b", "is_m"]
N_FEATS = len(FEATS)

def compute_top1_accuracy(weights, races, min_ev=0):
    """Given weights, compute what % of races the top-scored player is the actual winner"""
    correct = 0; total = 0
    for race in races:
        scores = []
        for p in race["players"]:
            s = sum(p[f] * w for f, w in zip(FEATS, weights))
            scores.append((s, p["num"], p["is_winner"]))
        scores.sort(key=lambda x: x[0], reverse=True)
        if min_ev > 0 and scores[0][0] < min_ev:
            continue
        total += 1
        if scores[0][2] == 1:  # top scored player is winner
            correct += 1
    return correct / total if total > 0 else 0, total

def neg_accuracy(weights):
    """Negative accuracy for minimization"""
    acc, _ = compute_top1_accuracy(weights, all_races)
    return -acc

# Current weights
current_w = np.array([0.4, 1.5, 1.2, 1.0, 1.0, 2.0, 0.5, 1.0, 3.0])
current_acc, current_n = compute_top1_accuracy(current_w, all_races)
print(f"\n現行ウェイト: {dict(zip(FEATS, current_w))}")
print(f"  1着的中率: {current_acc*100:.2f}% ({int(current_acc*current_n)}/{current_n})")

# === Step 3: Grid search on individual weights ===
print("\n=== 個別ウェイト感度分析 ===")
for i, feat in enumerate(FEATS):
    best_v = current_w[i]; best_acc = current_acc
    for v in np.arange(0, 5.1, 0.25):
        w = current_w.copy()
        w[i] = v
        acc, _ = compute_top1_accuracy(w, all_races)
        if acc > best_acc:
            best_acc = acc; best_v = v
    improvement = (best_acc - current_acc) * 100
    print(f"  {feat:>6s}: 現行{current_w[i]:.1f} → 最適{best_v:.2f}  "
          f"的中率 {current_acc*100:.2f}% → {best_acc*100:.2f}% ({improvement:+.2f}%)")

# === Step 4: Full optimization with scipy ===
print("\n=== 全ウェイト同時最適化 (Nelder-Mead) ===")
result = minimize(neg_accuracy, current_w, method='Nelder-Mead',
                  options={'maxiter': 5000, 'xatol': 0.01, 'fatol': 0.0001})
opt_w = result.x
opt_acc, opt_n = compute_top1_accuracy(opt_w, all_races)
print(f"最適ウェイト:")
for f, cw, ow in zip(FEATS, current_w, opt_w):
    diff = ow - cw
    print(f"  {f:>6s}: {cw:.1f} → {ow:.2f} ({diff:+.2f})")
print(f"  1着的中率: {current_acc*100:.2f}% → {opt_acc*100:.2f}% ({(opt_acc-current_acc)*100:+.2f}%)")

# === Step 5: Cross-validation ===
print("\n=== クロスバリデーション (前半最適化→後半検証) ===")
all_dates = sorted(set(r["date"] for r in all_races))
mid = len(all_dates) // 2
train = [r for r in all_races if r["date"] <= all_dates[mid-1]]
test = [r for r in all_races if r["date"] > all_dates[mid-1]]
print(f"  学習: {len(train)}R  検証: {len(test)}R")

# Optimize on train
def neg_acc_train(weights):
    acc, _ = compute_top1_accuracy(weights, train)
    return -acc

res_cv = minimize(neg_acc_train, current_w, method='Nelder-Mead',
                  options={'maxiter': 5000, 'xatol': 0.01, 'fatol': 0.0001})
cv_w = res_cv.x

# Evaluate on test
train_acc_current, _ = compute_top1_accuracy(current_w, train)
train_acc_opt, _ = compute_top1_accuracy(cv_w, train)
test_acc_current, _ = compute_top1_accuracy(current_w, test)
test_acc_opt, _ = compute_top1_accuracy(cv_w, test)

print(f"  学習データ: 現行{train_acc_current*100:.2f}% → 最適{train_acc_opt*100:.2f}%")
print(f"  検証データ: 現行{test_acc_current*100:.2f}% → 最適{test_acc_opt*100:.2f}%")
print(f"  CV最適ウェイト:")
for f, cw, ow in zip(FEATS, current_w, cv_w):
    print(f"    {f:>6s}: {cw:.1f} → {ow:.2f}")

# === Step 6: 3-fold CV ===
print("\n=== 3分割クロスバリデーション ===")
folds = [[], [], []]
for i, d in enumerate(sorted(set(r["date"] for r in all_races))):
    for r in all_races:
        if r["date"] == d:
            folds[i % 3].append(r)

fold_results = []
for fi in range(3):
    test_fold = folds[fi]
    train_fold = [r for j in range(3) if j != fi for r in folds[j]]
    def neg_acc_f(w):
        a, _ = compute_top1_accuracy(w, train_fold)
        return -a
    res_f = minimize(neg_acc_f, current_w, method='Nelder-Mead',
                     options={'maxiter': 3000, 'xatol': 0.01, 'fatol': 0.0001})
    fw = res_f.x
    test_cur, _ = compute_top1_accuracy(current_w, test_fold)
    test_opt, _ = compute_top1_accuracy(fw, test_fold)
    fold_results.append((test_cur, test_opt, fw))
    print(f"  Fold{fi+1}: 現行{test_cur*100:.1f}% → 最適{test_opt*100:.1f}% ({(test_opt-test_cur)*100:+.1f}%)")

avg_cur = np.mean([f[0] for f in fold_results])
avg_opt = np.mean([f[1] for f in fold_results])
print(f"  平均: 現行{avg_cur*100:.1f}% → 最適{avg_opt*100:.1f}% ({(avg_opt-avg_cur)*100:+.1f}%)")

# Average optimized weights across folds
avg_w = np.mean([f[2] for f in fold_results], axis=0)
print(f"\n=== CV平均 最適ウェイト ===")
for f, cw, ow in zip(FEATS, current_w, avg_w):
    diff = ow - cw
    arrow = "↑" if diff > 0.1 else ("↓" if diff < -0.1 else "→")
    print(f"  {f:>6s}: {cw:.1f} → {ow:.2f} ({diff:+.2f}) {arrow}")
