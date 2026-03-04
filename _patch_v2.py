#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""s3_predictor.py に展開V2ロジックを挿入するパッチスクリプト"""

path = r'c:\pdca\s3_predictor.py'
with open(path, encoding='utf-8') as f:
    txt = f.read()

# ===== 1. BANK_DETAIL と load_rescored_db を挿入 =====
# calc_mental_score の後、simulate_race_development の前に挿入
BANK_DETAIL_CODE = '''

# ===== バンク詳細データ (keirin_bank_data.txt より抽出) =====
# ip/ep/dp/bp補正 / kant強度(0-2) / 直線長(m)
BANK_DETAIL = {
    '前橋':   {'ip':2,'ep':1,'dp':1,'bp':0,'kant':2.0,'straight':46.7},
    '松戸':   {'ip':3,'ep':2,'dp':-2,'bp':0,'kant':0.5,'straight':38.2},
    '小田原': {'ip':3,'ep':2,'dp':-2,'bp':0,'kant':1.8,'straight':36.1},
    '伊東':   {'ip':1,'ep':0,'dp':1,'bp':0,'kant':1.8,'straight':46.6},
    '富山':   {'ip':2,'ep':2,'dp':-1,'bp':0,'kant':1.0,'straight':43.0},
    '奈良':   {'ip':2,'ep':1,'dp':0,'bp':1,'kant':1.8,'straight':38.0},
    '防府':   {'ip':1,'ep':1,'dp':0,'bp':0,'kant':1.0,'straight':42.5},
    '西武園': {'ip':2,'ep':1,'dp':-1,'bp':1,'kant':0.5,'straight':47.6},
    '佐世保': {'ip':2,'ep':2,'dp':-1,'bp':0,'kant':0.5,'straight':40.2},
    '京都向日町':{'ip':1,'ep':1,'dp':0,'bp':0,'kant':1.8,'straight':47.3},
    '玉野':   {'ip':1,'ep':1,'dp':-1,'bp':0,'kant':1.0,'straight':47.9},
    '立川':   {'ip':0,'ep':-2,'dp':1,'bp':1,'kant':0.5,'straight':58.0},
    '京王閣': {'ip':0,'ep':0,'dp':0,'bp':0,'kant':0.5,'straight':54.0},
    '平塚':   {'ip':0,'ep':0,'dp':1,'bp':0,'kant':1.0,'straight':54.2},
    '川崎':   {'ip':0,'ep':-1,'dp':0,'bp':2,'kant':0.5,'straight':58.0},
    'いわき平':{'ip':-1,'ep':-2,'dp':2,'bp':0,'kant':1.5,'straight':62.7},
    '四日市': {'ip':-1,'ep':-2,'dp':2,'bp':0,'kant':1.2,'straight':62.4},
    '弥彦':   {'ip':-1,'ep':-2,'dp':0,'bp':2,'kant':0.5,'straight':63.1},
    '名古屋': {'ip':0,'ep':0,'dp':1,'bp':0,'kant':1.0,'straight':58.8},
    '小倉':   {'ip':0,'ep':1,'dp':2,'bp':0,'kant':1.0,'straight':56.9},
    '青森':   {'ip':0,'ep':0,'dp':0,'bp':0,'kant':1.5,'straight':58.9},
    '函館':   {'ip':0,'ep':0,'dp':0,'bp':0,'kant':1.0,'straight':51.3},
    '豊橋':   {'ip':0,'ep':0,'dp':0,'bp':0,'kant':1.5,'straight':60.3},
    '松阪':   {'ip':0,'ep':0,'dp':0,'bp':0,'kant':2.0,'straight':58.9},
    '和歌山': {'ip':0,'ep':0,'dp':0,'bp':0,'kant':1.0,'straight':59.9},
    '岸和田': {'ip':0,'ep':0,'dp':0,'bp':0,'kant':1.0,'straight':56.7},
    '広島':   {'ip':0,'ep':0,'dp':0,'bp':1,'kant':1.0,'straight':57.9},
    '松山':   {'ip':0,'ep':0,'dp':0,'bp':0,'kant':2.0,'straight':58.6},
    '高松':   {'ip':0,'ep':0,'dp':0,'bp':0,'kant':1.0,'straight':54.5},
    '小松島': {'ip':0,'ep':0,'dp':0,'bp':0,'kant':1.0,'straight':55.5},
    '武雄':   {'ip':0,'ep':-2,'dp':1,'bp':2,'kant':1.0,'straight':64.4},
    '別府':   {'ip':0,'ep':0,'dp':0,'bp':0,'kant':1.0,'straight':59.9},
    '熊本':   {'ip':0,'ep':-1,'dp':2,'bp':0,'kant':2.0,'straight':60.9},
    '岐阜':   {'ip':0,'ep':0,'dp':0,'bp':0,'kant':1.0,'straight':59.3},
    '大垣':   {'ip':0,'ep':0,'dp':0,'bp':0,'kant':1.0,'straight':56.0},
    '取手':   {'ip':0,'ep':0,'dp':0,'bp':0,'kant':1.0,'straight':54.8},
    '静岡':   {'ip':0,'ep':0,'dp':0,'bp':0,'kant':1.0,'straight':56.4},
    '宇都宮': {'ip':-1,'ep':-3,'dp':1,'bp':3,'kant':0.3,'straight':63.3},
    '大宮':   {'ip':-1,'ep':-3,'dp':2,'bp':0,'kant':0.3,'straight':66.7},
    '高知':   {'ip':1,'ep':-1,'dp':-2,'bp':0,'kant':0.2,'straight':52.0},
    '久留米': {'ip':0,'ep':0,'dp':0,'bp':0,'kant':1.0,'straight':50.7},
}


def load_rescored_db(csv_path: str) -> pd.DataFrame:
    """
    top30_rescored_rank_change.csv を読み込んで
    選手別スコア（千切れリスク・隠れ鬼脚・死に駆け忠誠度）を返す。
    """
    try:
        df = pd.read_csv(csv_path, encoding='utf-8-sig')
    except Exception:
        try:
            df = pd.read_csv(csv_path, encoding='cp932')
        except Exception:
            return pd.DataFrame()
    df['選手名_norm'] = df['選手名'].apply(normalize_name)
    for col in ['新_千切れリスク', '新_隠れ鬼脚指数', '新_死に駆け忠誠度', '新_突っ込み力']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    return df


def _get_bank_detail(venue: str) -> dict:
    return BANK_DETAIL.get(venue, {'ip':0,'ep':0,'dp':0,'bp':0,'kant':1.0,'straight':55.0})

'''

NEW_SIMULATE = '''def simulate_race_development(player_scores: dict, line_map: dict,
                              venue: str = '',
                              rescored_df: pd.DataFrame = None) -> dict:
    """
    3フェーズ展開シミュレーション V2

    Phase① 主導権争い (どのラインが逃げるか)
    Phase② 捲りタイミング  (捲りラインの仕掛け時期)
    Phase③ 番手攻防    (独自スコアでEV計算)

    Returns: {車番: 展開適性EVスコア}
    """
    bk = _get_bank_detail(venue)
    kant = bk.get('kant', 1.0)
    straight = bk.get('straight', 55.0)
    bank_length = BANK_DICT.get(venue, {}).get('length', 400)
    is_short = bank_length <= 335
    is_long_straight = straight >= 60.0

    def get_rs(name_norm):
        if rescored_df is None or rescored_df.empty:
            return {}
        row = rescored_df[rescored_df['選手名_norm'] == name_norm]
        return row.iloc[0].to_dict() if not row.empty else {}

    # =====================================================
    # Phase①: 主導権争い --- 先行意欲スコア
    # =====================================================
    lead_will = {}
    for lno, bibs in line_map.items():
        if not bibs:
            continue
        head_num = bibs[0]
        sc = player_scores.get(head_num, {})
        ip   = sc.get('ip', 4.0) + bk.get('ip', 0)
        ep   = sc.get('ep', 4.0) + bk.get('ep', 0)
        sty  = str(sc.get('style', ''))
        line_len = len(bibs)
        style_bonus = {'逃': 1.8, '先': 1.3, '両': 0.8, '追': 0.3}.get(sty[:1], 0.8)
        short_bonus = 1.5 if is_short else 1.0
        rs = get_rs(normalize_name(sc.get('name', '')))
        loyalty = float(rs.get('新_死に駆け忠誠度', 0)) / 100.0
        will = (ip * 1.5 + ep * 0.5) * style_bonus * short_bonus + line_len * 0.5 + loyalty * 2.0
        lead_will[lno] = max(0, will)

    vals = sorted(lead_will.values(), reverse=True) if lead_will else [4.0]
    max_will = vals[0] if vals else 1.0
    n_high   = sum(1 for v in vals if v >= max_will * 0.85)
    lead_gap = max_will - vals[1] if len(vals) >= 2 else max_will

    if n_high >= 2:
        phase1 = 'B_chaos'
        p_escape, p_makuri, p_chaos_dev, stamina_loss = 0.15, 0.45, 0.40, 2.0
    elif lead_gap > max_will * 0.3:
        phase1 = 'A_smooth'
        p_escape, p_makuri, p_chaos_dev, stamina_loss = 0.55, 0.30, 0.15, 0.5
    else:
        phase1 = 'C_slow'
        p_escape, p_makuri, p_chaos_dev, stamina_loss = 0.25, 0.30, 0.45, 0.0

    kant_bonus = kant * 0.15

    # =====================================================
    # Phase②: 捲りタイミング
    # =====================================================
    def phase2_power(sc_):
        dp  = sc_.get('dp', 3.0) + bk.get('dp', 0)
        ep_ = sc_.get('ep', 4.0) + bk.get('ep', 0)
        rs_ = get_rs(normalize_name(sc_.get('name', '')))
        hid = float(rs_.get('新_隠れ鬼脚指数', 0)) / 100.0
        if dp > ep_ + 0.5:
            return dp * (1 + kant_bonus) + hid * 3
        elif ep_ > dp + 0.5:
            return ep_ * (1 + kant_bonus) + hid * 2
        else:
            return (dp + ep_) / 2 * (1 + kant_bonus) + hid * 2

    # =====================================================
    # Phase③: 番手攻防スコア
    # =====================================================
    dev_scores = {}
    for num, sc in player_scores.items():
        lno  = sc.get('line_no', 0)
        pos  = sc.get('pos_in_line', 1)
        ip   = sc.get('ip', 4.0) + bk.get('ip', 0)
        ep   = sc.get('ep', 4.0) + bk.get('ep', 0)
        dp   = sc.get('dp', 3.0) + bk.get('dp', 0)
        bp   = sc.get('bp', 3.0) + bk.get('bp', 0)
        sty  = str(sc.get('style', ''))
        rs   = get_rs(normalize_name(sc.get('name', '')))
        chigire = float(rs.get('新_千切れリスク', 0)) / 100.0
        hidden  = float(rs.get('新_隠れ鬼脚指数', 0)) / 100.0
        totsu   = float(rs.get('新_突っ込み力', 0)) / 100.0
        is_lead = lead_will.get(lno, 0) == max_will

        # Phase① 影響: 先行ライン有利
        if is_lead:
            if pos == 1:
                escape_val = p_escape * ip * 1.8
            elif pos == 2:
                block_power = bp * (1 - chigire * 0.5)
                escape_val  = p_escape * min(ip, block_power) * 1.2
            else:
                escape_val = p_escape * 0.3
        else:
            escape_val = 0.0

        # Phase② 影響: 捲りタイミングEV
        if not is_lead and pos == 1:
            makuri_val = p_makuri * phase2_power(sc) * 0.9
        elif not is_lead and pos >= 2:
            makuri_val = p_makuri * dp * 0.5
        else:
            makuri_val = 0.0

        # Phase③ 分岐
        p3a = p_escape * bp * 1.0 * (1 - stamina_loss * 0.1) if (is_lead and pos == 2 and chigire < 0.4) else 0.0
        p3c = p_makuri * totsu * 1.5 if (is_lead and pos == 2 and chigire >= 0.4) else 0.0
        p3e = p_chaos_dev * hidden * 3.0 if (is_long_straight and hidden > 0.5 and p_chaos_dev > 0.3 and pos >= 2) else 0.0

        style_chaos_coeff = 1.3 if '両' in sty else (1.1 if '追' in sty else 0.7)
        chaos_val = p_chaos_dev * bp * style_chaos_coeff * 0.6

        dev_scores[num] = escape_val + makuri_val + p3a + p3c + p3e + chaos_val

    return dev_scores
'''

# ===== 挿入位置を特定 =====
# calc_mental_score 関数の後、その次のdef行の前
import re

# calc_mental_score 後の位置を探す
match = list(re.finditer(r'\ndef simulate_race_development\(', txt))
if match:
    # 既存の関数を見つけて置換
    start = match[0].start()
    # 関数の終端を探す (次のdef行)
    rest = txt[start+1:]
    next_def = re.search(r'\n\ndef ', rest)
    if next_def:
        end = start + 1 + next_def.start()
    else:
        end = len(txt)
    txt = txt[:start] + '\n\n' + NEW_SIMULATE.strip() + '\n\n\n' + txt[end:]
    print('✅ simulate_race_development を V2に置換')
else:
    # 存在しない場合は calc_mental_score の後に挿入
    mc = list(re.finditer(r'\ndef run_s3_prediction\(', txt))
    if mc:
        ins = mc[0].start()
        txt = txt[:ins] + '\n\n' + NEW_SIMULATE.strip() + '\n\n\n' + txt[ins:]
        print('✅ simulate_race_development V2を新規挿入')
    else:
        print('⚠ 挿入位置が見つかりません')

# ===== BANK_DETAIL + load_rescored_db を calc_mental_score の後に挿入 =====
if 'BANK_DETAIL' not in txt:
    mcs = list(re.finditer(r'\ndef simulate_race_development\(', txt))
    if mcs:
        ins = mcs[0].start()
        txt = txt[:ins] + BANK_DETAIL_CODE + txt[ins:]
        print('✅ BANK_DETAIL + load_rescored_db を挿入')
else:
    print('ℹ BANK_DETAIL は既に存在')

# ===== run_s3_prediction の引数に rescored_df を追加 =====
if 'rescored_df' not in txt:
    txt = txt.replace(
        'relations_df=None,      # load_racer_relations() の結果（任意）\n)',
        'relations_df=None,      # load_racer_relations() の結果（任意）\n    rescored_df=None,       # load_rescored_db() の結果（任意）\n)',
        1
    )
    print('✅ run_s3_prediction に rescored_df 引数追加')
else:
    print('ℹ rescored_df は既に存在')

# ===== Phase 2.5のsimulate呼び出しにvenue/rescored_dfを追加 =====
old_call = 'dev_scores = simulate_race_development(player_scores, line_map)'
new_call = 'dev_scores = simulate_race_development(player_scores, line_map, venue=venue, rescored_df=rescored_df)'
if old_call in txt:
    txt = txt.replace(old_call, new_call, 1)
    print('✅ simulate_race_development 呼び出しを更新')
elif new_call in txt:
    print('ℹ 呼び出しは既に更新済み')
else:
    print('⚠ simulate_race_development の呼び出しが見つかりません')

with open(path, 'w', encoding='utf-8') as f:
    f.write(txt)

print('\n🏁 s3_predictor.py パッチ完了')
