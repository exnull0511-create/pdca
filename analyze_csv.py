import pandas as pd

df = pd.read_csv('data/sim_analysis_features.csv')

with open('data/analysis_result_utf8.txt', 'w', encoding='utf-8') as f:
    def log(msg):
        f.write(str(msg) + "\n")

    def show_roi(grp, name):
        log(f"\n【{name}の比較】")
        for idx, row in grp.iterrows():
            inv = row['invest']
            ret = row['return']
            hits = row['hit']
            cnt = row['count']
            roi = (ret / inv * 100) if inv > 0 else 0
            hit_rate = (hits / cnt * 100) if cnt > 0 else 0
            log(f" - {str(idx):<20}: 対象{int(cnt):>3}R | 投資 ¥{int(inv):>7,} | 回収 ¥{int(ret):>8,} | ROI {roi:>6.1f}% | 的中率 {hit_rate:>4.1f}%")

    # 全体
    total_inv = df['invest'].sum()
    total_ret = df['return'].sum()
    log(f"全体: 対象{len(df)}R | ROI {(total_ret/total_inv*100):.1f}%")

    # 1. カオス（荒れるレース）
    grp1 = df.groupby('is_chaos').agg({'invest':'sum', 'return':'sum', 'hit':'sum', 'race_id':'count'}).rename(columns={'race_id':'count'})
    show_roi(grp1, "カオス有無（True=もがき合い濃厚）")

    # 2. トップEV
    bins = [0, 60, 65, 70, 75, 100]
    df['ev_bin'] = pd.cut(df['top_ev'], bins=bins)
    grp2 = df.groupby('ev_bin', observed=False).agg({'invest':'sum', 'return':'sum', 'hit':'sum', 'race_id':'count'}).rename(columns={'race_id':'count'})
    show_roi(grp2, "TopEVの閾値別 (EV低い=本命不在)")

    # 3. バンク特性
    grp3 = df.groupby('bank_tier').agg({'invest':'sum', 'return':'sum', 'hit':'sum', 'race_id':'count'}).rename(columns={'race_id':'count'})
    show_roi(grp3, "バンク特性 (high, mid, low)")

    # 4. 鬼脚の有無
    grp4 = df.groupby('has_monster').agg({'invest':'sum', 'return':'sum', 'hit':'sum', 'race_id':'count'}).rename(columns={'race_id':'count'})
    show_roi(grp4, "鬼脚選手の有無")

    # 5. 単騎選手の数
    grp5 = df.groupby('num_tanqi').agg({'invest':'sum', 'return':'sum', 'hit':'sum', 'race_id':'count'}).rename(columns={'race_id':'count'})
    show_roi(grp5, "単騎の数")
