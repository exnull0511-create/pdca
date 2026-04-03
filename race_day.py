"""
race_day.py
===========
スケジュール駆動型 1日ジョブ予想スクリプト。
cron-job.org 不要。GitHub Actions の schedule トリガーで2セッション起動する。

セッション:
  morning  (8:00 JST 起動) : deadline < 14:30 のS級レースを担当
  evening  (13:30 JST 起動): deadline >= 13:30 のS級レースを担当
                              ※ 重複はbets_logのrace_id重複チェックで回避

使い方:
  python race_day.py --session morning
  python race_day.py --session evening
  python race_day.py --session morning --dry-run   # sleep省略・Discord送信なし
"""

import argparse
import os
import re
import subprocess
import sys
import time
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from bs4 import BeautifulSoup

from kdreams_scraper import KdreamsScraper
from fetch_schedule import fetch_today_f1_g3_races
from fetch_results import get_race_result
from bet_logger import (
    log_bet, update_result, get_pending_races, get_daily_summary,
    _load_all, _save_all,
)
from send_discord import send_prediction, send_daily_summary

# ── JST タイムゾーン ──────────────────────────────────────────────────────────
JST = timezone(timedelta(hours=9))

def now_jst() -> datetime:
    """JST固定の現在時刻（naive datetime）を返す。PC/サーバのTZ設定に依存しない。"""
    return datetime.now(JST).replace(tzinfo=None)

def today_jst() -> date:
    """JST固定の今日の日付を返す。"""
    return now_jst().date()

# ── 設定 ──────────────────────────────────────────────────────────────────────
DB_SLIM_PATH = os.environ.get("DB_SLIM_PATH", "data/S級DB_slim.xlsx")
DB_OLD_PATH  = os.environ.get("DB_OLD_PATH",  "data/S級選手究極DB(1).xlsx")

PRED_BEFORE_MIN  = 7    # 締切N分前に予想実行
RESULT_AFTER_MIN = 15   # 締切N分後に結果確認（☆☆☆のみ）
MAX_RESULT_RETRY = 5    # 結果取得リトライ回数
NEST_SIGMA       = 0.90 # Nested Logit ライン相関パラメータ (1.0=PLと同等)

STRATEGY_CFG = dict(
    skip_chaos=True, min_top_ev=60,      # PROD_3STAR と同一
    skip_low_bank=True, top_n_prob_bets=7,
)

BANK_DICT = {
    '前橋':    {'roi_tier': 'mid',  'sashi': 0.8, 'makuri': 1.2},
    '宇都宮':  {'roi_tier': 'high', 'sashi': 1.5, 'makuri': 1.1},
    '豊橋':    {'roi_tier': 'high', 'sashi': 1.3, 'makuri': 1.2},
    '岸和田':  {'roi_tier': 'low',  'sashi': 1.1, 'makuri': 1.3},
    '熊本':    {'roi_tier': 'high', 'sashi': 1.2, 'makuri': 1.1},
    'いわき平':{'roi_tier': 'mid',  'sashi': 0.9, 'makuri': 1.3},
    '広島':    {'roi_tier': 'mid',  'sashi': 1.2, 'makuri': 1.0},
    '別府':    {'roi_tier': 'mid',  'sashi': 1.1, 'makuri': 1.1},
    '松山':    {'roi_tier': 'mid',  'sashi': 1.0, 'makuri': 1.2},
    '小倉':    {'roi_tier': 'low',  'sashi': 1.1, 'makuri': 1.1},
    '京王閣':  {'roi_tier': 'high', 'sashi': 1.0, 'makuri': 1.1},
    '立川':    {'roi_tier': 'high', 'sashi': 1.1, 'makuri': 1.0},
    '取手':    {'roi_tier': 'mid',  'sashi': 1.1, 'makuri': 1.1},
    '伊東':    {'roi_tier': 'mid',  'sashi': 1.0, 'makuri': 1.2},
    '久留米':  {'roi_tier': 'low',  'sashi': 1.1, 'makuri': 1.1},
    '奈良':    {'roi_tier': 'low',  'sashi': 1.2, 'makuri': 1.0},
    '岐阜':    {'roi_tier': 'low',  'sashi': 1.1, 'makuri': 1.1},
    '小松島':  {'roi_tier': 'low',  'sashi': 1.1, 'makuri': 1.0},
    '防府':    {'roi_tier': 'low',  'sashi': 1.1, 'makuri': 1.1},
    '静岡':    {'roi_tier': 'low',  'sashi': 1.2, 'makuri': 1.0},
    '松阪':    {'roi_tier': 'mid',  'sashi': 1.1, 'makuri': 1.1},
    '高知':    {'roi_tier': 'mid',  'sashi': 1.0, 'makuri': 1.2},
    '松戸':    {'roi_tier': 'mid',  'sashi': 1.1, 'makuri': 1.0},
    '平塚':    {'roi_tier': 'mid',  'sashi': 1.2, 'makuri': 1.1},
    '西武園':  {'roi_tier': 'mid',  'sashi': 1.0, 'makuri': 1.1},
    '小田原':  {'roi_tier': 'mid',  'sashi': 1.0, 'makuri': 1.1},
    '大垣':    {'roi_tier': 'mid',  'sashi': 1.1, 'makuri': 1.1},
    '名古屋':  {'roi_tier': 'mid',  'sashi': 1.0, 'makuri': 1.1},
    '川崎':    {'roi_tier': 'mid',  'sashi': 1.1, 'makuri': 1.1},
    '大宮':    {'roi_tier': 'mid',  'sashi': 1.1, 'makuri': 1.1},
}

SENPO_LEAD = {
    '逃げ切り': 5, '逃げ粘り': 4, '突っ張り先行': 4, '抑え先行': 4,
    'カマシ先行': 5, '先行逃げ切り': 5, '先行': 4, '逃げ': 5,
    '先行争い敗北': 3, '捲り': 3, '番手捲り': 3, 'カマシ捲り': 4,
    '捲り差し': 3, '捲り不発': 2, '番手差し': 2, '差し': 2,
    '追い込み': 2, '流れ込み': 1, '追走': 1, 'マーク': 1,
}


def nobi_score(v):
    s = str(v).strip().upper()
    return 5 if s.startswith('S') else 4 if s.startswith('A') else 3 if s.startswith('B') else 1

def senpo_lead(v): return SENPO_LEAD.get(str(v).strip(), 1)
def norm(s): return str(s).replace(' ', '').replace('\u3000', '').strip()


# ── bets_log 即時保存 ─────────────────────────────────────────────────────────
def save_bets_log_to_git(msg: str = "auto: bets_log update"):
    """bets_log.csv を即時 git commit & push する（GitHub Actions 上で呼ぶ前提）"""
    try:
        subprocess.run(["git", "add", "data/bets_log.csv"],
                       check=True, timeout=10, capture_output=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"],
                                timeout=5, capture_output=True)
        if result.returncode != 0:  # 差分あり
            subprocess.run(
                ["git", "commit", "-m", msg],
                check=True, timeout=10, capture_output=True,
            )
            subprocess.run(
                ["git", "push"],
                check=True, timeout=30, capture_output=True,
            )
            print(f"  📁 bets_log.csv push成功")
    except subprocess.TimeoutExpired:
        print(f"  ⚠️ bets_log push タイムアウト")
    except subprocess.CalledProcessError as e:
        print(f"  ⚠️ bets_log push失敗: {e}")
    except Exception as e:
        print(f"  ⚠️ bets_log push予期しないエラー: {e}")


def expire_old_pending():
    """前日以前の date を持つ pending レコードを expired に変更する。"""
    today = date.today().isoformat()
    rows = _load_all()
    changed = 0
    for r in rows:
        if r.get('status') == 'pending' and r.get('date', '') != today:
            r['status'] = 'expired'
            r['profit'] = 0
            changed += 1
    if changed:
        _save_all(rows)
        print(f"⏰ {changed}件の古い pending を expired に変更しました")
        save_bets_log_to_git(f"auto: expire {changed} stale pending")


# ── DB ロード ──────────────────────────────────────────────────────────────────
def load_db():
    db_all = db_slim = pd.DataFrame()
    nobi_col = '直線の伸び'

    if Path(DB_OLD_PATH).exists():
        xl     = pd.ExcelFile(DB_OLD_PATH)
        sheets = [s for s in ['F1', 'G3~1'] if s in xl.sheet_names]
        db_all = pd.concat([xl.parse(s) for s in sheets], ignore_index=True)
        db_all['開催日'] = pd.to_datetime(db_all['開催日'], errors='coerce')
        for c in ['IP', 'EP', 'DP', 'BP']:
            db_all[c] = pd.to_numeric(db_all[c], errors='coerce')
        db_all['選手名_norm'] = db_all['選手名'].apply(norm)
        nbs = [c for c in db_all.columns if '直線' in c]
        if nbs: nobi_col = nbs[0]

    if Path(DB_SLIM_PATH).exists():
        sl  = pd.ExcelFile(DB_SLIM_PATH)
        dfs = [sl.parse(s) for s in ['F1', 'G3~1'] if s in sl.sheet_names]
        if dfs:
            db_slim = pd.concat(dfs, ignore_index=True)
            db_slim['開催日'] = pd.to_datetime(db_slim['開催日'], errors='coerce')
            for c in ['IP', 'EP', 'DP', 'BP']:
                if c in db_slim.columns:
                    db_slim[c] = pd.to_numeric(db_slim[c], errors='coerce')
            db_slim['選手名_norm'] = db_slim['選手名'].apply(norm)

    print(f"DB: oldDB={len(db_all)}件  slimDB={len(db_slim)}件  伸び列={nobi_col}")
    return db_all, db_slim, nobi_col


# ── オッズ取得 ─────────────────────────────────────────────────────────────────
def get_odds(scraper: KdreamsScraper, race_url: str) -> dict[str, float]:
    try:
        r    = scraper.session.get(race_url, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        result: dict[str, float] = {}

        for wrapper in soup.find_all('div', class_='oddspop_table_wrapper'):
            for tr in wrapper.find_all('tr'):
                txt = tr.get_text(separator=' ', strip=True)
                m = re.search(r'(\d)-(\d)-(\d)\s+([\d,]+\.?\d*)', txt)
                if m:
                    try:
                        o = float(m.group(4).replace(',', ''))
                        if o > 1.0:
                            result[f"{m.group(1)}-{m.group(2)}-{m.group(3)}"] = o
                    except ValueError:
                        pass

        if not result:  # フォールバック
            for tr in soup.find_all('tr'):
                txt = tr.get_text(separator=' ', strip=True)
                m = re.search(r'(\d)-(\d)-(\d)\s+([\d,]+\.?\d*)', txt)
                if m:
                    try:
                        o = float(m.group(4).replace(',', ''))
                        if o > 1.0:
                            result[f"{m.group(1)}-{m.group(2)}-{m.group(3)}"] = o
                    except ValueError:
                        pass

        return result
    except Exception as e:
        print(f"  ⚠️  オッズ取得エラー: {e}")
        return {}


# ── 出走表・ライン取得 ─────────────────────────────────────────────────────────
def get_race_info(scraper: KdreamsScraper, race_url: str):
    df         = scraper.get_race_card(race_url)
    lines_list = scraper.get_race_lines(race_url)
    num_to_line: dict[int, int] = {}
    num_to_bibs: dict[int, str] = {}
    for linfo in lines_list:
        lno  = linfo.get('line', 0)
        bibs = linfo.get('bibs', [])
        for b in bibs:
            num_to_line[b] = lno
            num_to_bibs[b] = '-'.join(str(x) for x in bibs)
    return df, num_to_line, num_to_bibs


# ── 予想コア（check_and_notify.py と同一ロジック） ──────────────────────────
def run_prediction(venue, race_no, race_card, num_to_line, num_to_bibs,
                   odds_dict, db_all, db_slim, nobi_col, today_dt):
    bp       = BANK_DICT.get(venue, {'roi_tier': 'mid', 'sashi': 1.0, 'makuri': 1.0})
    low_bank = STRATEGY_CFG['skip_low_bank'] and bp['roi_tier'] == 'low'

    if race_card is None or race_card.empty:
        return None

    past_db   = db_all[db_all['開催日'] < today_dt]   if not db_all.empty   else db_all
    past_slim = db_slim[db_slim['開催日'] < today_dt]  if not db_slim.empty  else pd.DataFrame()

    player_scores: dict[int, dict] = {}
    for _, row in race_card.iterrows():
        try:
            num  = int(row['車番'])
            name = str(row.get('選手名', ''))
            base = float(row.get('競走得点', 80) or 80)
            style= str(row.get('脚質', ''))
        except Exception:
            continue

        nm   = norm(name)
        hist = past_slim[past_slim['選手名_norm'] == nm] if not past_slim.empty else pd.DataFrame()
        use_slim = not hist.empty
        if hist.empty:
            hist = past_db[past_db['選手名_norm'] == nm] if not past_db.empty else pd.DataFrame()

        ip = ep = 4.0; dp = bp_v = 3.0; nb = sp = 2.0; is_m = is_u = False
        if not hist.empty:
            RECENT_W = 3.0
            sd = sorted(hist['開催日'].dropna().unique(), reverse=True)
            rd = set(sd[:2])
            def wm(series):
                v = pd.to_numeric(series, errors='coerce')
                w = np.where(hist['開催日'].isin(rd), RECENT_W, 1.0)
                mk = v.notna()
                return float((v[mk] * w[mk]).sum() / w[mk].sum()) if mk.any() else None
            ip   = wm(hist['IP'])  or 4.0
            ep   = wm(hist['EP'])  or 4.0
            dp   = wm(hist['DP'])  or 3.0
            bp_v = wm(hist['BP'])  or 3.0
            if use_slim and '直線の伸び' in hist.columns:
                nb = wm(hist['直線の伸び'].apply(nobi_score)) or 2.0
            elif nobi_col in hist.columns:
                nb = wm(hist[nobi_col].apply(nobi_score)) or 2.0
            if '戦法' in hist.columns:
                sp = wm(hist['戦法'].apply(senpo_lead)) or 2.0
            if use_slim:
                is_m = bool(hist.get('is_monster',    pd.Series([0])).max() >= 1)
                is_u = bool(hist.get('is_unreliable', pd.Series([0])).max() >= 1)
            else:
                cmt  = ' '.join(hist.get('解析コメント', pd.Series([''])).astype(str))
                is_m = any(k in cmt for k in ['脚余し', '鬼脚', '別次元', '圧倒'])
                is_u = any(k in cmt for k in ['共倒れ', '位置取り失敗', '不発', '失速'])

        lno  = num_to_line.get(num, 0)
        lbs  = [b for b, l in num_to_line.items() if l == lno]
        pos  = lbs.index(num) + 1 if num in lbs else 1
        posb = 0.5 if pos == 1 else -0.3 * (pos - 1)

        ev = (base * 0.4 + ip * 1.5 + ep * 1.2 + dp * bp['makuri'] + bp_v * bp['sashi']
              + nb * 2.0 + sp * 0.5 + posb
              + (3.0 if is_m else 0) - (2.0 if is_u else 0))

        player_scores[num] = {
            'name': name, 'ev': ev, 'ip': ip,
            'is_monster': is_m, 'pos_in_line': pos,
        }

    ranked = sorted(player_scores.items(), key=lambda x: x[1]['ev'], reverse=True)
    if len(ranked) < 3:
        return None

    strong_leaders = [n for n, d in player_scores.items()
                      if d['ip'] >= 5.5 and d['pos_in_line'] == 1]
    is_chaos = len(strong_leaders) >= 2
    top_ev   = ranked[0][1]['ev']
    if pd.isna(top_ev):
        return None

    # グレード判定
    low_ev    = top_ev < STRATEGY_CFG['min_top_ev']
    chaos_hit = is_chaos and STRATEGY_CFG['skip_chaos']
    grade = '☆' if (low_bank or low_ev or chaos_hit) else '☆☆☆'

    all_nums = [n for n, _ in ranked]
    max_e    = ranked[0][1]['ev']
    raw_s    = {n: np.exp(player_scores[n]['ev'] - max_e) for n in all_nums}

    # ── Nested Logit 確率計算（ラインをネスト構造として扱う） ──────────
    sigma = NEST_SIGMA

    # ライングループ構築用のヘルパ
    def _build_nests(members):
        nests = {}
        for n in members:
            ln = num_to_line.get(n, -n)  # ラインなしは個別ネスト
            if ln not in nests:
                nests[ln] = []
            nests[ln].append(n)
        return nests

    def nested_marginal(target, remaining):
        """Nested Logit: remaining集合からtargetが選ばれる確率"""
        if not remaining:
            return 0.0
        nests = _build_nests(remaining)
        IV = {}
        for ln, members in nests.items():
            inner = sum(raw_s[m] ** (1.0 / sigma) for m in members)
            IV[ln] = inner ** sigma if inner > 0 else 0.0
        total_IV = sum(IV.values())
        if total_IV == 0:
            return 0.0
        t_ln = num_to_line.get(target, -target)
        nest_p   = IV[t_ln] / total_IV
        inner_d  = sum(raw_s[m] ** (1.0 / sigma) for m in nests[t_ln])
        if inner_d == 0:
            return 0.0
        within_p = (raw_s[target] ** (1.0 / sigma)) / inner_d
        return nest_p * within_p

    def nested_trifecta(f, s, t):
        """3連単確率 P(1着=f, 2着=s, 3着=t) を逐次除去で計算"""
        p1 = nested_marginal(f, all_nums)
        if p1 == 0:
            return 0.0
        p2 = nested_marginal(s, [n for n in all_nums if n != f])
        if p2 == 0:
            return 0.0
        p3 = nested_marginal(t, [n for n in all_nums if n not in (f, s)])
        return p1 * p2 * p3

    # ── マルチ軸: 全選手を1着候補に展開し、確率Top N 点を選択 ──────────
    all_trifectas = []
    for f in all_nums:
        for s in all_nums:
            if s == f:
                continue
            for t in all_nums:
                if t == f or t == s:
                    continue
                combo = f"{f}-{s}-{t}"
                if combo not in odds_dict:
                    continue
                p_trio = nested_trifecta(f, s, t)
                odds_v = odds_dict[combo]
                ev_val = p_trio * odds_v
                all_trifectas.append((ev_val, combo, p_trio, odds_v))

    selected = sorted(all_trifectas, key=lambda x: x[2], reverse=True)[:STRATEGY_CFG['top_n_prob_bets']]
    bets_combos = [c for _, c, _, _ in selected]
    if not bets_combos:
        return None

    ev_lkup = {c: ev for ev, c, p, o in all_trifectas}
    bet_ev  = [(c, ev_lkup.get(c, 0.0)) for c in bets_combos]
    ev_vals = np.array([max(e, 0.0) for _, e in bet_ev])
    total_p = 100 * len(bets_combos)
    if ev_vals.sum() == 0:
        alloc = [100] * len(bets_combos)
    else:
        a    = (ev_vals / ev_vals.sum()) * total_p
        a100 = (a // 100).astype(int) * 100
        a100[int(np.argmax(ev_vals))] += (int(total_p - a100.sum()) // 100) * 100
        alloc = [max(int(x), 100) for x in a100]

    # 最頻1着選手を「軸」として記録（Discord表示用）
    first_nums = [int(c.split('-')[0]) for c in bets_combos]
    axis_num   = max(set(first_nums), key=first_nums.count)

    return {
        'top_ev':  top_ev,
        'axis_ev': player_scores[axis_num]['ev'],
        'axis':    f"車番{axis_num} {player_scores[axis_num]['name']}",
        'bets':    list(zip(bets_combos, alloc)),
        'total':   sum(alloc),
        'grade':   grade,
    }


# ── レース収集（セッションフィルタ適用） ────────────────────────────────────
def collect_races(session: str, target_date: date, dry_run: bool) -> list[dict]:
    print(f"\n📅 {target_date} 全S級レース取得中...")
    all_races = fetch_today_f1_g3_races(target_date, fetch_times=True)
    if not all_races:
        print("⚠️  本日開催なし")
        return []

    today = datetime.combine(target_date, datetime.min.time())
    cutoff_morning = datetime.combine(target_date, datetime.strptime("14:30", "%H:%M").time())
    cutoff_evening = datetime.combine(target_date, datetime.strptime("13:30", "%H:%M").time())

    def get_deadline(r) -> datetime | None:
        dl = r.get('deadline')
        if isinstance(dl, datetime):
            return dl
        ds = r.get('deadline_str', '')
        if ds:
            try:
                t = datetime.strptime(ds, "%H:%M").time()
                return datetime.combine(target_date, t)
            except Exception:
                pass
        return None

    filtered = []
    for r in all_races:
        dl = get_deadline(r)
        if dl is None:
            continue
        if session == 'morning' and dl < cutoff_morning:
            filtered.append({**r, '_deadline': dl})
        elif session == 'evening' and dl >= cutoff_evening:
            filtered.append({**r, '_deadline': dl})

    filtered.sort(key=lambda x: x['_deadline'])
    print(f"  セッション '{session}': 対象 {len(filtered)}R")
    for r in filtered:
        dl = r['_deadline']
        print(f"    {r['venue']:8s} {r['race_no']:2d}R  締切{dl.strftime('%H:%M')}"
              f"  [{r.get('race_name','?')}]")
    return filtered


# ── 結果確認・通知（全グレード対応） ──────────────────────────────────────────
def check_result_later(scraper: KdreamsScraper, race: dict, bets: list,
                       race_id: str, grade: str, dry_run: bool):
    """deadline + RESULT_AFTER_MIN 分後に結果を取得してログ更新。☆☆☆のみDiscord投稿。"""
    deadline = race['_deadline']
    wait_until = deadline + timedelta(minutes=RESULT_AFTER_MIN)
    now = now_jst()
    if wait_until > now and not dry_run:
        wait_sec = (wait_until - now).total_seconds()
        print(f"  ⏱️  結果確認まで {wait_sec/60:.1f}分待機...")
        time.sleep(wait_sec)

    venue     = race['venue']
    race_no   = race['race_no']
    race_name = race.get('race_name', 'S級')
    race_url  = race['race_url']

    for attempt in range(MAX_RESULT_RETRY):
        res = get_race_result(scraper, race_url)
        if res:
            break
        print(f"  ⏳ 結果未確定... ({attempt+1}/{MAX_RESULT_RETRY})")
        if not dry_run:
            time.sleep(60)
    else:
        print(f"  ⚠️  {venue} {race_no}R 結果取得断念")
        return

    combo  = res['combo']
    payout = res['payout']
    bet_combos = [c for c, _ in bets]
    hit    = combo in bet_combos
    amt    = dict(bets).get(combo, 0) if hit else 0
    return_amt = int(payout * amt / 100) if hit else 0
    invest = sum(a for _, a in bets)
    profit = return_amt - invest

    update_result(race_id=race_id, result_combo=combo, payout=payout)

    if not dry_run:
        save_bets_log_to_git(f"auto: result {venue} {race_no}R {'hit' if hit else 'miss'}")

    if dry_run:
        print(f"  [dry-run] 結果: {combo} {'✅的中' if hit else '❌外れ'} ({grade})")
        return

    print(f"  {'✅ 的中' if hit else '❌ 外れ'}  {combo}  払戻¥{payout:,}  ({grade})")


# ── 1レース処理 ───────────────────────────────────────────────────────────────
def process_race(race: dict, scraper: KdreamsScraper,
                 db_all, db_slim, nobi_col, today_dt, dry_run: bool):
    deadline  = race['_deadline']
    pred_time = deadline - timedelta(minutes=PRED_BEFORE_MIN)
    venue     = race['venue']
    race_no   = race['race_no']
    race_name = race.get('race_name', 'S級')
    race_url  = race['race_url']
    race_id   = str(race.get('race_id', ''))

    # ── 重複チェック（夕ジョブが朝ジョブ担当分を踏まないよう） ─────────────
    pending = get_pending_races()
    if any(str(pr.get('race_id', '')) == race_id for pr in pending):
        print(f"  ⏩ {venue} {race_no}R → bets_log済みスキップ")
        return

    # ── 締切判定 ─────────────────────────────────────────────────────────────
    now = now_jst()
    if now > deadline:
        print(f"  ⏭️  {venue} {race_no}R → 締切済みスキップ ({deadline.strftime('%H:%M')})")
        return

    # ── 予想時刻まで sleep ─────────────────────────────────────────────────────
    now = now_jst()  # 再取得（sleep後の遷移用）
    if pred_time > now:
        wait_sec = (pred_time - now).total_seconds()
        print(f"\n⏰ {venue} {race_no}R [{race_name}]  締切{deadline.strftime('%H:%M')}"
              f"  → あと{wait_sec/60:.1f}分後に予想")
        if not dry_run:
            time.sleep(wait_sec)
    else:
        print(f"\n🔥 {venue} {race_no}R [{race_name}]  締切{deadline.strftime('%H:%M')}  → 即実行")

    # ── 出走表・オッズ・ライン取得 ────────────────────────────────────────────
    print(f"  📋 出走表取得中...")
    race_card, num_to_line, num_to_bibs = get_race_info(scraper, race_url)
    if race_card is None or race_card.empty:
        print(f"  ⚠️  出走表なし → スキップ")
        return
    print(f"  📈 オッズ取得中...")
    odds_dict = get_odds(scraper, race_url)
    if not odds_dict:
        print(f"  ⚠️  オッズなし → スキップ")
        return

    # ── 予想実行 ─────────────────────────────────────────────────────────────
    result = run_prediction(
        venue, race_no, race_card, num_to_line, num_to_bibs,
        odds_dict, db_all, db_slim, nobi_col, today_dt,
    )
    if result is None:
        print(f"  ⚠️  予想生成失敗（選手不足/buy目なし）")
        return

    grade = result['grade']
    print(f"  {grade}  軸:{result['axis']}  topEV:{result['top_ev']:.1f}"
          f"  {'勝負' if grade == '☆☆☆' else 'ルック'}  {len(result['bets'])}点  ¥{result['total']:,}")

    # ── ☆（ルック）は記録・通知せずスキップ ─────────────────────────────────
    if grade != '☆☆☆':
        print(f"  📝 ルック判定（{grade}）→ スキップ（記録・通知なし）")
        return None

    # ── bets_log 記録（☆☆☆勝負レースのみ） ───────────────────────────────────
    start_str = race.get('start_time_str', race.get('start_time', '?'))
    if hasattr(start_str, 'strftime'):
        start_dt = start_str
        start_str = start_str.strftime('%H:%M')
    else:
        try:
            t = datetime.strptime(str(start_str), '%H:%M').time()
            start_dt = datetime.combine(date.today(), t)
        except Exception:
            start_dt = deadline

    log_bet(
        race_id=race_id, venue=venue, race_no=race_no,
        race_name=race_name, start_time=start_dt,
        bets=result['bets'], total=result['total'],
        status='pending', venue_slug=race.get('venue_slug', ''),
        grade=grade,
    )

    # ── bets_log 即時保存 ─────────────────────────────────────────────────────
    if not dry_run:
        save_bets_log_to_git(
            f"auto: bet {venue} {race_no}R {grade}"
        )

    # ── Discord 通知 ─────────────────────────────────────────────────────────
    lines_for_discord = [
        {'line': lno, 'bibs': [b for b, l in num_to_line.items() if l == lno]}
        for lno in sorted(set(num_to_line.values()))
    ]
    deadline_str = deadline.strftime('%H:%M')
    mins_left    = max(0, int((deadline - now_jst()).total_seconds() / 60))

    if not dry_run:
        send_prediction(
            venue=venue, race_no=race_no, race_name=race_name,
            start_str=start_str, deadline_str=deadline_str,
            mins_left=mins_left, lines=lines_for_discord,
            result=result, grade=grade,
        )
        print(f"  ✅ Discord送信完了")
    else:
        print(f"  [dry-run] Discord送信省略")

    # ── 結果収集情報を返す（☆☆☆のみ） ───────────────────────────────────────
    return {'race': race, 'bets': result['bets'], 'race_id': race_id, 'grade': grade}


# ── メイン ───────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="競輪S級レース 1日予想ジョブ")
    parser.add_argument('--session', choices=['morning', 'evening'], required=True,
                        help="morning=8:00JST起動 / evening=13:30JST起動")
    parser.add_argument('--dry-run', action='store_true',
                        help="sleep省略・Discord送信なし（テスト用）")
    parser.add_argument('--date', default=None,
                        help="対象日付 YYYY-MM-DD（省略時=当日）")
    args = parser.parse_args()

    target_date = (datetime.strptime(args.date, '%Y-%m-%d').date()
                   if args.date else today_jst())
    today_dt    = datetime.combine(target_date, datetime.min.time())
    dry_run     = args.dry_run

    print(f"🏁 race_day.py  session={args.session}  date={target_date}"
          f"  {'[DRY-RUN]' if dry_run else ''}")

    # ── stale pending 自動 expire ─────────────────────────────────────────────
    expire_old_pending()

    # DB 読込（起動時1回のみ）
    db_all, db_slim, nobi_col = load_db()

    # レース一覧取得（起動時1回のみ）
    races = collect_races(args.session, target_date, dry_run)
    if not races:
        print("本日の対象レースなし。終了します。")
        return

    # スクレイパー初期化
    scraper = KdreamsScraper()

    print(f"\n🚀 処理開始: {len(races)}R")
    all_logged_races = []  # 全グレードのレースを収集（結果確認用）
    for i, race in enumerate(races, 1):
        print(f"\n[{i}/{len(races)}]", end='')
        try:
            info = process_race(race, scraper, db_all, db_slim, nobi_col, today_dt, dry_run)
            if info:
                all_logged_races.append(info)
        except KeyboardInterrupt:
            print("\n⛔ 中断されました")
            break
        except Exception as e:
            print(f"  ⚠️  予期しないエラー: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)

    print(f"\n✅ セッション '{args.session}' 全レース予想完了")

    # ── ☆☆☆勝負レースの結果収集 ────────────────────────────────────────────
    if all_logged_races:
        print(f"\n🏁 結果収集開始: ☆☆☆ {len(all_logged_races)}R")
        for info in all_logged_races:
            check_result_later(
                scraper, info['race'], info['bets'], info['race_id'],
                info['grade'], dry_run,
            )
    else:
        print("\n（本セッションに対象レースなし）")

    # ── 日次収支サマリー投稿（両セッション共通） ─────────────────────────────
    print("\n📊 日次収支サマリーを投稿中...")
    # 他セッションが push した bets_log.csv を取り込む
    try:
        subprocess.run(["git", "pull", "--rebase", "origin", "main"],
                       check=True, timeout=30, capture_output=True)
        print("  🔄 git pull 完了（bets_log.csv 最新化）")
    except Exception as e:
        print(f"  ⚠️  git pull 失敗（ローカルのみで集計）: {e}")
    summary = get_daily_summary(grade='☆☆☆')
    print(f"  ☆☆☆: {summary['n_races']}R  的中{len(summary['hits'])}件  "
          f"収支{'+' if summary['profit']>=0 else ''}¥{summary['profit']:,}")
    if not dry_run:
        send_daily_summary(summary)
        print("  ✅ Discord投稿完了")
    else:
        print("  [dry-run] Discord投稿省略")

    print(f"\n🏁 セッション '{args.session}' 完了")


if __name__ == "__main__":
    main()
