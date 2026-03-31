import pandas as pd
from pathlib import Path

# 1. 本ロジック（シミュレーションモデル: 中穴・10点買い）の3月的中レースを抽出
try:
    master_df = pd.read_csv("data/sim_master_data.csv")
    master_df['date'] = pd.to_datetime(master_df['date'])
    sim_df = master_df[master_df['date'] >= pd.Timestamp('2026-03-01')]
    sim_df = sim_df[sim_df['num_tanqi'].isin([1, 2, 3])]
    
    sim_hits = set()
    for _, row in sim_df.iterrows():
        actual = str(row['actual'])
        bets_str = str(row['bets_data'])
        if pd.isna(actual) or bets_str == "nan": continue
        bet_items = bets_str.split('|')[:10]
        selected_bets = [item.split('#')[0] for item in bet_items if item]
        if actual in selected_bets:
            sim_hits.add(str(row['race_id']))
except Exception as e:
    print(f"新ロジック読込エラー: {e}")
    sim_hits = set()

# 2. 旧ロジック（LOOSE_Bフィルタ）の3月的中レースを抽出
old_file = Path("data/backtest_march_loose_b.csv")
old_hits = set()
old_df = pd.DataFrame()
if old_file.exists():
    try:
        old_df = pd.read_csv(old_file)
        if 'hit' in old_df.columns:
            hit_df = old_df[old_df['hit'] == 1]
            old_hits = set(hit_df['race_id'].astype(str))
        elif 'is_hit' in old_df.columns:
            hit_df = old_df[old_df['is_hit'] == True]
            old_hits = set(hit_df['race_id'].astype(str))
    except Exception as e:
        print(f"旧ロジック読込エラー: {e}")

# 3. 比較と出力
both_hits = sim_hits.intersection(old_hits)
only_sim = sim_hits - old_hits
only_old = old_hits - sim_hits

print("="*60)
print(f"🎯 新旧ロジック 3月的中レースの重複比較")
print(f"  ・新ロジック(SIMモデル 中穴・10点)     : {len(sim_hits)} レース的中")
print(f"  ・旧ロジック(旧PLモデル LOOSE_B設定) : {len(old_hits)} レース的中")
print("="*60)
print(f"🤝 【両方的中】: {len(both_hits)} レース (両方で拾えた堅実？な取り口)")
print(f"🚀 【新のみ的中】: {len(only_sim)} レース (シミュレーション特有の穴狙い)")
print(f"🛡️ 【旧のみ的中】: {len(only_old)} レース (旧ロジックでしか拾えなかったもの)")
print("="*60)

# 払い戻し額の比較（新のみと旧のみでどのくらい配当が違うか？）
print("\n【独自的中したレースの平均払戻額】")

def get_avg_payout(race_ids, is_sim=True):
    if not race_ids: return 0
    if is_sim:
        payouts = master_df[master_df['race_id'].astype(str).isin(race_ids)]['payout'].dropna()
        return int(payouts.mean()) if len(payouts) > 0 else 0
    else:
        # 旧データはカラム名が return, return_amount, payout などの可能性あり
        if old_df.empty: return 0
        target_df = old_df[old_df['race_id'].astype(str).isin(race_ids)]
        # hitした時の実績配当を取る。return列は購入金額倍率がかかっている場合があるので、
        # payout_trifecta または payout を探す。
        p_col = 'payout_trifecta' if 'payout_trifecta' in old_df.columns else 'payout' if 'payout' in old_df.columns else 'return'
        if p_col in target_df.columns:
            vals = target_df[p_col].replace('[^\d\.]', '', regex=True).astype(float).dropna()
            return int(vals.mean()) if len(vals) > 0 else 0
        return 0

sim_only_avg = get_avg_payout(only_sim, is_sim=True)
old_only_avg = get_avg_payout(only_old, is_sim=False)
both_avg = get_avg_payout(both_hits, is_sim=True) # 両年的中の実配当は同じなのでsimベースで

print(f"  ・両的中の平均配当     : ¥ {both_avg:,}")
print(f"  ・新(SIM)のみ的中の平均: ¥ {sim_only_avg:,}")
print(f"  ・旧のみ的中の平均配当 : ¥ {old_only_avg:,}")
