"""
ドローダウン分析: パターンB (EV比例 7点 / ev≥70 / chaos=N / low=Y)
242Rの収支推移と最大ドローダウンを計算
"""
import pandas as pd
import numpy as np
from backtest_model_comparison import (
    load_db, compute_player_scores, compute_raw_strengths,
    allocate_bets, STRATEGY, BANK_DICT,
)

NEST_SIGMA = 0.90
TOP_N = 7
FILTER = {'min_top_ev': 70, 'skip_chaos': False, 'skip_low_bank': True}

def engine_c(all_nums, raw_s, odds_dict, num_to_line):
    sigma = NEST_SIGMA
    def _nests(ms):
        nests = {}
        for n in ms:
            ln = num_to_line.get(n, -n)
            if ln not in nests: nests[ln]=[]
            nests[ln].append(n)
        return nests
    def nm(t, rem):
        if not rem: return 0.0
        nests=_nests(rem); IV={}
        for ln,ms in nests.items():
            inner=sum(raw_s[m]**(1.0/sigma) for m in ms)
            IV[ln]=inner**sigma if inner>0 else 0.0
        tIV=sum(IV.values())
        if tIV==0: return 0.0
        tln=num_to_line.get(t,-t)
        id_=sum(raw_s[m]**(1.0/sigma) for m in nests[tln])
        if id_==0: return 0.0
        return (IV[tln]/tIV)*(raw_s[t]**(1.0/sigma))/id_
    def tri(f,s,t):
        p1=nm(f,all_nums)
        if p1==0: return 0.0
        p2=nm(s,[n for n in all_nums if n!=f])
        if p2==0: return 0.0
        p3=nm(t,[n for n in all_nums if n not in (f,s)])
        return p1*p2*p3
    data=[]
    for f in all_nums:
        for s in all_nums:
            if s==f: continue
            for t in all_nums:
                if t==f or t==s: continue
                c=f"{f}-{s}-{t}"
                if c not in odds_dict: continue
                p=tri(f,s,t); o=odds_dict[c]
                data.append((p*o,c,p,o))
    sel=sorted(data,key=lambda x:x[2],reverse=True)[:TOP_N]
    if not sel: return None
    el={c:ev for ev,c,p,o in data}
    bets,total=allocate_bets(sel,el)
    return {'bets':bets,'total':total}

def main():
    db_slim,db_all,nobi_col=load_db()
    rc_df=pd.read_excel("data/racecard.xlsx")
    od_df=pd.read_excel("data/odds.xlsx")
    py_df=pd.read_excel("data/payouts.xlsx")
    rc_df['date']=pd.to_datetime(rc_df['date'].astype(str).str.strip(),format='%Y%m%d',errors='coerce')
    def cid(v):
        s=str(v).strip()
        if s.startswith('="') and s.endswith('"'): s=s[2:-1]
        return s
    for df in [rc_df,od_df,py_df]: df['race_id']=df['race_id'].apply(cid)
    try:
        bt=pd.read_csv("data/backtest_result_v2.csv"); bt['race_id']=bt['race_id'].apply(cid)
        sids=set(bt['race_id'].tolist())
    except: sids=None

    print("🔄 計算中...")
    races=[]
    for rid,g in rc_df.groupby('race_id'):
        if sids and rid not in sids: continue
        v=g.iloc[0]['venue']; dt=g.iloc[0]['date']
        if pd.isna(dt): continue
        ld=g[['line_no','車番']].dropna()
        if ld.empty: continue
        od=od_df[od_df['race_id']==rid]
        odds={str(r['組み合わせ']).strip():float(r['オッズ']) for _,r in od.iterrows() if pd.notna(r['オッズ'])}
        py=py_df[py_df['race_id']==rid]
        if py.empty: continue
        act=str(py.iloc[0].get('result_trifecta','')).strip().replace('="','').replace('"','')
        pay=py.iloc[0].get('payout_trifecta',0)
        try: pay=int(str(pay).replace(',',''))
        except: pay=0
        ps,ntl,lm=compute_player_scores(v,g,ld,db_slim,db_all,nobi_col,dt)
        rk=sorted(ps.items(),key=lambda x:x[1]['ev'],reverse=True)
        if len(rk)<3: continue
        an,rs=compute_raw_strengths(ps,rk)
        bp=BANK_DICT.get(v,{'roi_tier':'mid','sashi':1.0,'makuri':1.0})
        tev=rk[0][1]['ev']
        sl=[n for n,d in ps.items() if d['ip']>=5.5 and lm.get(ntl.get(n,0),[None])[0]==n]
        if FILTER['skip_low_bank'] and bp['roi_tier']=='low': continue
        if FILTER['min_top_ev']>0 and tev<FILTER['min_top_ev']: continue
        if FILTER['skip_chaos'] and len(sl)>=2: continue
        pred=engine_c(an,rs,odds,ntl)
        if pred is None: continue
        combos=[c for c,_ in pred['bets']]
        hit=act in combos
        if hit:
            idx=combos.index(act)
            bamt=pred['bets'][idx][1]
            ret=int(pay*bamt/100)
        else:
            ret=0
        races.append({'date':dt,'venue':v,'race_no':int(g.iloc[0]['race_no']),
                       'invest':pred['total'],'ret':ret,'hit':hit,'payout':pay})

    races.sort(key=lambda x:(x['date'],x['venue'],x['race_no']))
    print(f"対象: {len(races)}R\n")

    # 収支推移
    cumsum=0; peak=0; max_dd=0; dd_start=None; dd_end=None; worst_streak=0; cur_streak=0
    print(f"{'No':>3s}  {'日付':>10s} {'会場':>6s} {'R':>3s}  {'投資':>6s} {'払戻':>8s} {'損益':>8s} {'累計':>10s} {'DD':>8s}")
    print(f"{'-'*75}")

    for i,r in enumerate(races,1):
        pnl = r['ret'] - r['invest']
        cumsum += pnl
        if cumsum > peak:
            peak = cumsum
        dd = peak - cumsum
        if dd > max_dd:
            max_dd = dd

        if r['hit']:
            cur_streak = 0
        else:
            cur_streak += 1
            worst_streak = max(worst_streak, cur_streak)

        mark = "✅" if r['hit'] else "❌"
        d = r['date'].strftime('%m/%d') if hasattr(r['date'],'strftime') else str(r['date'])[:10]
        print(f"{i:3d}  {d} {r['venue']:>6s} {r['race_no']:3d}R  "
              f"¥{r['invest']:>5,} ¥{r['ret']:>7,} {pnl:>+7,} {cumsum:>+9,} {dd:>7,} {mark}")

    # サマリー
    total_in = sum(r['invest'] for r in races)
    total_re = sum(r['ret'] for r in races)
    n_hit = sum(1 for r in races if r['hit'])
    profit = total_re - total_in

    # 最小累計（最大のマイナス深さ）
    cum = 0; min_cum = 0
    for r in races:
        cum += r['ret'] - r['invest']
        min_cum = min(min_cum, cum)

    print(f"\n{'='*75}")
    print(f"  パターンB サマリー (EV比例 7点 / ev≥70 / chaos=N / low=Y)")
    print(f"{'='*75}")
    print(f"  レース数:     {len(races)}R")
    print(f"  的中:         {n_hit}件 ({n_hit/len(races)*100:.1f}%)")
    print(f"  投資合計:     ¥{total_in:,}")
    print(f"  払戻合計:     ¥{total_re:,}")
    print(f"  収支:         {'+'if profit>=0 else ''}¥{profit:,}")
    print(f"  ROI:          {total_re/total_in*100:.1f}%")
    print(f"  最大ドローダウン: ¥{max_dd:,} (高値からの最大下落)")
    print(f"  最深マイナス域:   ¥{min_cum:,} (初期資金からの最大含み損)")
    print(f"  最大連敗:     {worst_streak}連敗")
    print(f"{'='*75}")

if __name__=="__main__":
    main()
