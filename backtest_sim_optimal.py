"""
backtest_sim_optimal.py
=======================
シミュレーションモデル専用に最適化されたルック条件でのバックテスト。
【最適化条件】
1. TopEV < 70 のレースはルック
2. バンク特性が 'mid' のレースはルック
3. 単騎選手が 4人以上 いるレースはルック
※ カオス除外や鬼脚必須の条件は撤廃。EV配分を使用。
"""

import pandas as pd
import numpy as np
import warnings
from pathlib import Path
import simulation_model
import time

warnings.filterwarnings('ignore')

NUM_SIMULATIONS = 2000
BET_BASE = 100
TOP_N_BETS = 14

BANK_DICT = {
    '前橋':   {'roi_tier': 'mid'},   '宇都宮': {'roi_tier': 'high'},
    '豊橋':   {'roi_tier': 'high'},  '岸和田': {'roi_tier': 'low'},
    '熊本':   {'roi_tier': 'high'},  'いわき平':{'roi_tier': 'mid'},
    '広島':   {'roi_tier': 'mid'},   '別府':   {'roi_tier': 'mid'},
    '松山':   {'roi_tier': 'mid'},   '小倉':   {'roi_tier': 'low'},
    '京王閣': {'roi_tier': 'high'},  '立川':   {'roi_tier': 'high'},
    '取手':   {'roi_tier': 'mid'},   '伊東':   {'roi_tier': 'mid'},
    '久留米': {'roi_tier': 'low'},   '奈良':   {'roi_tier': 'low'},
    '岐阜':   {'roi_tier': 'low'},   '小松島': {'roi_tier': 'low'},
    '防府':   {'roi_tier': 'low'},   '静岡':   {'roi_tier': 'low'},
    '松阪':   {'roi_tier': 'mid'},   '高知':   {'roi_tier': 'mid'},
    '松戸':   {'roi_tier': 'mid'},   '平塚':   {'roi_tier': 'mid'},
    '西武園': {'roi_tier': 'mid'},   '大垣':   {'roi_tier': 'mid'},
    '名古屋': {'roi_tier': 'mid'},
}

def normalize_name(s): return str(s).replace(" ", "").replace("\u3000", "").strip()
def nobi_score(val):
    s = str(val).strip().upper()
    if s.startswith('S'): return 5
    elif s.startswith('A'): return 4
    elif s.startswith('B'): return 3
    elif s.startswith('C'): return 1
    return 2

def senpo_lead(val):
    d = {'逃げ切り':5, 'カマシ先行':5, '先行逃げ切り':5, '逃げ':5,
         '逃げ粘り':4, '突っ張り先行':4, '抑え先行':4, '先行':4, 'カマシ捲り':4,
         '先行争い敗北':3, '一発捲り':3, 'ロング捲り':3, '捲り':3, '番手捲り':3, '捲り差し':3,
         '捲り不発':2, '番手差し':2, '差し':2, '追い込み':2,
         '流れ込み':1, '追走':1, 'マーク':1}
    return d.get(str(val).strip(), 1)

def build_race_data_for_sim(race_info, past_db, past_slim, nobi_col):
    line_map = {}
    for _, row in race_info.iterrows():
        try:
            lno = int(row.get('line_no', 0) or 0)
            num = int(row['車番'])
        except: continue
        bibs_str = str(row.get('line_bibs', str(num)))
        if lno not in line_map:
            try: line_map[lno] = [int(b) for b in bibs_str.split('-') if b.isdigit()]
            except: line_map[lno] = [num]

    player_scores = {}
    for _, row in race_info.iterrows():
        try:
            num = int(row['車番'])
            nm = normalize_name(str(row.get('選手名', '')))
            base = float(row.get('競走得点', 80) or 80)
        except: continue

        hist = past_slim[past_slim['選手名_norm'] == nm] if not past_slim.empty else pd.DataFrame()
        use_slim = not hist.empty
        if hist.empty:
            hist = past_db[past_db['選手名_norm'] == nm] if not past_db.empty else pd.DataFrame()

        ip = ep = 4.0; dp = bp = 3.0; nb = sp = 2.0; is_monster = False

        if not hist.empty:
            def safe_mean(colname, default):
                if colname not in hist.columns: return default
                val = pd.to_numeric(hist[colname], errors='coerce').mean()
                return val if not pd.isna(val) else default
                
            ip = safe_mean('IP', 4.0)
            ep = safe_mean('EP', 4.0)
            dp = safe_mean('DP', 3.0)
            bp = safe_mean('BP', 3.0)
            
            if use_slim and "直線の伸び" in hist.columns:
                nb = hist["直線の伸び"].apply(nobi_score).mean() or 2.0
            elif nobi_col in hist.columns:
                nb = hist[nobi_col].apply(nobi_score).mean() or 2.0
                
            if "戦法" in hist.columns:
                sp = hist["戦法"].apply(senpo_lead).mean() or 2.0
                
            if use_slim and "is_monster" in hist.columns:
                is_monster = bool(hist["is_monster"].max() >= 1)
            else:
                cmt = " ".join(hist.get("解析コメント", pd.Series([""])).astype(str))
                is_monster = any(k in cmt for k in ["脚余し", "鬼脚", "別次元", "圧倒"])

        lno = next((k for k,v in line_map.items() if num in v), 0)
        lbs = line_map.get(lno, [])
        pos = lbs.index(num) + 1 if num in lbs else 1
        pos_b = 0.5 if pos == 1 else -0.3 * (pos - 1)
        ev = (base * 0.4 + ip * 1.5 + ep * 1.2 + dp * 1.0 + bp * 1.0 + nb * 2.0 + sp * 0.5 + pos_b + (3.0 if is_monster else 0))

        player_scores[num] = {
            'name': nm, 'ev_score': ev,
            'ip': ip, 'ep': ep, 'dp': dp, 'bp': bp,
            'style': str(row.get('脚質', '')),
            'nobi': nb, 'senpo': sp,
            'is_monster': is_monster, 'pos_in_line': pos
        }

    return player_scores, line_map

def ev_alloc(bet_ev_list, bet_base):
    n_bets = len(bet_ev_list)
    total_pool = bet_base * n_bets
    ev_vals = np.array([max(item['ev'], 0.0) for item in bet_ev_list])
    if ev_vals.sum() == 0:
        return [bet_base] * n_bets
    raw_alloc = (ev_vals / ev_vals.sum()) * total_pool
    alloc_100 = (raw_alloc // 100).astype(int) * 100
    remainder = int(total_pool - alloc_100.sum()); remainder = (remainder // 100) * 100
    alloc_100[int(np.argmax(ev_vals))] += remainder
    return [max(int(a), 100) for a in alloc_100]

def main():
    print("🚀 最適化ルック条件でのバックテスト（2月・3月）開始...")
    
    rc_paths = [Path("data/racecard.xlsx"), Path("data/racecard_march.xlsx")]
    od_paths = [Path("data/odds.xlsx"), Path("data/odds_march.xlsx")]
    py_paths = [Path("data/payouts.xlsx"), Path("data/payouts_march.xlsx")]
    
    rc_dfs, od_dfs, py_dfs = [], [], []
    for p in rc_paths:
        if p.exists(): rc_dfs.append(pd.read_excel(p, dtype={'race_id': str}))
    for p in od_paths:
        if p.exists(): od_dfs.append(pd.read_excel(p, dtype={'race_id': str}))
    for p in py_paths:
        if p.exists(): py_dfs.append(pd.read_excel(p, dtype={'race_id': str}))
        
    rc_df = pd.concat(rc_dfs, ignore_index=True).drop_duplicates(subset=['race_id', '車番'])
    od_df = pd.concat(od_dfs, ignore_index=True).drop_duplicates(subset=['race_id', '組み合わせ'])
    py_df = pd.concat(py_dfs, ignore_index=True).drop_duplicates(subset=['race_id'])
    
    rc_df['date'] = pd.to_datetime(rc_df['date'].astype(str), format='%Y%m%d', errors='coerce')
    rc_df = rc_df[rc_df['date'] >= pd.Timestamp('2026-02-01')]
    
    for df in [rc_df, od_df, py_df]:
        df['race_id'] = df['race_id'].apply(lambda v: str(v)[2:-1] if str(v).startswith('="') else str(v))
        
    od_df['オッズ'] = pd.to_numeric(od_df['オッズ'], errors='coerce')
    py_df['payout_trifecta'] = pd.to_numeric(py_df['payout_trifecta'], errors='coerce')
    py_df['result_trifecta'] = py_df['result_trifecta'].astype(str).apply(
        lambda v: v[2:-1] if v.startswith('="') else v.strip()
    )
    
    db_slim = pd.DataFrame(); db_all = pd.DataFrame(); nobi_col = "直線の伸び"
    if Path("data/S級DB_slim.xlsx").exists():
        xl = pd.ExcelFile("data/S級DB_slim.xlsx")
        dfs = [xl.parse(s) for s in ["F1", "G3~1"] if s in xl.sheet_names]
        if dfs:
            db_slim = pd.concat(dfs, ignore_index=True)
            db_slim["開催日"] = pd.to_datetime(db_slim["開催日"], errors="coerce")
            db_slim["選手名_norm"] = db_slim["選手名"].apply(normalize_name)
    if Path("data/S級選手究極DB(1).xlsx").exists():
        xl = pd.ExcelFile("data/S級選手究極DB(1).xlsx")
        dfs = [xl.parse(s) for s in ["F1", "G3~1"] if s in xl.sheet_names]
        if dfs:
            db_all = pd.concat(dfs, ignore_index=True)
            db_all["開催日"] = pd.to_datetime(db_all["開催日"], errors="coerce")
            db_all["選手名_norm"] = db_all["選手名"].apply(normalize_name)
            nb_cols = [c for c in db_all.columns if "直線" in c]
            if nb_cols: nobi_col = nb_cols[0]

    dates = sorted(rc_df["date"].dropna().unique())
    
    results = []
    skipped = {'low_ev': 0, 'mid_bank': 0, 'many_tanqi': 0, 'no_data': 0}
    total_invest, total_return, hit_count, bet_races = 0, 0, 0, 0
    start_time = time.time()
    
    for race_date in dates:
        past_slim = db_slim[db_slim["開催日"] < race_date] if not db_slim.empty else db_slim
        past_all  = db_all[db_all["開催日"]  < race_date] if not db_all.empty  else db_all
        daily_rc  = rc_df[rc_df["date"] == race_date]
        
        for race_id in daily_rc['race_id'].unique():
            race_info = daily_rc[daily_rc['race_id'] == race_id].copy()
            if race_info.empty: continue
            
            venue = race_info.iloc[0]['venue']
            
            # 【最適化フィルタ1】 バンク特性が mid の場合はルック
            if BANK_DICT.get(venue, {}).get('roi_tier') == 'mid':
                skipped['mid_bank'] += 1
                continue

            od_race = od_df[od_df['race_id'] == race_id]
            odds_dict = {str(r['組み合わせ']).strip(): float(r['オッズ']) 
                         for _, r in od_race.iterrows() if pd.notna(r['オッズ'])}
            py_race = py_df[py_df['race_id'] == race_id]
            
            if py_race.empty or not odds_dict:
                skipped['no_data'] += 1; continue
                
            actual = str(py_race.iloc[0]["result_trifecta"]).strip()
            payout = py_race.iloc[0]["payout_trifecta"]
            if not actual or actual == "nan":
                skipped['no_data'] += 1; continue
            try: payout = int(float(str(payout).replace(",", "")))
            except: payout = 0

            player_scores, line_map = build_race_data_for_sim(race_info, past_all, past_slim, nobi_col)
            if not player_scores:
                skipped['no_data'] += 1; continue
                
            # 【最適化フィルタ2】 TopEV < 70 の場合はルック
            top_ev = max(sc['ev_score'] for sc in player_scores.values())
            if top_ev < 70:
                skipped['low_ev'] += 1
                continue
                
            # 【最適化フィルタ3】 単騎が4人以上いる場合はルック
            num_tanqi = sum(1 for lst in line_map.values() if len(lst) == 1)
            if num_tanqi >= 4:
                skipped['many_tanqi'] += 1
                continue
                
            # シミュレーション実行
            race = simulation_model.build_race_from_system_data(player_scores, line_map)
            probs = simulation_model.simulate_race_n_times(race, num_simulations=NUM_SIMULATIONS)
            
            ev_list = simulation_model.calculate_expected_value(probs, odds_dict, top_n=TOP_N_BETS)
            if not ev_list:
                skipped['no_data'] += 1; continue
                
            # 資金傾斜配分
            alloc_units = ev_alloc(ev_list, BET_BASE)
            bets = [item['bet'] for item in ev_list]
            
            invest = sum(alloc_units)
            total_invest += invest
            bet_races += 1
            
            hit = actual in bets
            if hit:
                idx = bets.index(actual)
                ret = payout * (alloc_units[idx] // 100)
                hit_count += 1
            else:
                ret = 0
            total_return += ret

    # 結果出力
    elapsed = time.time() - start_time
    roi = (total_return / total_invest * 100) if total_invest > 0 else 0
    hit_rate = (hit_count / bet_races * 100) if bet_races > 0 else 0
    profit = total_return - total_invest
    
    print(f"\n{'='*60}")
    print(f"🏁 【SIM専用 最適化ルック条件での結果 (2月・3月)】")
    print(f"{'='*60}")
    print(f"  実行時間      : {elapsed:.1f} 秒")
    print(f"  対象レース数  : {bet_races+sum(skipped.values()):>5} R")
    print(f"  スキップ合計  : {sum(skipped.values()):>5} R")
    print(f"   (midバンク:{skipped['mid_bank']} EV<70:{skipped['low_ev']} 単騎過多:{skipped['many_tanqi']})")
    print(f"  ────────────────────────────")
    print(f"  買い(厳選)    : {bet_races:>5} R")
    print(f"  的中          : {hit_count:>5} R ({hit_rate:.1f}%)")
    print(f"  ────────────────────────────")
    print(f"  総投資        : ¥{total_invest:>10,}")
    print(f"  総払戻        : ¥{total_return:>10,}")
    print(f"  収支          : {'+' if profit>=0 else ''}¥{profit:>8,}")
    print(f"  ROI           : {roi:>7.1f}%")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
