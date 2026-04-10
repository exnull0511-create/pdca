"""鬼脚フラグ選手の3着以内入着率"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, sys
from collections import defaultdict

RC = pd.read_excel("data/racecard_hist.xlsx", dtype={"race_id": str})
PY = pd.read_excel("data/payouts_hist.xlsx", dtype={"race_id": str})
RC["date"] = pd.to_datetime(RC["date"].astype(str), format="%Y%m%d", errors="coerce")
PY["payout_trifecta"] = pd.to_numeric(PY["payout_trifecta"], errors="coerce")
PY["result_trifecta"] = PY["result_trifecta"].astype(str).str.strip()

import importlib.util
spec = importlib.util.spec_from_file_location("rb", "run_backtest.py")
rb = importlib.util.module_from_spec(spec); sys.modules["rb"] = rb; spec.loader.exec_module(rb)
db_slim, db_all, nobi_col = rb.load_db()

dates = sorted(RC["date"].dropna().unique())

# Build payout lookup: race_id → top3 set
py_lookup = {}
for _, row in PY.iterrows():
    rid = str(row["race_id"]).strip()
    actual = str(row["result_trifecta"]).strip()
    if not actual or actual == "nan": continue
    parts = actual.split("-")
    if len(parts) != 3: continue
    try:
        py_lookup[rid] = set(int(p) for p in parts)
    except:
        continue

print(f"Payout lookup: {len(py_lookup)} races", file=sys.stderr)

# For each rider in each race, check is_monster flag (from past data) and actual finish
total_oniashi_starts = 0
oniashi_top3 = 0
oniashi_1st = 0
oniashi_2nd = 0
oniashi_3rd = 0

# By month
by_month = defaultdict(lambda: {"starts": 0, "top3": 0, "wins": 0})
# By position in line
by_pos = defaultdict(lambda: {"starts": 0, "top3": 0})
# Non-oniashi for comparison
non_oniashi_starts = 0
non_oniashi_top3 = 0

print("Analyzing...", file=sys.stderr)
for race_date in dates:
    daily_rc = RC[RC["date"] == race_date]
    for race_id in daily_rc["race_id"].unique():
        race_info = daily_rc[daily_rc["race_id"] == race_id]
        if race_info.empty: continue
        if race_id not in py_lookup: continue
        top3_set = py_lookup[race_id]

        # past data (cumulative up to this race date - simulates actual production usage)
        past_slim = db_slim[db_slim["開催日"] < race_date] if not db_slim.empty else db_slim
        past_all = db_all[db_all["開催日"] < race_date] if not db_all.empty else db_all

        # Build line info for position lookup
        lines = {}
        for _, row in race_info.iterrows():
            try:
                num = int(row["車番"]); lno = int(row.get("line_no", 0) or 0)
            except: continue
            bs = str(row.get("line_bibs", str(num)))
            if lno not in lines:
                try: lines[lno] = [int(b) for b in bs.split("-") if b.isdigit()]
                except: lines[lno] = [num]

        for _, row in race_info.iterrows():
            try:
                num = int(row["車番"])
                nm = rb.norm(str(row.get("選手名", "")))
            except: continue

            # Check is_monster flag from past data
            hist = past_slim[past_slim["選手名_norm"] == nm] if not past_slim.empty else pd.DataFrame()
            use_slim = not hist.empty
            if hist.empty:
                hist = past_all[past_all["選手名_norm"] == nm] if not past_all.empty else pd.DataFrame()

            is_m = False
            if not hist.empty:
                if use_slim:
                    is_m = bool(hist.get("is_monster", pd.Series([0])).max() >= 1)
                else:
                    cmt = " ".join(hist.get("解析コメント", pd.Series([""])).astype(str))
                    is_m = any(k in cmt for k in ["脚余し", "鬼脚", "別次元", "圧倒"])

            in_top3 = num in top3_set

            # Find finishing position
            actual_pos = None
            if num in top3_set:
                # We need the order. Get from result string
                rid = str(row["race_id"]).strip()
                py_row = PY[PY["race_id"] == rid].iloc[0]
                parts = str(py_row["result_trifecta"]).strip().split("-")
                try:
                    nums = [int(p) for p in parts]
                    if num in nums:
                        actual_pos = nums.index(num) + 1
                except:
                    pass

            # Find line position
            lno = 0
            for ln, members in lines.items():
                if num in members:
                    lno = ln
                    break
            line_members = lines.get(lno, [num])
            pos_in_line = line_members.index(num) + 1 if num in line_members else 0

            if is_m:
                total_oniashi_starts += 1
                if in_top3:
                    oniashi_top3 += 1
                    if actual_pos == 1: oniashi_1st += 1
                    elif actual_pos == 2: oniashi_2nd += 1
                    elif actual_pos == 3: oniashi_3rd += 1
                # By month
                m = str(race_date)[:7]
                by_month[m]["starts"] += 1
                if in_top3: by_month[m]["top3"] += 1
                if actual_pos == 1: by_month[m]["wins"] += 1
                # By line position
                by_pos[pos_in_line]["starts"] += 1
                if in_top3: by_pos[pos_in_line]["top3"] += 1
            else:
                non_oniashi_starts += 1
                if in_top3:
                    non_oniashi_top3 += 1

print(f"\n{'='*70}")
print("=== 鬼脚フラグ選手の入着率 (1〜3月 全レース) ===")
print(f"{'='*70}")
print(f"\n鬼脚選手の出走数: {total_oniashi_starts:,}")
print(f"  3着以内入着: {oniashi_top3:,} ({oniashi_top3/total_oniashi_starts*100:.1f}%)")
print(f"    1着: {oniashi_1st} ({oniashi_1st/total_oniashi_starts*100:.1f}%)")
print(f"    2着: {oniashi_2nd} ({oniashi_2nd/total_oniashi_starts*100:.1f}%)")
print(f"    3着: {oniashi_3rd} ({oniashi_3rd/total_oniashi_starts*100:.1f}%)")
print()
print(f"非鬼脚選手の出走数: {non_oniashi_starts:,}")
print(f"  3着以内入着: {non_oniashi_top3:,} ({non_oniashi_top3/non_oniashi_starts*100:.1f}%)")
print()
print(f"差分: 鬼脚 {oniashi_top3/total_oniashi_starts*100:.1f}% vs 非鬼脚 {non_oniashi_top3/non_oniashi_starts*100:.1f}%")
print(f"      = 鬼脚は {oniashi_top3/total_oniashi_starts/(non_oniashi_top3/non_oniashi_starts):.2f}倍 入着しやすい")

print(f"\n{'='*70}")
print("=== 月別 ===")
print(f"{'='*70}")
print(f"{'月':>10s}  {'鬼脚出走':>8s}  {'3着内':>6s}  {'入着率':>6s}  {'1着':>4s}  {'勝率':>6s}")
for m in sorted(by_month):
    d = by_month[m]
    if d["starts"] == 0: continue
    rate = d["top3"]/d["starts"]*100
    win_rate = d["wins"]/d["starts"]*100
    print(f"  {m}  {d['starts']:8d}  {d['top3']:6d}  {rate:5.1f}%  {d['wins']:4d}  {win_rate:5.1f}%")

print(f"\n{'='*70}")
print("=== ライン位置別 ===")
print(f"{'='*70}")
print(f"{'位置':>6s}  {'出走数':>6s}  {'3着内':>6s}  {'入着率':>6s}")
for p in sorted(by_pos):
    d = by_pos[p]
    if d["starts"] == 0: continue
    label = f"{p}番手" if p > 0 else "単騎"
    print(f"  {label:>6s}  {d['starts']:6d}  {d['top3']:6d}  {d['top3']/d['starts']*100:5.1f}%")
