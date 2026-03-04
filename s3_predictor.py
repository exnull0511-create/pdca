"""
S3予想ロジック スタンドアロンモジュール
hardcore_ev.py のコアロジックを関数として切り出し、
Streamlit アプリから呼び出せるようにしたもの。
"""
import sys
import os
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# S3フィルタ設定（hardcore_ev.py の S3 と同一）
S3_CONFIG = {
    "min_top_ev":          70,
    "require_monster":     True,
    "skip_chaos":          False,
    "s3_chaos_filter":     True,
    "chaos_buy_leaders_ge": 5,
    "chaos_buy_ev_ge":      91,
    "chaos_buy_ev_gap_le":   3,
    "bet_base":            100,
    "bet_high":            200,
    "bet_high_ev_th":       90,
    "skip_low_bank":       False,
}

# バンク特性辞書（roi_tier付き）
BANK_DICT = {
    '前橋':   {'type': '超高速', 'length': 335, 'sashi': 0.8, 'makuri': 1.2, 'roi_tier': 'mid'},
    '宇都宮': {'type': '重い',   'length': 500, 'sashi': 1.5, 'makuri': 1.1, 'roi_tier': 'high'},
    '豊橋':   {'type': '風強',   'length': 400, 'sashi': 1.3, 'makuri': 1.2, 'roi_tier': 'high'},
    '岸和田': {'type': '波状',   'length': 400, 'sashi': 1.1, 'makuri': 1.3, 'roi_tier': 'low'},
    '熊本':   {'type': '標準',   'length': 400, 'sashi': 1.2, 'makuri': 1.1, 'roi_tier': 'high'},
    'いわき平':{'type':'短走路', 'length': 335, 'sashi': 0.9, 'makuri': 1.3, 'roi_tier': 'mid'},
    '広島':   {'type': '重い',   'length': 400, 'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'mid'},
    '別府':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '松山':   {'type': '標準',   'length': 333, 'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '小倉':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '京王閣': {'type': '標準',   'length': 400, 'sashi': 1.0, 'makuri': 1.1, 'roi_tier': 'high'},
    '立川':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'high'},
    '取手':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '伊東':   {'type': '標準',   'length': 333, 'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '久留米': {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '奈良':   {'type': '標準',   'length': 400, 'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'low'},
    '岐阜':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '小松島': {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'low'},
    '防府':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '静岡':   {'type': '標準',   'length': 400, 'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'low'},
    '松阪':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '高知':   {'type': '標準',   'length': 400, 'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '松戸':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'mid'},
    '平塚':   {'type': '標準',   'length': 400, 'sashi': 1.2, 'makuri': 1.1, 'roi_tier': 'mid'},
    '函館':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '青森':   {'type': '標準',   'length': 400, 'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'mid'},
    '弥彦':   {'type': '標準',   'length': 333, 'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '川崎':   {'type': '超高速', 'length': 333, 'sashi': 0.8, 'makuri': 1.3, 'roi_tier': 'mid'},
    '西武園': {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '大宮':   {'type': '標準',   'length': 400, 'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'mid'},
    '松戸':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'mid'},
    '千葉':   {'type': '超高速', 'length': 333, 'sashi': 0.8, 'makuri': 1.3, 'roi_tier': 'mid'},
    '京都向日町': {'type': '標準','length': 333,'sashi': 1.0,'makuri': 1.2,'roi_tier': 'mid'},
    '和歌山': {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '玉野':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'mid'},
    '高松':   {'type': '標準',   'length': 400, 'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '大分':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '佐世保': {'type': '標準',   'length': 400, 'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'mid'},
    '武雄':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '福岡':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.2, 'roi_tier': 'mid'},
}

SENPO_LEAD = {
    '逃げ切り': 5, '逃げ粘り': 4, '突っ張り先行': 4, '抑え先行': 4,
    'カマシ先行': 5, '先行逃げ切り': 5, '先行': 4, '逃げ': 5,
    '先行争い敗北': 3, '先行争い敗': 3,
    '一発捲り': 3, 'ロング捲り': 3, '捲り': 3, '番手捲り': 3,
    'カマシ捲り': 4, '捲り差し': 3, '捲り追い込み': 2, '捲り不発': 2,
    '番手差し': 2, '差し': 2, '追い込み': 2, '流れ込み': 1,
    '追走': 1, 'マーク': 1,
}


def normalize_name(s: str) -> str:
    return str(s).replace(" ", "").replace("\u3000", "").strip()


def nobi_score(val) -> int:
    s = str(val).strip().upper()
    if s.startswith('S'):   return 5
    elif s.startswith('A'): return 4
    elif s.startswith('B'): return 3
    elif s.startswith('C'): return 1
    return 2


def senpo_lead(val) -> int:
    return SENPO_LEAD.get(str(val).strip(), 1)


def load_sclass_db(xlsx_path: str) -> pd.DataFrame:
    """
    S級選手究極DBをロードする。
    F1 / G3~1 シートを連結して返す。
    """
    xl    = pd.ExcelFile(xlsx_path)
    db_f1 = xl.parse('F1')
    db_g3 = xl.parse('G3~1')
    db    = pd.concat([db_f1, db_g3], ignore_index=True)
    db['開催日']      = pd.to_datetime(db['開催日'], errors='coerce')
    db['IP']          = pd.to_numeric(db['IP'], errors='coerce')
    db['EP']          = pd.to_numeric(db['EP'], errors='coerce')
    db['DP']          = pd.to_numeric(db['DP'], errors='coerce')
    db['BP']          = pd.to_numeric(db['BP'], errors='coerce')
    db['選手名_norm'] = db['選手名'].apply(normalize_name)
    return db


def load_racer_relations(csv_path: str) -> pd.DataFrame:
    """
    s_class_racers.csv を読み込んで選手関係DBを返す。
    各選手に対して「師弟・練習仲間・ホームバンク・得意周長」を保持。
    """
    try:
        df = pd.read_csv(csv_path, encoding='utf-8-sig')
    except Exception:
        try:
            df = pd.read_csv(csv_path, encoding='cp932')
        except Exception:
            return pd.DataFrame()
    df['選手名_norm'] = df['選手名'].apply(normalize_name)
    # 数値化できる周長を抽出 (例: "400m" → 400, "333m" → 333)
    def parse_length(s):
        import re
        if pd.isna(s) or str(s).strip() in ('-', ''):
            return None
        m = re.search(r'(\d+)', str(s))
        return int(m.group(1)) if m else None
    df['好きな周長_int'] = df['好きな周長'].apply(parse_length)
    return df


def _extract_names(cell: str) -> list:
    """「山田 太郎（東京・99期）、鈴木 一郎（...）」形式から選手名リストを抽出"""
    import re
    if pd.isna(cell) or str(cell).strip() in ('-', ''):
        return []
    # 括弧の前の名前部分を抽出してnormalize
    names = re.findall(r'([\u3000-\u9FFF一-龥ぁ-ん\u30a1-\u30f6]+\s*[\u3000-\u9FFF一-龥ぁ-ん\u30a1-\u30f6]+)', str(cell))
    return [normalize_name(n) for n in names if len(normalize_name(n)) >= 2]


def calc_line_synergy(name_norm: str, line_bibs: list,
                      num_to_name: dict, relations_df: pd.DataFrame) -> float:
    """
    同ライン内の師弟・縁故・練習仲間関係からライン連携スコアを計算。
    
    Returns: 0.0 ~ 5.0 のスコア
    """
    if relations_df is None or relations_df.empty:
        return 0.0
    row = relations_df[relations_df['選手名_norm'] == name_norm]
    if row.empty:
        return 0.0
    row = row.iloc[0]

    # 同ライン内の他選手名
    other_names = set()
    for b, n in num_to_name.items():
        if n != name_norm and b in line_bibs:
            other_names.add(n)

    score = 0.0
    for col, bonus in [('師匠', 2.5), ('弟子', 2.0), ('縁故選手', 2.0),
                       ('練習仲間', 1.5), ('練習グループ', 0.5)]:
        if col not in row.index:
            continue
        related = set(_extract_names(str(row[col])))
        if related & other_names:
            score += bonus
    return min(score, 5.0)


def calc_mental_score(name_norm: str, venue: str, bank_length: int,
                      relations_df: pd.DataFrame) -> float:
    """
    ホームバンク一致・好きな周長一致で心理的有利スコアを返す。
    
    Returns: 0.0 ~ 3.5
    """
    if relations_df is None or relations_df.empty:
        return 0.0
    row = relations_df[relations_df['選手名_norm'] == name_norm]
    if row.empty:
        return 0.0
    row = row.iloc[0]

    score = 0.0
    # ホームバンク一致
    home = str(row.get('ホームバンク', '')).strip()
    if home and home != '-' and home != 'nan' and home in venue:
        score += 2.0
    # 得意周長一致
    fav_len = row.get('好きな周長_int', None)
    if fav_len and not pd.isna(fav_len) and bank_length:
        if int(fav_len) == int(bank_length):
            score += 1.5
    return score




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


def simulate_race_development(player_scores: dict, line_map: dict,
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




def run_s3_prediction(
    race_card_df: pd.DataFrame,
    lines: list,            # KdreamsScraper.get_race_lines() の結果
    odds_df: pd.DataFrame,  # KdreamsScraper.get_odds() の結果
    db_all: pd.DataFrame,   # load_sclass_db() の結果
    venue: str,
    race_date=None,         # datetime.date / None で全履歴使用
    relations_df=None,      # load_racer_relations() の結果（任意）
    rescored_df=None,       # load_rescored_db() の結果（任意）
) -> dict:
    """
    S3ロジックで三連単予想を実行する。

    Returns:
        {
          'ranked':      [(車番, スコア辞書), ...],
          'bets':        ['1-2-3', ...],        # 14点
          'is_chaos':    bool,
          'has_monster': bool,
          'top_ev':      float,
          'ev_gap':      float,
          'chaos_count': int,
          's3_pass':     bool,   # S3フィルタ通過か
          's3_skip_reason': str, # スキップ理由（通過時は空文字）
          'bet_unit':    int,    # 1点あたりの金額(円)
        }
    """
    if race_card_df is None or race_card_df.empty:
        return _empty_result("出走表データなし")

    cfg      = S3_CONFIG
    bank     = BANK_DICT.get(venue, {'type': '標準', 'length': 400,
                                      'sashi': 1.0, 'makuri': 1.0, 'roi_tier': 'mid'})
    # 過去データのみ使用
    if race_date is not None:
        import pandas as _pd
        past_db = db_all[db_all['開催日'] < _pd.Timestamp(race_date)]
    else:
        past_db = db_all

    nobi_col = [c for c in db_all.columns if '直線' in c][0]

    # ライン構成を解析（KdreamsScraper.get_race_lines() の形式）
    # lines = [{'line': 1, 'bibs': [7, 3]}, {'line': 2, 'bibs': [1]}, ...]
    line_map = {}   # {line_no: [車番, ...]}
    for item in (lines or []):
        line_map[item['line']] = item['bibs']

    num_to_line = {}
    for lno, bibs in line_map.items():
        for b in bibs:
            num_to_line[b] = lno

    # 数値変換
    for col in ['競走得点', 'S', 'B', '逃', '捲', '差', 'マ', '1着', '2着', '3着', '着外']:
        if col in race_card_df.columns:
            race_card_df[col] = pd.to_numeric(race_card_df[col], errors='coerce').fillna(0)

    # ---- Phase 2: EVスコア計算 ----
    player_scores = {}
    for _, row in race_card_df.iterrows():
        try:
            num  = int(row['車番'])
            name = str(row['選手名'])
            norm = normalize_name(name)

            base_score = float(row.get('競走得点', 50))

            hist   = past_db[past_db['選手名_norm'] == norm]
            ip_avg = hist['IP'].mean() if not hist.empty else 4.0
            ep_avg = hist['EP'].mean() if not hist.empty else 4.0
            dp_avg = hist['DP'].mean() if not hist.empty else 3.0
            bp_avg = hist['BP'].mean() if not hist.empty else 3.0
            # NaN を安全なデフォルト値に置換（ループ変数代入は効かないので直接置換）
            if pd.isna(ip_avg): ip_avg = 4.0
            if pd.isna(ep_avg): ep_avg = 4.0
            if pd.isna(dp_avg): dp_avg = 3.0
            if pd.isna(bp_avg): bp_avg = 3.0

            avg_nobi  = hist[nobi_col].apply(nobi_score).mean() if not hist.empty else 2.0
            avg_senpo_s = hist['戦法'].apply(senpo_lead) if not hist.empty else pd.Series([2.0])
            avg_senpo = pd.to_numeric(avg_senpo_s, errors='coerce').mean() if not hist.empty else 2.0
            if np.isnan(avg_nobi):  avg_nobi  = 2.0
            if np.isnan(avg_senpo) or pd.isna(avg_senpo): avg_senpo = 2.0

            comments      = " ".join(hist['解析コメント'].astype(str).tolist()) if not hist.empty else ""
            is_monster    = any(kw in comments for kw in ["脚余し", "鬼脚", "別次元", "圧倒", "豪快"])
            is_unreliable = any(kw in comments for kw in ["共倒れ", "位置取り失敗", "不発", "失速"])

            lno         = num_to_line.get(num, 0)
            line_bibs   = line_map.get(lno, [])
            pos_in_line = line_bibs.index(num) + 1 if num in line_bibs else 1
            line_bonus  = 0.5 if pos_in_line == 1 else (-0.3 * (pos_in_line - 1))

            base_ev = (
                base_score * 0.4
                + ip_avg   * 1.5
                + ep_avg   * 1.2
                + dp_avg   * bank['makuri']
                + bp_avg   * bank['sashi']
                + avg_nobi * 2.0
                + avg_senpo * 0.5
                + line_bonus
                + (3.0 if is_monster   else 0)
                - (2.0 if is_unreliable else 0)
            )

            player_scores[num] = {
                'name':          name,
                'ev_score':      base_ev,   # 後で展開EVを加算
                'base_ev':       base_ev,
                'base_score':    base_score,
                'ip':            ip_avg, 'ep': ep_avg,
                'dp':            dp_avg, 'bp': bp_avg,
                'nobi':          avg_nobi,
                'senpo':         avg_senpo,
                'is_monster':    is_monster,
                'is_unreliable': is_unreliable,
                'hist_count':    len(hist),
                'style':         str(row.get('脚質', '')),
                'line_no':       lno,
                'pos_in_line':   pos_in_line,
            }
        except Exception:
            continue

    if not player_scores:
        return _empty_result("EVスコア計算失敗")

    # ---- Phase 2.5: 展開予想EV 追加レイヤー ----
    # 選手名辞書（車番 -> 選手名_norm）
    num_to_name = {num: normalize_name(sc['name']) for num, sc in player_scores.items()}
    bank_length = bank.get('length', 400)

    # 展開シミュレーション（ライン先行憶大・捐り・差し展開確率）
    dev_scores = simulate_race_development(player_scores, line_map, venue=venue, rescored_df=rescored_df)

    for num, sc in player_scores.items():
        norm = normalize_name(sc['name'])
        lno  = sc['line_no']
        bibs = line_map.get(lno, [])

        # Layer 1: ライン連携スコア（師弟・練習仲間）
        synergy = calc_line_synergy(norm, bibs, num_to_name, relations_df)
        # Layer 2: 展開適性スコア
        dev    = dev_scores.get(num, 0.0)
        # Layer 3: 心理・地の利スコアメンタル
        mental = calc_mental_score(norm, venue, bank_length, relations_df)

        # 展開混合EV（元スコアを少しリスケールして展開要素を加算）
        sc['ev_score'] = sc['base_ev'] * 0.7 + synergy * 1.0 + dev * 0.5 + mental * 0.8
        sc['synergy']  = synergy
        sc['dev_score']= dev
        sc['mental']   = mental


    ranked = sorted(player_scores.items(), key=lambda x: x[1]['ev_score'], reverse=True)

    # ---- Phase 3: カオス判定 ----
    strong_leaders = [
        d['name'] for _, d in player_scores.items()
        if d['ip'] >= 5.5 and d['pos_in_line'] == 1
    ]
    hidden_monsters = [(n, d) for n, d in ranked if d['is_monster']]
    is_chaos    = len(strong_leaders) >= 2
    has_monster = bool(hidden_monsters)
    top_ev      = ranked[0][1]['ev_score'] if ranked else 0
    ev_gap      = (ranked[0][1]['ev_score'] - ranked[1][1]['ev_score']) if len(ranked) >= 2 else 0
    chaos_count = len(strong_leaders)

    # S3フィルタ庳止: 常に全レース購入
    s3_pass     = True
    skip_reason = ''

    # ---- Phase 4: 買い目構築 ----
    if hidden_monsters:
        axis_num = hidden_monsters[0][0]
    else:
        axis_num = ranked[0][0]

    others_ranked = [n for n, _ in ranked if n != axis_num]
    bet_combinations = []
    for second in others_ranked:
        for third in others_ranked:
            if second != third:
                combo = f"{axis_num}-{second}-{third}"
                if combo not in bet_combinations:
                    bet_combinations.append(combo)
                if len(bet_combinations) == 14:
                    break
        if len(bet_combinations) == 14:
            break

    bet_unit = cfg['bet_high'] if top_ev >= cfg['bet_high_ev_th'] else cfg['bet_base']

    return {
        'ranked':           ranked,
        'player_scores':    player_scores,
        'bets':             bet_combinations,
        'axis_num':         axis_num,
        'is_chaos':         is_chaos,
        'has_monster':      has_monster,
        'strong_leaders':   strong_leaders,
        'hidden_monsters':  hidden_monsters,
        'top_ev':           top_ev,
        'ev_gap':           round(ev_gap, 1),
        'chaos_count':      chaos_count,
        'line_map':         line_map,
        'bank':             bank,
        's3_pass':          s3_pass,
        's3_skip_reason':   skip_reason,
        'bet_unit':         bet_unit,
    }


def _check_s3_filter(meta: dict, cfg: dict) -> tuple[bool, str]:
    """S3フィルタ条件チェック。(通過か, スキップ理由) を返す。"""
    if meta['top_ev'] < cfg['min_top_ev']:
        return False, f"軸EV {meta['top_ev']:.1f} < 下限{cfg['min_top_ev']}"

    if cfg['require_monster'] and not meta['has_monster']:
        return False, "鬼脚（Hidden Monster）なし"

    if meta['is_chaos']:
        if cfg.get('s3_chaos_filter'):
            buy_leaders = meta['chaos_count'] >= cfg['chaos_buy_leaders_ge']
            buy_ev      = meta['top_ev']      >= cfg['chaos_buy_ev_ge']
            buy_gap     = (meta['ev_gap'] <= cfg['chaos_buy_ev_gap_le'] and meta['has_monster'])
            if not (buy_leaders or buy_ev or buy_gap):
                return False, (
                    f"捨てるカオス展開 "
                    f"(先行役{meta['chaos_count']}人 EV={meta['top_ev']:.1f} EV差={meta['ev_gap']:.1f})"
                )
    return True, ""


def _empty_result(reason: str) -> dict:
    return {
        'ranked': [], 'player_scores': {}, 'bets': [],
        'axis_num': None, 'is_chaos': False, 'has_monster': False,
        'strong_leaders': [], 'hidden_monsters': [],
        'top_ev': 0, 'ev_gap': 0, 'chaos_count': 0,
        'line_map': {}, 'bank': {},
        's3_pass': False, 's3_skip_reason': reason, 'bet_unit': 100,
    }
