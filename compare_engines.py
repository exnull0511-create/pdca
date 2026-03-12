"""
compare_engines.py
==================
ENGINE A: 現行ロジック (S_MAXHIT_14_EV_LOOSE_B 相当)
ENGINE B: HardcoreEV_Engine (LLM設計ロジック)

両エンジンを同一データ・同一フィルタ条件で走らせ、
ROI / 的中率 / 独自的中 などを比較します。

※ 公平比較のためPlackett-Luce確率計算は共通関数を使用。
  スコアリング式（選手の強さ評価）の違いだけを比較します。

【フィルタについて】
  ENGINE Aの ev_score は絶対値で約 70〜90 のスケール（競走得点×0.4 等）。
  ENGINE Bの final_score は絶対値が異なるスケールのため、
  「EVスコア1位と全選手平均の差（=優位性の強さ）」で正規化して同条件でフィルタする。
  閾値 EV_GAP_MIN: 上位選手が平均より何点優れていれば「買いレース」か。
"""

import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# ==========================================
# 共通設定（両エンジン共通フィルタ）
# LOOSE-B 相当
# ==========================================
SKIP_CHAOS     = True
SKIP_LOW_BANK  = True
TOP_N_PROB     = 14      # PL確率上位N点を購入
BET_BASE       = 100     # 1点あたり基準額（EV傾斜配分に使用）
EV_ALLOC       = True    # EV傾斜配分を使用

# ENGINE A 固有フィルタ（現行LOOSE-Bの min_top_ev=70）
MIN_TOP_EV_A   = 70      # EVスコア絶対値フィルタ（現行ロジックのスケールに合った値）

# ENGINE B 固有フィルタ（スコア相対優位差でフィルタ）
# B の final_score は IP/EP 等を組み合わせた別スケールなので
# 「スコア1位 - 全選手平均」が EV_GAP_MIN_B 以上のレースのみ購入
EV_GAP_MIN_B   = 3.5     # グリッドサーチの代わりに A と同等の選別率になるよう調整

print("🔥 compare_engines.py — Loading data...")

# ==========================================
# データロード
# ==========================================
def normalize_name(s):
    return str(s).replace(" ", "").replace("\u3000", "").strip()

racecard_raw = pd.read_excel("data/racecard.xlsx", dtype={'race_id': str})
odds_raw     = pd.read_excel("data/odds.xlsx",     dtype={'race_id': str})
payouts_raw  = pd.read_excel("data/payouts.xlsx",  dtype={'race_id': str})

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
nobi_col = [c for c in db_all.columns if '直線' in c][0]

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
    '西武園':   {'type': '標準',   'length': 335, 'sashi': 1.0, 'makuri': 1.1, 'roi_tier': 'mid'},
    '函館':     {'type': '標準',   'length': 400, 'sashi': 1.0, 'makuri': 1.0, 'roi_tier': 'mid'},
    '青森':     {'type': '標準',   'length': 400, 'sashi': 1.0, 'makuri': 1.0, 'roi_tier': 'mid'},
    '向日町':   {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '大垣':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '名古屋':   {'type': '標準',   'length': 400, 'sashi': 1.0, 'makuri': 1.1, 'roi_tier': 'mid'},
    '川崎':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
    '大宮':     {'type': '標準',   'length': 400, 'sashi': 1.1, 'makuri': 1.1, 'roi_tier': 'mid'},
}

# ==========================================
# ヘルパー関数（両エンジン共通）
# ==========================================
def nobi_score(val):
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

def build_player_base(race_info, past_db):
    """両エンジン共通の選手基礎データ（DB照合済み）を構築"""
    result = {}
    for _, row in race_info.iterrows():
        num  = int(row['車番'])
        name = str(row['選手名'])
        norm = normalize_name(name)
        hist = past_db[past_db['選手名_norm'] == norm]

        if not hist.empty:
            RECENT_W     = 3.0
            sorted_dates = sorted(hist['開催日'].dropna().unique(), reverse=True)
            recent_dates = set(sorted_dates[:2])

            def wmean(series):
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
            comments  = " ".join(hist['解析コメント'].astype(str).tolist())
        else:
            ip_avg = ep_avg = 4.0
            dp_avg = bp_avg = 3.0
            avg_nobi = avg_senpo = 2.0
            comments = ""

        for v, default in [(ip_avg, 4.0), (ep_avg, 4.0), (dp_avg, 3.0), (bp_avg, 3.0),
                           (avg_nobi, 2.0), (avg_senpo, 2.0)]:
            pass  # フォールバックは下で実施

        ip_avg    = ip_avg    if (ip_avg is not None and not np.isnan(ip_avg))       else 4.0
        ep_avg    = ep_avg    if (ep_avg is not None and not np.isnan(ep_avg))       else 4.0
        dp_avg    = dp_avg    if (dp_avg is not None and not np.isnan(dp_avg))       else 3.0
        bp_avg    = bp_avg    if (bp_avg is not None and not np.isnan(bp_avg))       else 3.0
        avg_nobi  = avg_nobi  if (avg_nobi is not None and not np.isnan(avg_nobi))   else 2.0
        avg_senpo = avg_senpo if (avg_senpo is not None and not np.isnan(avg_senpo)) else 2.0

        is_monster    = any(kw in comments for kw in ["脚余し", "鬼脚", "別次元", "圧倒", "豪快"])
        is_unreliable = any(kw in comments for kw in ["共倒れ", "位置取り失敗", "不発", "失速"])

        result[num] = {
            'name':          name,
            'base_score':    float(row['競走得点']),
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
        }
    return result


def pl_prob_from_scores(scores, first, second, third, all_nums):
    """Plackett-Luce: P(first-second-third) を scores辞書から計算"""
    max_ev = max(scores[n] for n in all_nums)
    raw_s  = {n: np.exp(scores[n] - max_ev) for n in all_nums}

    d1 = sum(raw_s[n] for n in all_nums)
    if d1 == 0: return 0.0
    d2 = sum(raw_s[n] for n in all_nums if n != first)
    if d2 == 0: return 0.0
    d3 = sum(raw_s[n] for n in all_nums if n not in (first, second))
    if d3 == 0: return 0.0
    return (raw_s[first]/d1) * (raw_s[second]/d2) * (raw_s[third]/d3)


def select_bets(scores, odds_dict, all_nums, top_n=14, ev_alloc=True, bet_base=100):
    """
    PLス確率上位N点を選択し、EV傾斜配分で返す
    戻り値: (bet_combinations, bet_ev_list, alloc_units)
    """
    # 全組み合わせのPL確率を計算
    all_prob_bets = []
    max_ev = max(scores[n] for n in all_nums)
    raw_s  = {n: np.exp(scores[n] - max_ev) for n in all_nums}

    for first in all_nums:
        for second in all_nums:
            if second == first: continue
            for third in all_nums:
                if third in (first, second): continue
                combo = f"{first}-{second}-{third}"
                d1 = sum(raw_s[n] for n in all_nums)
                d2 = sum(raw_s[n] for n in all_nums if n != first)
                d3 = sum(raw_s[n] for n in all_nums if n not in (first, second))
                if d1 == 0 or d2 == 0 or d3 == 0:
                    continue
                p = (raw_s[first]/d1) * (raw_s[second]/d2) * (raw_s[third]/d3)
                if combo in odds_dict:
                    ev = p * odds_dict[combo]
                    all_prob_bets.append((p, ev, combo, odds_dict[combo]))

    if not all_prob_bets:
        return [], [], []

    # P確率降順でTop-N点を選択
    all_prob_bets.sort(key=lambda x: x[0], reverse=True)
    selected = all_prob_bets[:top_n]
    bet_combinations = [c for _, _, c, _ in selected]
    bet_ev_list      = [(c, ev) for _, ev, c, _ in selected]

    # EV傾斜配分
    if ev_alloc and bet_ev_list:
        n_bets     = len(bet_combinations)
        total_pool = bet_base * n_bets
        ev_vals    = np.array([max(ev, 0.0) for _, ev in bet_ev_list])
        if ev_vals.sum() == 0:
            alloc_units = [bet_base] * n_bets
        else:
            raw_alloc  = (ev_vals / ev_vals.sum()) * total_pool
            alloc_100  = (raw_alloc // 100).astype(int) * 100
            remainder  = int(total_pool - alloc_100.sum())
            remainder  = (remainder // 100) * 100
            best_idx   = int(np.argmax(ev_vals))
            alloc_100[best_idx] += remainder
            alloc_units = [max(int(a), 100) for a in alloc_100]
    else:
        alloc_units = [bet_base] * len(bet_combinations)

    return bet_combinations, bet_ev_list, alloc_units


# ==========================================
# ENGINE A: 現行ロジック
# スコア = base*0.4 + IP*1.5 + EP*1.2 + DP*makuri + BP*sashi + nobi*2.0 + senpo*0.5
#         + ライン位置ボーナス + 鬼脚+3 - 不安-2
# ==========================================
def score_engine_a(player_base, line_map, num_to_line, bank_prof):
    scores = {}
    for num, d in player_base.items():
        lno         = num_to_line.get(num, 0)
        line_bibs   = line_map.get(lno, [])
        pos_in_line = line_bibs.index(num) + 1 if num in line_bibs else 1
        line_bonus  = 0.5 if pos_in_line == 1 else (-0.3 * (pos_in_line - 1))

        scores[num] = (
            d['base_score'] * 0.4
            + d['ip']      * 1.5
            + d['ep']      * 1.2
            + d['dp']      * bank_prof['makuri']
            + d['bp']      * bank_prof['sashi']
            + d['nobi']    * 2.0
            + d['senpo']   * 0.5
            + line_bonus
            + (3.0 if d['is_monster']    else 0)
            - (2.0 if d['is_unreliable'] else 0)
        )
    return scores


# ==========================================
# ENGINE B: HardcoreEV_Engine ロジック
# スコア = タテ脚（EP+nobi重視）× バンク特性 × 位置ロス × スタミナ消耗
#
# 設計思想:
# 1. 死に駆け: 後輩がライン先頭 → 先頭選手に「死に駆け」補正（+1.5）
#    ※ 後輩判定: ライン内で後ろに並ぶ選手のほうが競走得点が高い場合
# 2. 千切れ判定: 番手選手のEP<3.5かつリーダーのIP≥5.5 → スタミナペナルティ(-3.0)
#    また次の選手に「特等席」ボーナス(+2.0)を付与
# 3. 直線スピード: タテ脚(EP*1.8 + nobi*2.5)をベースにバンク特性で補正
#    - 差し向きバンク(sashi≥1.2): BP重み増加
#    - 捲り向きバンク(makuri≥1.2): DP重み増加
# 4. 位置ロス: ライン内ポジションが後ろほど直線出口でのロスが大きい
# ==========================================
def score_engine_b(player_base, line_map, num_to_line, bank_prof):
    scores = {}

    # ステップ1: 死に駆け判定
    # ラインリーダーよりフォロワーの競走得点が高い → リーダーは「死に駆け」
    shini_gake = set()
    for lno, bibs in line_map.items():
        if len(bibs) < 2:
            continue
        leader_num = bibs[0]
        follower_nums = bibs[1:]
        if leader_num not in player_base:
            continue
        leader_score = player_base[leader_num]['base_score']
        follower_max = max(
            (player_base[f]['base_score'] for f in follower_nums if f in player_base),
            default=0
        )
        if follower_max > leader_score + 2:  # フォロワーが2点以上上回る
            shini_gake.add(leader_num)

    # ステップ2: 千切れ判定 + 特等席割り当て
    chigire = set()      # 千切れるリスクが高い選手
    tokuto  = set()      # 特等席が転がり込む選手

    for lno, bibs in line_map.items():
        if len(bibs) < 2:
            continue
        leader_num = bibs[0]
        if leader_num not in player_base:
            continue
        leader_ip = player_base[leader_num]['ip']

        for i, bib in enumerate(bibs[1:], 1):
            if bib not in player_base:
                continue
            ep_val = player_base[bib]['ep']
            # 千切れリスク: 番手選手のEP低い + リーダーが猛ダッシュ型
            if ep_val < 3.5 and leader_ip >= 5.5:
                chigire.add(bib)
                # 千切れが生じると次のラインの先頭が特等席を得る
                # 他ライン先頭のうち最もEVスコアが高い選手に付与
                # （ここでは簡易的にnum_to_lineで別ラインの先頭を探す）
                for other_lno, other_bibs in line_map.items():
                    if other_lno != lno and other_bibs:
                        tokuto.add(other_bibs[0])

    # ステップ3: スコア計算（タテ脚 × バンク特性 × 位置ロス × スタミナ）
    sashi_coef  = bank_prof.get('sashi', 1.0)
    makuri_coef = bank_prof.get('makuri', 1.0)

    # バンク特性に応じてタテ脚の内訳ウェイトを調整
    # 差し向き(sashi≥1.2): 直線の伸び・BP重視
    # 捲り向き(makuri≥1.2): DP・EP重視
    if sashi_coef >= 1.2:
        ep_w, nobi_w, dp_w, bp_w = 1.4, 2.8, 0.9, 1.5
    elif makuri_coef >= 1.2:
        ep_w, nobi_w, dp_w, bp_w = 2.0, 2.2, 1.4, 0.8
    else:
        ep_w, nobi_w, dp_w, bp_w = 1.8, 2.5, 1.0, 1.0

    for num, d in player_base.items():
        lno         = num_to_line.get(num, 0)
        line_bibs   = line_map.get(lno, [])
        pos_in_line = line_bibs.index(num) + 1 if num in line_bibs else 1

        # タテ脚スコア（直線スピード）
        tate_ashi = (
            d['ep']   * ep_w
            + d['nobi'] * nobi_w
            + d['dp']   * dp_w
            + d['bp']   * bp_w
        )

        # 位置ロス（最終コーナー後の位置に応じたロス）
        # ライン内ポジションが後ろほど直線出口で外を回らされるロスが増える
        position_loss = (pos_in_line - 1) * 1.5  # 番手ごとに1.5点ロス

        # スタミナ消耗（位置取り争いが激しいほど消耗）
        # IP高い = 積極的に前に出る = スタミナ消耗大
        stamina_penalty = max(0, d['ip'] - 4.5) * 0.8

        # 基礎点
        final_score = (
            tate_ashi
            - position_loss
            - stamina_penalty
            + d['base_score'] * 0.2    # 競走得点は軽く参照
            + (d['ip'] * 0.5)          # 先行力も少し考慮
        )

        # ── 展開補正の適用 ──
        # 死に駆け: ライン先頭が捨て身の逃げ → そのライン先頭は本命度UP
        if num in shini_gake:
            final_score += 1.5

        # 千切れペナルティ
        if num in chigire:
            final_score -= 3.0

        # 特等席ボーナス（他ライン千切れの恩恵）
        if num in tokuto and num not in chigire:
            final_score += 2.0

        # 鬼脚・不安フラグ（現行と同じ定義を踏襲）
        if d['is_monster']:
            final_score += 2.5
        if d['is_unreliable']:
            final_score -= 1.5

        scores[num] = final_score

    return scores


# ==========================================
# エンジン別フィルタ判定
# ==========================================
def should_bet_a(is_chaos, top_ev, venue):
    """ENGINE A (現行ロジック): EVスコア絶対値フィルタ"""
    if SKIP_CHAOS and is_chaos:
        return False
    if top_ev < MIN_TOP_EV_A:
        return False
    if SKIP_LOW_BANK:
        if bank_dict.get(venue, {}).get('roi_tier') == 'low':
            return False
    return True

def should_bet_b(is_chaos, top_ev, mean_ev, venue):
    """ENGINE B (HardcoreEV_Engine): スコア優位差フィルタ"""
    if SKIP_CHAOS and is_chaos:
        return False
    ev_gap = top_ev - mean_ev
    if ev_gap < EV_GAP_MIN_B:
        return False
    if SKIP_LOW_BANK:
        if bank_dict.get(venue, {}).get('roi_tier') == 'low':
            return False
    return True


# ==========================================
# バックテスト実行
# ==========================================
def run_comparison():
    dates = sorted(racecard_raw['date'].unique())

    # 集計用
    results = []  # race単位の比較データ

    # エンジン別累計
    stats = {
        'A': {'invest': 0, 'ret': 0, 'hits': 0, 'bets': 0, 'skip': 0},
        'B': {'invest': 0, 'ret': 0, 'hits': 0, 'bets': 0, 'skip': 0},
    }

    print(f"\n🚀 バックテスト開始 ({len(dates)} 日分のデータ)\n")
    print(f"{'='*60}")
    print(f"フィルタ: skip_chaos={SKIP_CHAOS} / A:min_EV={MIN_TOP_EV_A} / B:ev_gap>={EV_GAP_MIN_B} / skip_low_bank={SKIP_LOW_BANK}")
    print(f"買い目: PL確率Top-{TOP_N_PROB}点 / EV傾斜配分={EV_ALLOC}")
    print(f"{'='*60}\n")

    for current_date in dates:
        past_db  = db_all[db_all['開催日'] < current_date]
        daily_rc = racecard_raw[racecard_raw['date'] == current_date]
        race_ids = daily_rc['race_id'].unique()

        for rid in race_ids:
            race_info = daily_rc[daily_rc['race_id'] == rid].copy()
            if race_info.empty:
                continue

            venue     = race_info['venue'].iloc[0]
            race_odds = odds_raw[odds_raw['race_id'] == rid]

            # オッズ辞書生成
            odds_dict = {}
            if not race_odds.empty:
                for _, orow in race_odds.iterrows():
                    odds_dict[str(orow['組み合わせ']).strip()] = float(orow['オッズ'])

            if not odds_dict:
                # オッズデータなし → スキップ
                stats['A']['skip'] += 1
                stats['B']['skip'] += 1
                continue

            # 基礎データ構築
            player_base = build_player_base(race_info, past_db)
            if not player_base:
                continue

            line_map     = parse_lines(race_info)
            num_to_line  = {}
            for lno, bibs in line_map.items():
                for b in bibs:
                    num_to_line[b] = lno

            bank_prof    = bank_dict.get(venue, {'type': '標準', 'length': 400, 'sashi': 1.0, 'makuri': 1.0, 'roi_tier': 'mid'})
            all_nums     = list(player_base.keys())

            # カオス判定（共通）
            strong_leaders = [
                d['name'] for n, d in player_base.items()
                if d['ip'] >= 5.5 and num_to_line.get(n, 0) in line_map
                and line_map.get(num_to_line.get(n, 0), [None])[0] == n
            ]
            is_chaos = len(strong_leaders) >= 2

            # 実際の結果
            race_payout  = payouts_raw[payouts_raw['race_id'] == rid]
            actual_result = None
            payout_odds   = None
            if not race_payout.empty:
                raw_pay = race_payout['payout_trifecta'].values[0]
                if not pd.isna(raw_pay):
                    actual_result = str(race_payout['result_trifecta'].values[0]).strip()
                    payout_odds   = float(raw_pay)

            # ──────────────────────────────
            # ENGINE A スコアリング＆判定
            # ──────────────────────────────
            scores_a = score_engine_a(player_base, line_map, num_to_line, bank_prof)
            ranked_a = sorted(scores_a.items(), key=lambda x: x[1], reverse=True)
            top_ev_a = ranked_a[0][1] if ranked_a else 0

            bet_a = hit_a = invest_a = ret_a = 0
            a_hit = False

            if should_bet_a(is_chaos, top_ev_a, venue):
                bets_a, bet_ev_a, alloc_a = select_bets(scores_a, odds_dict, all_nums, TOP_N_PROB, EV_ALLOC, BET_BASE)
                if bets_a:
                    invest_a = sum(alloc_a)
                    stats['A']['invest'] += invest_a
                    stats['A']['bets']   += 1
                    bet_a = 1
                    if actual_result and actual_result in bets_a:
                        hit_idx = bets_a.index(actual_result)
                        ret_a   = int(payout_odds * alloc_a[hit_idx] / 100)
                        stats['A']['ret']  += ret_a
                        stats['A']['hits'] += 1
                        hit_a = True
                else:
                    stats['A']['skip'] += 1
            else:
                stats['A']['skip'] += 1

            # ──────────────────────────────
            # ENGINE B スコアリング＆判定
            # ──────────────────────────────
            scores_b = score_engine_b(player_base, line_map, num_to_line, bank_prof)
            ranked_b = sorted(scores_b.items(), key=lambda x: x[1], reverse=True)
            top_ev_b = ranked_b[0][1] if ranked_b else 0
            mean_ev_b = np.mean(list(scores_b.values())) if scores_b else 0

            bet_b = hit_b = invest_b = ret_b = 0
            b_hit = False

            if should_bet_b(is_chaos, top_ev_b, mean_ev_b, venue):
                bets_b, bet_ev_b, alloc_b = select_bets(scores_b, odds_dict, all_nums, TOP_N_PROB, EV_ALLOC, BET_BASE)
                if bets_b:
                    invest_b = sum(alloc_b)
                    stats['B']['invest'] += invest_b
                    stats['B']['bets']   += 1
                    bet_b = 1
                    if actual_result and actual_result in bets_b:
                        hit_idx = bets_b.index(actual_result)
                        ret_b   = int(payout_odds * alloc_b[hit_idx] / 100)
                        stats['B']['ret']  += ret_b
                        stats['B']['hits'] += 1
                        b_hit = True
                else:
                    stats['B']['skip'] += 1
            else:
                stats['B']['skip'] += 1

            results.append({
                'race_id':      rid,
                'venue':        venue,
                'date':         str(current_date.date()),
                'is_chaos':     is_chaos,
                'actual':       actual_result,
                'A_bet':        bet_a,
                'A_hit':        int(hit_a),
                'A_invest':     invest_a,
                'A_return':     ret_a,
                'B_bet':        bet_b,
                'B_hit':        int(b_hit),
                'B_invest':     invest_b,
                'B_return':     ret_b,
                # 独自的中フラグ
                'A_only_hit':   int(hit_a and not b_hit),
                'B_only_hit':   int(b_hit and not hit_a),
                'both_hit':     int(hit_a and b_hit),
            })

    return results, stats


# ==========================================
# 結果出力
# ==========================================
def print_summary(stats, results):
    df = pd.DataFrame(results)

    print("\n" + "=" * 65)
    print("🏆 【比較バックテスト結果】")
    print("=" * 65)

    for eng, label in [('A', '現行ロジック (LOOSE-B)'),
                        ('B', 'HardcoreEV_Engine (LLM)')]:
        s   = stats[eng]
        roi = (s['ret'] / s['invest'] * 100) if s['invest'] > 0 else 0
        hr  = (s['hits'] / s['bets']  * 100) if s['bets']  > 0 else 0
        print(f"\n  ENGINE {eng}: {label}")
        print(f"  {'対象レース':12}: {s['bets']:>5} R")
        print(f"  {'スキップ':12}: {s['skip']:>5} R")
        print(f"  {'的中数':12}: {s['hits']:>5} R")
        print(f"  {'的中率':12}: {hr:>7.1f}%")
        print(f"  {'総投資額':12}: ¥{s['invest']:>10,}")
        print(f"  {'総回収額':12}: ¥{s['ret']:>10,}")
        print(f"  {'ROI':12}: {roi:>7.2f}%")

    print("\n" + "-" * 65)
    print("📊 【的中パターン分析】")
    both_bets = df[(df['A_bet'] == 1) & (df['B_bet'] == 1)]
    if len(both_bets) > 0:
        a_only = int(df['A_only_hit'].sum())
        b_only = int(df['B_only_hit'].sum())
        both   = int(df['both_hit'].sum())
        n = len(both_bets)
        print(f"  両エンジン参加レース: {n} R")
        print(f"  ✅ Aのみ的中 (現行ロジック優位): {a_only} R  ({a_only/n*100:.1f}%)")
        print(f"  ✅ Bのみ的中 (新ロジック優位):   {b_only} R  ({b_only/n*100:.1f}%)")
        print(f"  ✅ 両方的中:                     {both} R  ({both/n*100:.1f}%)")
    print("-" * 65)

    # 判定
    roi_a = (stats['A']['ret'] / stats['A']['invest'] * 100) if stats['A']['invest'] > 0 else 0
    roi_b = (stats['B']['ret'] / stats['B']['invest'] * 100) if stats['B']['invest'] > 0 else 0
    hr_a  = (stats['A']['hits'] / stats['A']['bets']  * 100) if stats['A']['bets']  > 0 else 0
    hr_b  = (stats['B']['hits'] / stats['B']['bets']  * 100) if stats['B']['bets']  > 0 else 0

    a_win = sum([roi_a > roi_b, hr_a > hr_b, int(df['A_only_hit'].sum()) > int(df['B_only_hit'].sum())])
    b_win = sum([roi_b > roi_a, hr_b > hr_a, int(df['B_only_hit'].sum()) > int(df['A_only_hit'].sum())])

    print(f"\n  勝敗スコア: ENGINE A = {a_win}/3  |  ENGINE B = {b_win}/3")
    if a_win > b_win:
        winner = "🔵 ENGINE A: 現行ロジック (LOOSE-B) が優秀！"
    elif b_win > a_win:
        winner = "🔴 ENGINE B: HardcoreEV_Engine (LLM) が優秀！"
    else:
        winner = "🟡 引き分け（ROI差で判定: " + ("A勝ち" if roi_a >= roi_b else "B勝ち") + "）"
    print(f"\n  >>> {winner}")
    print("=" * 65)


results, stats = run_comparison()

df_result = pd.DataFrame(results)
df_result.to_csv("data/compare_engines_result.csv", index=False, encoding='utf-8-sig')
print(f"\n💾 詳細結果を 'data/compare_engines_result.csv' に保存しました。")

print_summary(stats, results)
