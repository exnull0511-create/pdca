#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scenario_ev.py
展開シナリオ確率 × 3連単オッズ によるEV計算モジュール

設計思想:
  各レースで「成立しうる展開シナリオ」を列挙し、各シナリオの確率を計算。
  シナリオごとに予測着順を導き、全シナリオを合算した
  「各3連単の理論的中確率 P(A-B-C)」を算出する。
  実際のオッズ > 1/P(A-B-C) となる買い目のみ購入することで
  長期期待値プラスの賭けに絞る。

シナリオ構造:
  Phase1 ×  Phase2 ×  Phase3
  (主導権)   (捲り時期) (番手攻防)

Phase1: A_smooth(1強先行), B_chaos(複数もがき), C_slow(スロー牽制)
Phase2: A_kamashi(打鐘カマシ), B_back(最終バック捲り), C_line(直線勝負)
Phase3: A_bante_diff(番手差し成功), B_maenokori(前残り), C_makuri_blast(捲り炸裂),
        D_bante_makuri(番手捲り), E_monster(大外強襲)
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
import itertools

# =============================================================================
# データ構造
# =============================================================================

@dataclass
class Scenario:
    """1つの展開シナリオを表す"""
    name: str
    prob: float                        # このシナリオの成立確率 (0-1)
    # 車番→1着確率 / 2着確率 / 3着確率 の重みマップ
    pos1_weights: Dict[int, float] = field(default_factory=dict)
    pos2_weights: Dict[int, float] = field(default_factory=dict)
    pos3_weights: Dict[int, float] = field(default_factory=dict)


# =============================================================================
# Phase確率計算
# =============================================================================

def _phase1_probs(player_scores: dict, line_map: dict,
                  bank_detail: dict, is_short: bool) -> Tuple[str, float, float, float, float]:
    """
    Phase1: 主導権争い確率計算
    Returns: (phase1_branch, p_escape, p_makuri, p_chaos, stamina_loss)
    """
    lead_will = {}
    for lno, bibs in line_map.items():
        if not bibs:
            continue
        head = player_scores.get(bibs[0], {})
        ip  = head.get('ip', 4.0) + bank_detail.get('ip', 0)
        ep  = head.get('ep', 4.0) + bank_detail.get('ep', 0)
        sty = str(head.get('style', ''))
        sb  = {'逃': 1.8, '先': 1.3, '両': 0.8, '追': 0.3}.get(sty[:1], 0.8)
        short = 1.5 if is_short else 1.0
        loyalty = head.get('loyalty', 0.0)  # 事前に設定
        will = (ip * 1.5 + ep * 0.5) * sb * short + len(bibs) * 0.5 + loyalty * 2.0
        lead_will[lno] = max(0, will)

    vals = sorted(lead_will.values(), reverse=True) if lead_will else [4.0]
    max_will = vals[0] if vals else 1.0
    n_high   = sum(1 for v in vals if v >= max_will * 0.85)
    lead_gap = max_will - vals[1] if len(vals) >= 2 else max_will

    if n_high >= 2:
        return 'B_chaos',  0.15, 0.45, 0.40, 2.0
    elif lead_gap > max_will * 0.3:
        return 'A_smooth', 0.55, 0.30, 0.15, 0.5
    else:
        return 'C_slow',   0.25, 0.30, 0.45, 0.0


def _phase2_probs(lead_line_head: dict, bank_detail: dict) -> List[Tuple[str, float]]:
    """
    Phase2: 捲りタイミング確率
    Returns: [(branch_name, 条件付き確率), ...]  合計1.0
    """
    dp = lead_line_head.get('dp', 3.0) + bank_detail.get('dp', 0)
    ep = lead_line_head.get('ep', 4.0) + bank_detail.get('ep', 0)
    kant = bank_detail.get('kant', 1.0)

    # EPが高い→遅め捲り(B_back), DPが高い→早め仕掛け(A_kamashi)
    total = dp + ep + 1e-6
    p_kamashi = (dp / total) * (1 + kant * 0.1)
    p_back    = (ep / total)
    p_line    = max(0, 1.0 - p_kamashi - p_back)

    # 正規化
    s = p_kamashi + p_back + p_line
    return [
        ('A_kamashi', p_kamashi / s),
        ('B_back',    p_back    / s),
        ('C_line',    p_line    / s),
    ]


def _phase3_probs(bante: dict, head: dict, chigire: float, is_long: bool) -> List[Tuple[str, float]]:
    """
    Phase3: 番手攻防確率
    Returns: [(branch_name, 確率), ...]  合計1.0
    """
    bp     = bante.get('bp', 3.0) if bante else 3.0
    hidden = head.get('hidden_monster', 0.0)
    totsu  = bante.get('totsu', 0.0) if bante else 0.0

    # ブロック成功(A): BPが高くて千切れリスク低
    p_a = bp * (1 - chigire) * 0.2
    # 前残り(B): スタミナ消耗ブロック
    p_b = bp * chigire * 0.15
    # 捲り炸裂(C): 千切れ高い
    p_c = chigire * 0.3
    # 番手捲り(D): 突っ込み力
    p_d = totsu * 0.2
    # 大外強襲(E): 隠れ鬼脚 × 長直線
    p_e = hidden * (0.4 if is_long else 0.1)

    s = p_a + p_b + p_c + p_d + p_e + 1e-6
    return [
        ('A_bante_diff',   p_a / s),
        ('B_maenokori',    p_b / s),
        ('C_makuri_blast', p_c / s),
        ('D_bante_makuri', p_d / s),
        ('E_monster',      p_e / s),
    ]


# =============================================================================
# シナリオツリー生成
# =============================================================================

def generate_scenarios(player_scores: dict,
                       line_map: dict,
                       venue: str = '',
                       bank_detail: dict = None,
                       rescored_df: pd.DataFrame = None) -> List[Scenario]:
    """
    展開シナリオリストを生成する。
    各シナリオは成立確率と着順重みを持つ。

    Returns: List[Scenario]
    """
    if bank_detail is None:
        bank_detail = {}
    bank_length  = bank_detail.get('length', 400)
    is_short     = bank_length <= 335
    is_long      = bank_detail.get('straight', 55.0) >= 60.0
    kant         = bank_detail.get('kant', 1.0)

    # rescored_df から選手別スコアを取得
    def get_rs(name_norm: str) -> dict:
        if rescored_df is None or rescored_df.empty:
            return {}
        row = rescored_df[rescored_df.get('選手名_norm', pd.Series(dtype=str)) == name_norm]
        return row.iloc[0].to_dict() if not row.empty else {}

    # player_scores に loyalty / hidden_monster / chigire / totsu を付与
    for num, sc in player_scores.items():
        from s3_predictor import normalize_name
        rs = get_rs(normalize_name(sc.get('name', '')))
        sc['loyalty']        = float(rs.get('新_死に駆け忠誠度', 0)) / 100.0
        sc['chigire']        = float(rs.get('新_千切れリスク',   0)) / 100.0
        sc['hidden_monster'] = float(rs.get('新_隠れ鬼脚指数',  0)) / 100.0
        sc['totsu']          = float(rs.get('新_突っ込み力',     0)) / 100.0

    # Phase1 確率
    phase1, p_esc, p_mak, p_cha, s_loss = _phase1_probs(
        player_scores, line_map, bank_detail, is_short)

    # ライン別情報を整理
    # 先行意欲最大ラインを「逃げライン」と定義
    lead_line_wills = {}
    for lno, bibs in line_map.items():
        if bibs:
            sc_h = player_scores.get(bibs[0], {})
            ip = sc_h.get('ip', 4.0) + bank_detail.get('ip', 0)
            ep = sc_h.get('ep', 4.0) + bank_detail.get('ep', 0)
            sty = str(sc_h.get('style', ''))
            sb  = {'逃': 1.8, '先': 1.3, '両': 0.8, '追': 0.3}.get(sty[:1], 0.8)
            lead_line_wills[lno] = (ip * 1.5 + ep * 0.5) * sb + sc_h.get('loyalty', 0) * 2.0

    if not lead_line_wills:
        return []

    lead_lno   = max(lead_line_wills, key=lead_line_wills.get)
    lead_bibs  = line_map.get(lead_lno, [])
    lead_head  = lead_bibs[0] if lead_bibs else None
    lead_bante = lead_bibs[1] if len(lead_bibs) > 1 else None

    # 捲りライン候補 (逃げライン以外)
    attack_lines = [(lno, bibs) for lno, bibs in line_map.items()
                    if lno != lead_lno and bibs]

    # Phase2: 捲りラインの中で最もDP高い選手が仕掛け役
    attack_head = None
    attack_head_sc = {}
    if attack_lines:
        best_dp_lno = max(attack_lines, key=lambda x: player_scores.get(x[1][0], {}).get('dp', 0))
        attack_bibs = best_dp_lno[1]
        attack_head = attack_bibs[0]
        attack_head_sc = player_scores.get(attack_head, {})

    phase2_list = _phase2_probs(
        player_scores.get(lead_head, {}) if lead_head else {},
        bank_detail
    )

    lead_head_sc  = player_scores.get(lead_head, {})  if lead_head  else {}
    lead_bante_sc = player_scores.get(lead_bante, {}) if lead_bante else {}
    chigire_bante = lead_bante_sc.get('chigire', 0.3) if lead_bante else 0.3

    phase3_list = _phase3_probs(
        lead_bante_sc if lead_bante else {},
        lead_head_sc,
        chigire_bante,
        is_long
    )

    # ======================================================
    # シナリオツリー: Phase1(3) × Phase2(3) × Phase3(5) = 45パターン
    # ただし Phase2の捲りは「捲りライン存在時のみ」に適用し
    # Phase1(A_smooth)の場合は逃げ確率が高い = Phase2影響小
    # ======================================================
    scenarios = []

    # Phase1ブランチ確率: A_smooth=p_esc×2 / B_chaos=p_cha×2 / C_slow=その他
    p1_map = {
        'A_smooth': p_esc,
        'B_chaos':  p_cha,
        'C_slow':   p_mak,
    }

    for p1_name, p1_prob in p1_map.items():
        if p1_prob < 0.01:
            continue

        for p2_name, p2_prob in phase2_list:
            if p2_prob < 0.01:
                continue

            for p3_name, p3_prob in phase3_list:
                if p3_prob < 0.01:
                    continue

                scen_prob = p1_prob * p2_prob * p3_prob
                if scen_prob < 0.001:
                    continue

                scen_name = f"{p1_name}×{p2_name}×{p3_name}"

                # このシナリオでの着順重みを設定
                pos1 = {}
                pos2 = {}
                pos3 = {}

                def add_w(d, num, w):
                    if num is not None and num != 0:
                        d[num] = d.get(num, 0) + w

                # Phase3分岐ごとに着順を割り当て
                if p3_name == 'A_bante_diff':
                    # 番手差し成功: 逃げ先頭1着 or 番手差し1着
                    if p1_name == 'B_chaos':
                        # もがき合いで先頭タレ→番手1着の確率↑
                        add_w(pos1, lead_bante, 0.55)
                        add_w(pos1, lead_head,  0.30)
                        add_w(pos1, attack_head, 0.15)
                    else:
                        add_w(pos1, lead_head,  0.55)
                        add_w(pos1, lead_bante, 0.30)
                        add_w(pos1, attack_head, 0.15)
                    add_w(pos2, lead_bante, 0.40)
                    add_w(pos2, lead_head,  0.30)
                    add_w(pos2, attack_head, 0.30)
                    add_w(pos3, attack_head, 0.40)
                    add_w(pos3, lead_bante, 0.30)
                    add_w(pos3, lead_head,  0.30)

                elif p3_name == 'B_maenokori':
                    # 前残り: 逃げ先頭1着・番手は差せず3着以下
                    add_w(pos1, lead_head,  0.70)
                    add_w(pos1, attack_head, 0.20)
                    add_w(pos1, lead_bante, 0.10)
                    add_w(pos2, attack_head, 0.50)
                    add_w(pos2, lead_head,  0.30)
                    add_w(pos2, lead_bante, 0.20)
                    add_w(pos3, lead_bante, 0.50)
                    add_w(pos3, attack_head, 0.30)
                    add_w(pos3, lead_head,  0.20)

                elif p3_name == 'C_makuri_blast':
                    # 捲り炸裂: 捲りライン先頭1着
                    add_w(pos1, attack_head, 0.65)
                    add_w(pos1, lead_head,  0.20)
                    add_w(pos1, lead_bante, 0.15)
                    # 捲りラインの2番手も上位
                    attack_2nd = None
                    if attack_lines:
                        ab = best_dp_lno[1]
                        attack_2nd = ab[1] if len(ab) > 1 else None
                    add_w(pos2, attack_2nd, 0.40)
                    add_w(pos2, lead_head,  0.35)
                    add_w(pos2, lead_bante, 0.25)
                    add_w(pos3, lead_bante, 0.40)
                    add_w(pos3, lead_head,  0.35)
                    add_w(pos3, attack_2nd, 0.25)

                elif p3_name == 'D_bante_makuri':
                    # 番手捲り: 番手が自ら捲り出す
                    add_w(pos1, lead_bante, 0.60)
                    add_w(pos1, attack_head, 0.25)
                    add_w(pos1, lead_head,  0.15)
                    add_w(pos2, attack_head, 0.45)
                    add_w(pos2, lead_head,  0.30)
                    add_w(pos2, lead_bante, 0.25)
                    add_w(pos3, lead_head,  0.45)
                    add_w(pos3, lead_bante, 0.35)
                    add_w(pos3, attack_head, 0.20)

                elif p3_name == 'E_monster':
                    # 大外強襲: 隠れ鬼脚選手が1着
                    # 隠れ鬼脚指数最大の選手を特定
                    monster_num = max(
                        player_scores,
                        key=lambda n: player_scores[n].get('hidden_monster', 0),
                        default=None
                    )
                    add_w(pos1, monster_num, 0.60)
                    add_w(pos1, attack_head, 0.25)
                    add_w(pos1, lead_head,  0.15)
                    add_w(pos2, attack_head, 0.40)
                    add_w(pos2, lead_bante, 0.35)
                    add_w(pos2, monster_num, 0.25)
                    add_w(pos3, lead_bante, 0.40)
                    add_w(pos3, lead_head,  0.35)
                    add_w(pos3, monster_num, 0.25)

                # None キーを除去
                for d in [pos1, pos2, pos3]:
                    for k in list(d.keys()):
                        if k is None:
                            del d[k]

                # 重みを正規化
                def norm(d):
                    s = sum(d.values()) + 1e-9
                    return {k: v / s for k, v in d.items()}

                scenarios.append(Scenario(
                    name=scen_name,
                    prob=scen_prob,
                    pos1_weights=norm(pos1),
                    pos2_weights=norm(pos2),
                    pos3_weights=norm(pos3),
                ))

    # 全体の確率を正規化
    total_prob = sum(s.prob for s in scenarios) + 1e-9
    for s in scenarios:
        s.prob /= total_prob

    return scenarios


# =============================================================================
# 3連単確率計算
# =============================================================================

def calc_combo_probs(scenarios: List[Scenario],
                     all_nums: List[int],
                     top_n: int = 84) -> Dict[str, float]:
    """
    各展開シナリオを合算して3連単(A-B-C)の的中確率を計算する。

    Args:
        scenarios: generate_scenarios()の結果
        all_nums:  出走車番リスト
        top_n:     確率上位N組だけ返す

    Returns:
        {'1-2-3': 確率, '2-1-3': 確率, ...}
    """
    combo_prob: Dict[str, float] = {}

    for scen in scenarios:
        p1w = scen.pos1_weights
        p2w = scen.pos2_weights
        p3w = scen.pos3_weights

        # 各着順の車番をサンプリングして結合確率を計算
        for n1, w1 in p1w.items():
            if n1 not in all_nums:
                continue
            for n2, w2 in p2w.items():
                if n2 not in all_nums or n2 == n1:
                    continue
                for n3, w3 in p3w.items():
                    if n3 not in all_nums or n3 == n1 or n3 == n2:
                        continue
                    key = f"{n1}-{n2}-{n3}"
                    prob = scen.prob * w1 * w2 * w3
                    combo_prob[key] = combo_prob.get(key, 0) + prob

    # 正規化
    total = sum(combo_prob.values()) + 1e-9
    combo_prob = {k: v / total for k, v in combo_prob.items()}

    # 上位N組を返す
    sorted_combos = sorted(combo_prob.items(), key=lambda x: x[1], reverse=True)
    return dict(sorted_combos[:top_n])


# =============================================================================
# EV計算・買い目選択
# =============================================================================

def pick_positive_ev_bets(combo_probs: Dict[str, float],
                          odds_dict: Dict[str, float],
                          ev_threshold: float = 0.0,
                          max_bets: int = 18) -> List[Tuple[str, float, float]]:
    """
    EV > ev_threshold の3連単を選んで返す。

    Args:
        combo_probs: {'1-2-3': 確率, ...}   calc_combo_probsの結果
        odds_dict:   {'1-2-3': 倍率, ...}   3連単オッズ (100円あたりの払戻倍率)
        ev_threshold: EV下限 (0.0=損益分岐, 0.1=10%優位)
        max_bets:    最大購入点数

    Returns:
        [(combo, ev, prob), ...]  EV降順
    """
    bets = []
    for combo, prob in combo_probs.items():
        if prob <= 0:
            continue
        odds = odds_dict.get(combo, None)
        if odds is None:
            # オッズ不明の場合はスキップ
            continue
        # EV = 確率 × オッズ - 1  (1点100円ベース)
        ev = prob * odds - 1.0
        if ev > ev_threshold:
            bets.append((combo, ev, prob))

    bets.sort(key=lambda x: x[1], reverse=True)
    return bets[:max_bets]


def pick_bets_by_prob_rank(combo_probs: Dict[str, float],
                            n: int = 14) -> List[str]:
    """
    オッズ情報がない場合に確率上位N組を返す（バックテスト用フォールバック）。
    """
    sorted_combos = sorted(combo_probs.items(), key=lambda x: x[1], reverse=True)
    return [k for k, _ in sorted_combos[:n]]


# =============================================================================
# パブリックAPI
# =============================================================================

def run_scenario_ev(player_scores: dict,
                    line_map: dict,
                    venue: str,
                    bank_detail: dict,
                    rescored_df: pd.DataFrame = None,
                    odds_dict: Dict[str, float] = None,
                    ev_threshold: float = 0.0,
                    max_bets: int = 18) -> dict:
    """
    シナリオEV計算のメインエントリーポイント。

    Args:
        player_scores: {車番: スコア辞書}
        line_map:      {line_no: [車番, ...]}
        venue:         会場名
        bank_detail:   BANK_DETAIL[venue]
        rescored_df:   top30_rescored_rank_change.csv のDataFrame
        odds_dict:     {combo_str: 倍率} (Noneの場合は確率順フォールバック)
        ev_threshold:  EV下限
        max_bets:      最大購入点数

    Returns:
        {
          'scenarios':    [Scenario, ...],
          'combo_probs':  {'1-2-3': 確率, ...},
          'bets':         ['1-2-3', ...],
          'bet_evs':      [(combo, ev, prob), ...],  # オッズあり時のみ
          'top_scenario': Scenario,          # 最も確率の高いシナリオ
          'phase1':       str,               # 展開フェーズ1ラベル
        }
    """
    all_nums = list(player_scores.keys())

    # シナリオ生成
    scenarios = generate_scenarios(
        player_scores, line_map, venue, bank_detail, rescored_df
    )

    if not scenarios:
        return {
            'scenarios': [],
            'combo_probs': {},
            'bets': [],
            'bet_evs': [],
            'top_scenario': None,
            'phase1': '',
        }

    # 3連単確率計算
    combo_probs = calc_combo_probs(scenarios, all_nums)

    # 最確率シナリオ
    top_scen = max(scenarios, key=lambda s: s.prob)
    phase1 = top_scen.name.split('×')[0] if top_scen else ''

    # 買い目選択
    if odds_dict:
        bet_evs = pick_positive_ev_bets(combo_probs, odds_dict, ev_threshold, max_bets)
        bets = [b[0] for b in bet_evs]
    else:
        # オッズなし: 確率上位14点フォールバック
        bets   = pick_bets_by_prob_rank(combo_probs, n=max_bets)
        bet_evs = []

    return {
        'scenarios':    scenarios,
        'combo_probs':  combo_probs,
        'bets':         bets,
        'bet_evs':      bet_evs,
        'top_scenario': top_scen,
        'phase1':       phase1,
    }
