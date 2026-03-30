"""
bet_logger.py
=============
買い予測の記録・結果追記・収支集計を管理するモジュール。

データは data/bets_log.csv に保存し、GitHub Actions が
commit & push することで永続化する。
"""

import csv
import json
import os
from datetime import datetime, date
from pathlib import Path

BETS_LOG = Path(os.environ.get("BETS_LOG_PATH", "data/bets_log.csv"))

COLUMNS = [
    "date", "race_id", "venue", "venue_slug", "race_no", "race_name",
    "start_time", "bets_json", "total_bet",
    "result_combo", "payout", "profit", "status", "grade",
]


def _ensure_file():
    BETS_LOG.parent.mkdir(exist_ok=True)
    if not BETS_LOG.exists():
        with open(BETS_LOG, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=COLUMNS).writeheader()


def log_bet(race_id: str, venue: str, race_no: int, race_name: str,
            start_time: datetime, bets: list[tuple[str, int]], total: int,
            status: str = "pending", deadline_str: str = "",
            venue_slug: str = "", grade: str = "☆☆☆"):
    """
    買い予測を記録する。同一 race_id が既にある場合は上書きしない。
    status: "candidate"(Phase1候補) / "pending"(Phase2確定済み)
    """
    _ensure_file()

    # 既に pending/hit/miss/candidate で記録済みなら何もしない
    existing = _load_all()
    if any(r["race_id"] == race_id and r["status"] in ("pending","hit","miss","candidate") for r in existing):
        print(f"   [log_bet] {race_id} は既に記録済みスキップ")
        return

    row = {
        "date":         date.today().isoformat(),
        "race_id":      race_id,
        "venue":        venue,
        "venue_slug":   venue_slug,
        "race_no":      race_no,
        "race_name":    race_name,
        "start_time":   start_time.strftime("%H:%M") if start_time else "?",
        "bets_json":    json.dumps([[c, a] for c, a in bets], ensure_ascii=False),
        "total_bet":    total,
        "result_combo": "",
        "payout":       0,
        "profit":       -total,
        "status":       status,
        "grade":        grade,
    }
    with open(BETS_LOG, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=COLUMNS).writerow(row)
    tag = "🔍候補" if status == "candidate" else "✅bet"
    print(f"   {tag} 記録: {venue} {race_no}R  {len(bets)}点  ¥{total:,}")


def update_result(race_id: str, result_combo: str, payout: int):
    """
    結果が出たレースを更新する。
    payout: 3連単100円あたりの払戻金額
    """
    rows = _load_all()
    updated = False
    for r in rows:
        if r["race_id"] == race_id and r["status"] == "pending":
            bets = json.loads(r["bets_json"])
            # 的中判定: 買い目の中に result_combo があるか
            hit = any(combo == result_combo for combo, _ in bets)
            if hit:
                # 的中: 各組み合わせの掛け金に応じて払戻計算
                bet_amt = next((amt for combo, amt in bets if combo == result_combo), 100)
                actual_payout = int(payout * bet_amt / 100)
                total_bet     = int(r["total_bet"])
                r["result_combo"] = result_combo
                r["payout"]       = actual_payout
                r["profit"]       = actual_payout - total_bet
                r["status"]       = "hit"
            else:
                r["result_combo"] = result_combo
                r["payout"]       = 0
                r["profit"]       = -int(r["total_bet"])
                r["status"]       = "miss"
            updated = True
            break

    if updated:
        _save_all(rows)
        print(f"   ✅ 結果更新: {race_id}  {result_combo}  払戻¥{payout}")
    return updated


def get_pending_races() -> list[dict]:
    """発走時刻が過ぎていて結果未取得のレースを返す"""
    _ensure_file()
    now   = datetime.now()
    today = date.today().isoformat()
    rows  = _load_all()
    result = []
    for r in rows:
        if r["date"] != today or r["status"] != "pending":
            continue
        st = r.get("start_time", "23:59")
        try:
            h, m = map(int, st.split(":"))
            start_dt = datetime.combine(date.today(), datetime.min.time()).replace(hour=h, minute=m)
            # 発走から10分以上経過していれば結果確認対象（審議・写真判定考慮）
            if (now - start_dt).total_seconds() >= 600:
                result.append(r)
        except Exception:
            pass
    return result


def get_candidates() -> list[dict]:
    """今日のstatus=candidateのレースを返す（Phase2で最終確認する対象）"""
    _ensure_file()
    today = date.today().isoformat()
    return [r for r in _load_all()
            if r["date"] == today and r["status"] == "candidate"]


def confirm_candidate(race_id: str, bets: list[tuple[str, int]], total: int) -> bool:
    """
    candidate → pending に昇格（Phase2で勝負確定時）。
    買い目・配分がPhase2の最終オッズで更新される。
    """
    rows = _load_all()
    for r in rows:
        if r["race_id"] == race_id and r["status"] == "candidate":
            r["bets_json"]  = json.dumps([[c, a] for c, a in bets], ensure_ascii=False)
            r["total_bet"]  = total
            r["profit"]     = -total
            r["status"]     = "pending"
            _save_all(rows)
            print(f"   ✅ candidate→pending: {race_id}")
            return True
    return False


def cancel_candidate(race_id: str) -> bool:
    """candidate → cancelled に変更（Phase2で落第した場合）"""
    rows = _load_all()
    for r in rows:
        if r["race_id"] == race_id and r["status"] == "candidate":
            r["status"] = "cancelled"
            r["profit"]  = 0   # キャンセルなので損益なし
            _save_all(rows)
            print(f"   ⏭️  cancelled: {race_id}")
            return True
    return False


def get_daily_summary(target_date: str | None = None, grade: str | None = None) -> dict:
    """日次収支サマリーを返す。grade を指定するとそのグレードのみ集計。"""
    _ensure_file()
    today = target_date or date.today().isoformat()
    rows  = [r for r in _load_all() if r["date"] == today]

    if grade:
        rows = [r for r in rows if r.get("grade", "") == grade]

    settled  = [r for r in rows if r["status"] in ("hit", "miss")]
    total_bet    = sum(int(r["total_bet"]) for r in settled)
    total_payout = sum(int(r["payout"])    for r in settled)
    profit       = sum(int(r["profit"])    for r in settled)
    hits         = [r for r in rows if r["status"] == "hit"]
    misses       = [r for r in rows if r["status"] == "miss"]
    pending      = [r for r in rows if r["status"] == "pending"]

    return {
        "date":       today,
        "grade":      grade,
        "total_bet":  total_bet,
        "payout":     total_payout,
        "profit":     profit,
        "roi":        round(total_payout / total_bet * 100, 1) if total_bet else 0,
        "hits":       hits,
        "misses":     misses,
        "pending":    pending,
        "n_races":    len(rows),
        "settled":    settled,
    }


def _load_all() -> list[dict]:
    _ensure_file()
    with open(BETS_LOG, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _save_all(rows: list[dict]):
    with open(BETS_LOG, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    # 動作確認
    _ensure_file()
    print(f"bets_log: {BETS_LOG}  存在={BETS_LOG.exists()}")
    s = get_daily_summary()
    print(f"本日サマリー: {s}")
