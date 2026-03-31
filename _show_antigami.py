import pandas as pd
df = pd.read_csv('data/antigami_v2_comparison.csv')
for _, r in df.iterrows():
    s = '+' if r['profit'] >= 0 else ''
    st = '*' if r.get('roi_ex1',0) >= 100 else ' '
    label = r['label']
    print(f"{st} {label:35s}  R:{int(r['n']):3d} Hit:{int(r['hits']):2d} HR:{r['hr']:.1f}% "
          f"ROI:{r['roi']:.1f}% {s}{int(r['profit']):>+9,} "
          f"Gami:{int(r['gami'])}/{int(r['hits'])} ({r['gami_rate']:.0f}%) "
          f"Ex1:{r['roi_ex1']:.1f}% avg:{r['avg_bets']:.1f}pt")
