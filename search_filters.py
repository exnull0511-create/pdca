"""
search_filters.py
=================
generate_master_sim.py で生成したマスターデータ (sim_master_data.csv) を読み込み、
投資点数 (Top 5, 7, 10, 14 点) と各種ルック条件 (カオスのみ、TopEV条件など) の組み合わせを
総当たりでテストし、最も現実的で高ROIな投資戦略（フィルタ）を探索する。
"""

import pandas as pd
import numpy as np
from pathlib import Path

# 解析対象のマスターデータ
MASTER_CSV = "data/sim_master_data.csv"

# 調査するフィルタ条件のリスト
# 各辞書は DataFrame に対する query 文字列、または lambda 関数を想定するが
# シンプルに辞書で条件を定義する
FILTER_CONDITIONS = [
    {"name": "1. フィルタなし (全レース)", "query": "index >= 0"},
    {"name": "2. High/Lowバンクのみ (mid除外)", "query": "bank_tier in ['high', 'low']"},
    {"name": "3. 高EV狙い (TopEV >= 70)", "query": "top_ev >= 70"},
    {"name": "4. 高EV + High/Lowバンク", "query": "top_ev >= 70 and bank_tier in ['high', 'low']"},
    {"name": "5. カオスのみ (もがき合い)", "query": "is_chaos == True"},
    {"name": "6. カオス + 高EV (>= 70)", "query": "is_chaos == True and top_ev >= 70"},
    {"name": "7. カオス + High/Lowバンク", "query": "is_chaos == True and bank_tier in ['high', 'low']"},
    {"name": "8. 非カオス順当 (カオス除外)", "query": "is_chaos == False"},
    {"name": "9. 非カオス + 高EV (>= 75)", "query": "is_chaos == False and top_ev >= 75"},
    {"name": "10. 中穴狙い (単騎 1,2,3人)", "query": "num_tanqi in [1, 2, 3]"},
    {"name": "11. 厳選 (カオス + High/Low + EV>=70)", "query": "is_chaos == True and bank_tier in ['high', 'low'] and top_ev >= 70"},
]

# 調査する買い目点数
BET_COUNTS = [7, 10, 14]
BET_BASE = 100

def evaluate_filter(df, condition_query, bet_count):
    # 条件でフィルタリング
    filtered_df = df.query(condition_query) if condition_query != "index >= 0" else df
    target_races = len(filtered_df)
    
    if target_races == 0:
        return 0, 0, 0, 0, 0
        
    total_invest = 0
    total_return = 0
    hit_count = 0
    
    for _, row in filtered_df.iterrows():
        bets_str = str(row['bets_data'])
        if bets_str == "nan" or not bets_str: continue
        
        actual = str(row['actual'])
        payout = row['payout']
        try: payout = int(payout)
        except: payout = 0
            
        # bets_str format: "1-2-3#0.012#150.0#1.8|4-5-6#..."
        # 既にEV順（あるいは確率順）にソートされている前提で、上から N 個取る
        bet_items = bets_str.split('|')
        
        # 均等買い
        selected_bets = []
        for i, item in enumerate(bet_items):
            if i >= bet_count: break
            parts = item.split('#')
            if len(parts) >= 1:
                selected_bets.append(parts[0])
                
        invest = len(selected_bets) * BET_BASE
        total_invest += invest
        
        if actual in selected_bets:
            total_return += payout * (BET_BASE // 100)
            hit_count += 1
            
    roi = (total_return / total_invest * 100) if total_invest > 0 else 0
    hit_rate = (hit_count / target_races * 100) if target_races > 0 else 0
    
    return target_races, hit_count, hit_rate, total_invest, total_return, roi

def main():
    print("🚀 グリッドサーチ（最適ルックフィルタ・投資点数探索）開始")
    if not Path(MASTER_CSV).exists():
        print(f"❌ {MASTER_CSV} が見つかりません。先に generate_master_sim.py を実行してください。")
        return
        
    df = pd.read_csv(MASTER_CSV)
    print(f"マスターデータロード完了: 全 {len(df)} レース\n")
    
    results = []
    
    # グリッドサーチ実行
    for cond in FILTER_CONDITIONS:
        for bet_n in BET_COUNTS:
            tr, hc, hr, inv, ret, roi = evaluate_filter(df, cond['query'], bet_n)
            
            # 結果をプール
            results.append({
                'Filter': cond['name'],
                'Pts': bet_n,
                'Races': tr,
                'Hits': hc,
                'HitRate': hr,
                'Invest': inv,
                'Return': ret,
                'ROI': roi,
                'Profit': ret - inv
            })
            
    # 分析・表示
    res_df = pd.DataFrame(results)
    
    print("=" * 110)
    print(f"{'フィルタ条件':<40} | {'点数':>3} | {'対象R':>4} | {'的中':>3} | {'的中率':>5}% | {'ROI':>6}% | {'収支':>9}")
    print("-" * 110)
    
    # ROI順にソートして出力（マイナスROIも下位に回す）
    sorted_df = res_df.sort_values(by='ROI', ascending=False)
    
    for _, row in sorted_df.iterrows():
        roi_str = f"{row['ROI']:.1f}"
        hr_str = f"{row['HitRate']:.1f}"
        profit_str = f"{int(row['Profit']):,}"
        print(f"{row['Filter']:<40} | {row['Pts']:>3}点 | {row['Races']:>4}R | {row['Hits']:>3}r | {hr_str:>5}% | {roi_str:>6}% | ¥{profit_str:>8}")
        
    print("=" * 110)
    print("\n💡 考察:")
    print("上位にランキングされた条件と点数が、このシミュレーションモデルにおいて一番『現実的（投資金が適切）で高回収』な投資戦略です。")
    
    # CSVに保存
    sorted_df.to_csv("data/grid_search_sim_filters.csv", index=False, encoding="utf-8-sig")
    print("📁 結果を data/grid_search_sim_filters.csv に保存しました。")

if __name__ == "__main__":
    main()
