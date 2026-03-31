import random
import math
from typing import List, Dict, Tuple
from collections import defaultdict

# ----------------------------------------------------
# シミュレーション用ベースパラメータ（基底係数）
# ----------------------------------------------------
BASE_COST_MOGAKI = 0.4            # もがき合い時のベース消費割合
BASE_COST_SMOOTH = 0.1            # すんなり先行時のベース消費割合
BASE_COST_BLOCK_SUCCESS = 0.2     # ブロック成功時の番手ベース消費割合
STAMINA_DROP_OUT = 0.05           # 着外へ沈む場合(捲り不能や被捲り時)の残りスタミナ割合

STRETCH_WEIGHTS = {'S': 1.2, 'A': 1.0, 'B': 0.8, 'C': 0.6}
GUARD_WEIGHTS = {'S': 1.2, 'A': 1.1, 'B': 1.0, 'C': 0.8}

class Rider:
    """
    選手クラス
    個体能力値とシミュレーション内で増減するスタミナを管理
    """
    def __init__(self, rider_id: int, name: str, ip: float, ep: float, dp: float, bp: float,
                 stretch_rank: str, guard_rank: str, ev_score: float, 
                 style: str = '', senpo_score: float = 2.0):
        self.id = rider_id
        self.name = name
        
        self.ip = ip  # 先行力
        self.ep = ep  # 持久力・仕掛け力
        self.dp = dp  # ダッシュ力・トップスピード
        self.bp = bp  # 番手力・牽制力
        
        self.stretch_rank = stretch_rank
        self.guard_rank = guard_rank
        
        self.ev_score = ev_score
        self.style = style             # 脚質 (逃, 両, 追 など)
        self.senpo_score = senpo_score # 戦法スコア (逃げは高いなど)
        
        # 初期スタミナ (EP×0.6 + EV×0.4)
        self.initial_stamina = (self.ep * 0.6) + (self.ev_score * 0.4)
        self.current_stamina = self.initial_stamina
        
    def get_stretch_weight(self) -> float:
        # スコアベースの伸びがあればそちらを優先（今回はS/Aランク、または数値の両対応）
        if isinstance(self.stretch_rank, str) and self.stretch_rank in STRETCH_WEIGHTS:
            return STRETCH_WEIGHTS[self.stretch_rank]
        if isinstance(self.stretch_rank, (int, float)):
            # 1.0〜5.0 の数値なら 0.6〜1.2 にスケーリング
            return 0.6 + ((self.stretch_rank - 1) / 4.0) * 0.6
        return 0.8

    def get_guard_weight(self) -> float:
        if isinstance(self.guard_rank, str) and self.guard_rank in GUARD_WEIGHTS:
            return GUARD_WEIGHTS[self.guard_rank]
        return 1.0

    def reset_stamina(self):
        self.current_stamina = self.initial_stamina

class Line:
    """ラインクラス"""
    def __init__(self, line_id: int, riders: List[Rider]):
        self.line_id = line_id
        self.riders = riders  # インデックス0が先頭
        
    def get_lead_rider(self) -> Rider:
        return self.riders[0] if self.riders else None
    
    def get_mark_rider(self) -> Rider:
        return self.riders[1] if len(self.riders) > 1 else None
    
    def calculate_initiative_score(self) -> float:
        """先行意欲スコアの計算"""
        lead = self.get_lead_rider()
        if not lead: return 0.0
        
        # 脚質と戦法によるボーナス
        style_bonus = 1.5 if '逃' in lead.style else (1.2 if '両' in lead.style else 0.8)
        senpo_bonus = lead.senpo_score * 0.5
        
        return (lead.ip * 1.5 + lead.ev_score * 0.5) * style_bonus + senpo_bonus
    
    def calculate_defense_score(self) -> float:
        """ライン総合守備力の計算"""
        mark = self.get_mark_rider()
        if not mark: return 0.0
        return mark.bp * mark.get_guard_weight()

    def reset_line_stamina(self):
        for r in self.riders:
            r.reset_stamina()

class Race:
    """レース展開シミュレーション"""
    def __init__(self, lines: List[Line]):
        self.lines = lines

    def _phase1_determine_initiative(self) -> Tuple[Line, Line, Line]:
        """フェーズ1: 主導権(シナリオ)の決定"""
        scores = [line.calculate_initiative_score() for line in self.lines]
        total_score = sum(scores)
        
        if total_score > 0:
            probs = [s / total_score for s in scores]
        else:
            probs = [1.0 / len(self.lines) for _ in self.lines]
            
        indices = list(range(len(self.lines)))
        lead_idx = random.choices(indices, weights=probs, k=1)[0]
        
        remaining = [i for i in indices if i != lead_idx]
        random.shuffle(remaining)
        
        middle_idx = remaining[0] if len(remaining) > 0 else None
        back_idx = remaining[1] if len(remaining) > 1 else None
        
        lead_line = self.lines[lead_idx]
        middle_line = self.lines[middle_idx] if middle_idx is not None else None
        back_line = self.lines[back_idx] if back_idx is not None else None
        
        return lead_line, middle_line, back_line

    def _phase2_state_transition(self, lead_line: Line, middle_line: Line, back_line: Line):
        """フェーズ2: 道中の物理衝突・状態遷移（動的パラメータ）"""
        if not lead_line: return

        lead_rider = lead_line.get_lead_rider()
        
        # --- (1) もがき合いの動的確率 ---
        if middle_line:
            mid_rider = middle_line.get_lead_rider()
            # 逃げと中団の先行力が拮抗し、共に高いほどもがき合いやすい
            ip_sum = lead_rider.ip + (mid_rider.ip if mid_rider else 0.0)
            ip_diff = abs(lead_rider.ip - (mid_rider.ip if mid_rider else 0.0))
            
            # 動的にもがき確率を算出(0.1 〜 0.8 の間)
            prob_mogaki = min(0.8, max(0.1, (ip_sum - 6.0) * 0.1 - (ip_diff * 0.05)))
        else:
            prob_mogaki = 0.0
            
        if middle_line and random.random() < prob_mogaki:
            mid_rider = middle_line.get_lead_rider()
            if mid_rider:
                # 互いの能力比でスタミナ消費を分散
                total_ip = lead_rider.ip + mid_rider.ip
                lead_burden = mid_rider.ip / total_ip if total_ip > 0 else 0.5
                mid_burden = lead_rider.ip / total_ip if total_ip > 0 else 0.5
                
                lead_rider.current_stamina -= (BASE_COST_MOGAKI * lead_burden * 2) * lead_rider.initial_stamina
                mid_rider.current_stamina -= (BASE_COST_MOGAKI * mid_burden * 2) * mid_rider.initial_stamina
        else:
            if lead_rider:
                lead_rider.current_stamina -= BASE_COST_SMOOTH * lead_rider.initial_stamina

        # --- (2) 後方ラインの捲り vs 防御 ---
        if back_line:
            back_lead = back_line.get_lead_rider()
            lead_mark = lead_line.get_mark_rider()
            
            if back_lead:
                # 捲る確率はDP(ダッシュ力)と脚質に依存
                makuri_base = 0.4 + (back_lead.dp - 3.0) * 0.1
                # 負けているラインなら捲り意欲増
                if '追' in back_lead.style: makuri_base -= 0.2
                prob_make_move = min(0.9, max(0.2, makuri_base))
                
                if random.random() < prob_make_move:
                    attack_power = back_lead.dp * 1.5 + back_lead.ev_score * 0.2
                    defense_power = lead_line.calculate_defense_score()
                    
                    total_power = attack_power + defense_power
                    success_prob = attack_power / total_power if total_power > 0 else 0.5
                    
                    if random.random() < success_prob:
                        # 捲り成功 → 逃げ沈む
                        for r in lead_line.riders:
                            r.current_stamina = max(r.current_stamina * STAMINA_DROP_OUT, 0.1)
                        # 捲りラインのアドバンテージ (スタミナ少し回復)
                        for r in back_line.riders:
                            r.current_stamina *= 1.1
                    else:
                        # ブロック成功 → 捲り沈む
                        for r in back_line.riders:
                            r.current_stamina = max(r.current_stamina * STAMINA_DROP_OUT, 0.1)
                        if lead_mark:
                            lead_mark.current_stamina -= (BASE_COST_BLOCK_SUCCESS * defense_power / 10.0) * lead_mark.initial_stamina

    def _phase3_plackett_luce(self) -> Tuple[int, int, int]:
        """フェーズ3: 最終直線の確率計算"""
        all_riders = []
        for line in self.lines:
            all_riders.extend(line.riders)
            
        weights = []
        for r in all_riders:
            stamina = max(r.current_stamina, 0.1)
            final_weight = stamina * r.get_stretch_weight() * (1 + (r.ev_score / 200.0))
            
            scaled_weight = max(min(final_weight / 50.0, 100), -100)
            exp_weight = math.exp(scaled_weight)
            weights.append({'id': r.id, 'weight': exp_weight})
            
        results = []
        remaining_weights = weights.copy()
        for _ in range(min(3, len(weights))):
            total_w = sum(rw['weight'] for rw in remaining_weights)
            if total_w <= 0:
                probs = [1.0 / len(remaining_weights)] * len(remaining_weights)
            else:
                probs = [rw['weight'] / total_w for rw in remaining_weights]
                
            chosen_idx = random.choices(range(len(remaining_weights)), weights=probs, k=1)[0]
            chosen = remaining_weights.pop(chosen_idx)
            results.append(chosen['id'])
            
        while len(results) < 3:
            results.append(-1)
            
        return (results[0], results[1], results[2])

    def simulate_once(self) -> Tuple[int, int, int]:
        for line in self.lines:
            line.reset_line_stamina()
        lead_line, middle_line, back_line = self._phase1_determine_initiative()
        self._phase2_state_transition(lead_line, middle_line, back_line)
        result = self._phase3_plackett_luce()
        return result

def simulate_race_n_times(race: Race, num_simulations: int = 10000) -> Dict[Tuple[int, int, int], float]:
    results_count = defaultdict(int)
    for _ in range(num_simulations):
        results_count[race.simulate_once()] += 1
    return {bet: count / num_simulations for bet, count in results_count.items()}

def calculate_expected_value(probabilities: Dict[Tuple[int, int, int], float], 
                             odds_data: Dict[str, float],
                             top_n: int = 14) -> List[Dict]:
    """
    オッズと掛け合わせてEVを算出。
    odds_data のキーは '1-2-3' などの文字列形式を想定
    """
    ev_list = []
    for bet, prob in probabilities.items():
        if -1 in bet: continue
        bet_str = f"{bet[0]}-{bet[1]}-{bet[2]}"
        odds = odds_data.get(bet_str, 0.0)
        ev_list.append({
            'bet': bet_str,
            'prob': prob,
            'odds': odds,
            'ev': prob * odds
        })
    ev_list.sort(key=lambda x: x['ev'], reverse=True)
    return ev_list[:top_n]


# ----------------------------------------------------
# システム統合用アダプター (ステップ1 & 2)
# ----------------------------------------------------
def build_race_from_system_data(player_scores: dict, line_map: dict) -> Race:
    """
    predict.py や s3_predictor.py の出力をモデルへ変換し、Raceインスタンスを構築するアダプター。
    
    player_scores: {車番: {name, ev_score, ip, ep, dp, bp, style, nobi, senpo...}}
    line_map: {1: [7, 3], 2: [1], 3: [2, 5, 4]}  (キーはライン番号、値は車番リスト)
    """
    lines_obj = []
    
    # line_map からラインごと（複数のRider）を構築
    for lno, bibs in line_map.items():
        if not bibs: continue
        
        riders_in_line = []
        for bib in bibs:
            if bib not in player_scores: continue
            
            sc = player_scores[bib]
            # None等のフォールバック
            ip = float(sc.get('ip', 4.0)) if sc.get('ip') is not None else 4.0
            ep = float(sc.get('ep', 4.0)) if sc.get('ep') is not None else 4.0
            dp = float(sc.get('dp', 3.0)) if sc.get('dp') is not None else 3.0
            bp = float(sc.get('bp', 3.0)) if sc.get('bp') is not None else 3.0
            ev = float(sc.get('ev_score', 50.0))
            
            nobi = sc.get('nobi', 2.0)
            senpo = sc.get('senpo', 2.0)
            style = str(sc.get('style', ''))
            
            rider = Rider(
                rider_id=bib,
                name=sc.get('name', f"選手{bib}"),
                ip=ip, ep=ep, dp=dp, bp=bp,
                stretch_rank=nobi,        # ランク文字列か数値に対応
                guard_rank='B',           # 現在は基本B (DBにあれば使用)
                ev_score=ev,
                style=style,
                senpo_score=senpo
            )
            riders_in_line.append(rider)
            
        if riders_in_line:
            lines_obj.append(Line(lno, riders_in_line))
            
    return Race(lines_obj)

# ----------------------------------------------------
# テスト用メイン
# ----------------------------------------------------
if __name__ == "__main__":
    # モックの existing system 形式データ
    mock_scores = {
        1: {'name': '先行屋', 'ip': 6.5, 'ep': 5.0, 'dp': 3.0, 'bp': 2.0, 'ev_score': 85.0, 'style': '逃', 'nobi': 3.0, 'senpo': 4.5},
        2: {'name': '番手', 'ip': 2.0, 'ep': 4.0, 'dp': 4.0, 'bp': 5.5, 'ev_score': 80.0, 'style': '追', 'nobi': 4.0, 'senpo': 2.0},
        3: {'name': '捲り屋', 'ip': 4.0, 'ep': 4.5, 'dp': 6.0, 'bp': 3.0, 'ev_score': 90.0, 'style': '両', 'nobi': 5.0, 'senpo': 3.0},
        4: {'name': '捲り番手', 'ip': 1.0, 'ep': 3.0, 'dp': 4.0, 'bp': 4.5, 'ev_score': 70.0, 'style': '追', 'nobi': 3.0, 'senpo': 1.0},
        5: {'name': '単騎', 'ip': 3.0, 'ep': 3.5, 'dp': 4.5, 'bp': 4.0, 'ev_score': 65.0, 'style': '追', 'nobi': 2.0, 'senpo': 1.5},
    }
    mock_line_map = {
        1: [1, 2],    # 逃げライン
        2: [3, 4],    # 捲りライン
        3: [5]        # 単騎
    }
    
    print("システムのデータからレースを構築中...")
    race = build_race_from_system_data(mock_scores, mock_line_map)
    for l in race.lines:
        print(f"Line {l.line_id}: 車番 {[r.id for r in l.riders]}")
        
    print("\nシミュレーションを1万回実行中...")
    probs = simulate_race_n_times(race, num_simulations=10000)
    
    mock_odds = {f"{i}-{j}-{k}": random.uniform(10.0, 150.0) 
                 for i in range(1,6) for j in range(1,6) for k in range(1,6) 
                 if len(set([i,j,k])) == 3}
                 
    top_ev = calculate_expected_value(probs, mock_odds, top_n=5)
    print("\n【期待値(EV)上位5件】")
    for r in top_ev:
        print(f"買い目 {r['bet']} : 確率 {r['prob']:.4f} | オッズ {r['odds']:.1f} | EV {r['ev']:.2f}")
