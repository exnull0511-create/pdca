"""
_ito_predict.py
===============
伊東競輪 3/4 8〜12R テスト予想 (LOOSE-B 軸固定 EV傾斜)
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# =========================================================
# ライン情報（ユーザー提供）
# =========================================================
RACE_LINES = {
    '8R':  [[7,1],  [6,2],  [5,3],  [4]],
    '9R':  [[1,4],  [2,5],  [3,7,6]],
    '10R': [[5,1,6],[7,2],  [4,3]],
    '11R': [[4,1,5],[2,6],  [7,3]],
    '12R': [[7,2],  [6,1],  [5,3],  [4]],
}

# =========================================================
# 設定
# =========================================================
MIN_TOP_EV   = 70
SKIP_CHAOS   = True
SKIP_LOW_BANK = True
TOP_N_PROB   = 14
BET_BASE     = 100
VENUE        = '伊東'

bank_dict = {
    '前橋': {'sashi': 0.8, 'makuri': 1.2, 'roi_tier': 'mid'},
    '宇都宮': {'sashi': 1.5, 'makuri': 1.1, 'roi_tier': 'high'},
    '豊橋': {'sashi': 1.3, 'makuri': 1.2, 'roi_tier': 'high'},
    '岸和田': {'sashi': 1.1, 'makuri': 1.3, 'roi_tier': 'low'},
    '熊本': {'sashi': 1.2, 'makuri': 1.1, 'roi_tier': 'high'},
    'いわき平': {'sashi': 0.9, 'makuri': 1.3, 'roi_tier': 'mid'},
    '広島': {'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'mid'},
    '別府': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '松山': {'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '小倉': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '京王閣': {'sashi': 1.0, 'makuri': 1.1, 'roi_tier': 'high'},
    '立川': {'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'high'},
    '取手': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '伊東': {'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '久留米': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '奈良': {'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'low'},
    '岐阜': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '小松島': {'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'low'},
    '防府': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '静岡': {'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'low'},
    '松阪': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '高知': {'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '松戸': {'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'mid'},
    '平塚': {'sashi': 1.2, 'makuri': 1.1, 'roi_tier': 'mid'},
    '西武園': {'sashi': 1.0, 'makuri': 1.1, 'roi_tier': 'mid'},
    '函館': {'sashi': 1.0, 'makuri': 1.0, 'roi_tier': 'mid'},
    '青森': {'sashi': 1.0, 'makuri': 1.0, 'roi_tier': 'mid'},
    '向日町': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '大垣': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '名古屋': {'sashi': 1.0, 'makuri': 1.1, 'roi_tier': 'mid'},
    '川崎': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '大宮': {'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '松山': {'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
}

SENPO_LEAD = {
    '逃げ切り': 5, '逃げ粘り': 4, '突っ張り先行': 4, '抑え先行': 4,
    'カマシ先行': 5, '先行逃げ切り': 5, '先行': 4, '逃げ': 5,
    '先行争い敗北': 3, '先行争い敗': 3,
    '一発捲り': 3, 'ロング捲り': 3, '捲り': 3, '番手捲り': 3,
    'カマシ捲り': 4, '捲り差し': 3, '捲り追い込み': 2, '捲り不発': 2,
    '番手差し': 2, '差し': 2, '追い込み': 2, '流れ込み': 1, '追走': 1, 'マーク': 1,
}

def nobi_score(v):
    s = str(v).strip().upper()
    return 5 if s.startswith('S') else 4 if s.startswith('A') else 3 if s.startswith('B') else 1

def senpo_lead(v): return SENPO_LEAD.get(str(v).strip(), 1)
def normalize_name(s): return str(s).replace(' ','').replace('\u3000','').strip()

# =========================================================
# データロード
# =========================================================
print('🔥 データ読み込み中...')
xl_ito = pd.ExcelFile('data/伊東_全レースデータ.xlsx')
rc_ito = xl_ito.parse('出走表')
od_ito = xl_ito.parse('オッズ')

xl_db  = pd.ExcelFile('data/S級選手究極DB(1).xlsx')
db_all = pd.concat([xl_db.parse('F1'), xl_db.parse('G3~1')], ignore_index=True)
db_all['開催日'] = pd.to_datetime(db_all['開催日'], errors='coerce')
for c in ['IP','EP','DP','BP']:
    db_all[c] = pd.to_numeric(db_all[c], errors='coerce')
db_all['選手名_norm'] = db_all['選手名'].apply(normalize_name)
nobi_col = [c for c in db_all.columns if '直線' in c][0]
# 2026-03-04より前のデータを使用
today_dt = pd.Timestamp('2026-03-04')
past_db  = db_all[db_all['開催日'] < today_dt]

od_ito['オッズ'] = pd.to_numeric(od_ito['オッズ'], errors='coerce')
rc_ito['競走得点'] = pd.to_numeric(rc_ito['競走得点'], errors='coerce').fillna(80)

bank_prof = bank_dict.get(VENUE, {'sashi': 1.0, 'makuri': 1.0, 'roi_tier': 'mid'})

# =========================================================
# 予想関数
# =========================================================
def predict_race(race_label, lines):
    race_rc = rc_ito[rc_ito['レース'] == race_label]
    race_od = od_ito[od_ito['レース'] == race_label]
    if race_rc.empty:
        print(f'  ⚠️  {race_label}: 出走表データなし')
        return

    # ライン情報からnum_to_line構築
    num_to_line = {}
    line_map    = {}
    for lno, bibs in enumerate(lines, 1):
        line_map[lno] = bibs
        for b in bibs:
            num_to_line[b] = lno

    # オッズ辞書
    odds_dict = {}
    for _, orow in race_od.iterrows():
        combo = str(orow['組み合わせ']).strip()
        odds_dict[combo] = float(orow['オッズ'])

    # スコア計算
    player_scores = {}
    for _, row in race_rc.iterrows():
        num  = int(row['車番'])
        norm = normalize_name(str(row['選手名']))
        hist = past_db[past_db['選手名_norm'] == norm]

        ip=ep=4.0; dp=bp_v=3.0; nb=sp=2.0; is_m=is_u=False
        if not hist.empty:
            RW = 3.0
            sd = sorted(hist['開催日'].dropna().unique(), reverse=True)
            rd = set(sd[:2])
            def wm(series, h=hist, r=rd):
                v = pd.to_numeric(series, errors='coerce')
                w = np.where(h['開催日'].isin(r), RW, 1.0)
                mk = v.notna()
                return float((v[mk]*w[mk]).sum()/w[mk].sum()) if mk.any() else np.nan
            ip   = wm(hist['IP'])   or 4.0
            ep   = wm(hist['EP'])   or 4.0
            dp   = wm(hist['DP'])   or 3.0
            bp_v = wm(hist['BP'])   or 3.0
            nb   = wm(hist[nobi_col].apply(nobi_score)) or 2.0
            sp   = wm(hist['戦法'].apply(senpo_lead)) if '戦法' in hist.columns else 2.0
            cmt  = ' '.join(hist['解析コメント'].astype(str))
            is_m = any(k in cmt for k in ['脚余し','鬼脚','別次元','圧倒','豪快'])
            is_u = any(k in cmt for k in ['共倒れ','位置取り失敗','不発','失速'])

        ip=ip if ip and not np.isnan(ip) else 4.0
        ep=ep if ep and not np.isnan(ep) else 4.0
        dp=dp if dp and not np.isnan(dp) else 3.0
        bp_v=bp_v if bp_v and not np.isnan(bp_v) else 3.0
        nb=nb if nb and not np.isnan(nb) else 2.0
        sp=sp if sp and not np.isnan(sp) else 2.0

        lno   = num_to_line.get(num, 0)
        lbs   = line_map.get(lno, [])
        pos   = lbs.index(num)+1 if num in lbs else 1
        bonus = 0.5 if pos==1 else -0.3*(pos-1)

        ev = (float(row['競走得点'])*0.4 + ip*1.5 + ep*1.2
              + dp*bank_prof['makuri'] + bp_v*bank_prof['sashi']
              + nb*2.0 + sp*0.5 + bonus
              + (3.0 if is_m else 0) - (2.0 if is_u else 0))

        player_scores[num] = {'name': str(row['選手名']), 'ev': ev,
                               'ip': ip, 'is_monster': is_m}

    ranked    = sorted(player_scores.items(), key=lambda x: x[1]['ev'], reverse=True)
    all_nums  = [n for n, _ in ranked]
    top_ev    = ranked[0][1]['ev']

    # カオス判定
    strong_leaders = [
        n for n, d in player_scores.items()
        if d['ip'] >= 5.5 and line_map.get(num_to_line.get(n,0),[None])[0] == n
    ]
    is_chaos = len(strong_leaders) >= 2

    # ── 結果表示（フィルタ適用前に選手スコアを表示）──
    print(f'\n{"="*60}')
    print(f' 🏁 {race_label}  伊東バンク  (makuri={bank_prof["makuri"]}, sashi={bank_prof["sashi"]})')
    print(f'{"="*60}')
    print(f'  {"車番":<4} {"選手名":<10} {"EVスコア":>8}  {"ラインPos"}  {"鬼脚"}')
    print(f'  {"─"*50}')
    for n, d in ranked:
        lno = num_to_line.get(n, 0)
        lbs = line_map.get(lno, [])
        pos = lbs.index(n)+1 if n in lbs else 1
        bibs_str = '-'.join(str(b) for b in lbs)
        print(f'  {n:<4} {d["name"]:<10} {d["ev"]:>8.2f}  L{lno}({bibs_str}) pos{pos}  {"★鬼脚" if d["is_monster"] else ""}')

    print(f'\n  カオス: {"あり ⚠️" if is_chaos else "なし"}  top_ev={top_ev:.2f}')

    # フィルタ
    if SKIP_CHAOS and is_chaos:
        print(f'  => ⏭️  カオス除外 (強い先行 {len(strong_leaders)}人)')
        return
    if top_ev < MIN_TOP_EV:
        print(f'  => ⏭️  EVスコア不足 (top_ev={top_ev:.1f} < {MIN_TOP_EV})')
        return
    if SKIP_LOW_BANK and bank_prof.get('roi_tier') == 'low':
        print(f'  => ⏭️  低バンク除外')
        return
    if not odds_dict:
        print(f'  => ⏭️  オッズデータなし')
        return

    # 軸決定
    monsters = [(n, d) for n, d in ranked if d['is_monster']]
    axis_num = monsters[0][0] if monsters else ranked[0][0]
    others   = [n for n, _ in ranked if n != axis_num]

    # PL確率計算
    max_e = ranked[0][1]['ev']
    raw_s = {n: np.exp(player_scores[n]['ev'] - max_e) for n in all_nums}
    def pl(f,s,t):
        d1=sum(raw_s[n] for n in all_nums); d2=sum(raw_s[n] for n in all_nums if n!=f)
        d3=sum(raw_s[n] for n in all_nums if n not in (f,s))
        return 0.0 if 0 in (d1,d2,d3) else (raw_s[f]/d1)*(raw_s[s]/d2)*(raw_s[t]/d3)

    ev_bets = sorted(
        [(pl(axis_num,s,t)*odds_dict.get(f'{axis_num}-{s}-{t}',0),
          f'{axis_num}-{s}-{t}', pl(axis_num,s,t), odds_dict.get(f'{axis_num}-{s}-{t}',0))
         for s in others for t in others if s!=t and f'{axis_num}-{s}-{t}' in odds_dict],
        key=lambda x: x[2], reverse=True
    )
    bets = [c for _,c,_,_ in ev_bets[:TOP_N_PROB]]
    if not bets:
        print(f'  => ⏭️  買い目なし（オッズ組み合わせ未対応）')
        return

    el     = {c:ev for ev,c,p,o in sorted(ev_bets, key=lambda x: x[0], reverse=True)}
    bev    = [(c, el.get(c,0.0)) for c in bets]
    ev_vals= np.array([max(e,0.0) for _,e in bev])
    total_p= BET_BASE * len(bets)
    if ev_vals.sum()==0:
        alloc = [BET_BASE]*len(bets)
    else:
        a    = (ev_vals/ev_vals.sum())*total_p
        a100 = (a//100).astype(int)*100
        a100[int(np.argmax(ev_vals))] += (int(total_p-a100.sum())//100)*100
        alloc = [max(int(x),100) for x in a100]

    axis_name = player_scores[axis_num]['name']
    print(f'\n  🎯 勝負レース！')
    print(f'  軸: 車番{axis_num} {axis_name}  top_ev={top_ev:.2f}')
    print(f'\n  {"組み合わせ":<12}  {"EV":>7}  {"配分":>8}  {"オッズ":>8}')
    print(f'  {"─"*50}')
    for idx, (combo, unit) in enumerate(zip(bets, alloc)):
        ev2 = bev[idx][1]
        o = odds_dict.get(combo, 0)
        print(f'  {combo:<12}  {ev2:>7.3f}  ¥{unit:>6,}  {o:>7.1f}倍')
    print(f'\n  合計投資: ¥{sum(alloc):,}  ({len(bets)}点)')

# =========================================================
# 8〜12R を順番に予想
# =========================================================
print('\n🚀 伊東競輪 3/4 テスト予想 (LOOSE-B 軸固定) 開始\n')
for race, lines in RACE_LINES.items():
    predict_race(race, lines)
print('\n\n✅ 全レース予想完了')
