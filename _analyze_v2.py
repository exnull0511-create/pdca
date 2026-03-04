import pandas as pd
df = pd.read_csv(r'c:\pdca\data\backtest_result_v2.csv')
bv = df.groupby('venue').agg(n=('hit','count'), hits=('hit','sum'), ret=('return','sum'), inv=('invest','sum')).reset_index()
bv['roi'] = (bv['ret'] / bv['inv'].clip(lower=1) * 100).round(1)
bv = bv.sort_values('roi', ascending=False)
for _, r in bv.iterrows():
    print(r['venue'] + ': ' + str(r['n']) + 'R  的中' + str(r['hits']) + 'R  ROI=' + str(r['roi']) + '%')
