import pandas as pd
df = pd.read_csv('data/gami_filter_results.csv')
df = df.sort_values('profit', ascending=False)

# 安定候補
stable = df[df['roi_ex1']>=100].head(15)
print('=== Top1除外ROI>=100 & 利益順Top15 ===')
for _, r in stable.iterrows():
    s = '+' if r['profit'] >= 0 else ''
    print(f"  {r['sort']:>4s} minEV={r['min_ev']:.1f} max={int(r['max_n']):2d}  "
          f"R:{int(r['n']):3d} Hit:{int(r['hits']):3d} HR:{r['hr']:.1f}% "
          f"ROI:{r['roi']:.1f}% {s}{int(r['profit']):>+8,} "
          f"Gami:{r['gami_rate']:.0f}% Ex1:{r['roi_ex1']:.1f}% avg:{r['avg_bets']:.1f}pt")

print()
print('=== 全結果 利益順Top20 ===')
for _, r in df.head(20).iterrows():
    s = '+' if r['profit'] >= 0 else ''
    st = '*' if r['roi_ex1']>=100 else ' '
    print(f"{st} {r['sort']:>4s} minEV={r['min_ev']:.1f} max={int(r['max_n']):2d}  "
          f"R:{int(r['n']):3d} Hit:{int(r['hits']):3d} HR:{r['hr']:.1f}% "
          f"ROI:{r['roi']:.1f}% {s}{int(r['profit']):>+8,} "
          f"Gami:{r['gami_rate']:.0f}% Ex1:{r['roi_ex1']:.1f}%")
