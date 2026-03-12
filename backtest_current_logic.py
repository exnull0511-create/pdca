"""
backtest_current_logic.py
=========================
check_and_notify.py の現在の run_prediction() ロジックで
2月のバックテストデータを再検証するスクリプト。

hardcore_ev.py と check_and_notify.py のロジック差異を数値で明らかにする。
"""

import sys, os
import pandas as pd
import numpy as np
from datetime import datetime, date
from pathlib import Path

# ── 設定（LOOSE_B と同一） ─────────────────────────────────────────────────
DB_SLIM = "data/S級DB_slim.xlsx"
DB_OLD  = "data/S級選手究極DB(1).xlsx"

LOW_BANK  = {'岸和田','久留米','奈良','岐阜','小松島','防府','静岡','小倉'}
STRATEGY  = dict(skip_chaos=True, min_top_ev=70, skip_low_bank=True, top_n_prob_bets=14)
BET_BASE  = 100
BANK_DICT = {
    '前橋':     {'roi_tier':'mid', 'sashi':0.8,'makuri':1.2},
    '宇都宮':   {'roi_tier':'high','sashi':1.5,'makuri':1.1},
    '豊橋':     {'roi_tier':'high','sashi':1.3,'makuri':1.2},
    '岸和田':   {'roi_tier':'low', 'sashi':1.1,'makuri':1.3},
    '熊本':     {'roi_tier':'high','sashi':1.2,'makuri':1.1},
    'いわき平': {'roi_tier':'mid', 'sashi':0.9,'makuri':1.3},
    '広島':     {'roi_tier':'mid', 'sashi':1.2,'makuri':1.0},
    '別府':     {'roi_tier':'mid', 'sashi':1.1,'makuri':1.1},
    '松山':     {'roi_tier':'mid', 'sashi':1.0,'makuri':1.2},
    '小倉':     {'roi_tier':'low', 'sashi':1.1,'makuri':1.1},
    '京王閣':   {'roi_tier':'high','sashi':1.0,'makuri':1.1},
    '立川':     {'roi_tier':'high','sashi':1.1,'makuri':1.0},
    '取手':     {'roi_tier':'mid', 'sashi':1.1,'makuri':1.1},
    '伊東':     {'roi_tier':'mid', 'sashi':1.0,'makuri':1.2},
    '久留米':   {'roi_tier':'low', 'sashi':1.1,'makuri':1.1},
    '奈良':     {'roi_tier':'low', 'sashi':1.2,'makuri':1.0},
    '岐阜':     {'roi_tier':'low', 'sashi':1.1,'makuri':1.1},
    '小松島':   {'roi_tier':'low', 'sashi':1.1,'makuri':1.0},
    '防府':     {'roi_tier':'low', 'sashi':1.1,'makuri':1.1},
    '静岡':     {'roi_tier':'low', 'sashi':1.2,'makuri':1.0},
    '松阪':     {'roi_tier':'mid', 'sashi':1.1,'makuri':1.1},
    '高知':     {'roi_tier':'mid', 'sashi':1.0,'makuri':1.2},
    '松戸':     {'roi_tier':'mid', 'sashi':1.1,'makuri':1.0},
    '平塚':     {'roi_tier':'mid', 'sashi':1.2,'makuri':1.1},
    '西武園':   {'roi_tier':'mid', 'sashi':1.0,'makuri':1.1},
    '小田原':   {'roi_tier':'mid', 'sashi':1.0,'makuri':1.1},
}

SENPO_LEAD = {
    '逃げ切り':5,'逃げ粘り':4,'突っ張り先行':4,'抑え先行':4,
    '先行':4,'逃げ':5,'カマシ先行':5,'先行逃げ切り':5,
    '捲り':3,'番手捲り':3,'カマシ捲り':4,'捲り差し':3,
    '差し':2,'番手差し':2,'追い込み':2,'流れ込み':1,'追走':1,'マーク':1,
}

def norm(s): return str(s).replace(' ','').replace('　','')
def nobi_score(v):
    m={'S':5,'A':4,'B':3,'C':2,'D':1,'E':0}
    s=str(v).strip()
    return m.get(s,m.get(s[:1],2.5))
def senpo_lead(v):
    s=str(v).strip()
    for k,sc in SENPO_LEAD.items():
        if k in s: return sc
    return 2
def safe(v,d):
    try: return d if (v is None or (isinstance(v,float) and np.isnan(v))) else float(v)
    except: return d


# ── DB読み込み ───────────────────────────────────────────────────────────
def load_db():
    db_slim=pd.DataFrame(); db_all=pd.DataFrame()
    try:
        r=pd.read_excel(DB_SLIM)
        r['開催日']=pd.to_datetime(r['開催日'],errors='coerce')
        r['選手名_norm']=r['選手名'].apply(norm)
        db_slim=r[r['開催日'].notna()].reset_index(drop=True)
    except Exception as e: print(f"slimDB失敗: {e}")
    try:
        r2=pd.read_excel(DB_OLD)
        if '例' in str(r2.iloc[0].get('開催日','')):
            r2=r2.iloc[1:].reset_index(drop=True)
        r2['開催日']=pd.to_datetime(r2['開催日'],format='%Y/%m/%d',errors='coerce')
        r2['選手名_norm']=r2['選手名'].apply(norm)
        db_all=r2[r2['開催日'].notna()].reset_index(drop=True)
    except Exception as e: print(f"oldDB失敗: {e}")
    nobi_col=next((c for c in db_all.columns if '伸び' in c and '直線' not in c), None)
    print(f"slimDB:{len(db_slim)}件  oldDB:{len(db_all)}件  伸び列:{nobi_col}")
    return db_slim, db_all, nobi_col


# ── 予想コア（check_and_notify.py と同一ロジック） ─────────────────────
def run_prediction(venue, race_card, lines_df, odds_dict, db_slim, db_all, nobi_col, race_dt):
    """
    lines_df: DataFrame with columns [line_no, vehicle_no]
    """
    bp = BANK_DICT.get(venue, {'roi_tier':'mid','sashi':1.0,'makuri':1.0})
    if STRATEGY['skip_low_bank'] and venue in LOW_BANK:
        return None, "低bank"

    # ライン辞書構築
    line_map    = {}
    num_to_line = {}
    for _, row in lines_df.iterrows():
        lno = int(row['line_no'])
        num = int(row['車番'])
        if lno not in line_map: line_map[lno] = []
        line_map[lno].append(num)
        num_to_line[num] = lno

    past_slim = db_slim[db_slim['開催日'] < race_dt] if not db_slim.empty else db_slim
    past_all  = db_all[db_all['開催日']  < race_dt] if not db_all.empty  else db_all

    player_scores = {}
    for _, row in race_card.iterrows():
        try: num = int(row['車番'])
        except: continue
        nm   = norm(str(row.get('選手名','')))
        base = float(row.get('競走得点', 80) or 80)

        hist     = past_slim[past_slim['選手名_norm']==nm] if not past_slim.empty else pd.DataFrame()
        use_slim = not hist.empty
        if hist.empty:
            hist = past_all[past_all['選手名_norm']==nm] if not past_all.empty else pd.DataFrame()

        ip=ep=4.0; dp=bp_v=3.0; nb=sp=2.0; is_m=is_u=False
        if not hist.empty:
            RECENT_W=3.0
            sd=sorted(hist['開催日'].dropna().unique(),reverse=True)
            rd=set(sd[:2])
            def wm(series):
                v=pd.to_numeric(series,errors='coerce')
                w=np.where(hist['開催日'].isin(rd),RECENT_W,1.0)
                mk=v.notna()
                return float((v[mk]*w[mk]).sum()/w[mk].sum()) if mk.any() else np.nan
            ip  =safe(wm(hist['IP']),   4.0)
            ep  =safe(wm(hist['EP']),   4.0)
            dp  =safe(wm(hist['DP']),   3.0)
            bp_v=safe(wm(hist['BP']),   3.0)
            if use_slim and '直線の伸び' in hist.columns:
                nb=safe(wm(hist['直線の伸び'].apply(nobi_score)),2.0)
            elif nobi_col and nobi_col in hist.columns:
                nb=safe(wm(hist[nobi_col].apply(nobi_score)),2.0)
            if '戦法' in hist.columns:
                sp=safe(wm(hist['戦法'].apply(senpo_lead)),2.0)
            if use_slim:
                is_m=bool(hist.get('is_monster',  pd.Series([0])).max()>=1)
                is_u=bool(hist.get('is_unreliable',pd.Series([0])).max()>=1)
            else:
                cmt=' '.join(hist.get('解析コメント',pd.Series([''])).astype(str))
                is_m=any(k in cmt for k in ['脚余し','鬼脚','別次元','圧倒'])
                is_u=any(k in cmt for k in ['共倒れ','位置取り失敗','不発','失速'])

        lno  =num_to_line.get(num,0)
        lbs  =line_map.get(lno,[])
        pos  =lbs.index(num)+1 if num in lbs else 1
        pos_b=0.5 if pos==1 else -0.3*(pos-1)

        ev=(base*0.4+ip*1.5+ep*1.2+dp*bp['makuri']+bp_v*bp['sashi']
            +nb*2.0+sp*0.5+pos_b+(3.0 if is_m else 0)-(2.0 if is_u else 0))
        player_scores[num]={'name':str(row.get('選手名','')),'ev':ev,'ip':ip,'is_monster':is_m}

    ranked=sorted(player_scores.items(),key=lambda x:x[1]['ev'],reverse=True)
    if len(ranked)<3: return None,"選手不足"

    # カオス判定（修正済み）
    strong_leaders=[n for n,d in player_scores.items()
                    if d['ip']>=5.5 and line_map.get(num_to_line.get(n,0),[None])[0]==n]
    is_chaos=len(strong_leaders)>=2

    top_ev=ranked[0][1]['ev']
    if top_ev<STRATEGY['min_top_ev']: return None,f"EV不足({top_ev:.1f})"
    if is_chaos and STRATEGY['skip_chaos']: return None,f"カオス(先行×{len(strong_leaders)})"

    all_nums=[n for n,_ in ranked]
    max_e=ranked[0][1]['ev']
    raw_s={n:np.exp(player_scores[n]['ev']-max_e) for n in all_nums}

    def pl(f,s,t):
        d1=sum(raw_s[n] for n in all_nums)
        d2=sum(raw_s[n] for n in all_nums if n!=f)
        d3=sum(raw_s[n] for n in all_nums if n not in (f,s))
        return 0.0 if 0 in (d1,d2,d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)

    axis_num=next((n for n,d in ranked if d['is_monster']),ranked[0][0])
    others  =[n for n,_ in ranked if n!=axis_num]

    all_ev_bets=[]
    for s in others:
        for t in others:
            if s==t: continue
            combo=f"{axis_num}-{s}-{t}"
            p_trio=pl(axis_num,s,t)
            odds=odds_dict.get(combo,0)
            ev_val=p_trio*odds if odds>0 else 0
            all_ev_bets.append((ev_val,combo,p_trio,odds))

    # PL確率上位14点（LOOSE_B仕様）
    all_prob_bets=sorted(all_ev_bets,key=lambda x:x[2],reverse=True)
    selected=all_prob_bets[:STRATEGY['top_n_prob_bets']]
    ev_lookup={c:ev for ev,c,p,o in all_ev_bets}
    bets=[c for _,c,_,_ in selected]
    if not bets: return None,"買い目なし"

    bev   =[(c,ev_lookup.get(c,0.0)) for c in bets]
    ev_va =np.array([max(e,0.0) for _,e in bev])
    total_p=BET_BASE*len(bets)
    if ev_va.sum()==0:
        alloc=[BET_BASE]*len(bets)
    else:
        a=((ev_va/ev_va.sum())*total_p)
        a100=(a//100).astype(int)*100
        a100[int(np.argmax(ev_va))]+=(int(total_p-a100.sum())//100)*100
        alloc=[max(int(x),100) for x in a100]

    return {'axis':axis_num,'axis_name':player_scores[axis_num]['name'],
            'axis_ev':player_scores[axis_num]['ev'],'top_ev':top_ev,
            'bets':list(zip(bets,alloc)),'total':sum(alloc),'is_chaos':is_chaos}, None


# ── メイン ─────────────────────────────────────────────────────────────────
def main():
    db_slim, db_all, nobi_col = load_db()

    # データ読み込み
    rc_df = pd.read_excel("data/racecard.xlsx")
    od_df = pd.read_excel("data/odds.xlsx")
    py_df = pd.read_excel("data/payouts.xlsx")

    # date列を正しくパース
    rc_df['date'] = pd.to_datetime(rc_df['date'].astype(str).str.strip(), format='%Y%m%d', errors='coerce')

    # race_id を文字列に統一（="..." 形式を除去）
    def clean_id(v):
        s = str(v).strip()
        if s.startswith('="') and s.endswith('"'): s = s[2:-1]
        return s
    for df in [rc_df, od_df, py_df]:
        df['race_id'] = df['race_id'].apply(clean_id)

    # S級レースのrace_id一覧（backtest_result_v2.csvから取得）
    try:
        bt = pd.read_csv("data/backtest_result_v2.csv")
        bt['race_id'] = bt['race_id'].apply(clean_id)
        s_race_ids = set(bt['race_id'].tolist())
        print(f"S級race_id: {len(s_race_ids)}件")
    except Exception as e:
        print(f"S級race_id取得失敗: {e}")
        s_race_ids = None

    races = rc_df.groupby('race_id')

    results = []
    skipped = []
    print(f"\n{'='*65}")
    print(f"  現ロジック バックテスト（2月）")
    print(f"{'='*65}\n")

    for race_id, rc_group in races:
        # S級フィルター
        if s_race_ids is not None and race_id not in s_race_ids:
            continue

        venue    = rc_group.iloc[0]['venue']
        race_no  = int(rc_group.iloc[0]['race_no'])
        race_dt  = rc_group.iloc[0]['date']
        if pd.isna(race_dt): continue

        # ライン情報
        lines_df = rc_group[['line_no','車番']].dropna()
        if lines_df.empty: continue

        # オッズ辞書
        od_race  = od_df[od_df['race_id']==race_id]
        odds_dict= {str(r['組み合わせ']).strip(): float(r['オッズ'])
                    for _,r in od_race.iterrows() if pd.notna(r['オッズ'])}

        # 払戻・結果
        py_race  = py_df[py_df['race_id']==race_id]
        if py_race.empty: continue
        actual   = str(py_race.iloc[0].get('result_trifecta','')).strip().replace('="','').replace('"','')
        payout   = py_race.iloc[0].get('payout_trifecta', 0)
        try: payout = int(str(payout).replace(',',''))
        except: payout = 0

        pred, reason = run_prediction(venue, rc_group, lines_df, odds_dict,
                                       db_slim, db_all, nobi_col, race_dt)

        if pred is None:
            skipped.append({'venue':venue,'race_no':race_no,'date':str(race_dt.date()),'reason':reason})
            continue

        # 的中判定
        bet_combos = [c for c,_ in pred['bets']]
        hit        = actual in bet_combos
        bet_amt    = dict(pred['bets']).get(actual, 0) if hit else 0
        ret        = int(payout * bet_amt / 100) if hit else 0

        row = {
            'race_id':  race_id,
            'venue':    venue,
            'date':     str(race_dt.date()),
            'race_no':  race_no,
            'axis':     pred['axis'],
            'axis_name':pred['axis_name'],
            'axis_ev':  round(pred['axis_ev'],1),
            'top_ev':   round(pred['top_ev'],1),
            'invest':   pred['total'],
            'return':   ret,
            'payout_100': payout,
            'hit':      hit,
            'actual':   actual,
            'bets':     ','.join(bet_combos[:7]),
        }
        results.append(row)

        status    = "✅ 的中" if hit else "❌ 外れ"
        axis_diff = abs(pred['axis_ev']-pred['top_ev'])
        axis_note = f" ⚠️軸≠最高EV(差{axis_diff:.1f})" if axis_diff > 2 else ""
        print(f"  {row['date']} {venue:6s} {race_no:>2d}R"
              f"  軸:{pred['axis']}({pred['axis_ev']:.1f})"
              f"  最高EV:{pred['top_ev']:.1f}"
              f"  {status}  {actual}({payout//10}倍){axis_note}")

    # 集計
    df_res = pd.DataFrame(results)
    if df_res.empty:
        print("\nデータなし（フィルタ条件を確認してください）")
        return

    n        = len(df_res)
    n_hit    = int(df_res['hit'].sum())
    total_in = int(df_res['invest'].sum())
    total_re = int(df_res['return'].sum())
    profit   = total_re - total_in
    roi      = total_re / total_in * 100 if total_in > 0 else 0
    hit_rate = n_hit / n * 100
    n_axis_diff = int((abs(df_res['axis_ev'] - df_res['top_ev']) > 2).sum())

    print(f"\n{'='*65}")
    print(f"  【現ロジック バックテスト結果】（2月）")
    print(f"  対象R:    {n}R  (スキップ: {len(skipped)}件)")
    print(f"  的中:     {n_hit}件  ({hit_rate:.1f}%)")
    print(f"  投資:     ¥{total_in:,}")
    print(f"  払戻:     ¥{total_re:,}")
    print(f"  収支:     {'+'if profit>=0 else ''}¥{profit:,}")
    print(f"  ROI:      {roi:.1f}%")
    print()
    print(f"  ── 欠陥チェック ──")
    print(f"  ⚠️ 軸≠最高EV(差>2): {n_axis_diff}/{n}R ({n_axis_diff/n*100:.1f}%)")
    print(f"     → is_monsterが軸を別人に引っ張っているケース")

    sk_df = pd.DataFrame(skipped)
    if not sk_df.empty:
        print(f"\n  スキップ内訳:")
        for reason, cnt in sk_df['reason'].value_counts().items():
            print(f"    {reason}: {cnt}件")

    # 参考: hardcore_ev.pyのLOOSE-B結果
    print(f"\n  ── 比較: hardcore_ev.py LOOSE-B（公式BT）──")
    print(f"  対象R: 73R  的中: 20件(27.4%)  収支: +¥434,030  ROI: 525%")

    df_res.to_csv("data/backtest_current_logic.csv", index=False, encoding='utf-8-sig')
    print(f"\n  → data/backtest_current_logic.csv 保存完了")
    print(f"{'='*65}")

if __name__ == "__main__":
    main()
