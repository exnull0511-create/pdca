import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# ==========================================
# 🎮 STRATEGY 設定（ここを変えるだけで切り替え）
# ==========================================
# S1 : フィルタなし・全レース14点買い（ベースライン）
# S2 : 改善版（カオス展開除外 / EV61-70除外 / 鬼脚なし除外）
STRATEGY = "S_MAXHIT_14_EV_LOOSE_B"  # ← 本採用: EV傾斜+EV70+chaos除外+低bank除外 (73R/525%)

STRATEGY_CONFIGS = {
    "S1": {
        "name":               "ベースライン（フィルタなし・全レース）",
        "skip_chaos":         False,
        "min_top_ev":         0,
        "require_monster":    False,
        "s3_chaos_filter":    False,
        "use_full_permutation": True,   # ← 全順列PL+均等下限フィルタ
    },
    "S2": {
        "name":               "改善版（カオス除外 / EV<70除外 / 鬼脚必須）",
        "skip_chaos":         True,
        "min_top_ev":         70,
        "require_monster":    True,
        "s3_chaos_filter":    False,
        "use_full_permutation": True,   # ← 全順列PL+均等下限フィルタ
    },
    "S3": {
        "name":               "カオス細分判定版（読めるカオスは買う）",
        "skip_chaos":         False,
        "min_top_ev":         70,
        "require_monster":    True,
        "s3_chaos_filter":    True,
        "chaos_buy_leaders_ge": 5,
        "chaos_buy_ev_ge":      91,
        "chaos_buy_ev_gap_le":   3,
        # ベットコントロール
        "bet_base":           100,
        "bet_high":           200,
        "bet_high_ev_th":      90,
        # バンクROIフィルタ
        "skip_low_bank":      False,
        "use_full_permutation": False,  # 軸固定 PL
        "top_n_bets":          1,         # EV順上位1点のみ購入（グリッドサーチ最適値）
    },
    "S4": {
        "name":               "ROI最大化版（EV80以上 / カオスEV91orリーダー5人 / BC付き）",
        "skip_chaos":         False,
        "min_top_ev":         80,
        "require_monster":    True,
        "s3_chaos_filter":    True,
        "chaos_buy_leaders_ge": 5,
        "chaos_buy_ev_ge":      91,
        "chaos_buy_ev_gap_le":   0,
        # ベットコントロール
        "bet_base":           100,
        "bet_high":           200,
        "bet_high_ev_th":      90,
        # バンクROIフィルタ
        "skip_low_bank":      True,
        "use_full_permutation": False,  # 軸固定 PL
        "top_n_bets":          1,         # EV順上位1点のみ購入
    },
    "S_UNION": {
        # 実戦用ユニオン: S2∨S3∨S4いずれか通過でベット、クロス数で増額
        "name":               "S234ユニオン（S2∨S3∨S4通過 + クロス増額）",
        "skip_chaos":         False,
        "min_top_ev":         0,
        "require_monster":    False,
        "s3_chaos_filter":    False,
        "use_union_filter":   True,    # S2∨S3∨S4 判定モード
        "use_full_permutation": False, # 軸固定-PL
        "bet_base":           100,
        "skip_low_bank":      False,
    },
    # =====================================================
    # S_MAXHIT: 的中最大化モード
    # EV / オッズは完全無視。PL確率上位N点を買う。
    # 「モデルが最も来ると思う組み合わせ」に全集中。
    # =====================================================
    "S_MAXHIT_3": {
        "name":               "的中最大化×3点（PL確率Top3・EVなし）",
        "skip_chaos":         False,
        "min_top_ev":         0,
        "require_monster":    False,
        "s3_chaos_filter":    False,
        "use_full_permutation": False,  # 軸固定-PL（軸=EVスコア1位）
        "top_n_prob_bets":    3,
    },
    "S_MAXHIT_7": {
        "name":               "的中最大化×7点（PL確率Top7・EVなし）",
        "skip_chaos":         False,
        "min_top_ev":         0,
        "require_monster":    False,
        "s3_chaos_filter":    False,
        "use_full_permutation": False,
        "top_n_prob_bets":    7,
    },
    "S_MAXHIT_14": {
        "name":               "的中最大化×14点（PL確率Top14・EVなし）",
        "skip_chaos":         False,
        "min_top_ev":         0,
        "require_monster":    False,
        "s3_chaos_filter":    False,
        "use_full_permutation": False,
        "top_n_prob_bets":    14,
    },
    # =====================================================
    # S_MAXHIT_14_EV: 的中最大化 + 高EV傾斜配分モード
    # 買い目はS_MAXHIT_14と同じPL確率上位14点を選択。
    # ただし各買い目へのベット額をEV値に比例して配分する。
    # ベース総額 = bet_base × 14 を各点のEV値で按分。
    # 最低100円/点保証・100円単位丸め。
    # =====================================================
    "S_MAXHIT_14_EV": {
        "name":               "的中最大化×14点（PL確率Top14 + 高EV傾斜配分）",
        "skip_chaos":         False,
        "min_top_ev":         0,
        "require_monster":    False,
        "s3_chaos_filter":    False,
        "use_full_permutation": False,
        "top_n_prob_bets":    14,
        "ev_alloc":           True,   # EV比例配分モード
        "bet_base":           100,    # 1点あたりの基準額（総額 = bet_base × 14 = 1400円）
    },
    # =====================================================
    # S_MAXHIT_14_EV_FINAL: グリッドサーチ最適フィルター（ROI最高）
    # 🥇 ROI=524% / 39R / 的中率28.2%
    # skip_chaos=True / min_top_ev=75 / require_monster=True / skip_low_bank=True
    # =====================================================
    "S_MAXHIT_14_EV_FINAL": {
        "name":               "EV傾斜配分【最適フィルター MAX-ROI】",
        "skip_chaos":         True,    # カオス展開は除外
        "min_top_ev":         75,      # EVスコア75以上のみ
        "require_monster":    True,    # 鬼脚選手が必須
        "s3_chaos_filter":    False,
        "use_full_permutation": False,
        "top_n_prob_bets":    14,
        "ev_alloc":           True,
        "bet_base":           100,
        "skip_low_bank":      True,    # 低ROIバンク除外
    },
    # =====================================================
    # S_MAXHIT_14_EV_BAL: グリッドサーチ最適バランス版
    # 🥈 ROI=479% / 46R / 的中率26.1%
    # skip_chaos=True / min_top_ev=70 / require_monster=True / skip_low_bank=True
    # =====================================================
    "S_MAXHIT_14_EV_BAL": {
        "name":               "EV傾斜配分【最適フィルター BALANCE】",
        "skip_chaos":         True,
        "min_top_ev":         70,
        "require_monster":    True,
        "s3_chaos_filter":    False,
        "use_full_permutation": False,
        "top_n_prob_bets":    14,
        "ev_alloc":           True,
        "bet_base":           100,
        "skip_low_bank":      True,
    },
    # =====================================================
    # LOOSE バリアント: 鬼脚必須を外して対象レースを増やす
    # （「確実な損切り」だけ除外して、それ以外は買う方針）
    # =====================================================
    "S_MAXHIT_14_EV_LOOSE_A": {
        # 🔹 require_monster外す / EV≥75 / skip_chaos / low_bank除外
        # グリッドサーチ予測 ~51R / ROI≈416%  (EV傾斜で実際はさらに高い見込み)
        "name":               "EV傾斜【LOOSE-A: 鬼脚なし+EV75+カオス除外+低bank除外】",
        "skip_chaos":         True,
        "min_top_ev":         75,
        "require_monster":    False,   # ← ここを外した
        "s3_chaos_filter":    False,
        "use_full_permutation": False,
        "top_n_prob_bets":    14,
        "ev_alloc":           True,
        "bet_base":           100,
        "skip_low_bank":      True,
    },
    "S_MAXHIT_14_EV_LOOSE_B": {
        # 🔸 require_monster外す / EV≥70 / skip_chaos / low_bank除外
        # グリッドサーチ予測 ~73R / ROI≈345%
        "name":               "EV傾斜【LOOSE-B: 鬼脚なし+EV70+カオス除外+低bank除外】",
        "skip_chaos":         True,
        "min_top_ev":         70,
        "require_monster":    False,
        "s3_chaos_filter":    False,
        "use_full_permutation": False,
        "top_n_prob_bets":    14,
        "ev_alloc":           True,
        "bet_base":           100,
        "skip_low_bank":      True,
    },
    "S_MAXHIT_14_EV_LOOSE_C": {
        # 🔶 require_monster外す / EV≥65 / skip_chaos / low_bank除外
        # グリッドサーチ予測 ~80R / ROI≈325%
        "name":               "EV傾斜【LOOSE-C: 鬼脚なし+EV65+カオス除外+低bank除外】",
        "skip_chaos":         True,
        "min_top_ev":         65,
        "require_monster":    False,
        "s3_chaos_filter":    False,
        "use_full_permutation": False,
        "top_n_prob_bets":    14,
        "ev_alloc":           True,
        "bet_base":           100,
        "skip_low_bank":      True,
    },
}

SCFG = STRATEGY_CONFIGS[STRATEGY]
print(f"🎮 Strategy: {STRATEGY} — {SCFG['name']}")

# ==========================================
# Phase 0: データのロードと前処理
# ==========================================
print("🔥 Loading Hardcore EV Datasets...")

def normalize_name(s):
    """選手名の空白を除去して比較用に正規化"""
    return str(s).replace(" ", "").replace("\u3000", "").strip()

# ---- XLSXロード -----------------------------------------------------
# racecard.xlsxに出走表・ライン情報が統合済み
# payouts.xlsxに結果・払戻が統合済み
racecard_raw = pd.read_excel("data/racecard.xlsx", dtype={'race_id': str})
odds_raw     = pd.read_excel("data/odds.xlsx",     dtype={'race_id': str})
payouts_raw  = pd.read_excel("data/payouts.xlsx",  dtype={'race_id': str})

# ---- S級選手究極DB ロード (F1 + G3~1 シート) --------------------------
xl     = pd.ExcelFile("data/S級選手究極DB(1).xlsx")
db_f1  = xl.parse('F1')
db_g3  = xl.parse('G3~1')
db_all = pd.concat([db_f1, db_g3], ignore_index=True)

db_all['開催日']      = pd.to_datetime(db_all['開催日'], errors='coerce')
db_all['IP']          = pd.to_numeric(db_all['IP'], errors='coerce')
db_all['EP']          = pd.to_numeric(db_all['EP'], errors='coerce')
db_all['DP']          = pd.to_numeric(db_all['DP'], errors='coerce')
db_all['BP']          = pd.to_numeric(db_all['BP'], errors='coerce')
db_all['選手名_norm'] = db_all['選手名'].apply(normalize_name)

# 直線の伸び列名（全角チルダ対応）
nobi_col = [c for c in db_all.columns if '直線' in c][0]

# ---- racecard 型整備 -------------------------------------------------
# race_id / result_trifecta の =" ... " 形式を除去（念のため）
for df in [racecard_raw, odds_raw, payouts_raw]:
    df['race_id'] = df['race_id'].apply(lambda v: str(v)[2:-1] if str(v).startswith('="') else str(v))
payouts_raw['result_trifecta'] = payouts_raw['result_trifecta'].apply(
    lambda v: str(v)[2:-1] if str(v).startswith('="') else str(v))

racecard_raw['date'] = pd.to_datetime(racecard_raw['date'].astype(str), format='%Y%m%d')

for col in ['競走得点', 'S', 'B', '逃', '捲', '差', 'マ', '1着', '2着', '3着', '着外']:
    racecard_raw[col] = pd.to_numeric(racecard_raw[col], errors='coerce').fillna(0)

odds_raw['オッズ'] = pd.to_numeric(odds_raw['オッズ'], errors='coerce')

# ==========================================
# バンク特性辞書
# ==========================================
# roi_tier: 'high'=高ROI実績バンク / 'mid'=標準 / 'low'=要注意バンク
# (S3実績データ: 久留米0%/岐阜0%/岸和田0%/防府3%/静岡24%/奈良29%/小松島14%を要注意に設定)
bank_dict = {
    '前橋':     {'type': '超高速', 'length': 335, 'sashi': 0.8, 'makuri': 1.2, 'roi_tier': 'mid'},
    '宇都宮':   {'type': '重い',   'length': 500, 'sashi': 1.5, 'makuri': 1.1, 'roi_tier': 'high'},
    '豊橋':     {'type': '風強',   'length': 400, 'sashi': 1.3, 'makuri': 1.2, 'roi_tier': 'high'},
    '岸和田':   {'type': '波状',   'length': 400, 'sashi': 1.1, 'makuri': 1.3, 'roi_tier': 'low'},
    '熊本':     {'type': '標準',   'length': 400, 'sashi': 1.2, 'makuri': 1.1, 'roi_tier': 'high'},
    'いわき平': {'type': '短走路', 'length': 335, 'sashi': 0.9, 'makuri': 1.3, 'roi_tier': 'mid'},
    '広島':     {'type': '重い',   'length': 400, 'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'mid'},
    '別府':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '松山':     {'type': '標準',   'length': 333, 'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '小倉':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '京王閣':   {'type': '標準',   'length': 400, 'sashi': 1.0, 'makuri': 1.1, 'roi_tier': 'high'},
    '立川':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'high'},
    '取手':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '伊東':     {'type': '標準',   'length': 333, 'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '久留米':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '奈良':     {'type': '標準',   'length': 400, 'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'low'},
    '岐阜':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '小松島':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'low'},
    '防府':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'low'},
    '静岡':     {'type': '標準',   'length': 400, 'sashi': 1.2, 'makuri': 1.0, 'roi_tier': 'low'},
    '松阪':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '高知':     {'type': '標準',   'length': 400, 'sashi': 1.0, 'makuri': 1.2, 'roi_tier': 'mid'},
    '松戸':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.0, 'roi_tier': 'mid'},
    '平塚':     {'type': '標準',   'length': 400, 'sashi': 1.2, 'makuri': 1.1, 'roi_tier': 'mid'},
}

# ==========================================
# ヘルパー関数
# ==========================================
def nobi_score(val):
    """直線の伸びをS=5/A=4/B=3/C=1に数値化"""
    s = str(val).strip().upper()
    if s.startswith('S'):   return 5
    elif s.startswith('A'): return 4
    elif s.startswith('B'): return 3
    elif s.startswith('C'): return 1
    return 2

SENPO_LEAD = {
    '逃げ切り': 5, '逃げ粘り': 4, '突っ張り先行': 4, '抑え先行': 4,
    'カマシ先行': 5, '先行逃げ切り': 5, '先行': 4, '逃げ': 5,
    '先行争い敗北': 3, '先行争い敗': 3,
    '一発捲り': 3, 'ロング捲り': 3, '捲り': 3, '番手捲り': 3,
    'カマシ捲り': 4, '捲り差し': 3, '捲り追い込み': 2, '捲り不発': 2,
    '番手差し': 2, '差し': 2, '追い込み': 2, '流れ込み': 1,
    '追走': 1, 'マーク': 1,
}

def senpo_lead(val):
    return SENPO_LEAD.get(str(val).strip(), 1)

def parse_lines(race_info):
    """
    racecard.csvのline_no / line_bibsからライン構成を解析する。
    戻り値: {line_no: [車番, ...], ...}
    例) line_bibs="5-3-1" → line 1のラインは [5, 3, 1]
    各選手は同じrace_id内で同じline_noを共有しており、
    line_bibsが同じライン全員に記録されている。
    """
    lines = {}
    for _, row in race_info.iterrows():
        lno  = int(row['line_no']) if not pd.isna(row['line_no']) else 0
        bibs = str(row['line_bibs'])
        if lno not in lines:
            try:
                lines[lno] = [int(x) for x in bibs.split('-') if x.isdigit()]
            except Exception:
                lines[lno] = []
    return lines

# ==========================================
# 予想ロジック・コア関数 (S級DB + ライン構成統合版)
# ==========================================
def analyze_race(race_id, venue, current_date, race_info, race_odds, past_db):
    """
    ライン構成（racecard.line_no/line_bibs）とS級DBを組み合わせたEV予想。
    未来遮断: past_db は current_date 未満のデータのみ。
    """
    bank_prof = bank_dict.get(venue, {'type': '標準', 'length': 400, 'sashi': 1.0, 'makuri': 1.0})

    if race_info.empty:
        return "", []

    racer_nums = race_info['車番'].tolist()

    # ---- Phase 1: ライン構成の解析 ----------------------------------------
    line_map = parse_lines(race_info)
    # 各車番がどのラインに属するか
    num_to_line = {}
    for lno, bibs in line_map.items():
        for b in bibs:
            num_to_line[b] = lno
    # ライン先頭（line_bibsの最初の車番）
    line_leaders = {lno: bibs[0] for lno, bibs in line_map.items() if bibs}

    # ---- Phase 2: 選手スコアテーブル構築 ------------------------------------
    player_scores = {}

    for _, row in race_info.iterrows():
        num  = int(row['車番'])
        name = str(row['選手名'])
        norm = normalize_name(name)

        # 基礎スコア
        base_score = float(row['競走得点'])

        # DB履歴照合（直近2開催分を重み3倍で住み付き平均）
        hist = past_db[past_db['選手名_norm'] == norm]

        if not hist.empty:
            # 直近2開催分を璹定（開催日の降順で並び、上位2開催日が対象）
            RECENT_W     = 3.0    # 直近2開催の重み倍率
            sorted_dates = sorted(hist['開催日'].dropna().unique(), reverse=True)
            recent_dates = set(sorted_dates[:2])   # 直近2開催日

            def wmean(series):
                """is_recentに応じた重み付き平均"""
                vals    = pd.to_numeric(series, errors='coerce')
                is_rec  = hist['開催日'].isin(recent_dates)
                weights = np.where(is_rec, RECENT_W, 1.0)
                mask    = vals.notna()
                if not mask.any(): return np.nan
                return float((vals[mask] * weights[mask]).sum() / weights[mask].sum())

            ip_avg    = wmean(hist['IP'])
            ep_avg    = wmean(hist['EP'])
            dp_avg    = wmean(hist['DP'])
            bp_avg    = wmean(hist['BP'])
            avg_nobi  = wmean(hist[nobi_col].apply(nobi_score))
            avg_senpo = wmean(hist['戦法'].apply(senpo_lead))
        else:
            ip_avg = ep_avg = 4.0
            dp_avg = bp_avg = 3.0
            avg_nobi = avg_senpo = 2.0

        # 欠損値 フォールバック
        if ip_avg is None or np.isnan(ip_avg):    ip_avg    = 4.0
        if ep_avg is None or np.isnan(ep_avg):    ep_avg    = 4.0
        if dp_avg is None or np.isnan(dp_avg):    dp_avg    = 3.0
        if bp_avg is None or np.isnan(bp_avg):    bp_avg    = 3.0
        if avg_nobi  is None or np.isnan(avg_nobi):  avg_nobi  = 2.0
        if avg_senpo is None or np.isnan(avg_senpo): avg_senpo = 2.0

        comments      = " ".join(hist['解析コメント'].astype(str).tolist()) if not hist.empty else ""
        is_monster    = any(kw in comments for kw in ["脚余し", "鬼脚", "別次元", "圧倒", "豪快"])
        is_unreliable = any(kw in comments for kw in ["共倒れ", "位置取り失敗", "不発", "失速"])

        # ライン内ポジション補正
        # ライン先頭（逃げ役）はEV+0.5、番手以降はやや低め
        lno            = num_to_line.get(num, 0)
        line_bibs      = line_map.get(lno, [])
        pos_in_line    = line_bibs.index(num) + 1 if num in line_bibs else 1
        line_pos_bonus = 0.5 if pos_in_line == 1 else (-0.3 * (pos_in_line - 1))

        ev_score = (
            base_score * 0.4
            + ip_avg   * 1.5
            + ep_avg   * 1.2
            + dp_avg   * bank_prof['makuri']
            + bp_avg   * bank_prof['sashi']
            + avg_nobi * 2.0
            + avg_senpo * 0.5
            + line_pos_bonus
            + (3.0 if is_monster   else 0)
            - (2.0 if is_unreliable else 0)
        )

        player_scores[num] = {
            'name':          name,
            'ev_score':      ev_score,
            'base_score':    base_score,
            'ip':            ip_avg,
            'ep':            ep_avg,
            'dp':            dp_avg,
            'bp':            bp_avg,
            'nobi':          avg_nobi,
            'senpo':         avg_senpo,
            'is_monster':    is_monster,
            'is_unreliable': is_unreliable,
            'hist_count':    len(hist),
            'style':         str(row['脚質']),
            'line_no':       lno,
            'pos_in_line':   pos_in_line,
        }

    ranked = sorted(player_scores.items(), key=lambda x: x[1]['ev_score'], reverse=True)

    # ---- Phase 3: 心理分析 (カオス判定) ------------------------------------
    strong_leaders = [
        d['name'] for _, d in player_scores.items()
        if d['ip'] >= 5.5 and d['pos_in_line'] == 1
    ]
    hidden_monsters = [(n, d) for n, d in ranked if d['is_monster']]
    is_chaos = len(strong_leaders) >= 2

    # ---- Phase 4: Plackett-Luce EV フィルタ --------------------------------
    #   use_full_permutation=True  → 全順列 + 均等確率下限（S1/S2向け）
    #   use_full_permutation=False → 軸固定 PL（S3/S4向け）
    all_nums = [n for n, _ in ranked]
    n        = len(all_nums)
    max_ev   = ranked[0][1]['ev_score']
    raw_s    = {num: np.exp(player_scores[num]['ev_score'] - max_ev) for num in all_nums}

    def pl_prob(first, second, third):
        """プラケット＝ルースによる P(first-second-third) 計算"""
        s = raw_s
        # --- 1着 ---
        d1 = sum(s[n] for n in all_nums)
        if d1 == 0: return 0.0
        # --- 2着（1着除く）---
        d2 = sum(s[n] for n in all_nums if n != first)
        if d2 == 0: return 0.0
        # --- 3着（1着・2着除く）---
        d3 = sum(s[n] for n in all_nums if n not in (first, second))
        if d3 == 0: return 0.0
        return (s[first] / d1) * (s[second] / d2) * (s[third] / d3)

    # 均等確率下限: 全員が同確率なら各組合は 1/(N×(N-1)×(N-2))
    n_combos = n * (n - 1) * (n - 2) if n >= 3 else 1
    p_floor  = 1.0 / n_combos   # ← これを下回る買い目 = 「ランダム以下」の確率

    # --- オッズ辞書を生成 ---
    odds_dict = {}
    if not race_odds.empty:
        for _, orow in race_odds.iterrows():
            odds_dict[str(orow['組み合わせ']).strip()] = float(orow['オッズ'])

    ev_positive_bets = []
    all_ev_bets      = []   # top_n_bets モード用（hard cutoff なし）
    fallback_bets    = []

    if SCFG.get('use_full_permutation', False):
        # ── 全順列モード（S2） ──────────────────────────────────────────
        n_combos    = n * (n - 1) * (n - 2) if n >= 3 else 1
        p_floor     = 1.0 / n_combos
        p_floor_str = f"P≥{p_floor:.4f}"

        for first in all_nums:
            for second in all_nums:
                if second == first: continue
                for third in all_nums:
                    if third in (first, second): continue
                    combo  = f"{first}-{second}-{third}"
                    p_trio = pl_prob(first, second, third)
                    if p_trio < p_floor: continue
                    if combo in odds_dict:
                        ev_val = p_trio * odds_dict[combo]
                        all_ev_bets.append((ev_val, combo, p_trio, odds_dict[combo]))
                        if ev_val > 1.0:
                            ev_positive_bets.append((ev_val, combo, p_trio, odds_dict[combo]))
                    else:
                        fallback_bets.append((p_trio, combo, p_trio, 0.0))
        mode_tag = "全順列-PL"

    else:
        # ── 軸固定モード（S3/S4） ──────────────────────────────────────────
        axis_num    = hidden_monsters[0][0] if hidden_monsters else ranked[0][0]
        others_all  = [num for num, _ in ranked if num != axis_num]
        p_floor_str = f"軸:{axis_num}"

        for second in others_all:
            for third in others_all:
                if second == third: continue
                combo  = f"{axis_num}-{second}-{third}"
                p_trio = pl_prob(axis_num, second, third)
                if combo in odds_dict:
                    ev_val = p_trio * odds_dict[combo]
                    all_ev_bets.append((ev_val, combo, p_trio, odds_dict[combo]))
                    if ev_val > 1.0:
                        ev_positive_bets.append((ev_val, combo, p_trio, odds_dict[combo]))
                else:
                    fallback_bets.append((p_trio, combo, p_trio, 0.0))
        mode_tag = "軸固定-PL"

    ev_positive_bets.sort(key=lambda x: x[0], reverse=True)
    all_ev_bets.sort(key=lambda x: x[0], reverse=True)
    fallback_bets.sort(key=lambda x: x[0], reverse=True)
    # 確率純粋順（Pだけでソート — EV ・オッズは選沢基準に入れない）
    all_prob_bets = sorted(all_ev_bets, key=lambda x: x[2], reverse=True)  # x[2] = p_trio

    top_n      = SCFG.get('top_n_bets',      None)  # EV順 Top-N
    top_n_prob = SCFG.get('top_n_prob_bets', None)  # P確率順 Top-N（的中最大化モード）

    if top_n_prob is not None:
        # ── PL確率上位N点モード（EVR/オッズ完全無視） ────────────────────
        # 「モデルが最も来ると思う順に上位N点を買う」—安い/高いオッズは関係ない
        if all_prob_bets:
            selected_prob_bets = all_prob_bets[:top_n_prob]
            bet_combinations   = [c for _, c, _, _ in selected_prob_bets]
            # ev_alloc用: prob上位14点にEV値を対応付ける
            # all_ev_betsはEV順なので、選ばれた組み合わせのEVを辞書引き
            ev_lookup = {c: ev for ev, c, p, o in all_ev_bets}
            bet_ev_list = [(c, ev_lookup.get(c, 0.0)) for c in bet_combinations]
            bet_method  = f"{mode_tag} P確率Top-{top_n_prob}（的中全集中）"
            if SCFG.get('ev_alloc'):
                bet_method += " + EV傾斜配分"
        else:
            bet_combinations = []
            bet_ev_list      = []
            bet_method       = f"ベットなし（オッズデータなし）"
    elif top_n is not None:
        # ── EV順 Top-Nモード ──────────────────────────────────────────────
        if all_ev_bets:
            bet_combinations = [c for _, c, _, _ in all_ev_bets[:top_n]]
            bet_ev_list      = [(c, ev) for ev, c, p, o in all_ev_bets[:top_n]]
            bet_method       = f"{mode_tag} EV Top-{top_n} ({p_floor_str})"
        else:
            bet_combinations = []
            bet_ev_list      = []
            bet_method       = f"ベットなし（オッズデータなし）"
    else:
        # ── EV>1.0 Hard cutoffモード ─────────────────────────────────────────
        if ev_positive_bets:
            bet_combinations = [c for _, c, _, _ in ev_positive_bets[:14]]
            bet_ev_list      = [(c, ev) for ev, c, p, o in ev_positive_bets[:14]]
            bet_method       = f"{mode_tag} EV>0 ({p_floor_str})"
        else:
            bet_combinations = []
            bet_ev_list      = []
            bet_method       = f"ベットなし（EV>0なし）"

    # ---- Phase 5: レポート生成 ---------------------------------------------
    report  = f"=========================================================\n"
    report += f"🔥 【Hardcore EV 推論レポート】 {venue}バンク Race ID: {race_id}\n"
    report += f"=========================================================\n"
    report += (f"🏟️  バンク特性: {bank_prof['type']} "
               f"(全長{bank_prof['length']}m) "
               f"差し係数={bank_prof['sashi']} 捲り係数={bank_prof['makuri']}\n\n")

    # ライン構成
    report += f"🔗 【ライン構成】\n"
    for lno in sorted(line_map.keys()):
        bibs = line_map[lno]
        names = [player_scores[b]['name'] if b in player_scores else f"#{b}" for b in bibs]
        report += f"  ライン{lno}: {' → '.join(f'車番{b}({n})' for b, n in zip(bibs, names))}\n"
    report += "\n"

    # 心理分析
    report += f"🧠 【大衆心理とラインの意志（Psycho-Analysis）】\n"
    if is_chaos:
        report += f"・先行役（IP≥5.5）が複数存在 → カオス展開が濃厚\n"
        report += f"  対象選手: {', '.join(strong_leaders)}\n"
    else:
        report += f"・先行争いは穏やか。主導権ラインに乗った選手が有利。\n"
    report += "\n"

    # 隠れ鬼脚
    report += f"💡 【Hidden Monster (S級DB解析)】\n"
    if hidden_monsters:
        for n, d in hidden_monsters[:2]:
            report += (f"  車番{n} {d['name']} — 解析コメントに鬼脚ワード検出\n"
                       f"  IP:{d['ip']:.1f} EP:{d['ep']:.1f} DP:{d['dp']:.1f} BP:{d['bp']:.1f} "
                       f"伸び:{d['nobi']:.1f}/5 EV:{d['ev_score']:.1f}\n")
    else:
        report += f"  顕著な隠れ鬼脚は検出されず。\n"
    report += "\n"

    # EVランキング
    report += f"📋 【出走選手EVランキング（S級DB + ライン補正）】\n"
    for rank_i, (num, d) in enumerate(ranked, 1):
        db_tag      = f"DB:{d['hist_count']}戦" if d['hist_count'] > 0 else "DBなし"
        monster_tag = " 🔥鬼脚"  if d['is_monster']    else ""
        unrel_tag   = " ⚠️不安"  if d['is_unreliable'] else ""
        report += (f"  {rank_i}位 車番{num} {d['name']} ({d['style']}) "
                   f"EV:{d['ev_score']:.1f} 基礎:{d['base_score']:.1f} "
                   f"IP:{d['ip']:.1f} EP:{d['ep']:.1f} 伸び:{d['nobi']:.1f}/5 "
                   f"ライン{d['line_no']}-{d['pos_in_line']}番手 "
                   f"[{db_tag}]{monster_tag}{unrel_tag}\n")

    # 買い目詳細（EV値付き）
    report += f"\n🎯 【極限フォーメーション】 {bet_method} / 買い目 {len(bet_combinations)}点\n"
    if ev_positive_bets:
        for ev_val, combo, p_trio, odds_val in ev_positive_bets[:14]:
            report += f"  ✅ {combo}  P={p_trio:.4f}  オッズ {odds_val:.1f}倍  EV={ev_val:.3f}\n"
    else:
        report += f"  推奨: {', '.join(bet_combinations)}\n"
    report += "\n"
    report += f"  EV>0 買い目数: {len(ev_positive_bets)}点 / 全候補中\n\n"

    max_combo_ev = ev_positive_bets[0][0] if ev_positive_bets else 0.0

    return report, bet_combinations, bet_ev_list, {
        'is_chaos':      is_chaos,
        'has_monster':   bool(hidden_monsters),
        'top_ev':        ranked[0][1]['ev_score'] if ranked else 0,
        'ev_gap':        (ranked[0][1]['ev_score'] - ranked[1][1]['ev_score']) if len(ranked) >= 2 else 0,
        'chaos_count':   len(strong_leaders),
        'ev_positive_n': len(ev_positive_bets),
        'max_combo_ev':  max_combo_ev,
        'has_odds_data': bool(odds_dict),
    }


# ==========================================
# Phase 6: バックテスト実行エンジン
# ==========================================
def should_bet_race(meta: dict) -> bool:
    """ストラテジーの条件を満たすレースか判定（Trueなら購入）"""
    cfg         = SCFG
    is_chaos    = meta['is_chaos']
    has_monster = meta['has_monster']
    top_ev      = meta['top_ev']
    ev_gap      = meta['ev_gap']
    chaos_count = meta['chaos_count']

    # EV下限チェック（全Strategy共通）
    if top_ev < cfg['min_top_ev']:
        return False

    # 鬼脚必須チェック（全Strategy共通）
    if cfg['require_monster'] and not has_monster:
        return False

    # カオス判定
    if is_chaos:
        if cfg.get('s3_chaos_filter'):
            # S3: カオス細分判定 — 3条件のどれか1つを満たせば買う
            buy_on_leaders = chaos_count >= cfg['chaos_buy_leaders_ge']
            buy_on_ev      = top_ev      >= cfg['chaos_buy_ev_ge']
            buy_on_gap     = ev_gap      <= cfg['chaos_buy_ev_gap_le'] and has_monster
            if not (buy_on_leaders or buy_on_ev or buy_on_gap):
                return False  # 「捨てるカオス」
        elif cfg['skip_chaos']:
            return False  # S2: カオス全除外
        # S1: カオスも全部買う

    # S_UNIONモード: S2 or S3 or S4 のいずれか通過すれば購入
    if SCFG.get('use_union_filter'):
        return any(
            should_bet_race_for(STRATEGY_CONFIGS[s], meta, venue='')
            for s in ['S2', 'S3', 'S4']
        )

    return True


def should_bet_race_for(cfg: dict, meta: dict, venue: str) -> bool:
    """任意のストラテジー設定でレースが対象かを判定（バンクROIフィルタ含む）"""
    top_ev      = meta['top_ev']
    is_chaos    = meta['is_chaos']
    has_monster = meta['has_monster']
    ev_gap      = meta['ev_gap']
    chaos_count = meta['chaos_count']

    if top_ev < cfg.get('min_top_ev', 0):
        return False
    if cfg.get('require_monster') and not has_monster:
        return False
    if is_chaos:
        if cfg.get('s3_chaos_filter'):
            buy_l = chaos_count >= cfg.get('chaos_buy_leaders_ge', 999)
            buy_e = top_ev      >= cfg.get('chaos_buy_ev_ge',      999)
            buy_g = ev_gap      <= cfg.get('chaos_buy_ev_gap_le',   -1) and has_monster
            if not (buy_l or buy_e or buy_g):
                return False
        elif cfg.get('skip_chaos'):
            return False
    if cfg.get('skip_low_bank'):
        if bank_dict.get(venue, {}).get('roi_tier') == 'low':
            return False
    return True


def cross_strategy_bet_multiplier(meta: dict, venue: str) -> int:
    """S2・S3・S4 の通過数に応じたベット倍率を返す

    S2∩S3∩S4 全通過 → 5倍
    S3∩S4 通過     → 3倍
    S4 のみ通過    → 1倍（変化なし）
    """
    passes = sum(
        1 for s in ['S2', 'S3', 'S4']
        if should_bet_race_for(STRATEGY_CONFIGS[s], meta, venue)
    )
    if passes == 3:   # S2∩S3∩S4
        return 5
    elif passes == 2: # S3∩S4 または S2∩S4
        return 3
    return 1


def run_backtest():
    dates = sorted(racecard_raw['date'].unique())
    total_investment = 0
    total_return     = 0
    hit_count        = 0
    total_races_bet  = 0
    skipped_count    = 0

    log_name = f"iteration_1_logs_{STRATEGY}.txt"
    log_file = open(log_name, "w", encoding="utf-8")
    print(f"🚀 Starting Backtest [{STRATEGY}]...\n")

    for current_date in dates:
        # ── 未来データ完全遮断 ──
        past_db  = db_all[db_all['開催日'] < current_date]
        daily_rc = racecard_raw[racecard_raw['date'] == current_date]
        race_ids = daily_rc['race_id'].unique()

        for rid in race_ids:
            race_info = daily_rc[daily_rc['race_id'] == rid].copy()
            if race_info.empty:
                continue

            venue      = race_info['venue'].iloc[0]
            race_odds  = odds_raw[odds_raw['race_id'] == rid]

            report, bets, bet_ev_list, meta = analyze_race(rid, venue, current_date, race_info, race_odds, past_db)
            if not report:
                continue

            # --- ストラテジーフィルタ ---
            if not should_bet_race(meta):
                skipped_count += 1
                log_file.write(
                    f"⏭️  【スキップ】 {STRATEGY}フィルタ適用 "
                    f"(カオス={meta['is_chaos']} 先行役{meta['chaos_count']}人 "
                    f"鬼脚={meta['has_monster']} EV={meta['top_ev']:.1f} EV差={meta['ev_gap']:.1f})\n\n"
                )
                continue

            # --- バンクROIフィルタ ---
            bank_prof = bank_dict.get(venue, {'roi_tier': 'mid'})
            if SCFG.get('skip_low_bank') and bank_prof.get('roi_tier') == 'low':
                skipped_count += 1
                log_file.write(f"⏭️  【スキップ】 要注意バンク: {venue}\n\n")
                continue

            log_file.write(report)

            if bets:
                # --- ベットコントロール ---
                bet_base = SCFG.get('bet_base', 100)
                bet_high = SCFG.get('bet_high', 100)
                ev_th    = SCFG.get('bet_high_ev_th', 9999)
                bet_unit = bet_high if meta['top_ev'] >= ev_th else bet_base

                # --- クロスストラテジー 増額判定 ---
                cross_mult = cross_strategy_bet_multiplier(meta, venue)
                bet_unit   = bet_unit * cross_mult
                cross_tag  = f" [×{cross_mult}クロス増額]" if cross_mult > 1 else ""

                # ── EV傾斜配分モード ─────────────────────────────────────────
                # 各買い目のEV値を重みとして、総額(bet_base×点数)を按分する。
                # EV値が負/0の場合は最低保証100円を確保し、残りを正EVで按分。
                if SCFG.get('ev_alloc') and bet_ev_list:
                    n_bets    = len(bets)
                    total_pool = bet_base * n_bets * cross_mult  # 総予算

                    ev_vals = np.array([max(ev, 0.0) for _, ev in bet_ev_list])
                    if ev_vals.sum() == 0:
                        # EVが全て0以下 → 均等配分（S_MAXHIT_14と同一）
                        alloc_units = [bet_base * cross_mult] * n_bets
                    else:
                        # EV比例配分 → 100円単位に切り捨て → 余りを最高EV点に加算
                        raw_alloc   = (ev_vals / ev_vals.sum()) * total_pool
                        alloc_100   = (raw_alloc // 100).astype(int) * 100  # 100円単位切り捨て
                        remainder   = int(total_pool - alloc_100.sum())
                        remainder   = (remainder // 100) * 100  # 100円単位に切り捨て
                        best_idx    = int(np.argmax(ev_vals))
                        alloc_100[best_idx] += remainder
                        # 最低100円保証
                        alloc_units = [max(int(a), 100) for a in alloc_100]

                    cost             = sum(alloc_units)
                    total_investment += cost
                    total_races_bet  += 1
                    log_file.write(f"💰 【投資】 ¥{cost:,} ({len(bets)}点 EV傾斜配分{cross_tag})\n")

                    race_payout = payouts_raw[payouts_raw['race_id'] == rid]
                    if not race_payout.empty:
                        raw_payout = race_payout['payout_trifecta'].values[0]
                        if pd.isna(raw_payout):
                            log_file.write(f"⚠️  【払戻未集計】 race_id: {rid}\n\n")
                        else:
                            actual_result = str(race_payout['result_trifecta'].values[0]).strip()
                            if actual_result in bets:
                                hit_idx    = bets.index(actual_result)
                                hit_unit   = alloc_units[hit_idx]
                                payout_val = int(raw_payout * hit_unit / 100)
                                total_return += payout_val
                                hit_count    += 1
                                # 配分サマリをログ出力
                                alloc_log = " | ".join(f"{c}:{u}円(EV{ev:.3f})" for (c, ev), u in zip(bet_ev_list, alloc_units))
                                log_file.write(
                                    f"🎉 【的中】 結果: {actual_result} / 払戻: ¥{payout_val:,}\n"
                                    f"   配分: {alloc_log}\n\n"
                                )
                            else:
                                log_file.write(f"💀 【ハズレ】 結果: {actual_result}{cross_tag}\n\n")
                    else:
                        log_file.write(f"⚠️  【結果データなし】 race_id: {rid}\n\n")

                else:
                    # ── 均等配分（従来通り） ──────────────────────────────────
                    cost              = len(bets) * bet_unit
                    total_investment += cost
                    total_races_bet  += 1
                    log_file.write(f"💰 【投資】 ¥{cost:,} ({len(bets)}点 均等{bet_unit}円{cross_tag})\n")

                    race_payout = payouts_raw[payouts_raw['race_id'] == rid]
                    if not race_payout.empty:
                        raw_payout = race_payout['payout_trifecta'].values[0]
                        if pd.isna(raw_payout):
                            log_file.write(f"⚠️  【払戻未集計】 race_id: {rid}\n\n")
                        else:
                            actual_result = str(race_payout['result_trifecta'].values[0]).strip()
                            if actual_result in bets:
                                payout_val    = int(raw_payout * bet_unit / 100)
                                total_return += payout_val
                                hit_count    += 1
                                log_file.write(f"🎉 【的中】 結果: {actual_result} / 払戻: ¥{payout_val:,} (×{bet_unit}円{cross_tag})\n\n")
                            else:
                                log_file.write(f"💀 【ハズレ】 結果: {actual_result}{cross_tag}\n\n")
                    else:
                        log_file.write(f"⚠️  【結果データなし】 race_id: {rid}\n\n")

    log_file.close()

    roi      = (total_return  / total_investment) * 100 if total_investment > 0 else 0
    hit_rate = (hit_count / total_races_bet) * 100      if total_races_bet  > 0 else 0

    print("=============================================")
    print(f"🏁 バックテスト結果 [{STRATEGY}] {SCFG['name']}")
    print(f"全レース数   : {total_races_bet + skipped_count} レース")
    print(f"スキップ     : {skipped_count} レース")
    print(f"対象レース数 : {total_races_bet} レース")
    print(f"的中数       : {hit_count} レース")
    print(f"的中率       : {hit_rate:.1f}%")
    print(f"総投資額     : ¥{total_investment:,}")
    print(f"総回収額     : ¥{total_return:,}")
    print(f"🔥 回収率 (ROI): {roi:.2f}%")
    print("=============================================")
    print(f"※ 詳細ログ → '{log_name}'")

run_backtest()