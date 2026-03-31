"""
send_discord.py
===============
Discord Webhook 経由で予想通知を送信するモジュール。

環境変数:
  DISCORD_WEBHOOK_URL  - #予想通知チャンネルのWebhook URL
  DISCORD_WEBHOOK_FREE - #実績公開チャンネルのWebhook URL（省略可）

使い方:
  from send_discord import send_prediction, send_result
  send_prediction(race_info, lines, result)
"""

import os
import json
import requests
from datetime import datetime

WEBHOOK_PAID  = os.environ.get("DISCORD_WEBHOOK_URL", "")
WEBHOOK_FREE  = os.environ.get("DISCORD_WEBHOOK_FREE", "")

# Discord Embed カラー
COLOR_BET       = 0x00b4d8  # シアン（買い推奨）
COLOR_CANDIDATE = 0xffd166  # オレンジ（Phase1候補）
COLOR_SKIP      = 0x6c757d  # グレー（スキップ）
COLOR_CANCEL    = 0xff9f43  # オレンジ系（キャンセル）
COLOR_HIT       = 0x2dc653  # グリーン（的中）
COLOR_MISS      = 0xe63946  # レッド（ハズレ）


def _post_webhook(url: str, payload: dict) -> bool:
    """Discord Webhook にPOSTする"""
    if not url:
        print("[Discord省略] WEBHOOK URLが未設定")
        return False
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code in (200, 204):
            return True
        print(f"⚠️  Discord送信失敗 status={r.status_code}: {r.text[:100]}")
        return False
    except Exception as e:
        print(f"⚠️  Discord送信エラー: {e}")
        return False


def send_prediction(
    venue: str,
    race_no: int,
    race_name: str,
    start_str: str,
    deadline_str: str,
    mins_left: int,
    lines: list[dict],        # [{'line':1,'bibs':[1,5,7]}, ...]
    result: dict,             # run_prediction() の返り値
    grade: str = "☆☆☆",    # "☆☆☆"=勝負 / "☆"=ルック
) -> bool:
    """
    ☆☆☆（勝負レース）の買い推奨通知を有料チャンネルに送信する。
    ☆☆☆以外のgradeが渡された場合は送信しない。
    """
    # ☆☆☆（勝負レース）以外はDiscordに送信しない
    if grade != "☆☆☆":
        print(f"[Discord省略] グレード {grade} のため送信スキップ ({venue} {race_no}R)")
        return False

    color  = COLOR_BET
    icon   = "🎯"
    label  = "勝負"
    # ライン情報の整形
    line_text = ""
    for li in lines:
        bibs_str = " → ".join(str(b) for b in li['bibs'])
        line_text += f"> ライン{li['line']}: **{bibs_str}**\n"
    if not line_text:
        line_text = "> (ライン情報なし)\n"

    # 買い目（全点表示）
    bets_text = ""
    for i, (combo, amt) in enumerate(result['bets'], 1):
        bets_text += f"> `{combo}`  ¥{amt:,}\n"

    embed = {
        "title": f"{icon} {grade}【{label}】 {venue}  {race_no}R  {race_name}",
        "color": color,
        "description": (
            f"**発走** {start_str}　**締切** {deadline_str}（あと **{mins_left}分**）"
        ),
        "fields": [
            {
                "name": "📋 ライン構成",
                "value": line_text.strip(),
                "inline": False,
            },
            {
                "name": "⚙️ 予想",
                "value": (
                    f"> 軸: **{result['axis']}**\n"
                    f"> 軸EV: `{result.get('axis_ev', result['top_ev']):.1f}`  "
                    f"(最高EV: `{result['top_ev']:.1f}`)"
                ),
                "inline": True,
            },
            {
                "name": "💰 投資計画",
                "value": (
                    f"> 合計: **¥{result['total']:,}**\n"
                    f"> {len(result['bets'])}点流し"
                ),
                "inline": True,
            },
            {
                "name": "🔢 買い目",
                "value": bets_text.strip(),
                "inline": False,
            },
        ],
        "footer": {
            "text": f"自動予想 • {datetime.now().strftime('%H:%M')}"
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    payload = {
        "username": "競輪予想Bot",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/3176/3176369.png",
        "embeds": [embed],
    }
    return _post_webhook(WEBHOOK_PAID, payload)


def send_skip(
    venue: str, race_no: int, race_name: str,
    start_str: str, reason: str
) -> bool:
    """スキップしたレースをログ用に送信（フリーチャンネルには出さない）"""
    # スキップはコンソールのみ（Discordには送らない）
    print(f"⏭️  [{venue} {race_no}R {race_name}] {reason}")
    return True


def send_candidate(
    venue: str,
    race_no: int,
    race_name: str,
    start_str: str,
    deadline_str: str,
    mins_left: int,
    lines: list[dict],
    result: dict,
) -> bool:
    """
    Phase1候補通知（締切8〜13分前）。
    「最終確認中」バッジ付きで载せる。
    """
    line_text = ""
    for li in lines:
        bibs_str = " → ".join(str(b) for b in li['bibs'])
        line_text += f"> ライン{li['line']}: **{bibs_str}**\n"
    if not line_text:
        line_text = "> (ライン情報なし)\n"

    embed = {
        "title": f"🔍  {venue}  {race_no}R  {race_name}  [最終確認中]",
        "color": COLOR_CANDIDATE,
        "description": (
            f"🕒 **発走** {start_str}　**締切** {deadline_str}（あと **{mins_left}分**）\n"
            f"⚠️ Phase1判定通過 — {mins_left-6}〜{mins_left-3}分後に最終オッズで再判定します"
        ),
        "fields": [
            {
                "name": "📋 ライン構成",
                "value": line_text.strip(),
                "inline": False,
            },
            {
                "name": "⚙️ 軸候補",
                "value": (
                    f"> 軸: **{result['axis']}**\n"
                    f"> 軸EV: `{result.get('axis_ev', result['top_ev']):.1f}`"
                ),
                "inline": True,
            },
        ],
        "footer": {
            "text": f"自動予想 Phase1 • {datetime.now().strftime('%H:%M')}"
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    payload = {
        "username": "競輪予想Bot",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/3176/3176369.png",
        "embeds": [embed],
    }
    return _post_webhook(WEBHOOK_PAID, payload)


def send_cancel(
    venue: str, race_no: int, race_name: str,
    start_str: str, deadline_str: str, reason: str
) -> bool:
    """
    Phase2キャンセル通知。
    Phase1で候補だったレースが最終オッズで落第したときに送信。
    """
    embed = {
        "title": f"⏭️  {venue}  {race_no}R  {race_name}  [キャンセル]",
        "color": COLOR_CANCEL,
        "description": (
            f"🕒 **発走** {start_str}　**締切** {deadline_str}\n"
            f"⚠️ Phase2最終オッズで落第— {reason}"
        ),
        "footer": {
            "text": f"自動予想 Phase2キャンセル • {datetime.now().strftime('%H:%M')}"
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    payload = {
        "username": "競輪予想Bot",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/3176/3176369.png",
        "embeds": [embed],
    }
    return _post_webhook(WEBHOOK_PAID, payload)


def send_race_result(
    venue: str, race_no: int, race_name: str,
    result_combo: str, payout: int,
    hit: bool, profit: int, total_today: int = 0,
) -> bool:
    """
    レース1件の結果（的中/外れ）をDiscordに通知する。

    Args:
        result_combo: 実際の着順 (例: "5-1-7")
        payout: 払戻金額（的中時のみ）
        hit: 的中したか
        profit: このレースの収支
        total_today: 本日累計収支（現在は表示しない）
    """
    color = COLOR_HIT if hit else COLOR_MISS
    icon  = "🎊 的中！" if hit else "💀 外れ"

    profit_str = f"{'+'if profit>=0 else ''}¥{profit:,}"

    fields = [
        {
            "name": "🏁 確定着順",
            "value": f"> `{result_combo}`" + (f"  **{payout:,}円**" if hit else ""),
            "inline": True,
        },
        {
            "name": "💰 収支",
            "value": f"> このレース: **{profit_str}**",
            "inline": True,
        },
    ]

    embed = {
        "title": f"{icon}  {venue}  {race_no}R  {race_name}",
        "color": color,
        "fields": fields,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "footer": {"text": "※ 投資は自己責任でお願いします"},
    }
    payload = {
        "username": "競輪予想Bot",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/3176/3176369.png",
        "embeds": [embed],
    }
    return _post_webhook(WEBHOOK_PAID, payload)


def send_daily_summary(summary: dict) -> bool:
    """
    日次収支サマリー（☆☆☆勝負レースのトータル）を迓む。
    bet_logger.get_daily_summary(grade='☆☆☆') の返り値を渡す。
    """
    profit   = summary['profit']
    n_races  = summary['n_races']
    hits     = summary['hits']
    misses   = summary['misses']
    pending  = summary['pending']
    n_settled = len(hits) + len(misses)
    hit_rate  = round(len(hits) / n_settled * 100, 1) if n_settled else 0
    color     = COLOR_HIT if profit >= 0 else COLOR_MISS
    sign      = '+' if profit >= 0 else ''
    today     = summary.get('date', datetime.now().strftime('%Y-%m-%d'))

    # レース別明細
    detail_lines = []
    for r in sorted(hits + misses + pending,
                    key=lambda x: x.get('start_time', '')):
        icon = '✅' if r['status'] == 'hit' else ('❌' if r['status'] == 'miss' else '⏳')
        prf  = int(r['profit'])
        ps   = f"{'+'if prf>=0 else ''}¥{prf:,}"
        detail_lines.append(
            f"{icon} **{r['venue']} {r['race_no']}R** — {ps}"
            + (f"  `{r['result_combo']}`" if r.get('result_combo') else "")
        )

    detail_text = '\n'.join(detail_lines) if detail_lines else 'データなし'

    embed = {
        'title': f'\U0001f3c6  {today}  ☆☆☆勝負レース  日次収支報告',
        'color': color,
        'fields': [
            {
                'name': '📊 本日サマリー',
                'value': (
                    f'> 勝負対象R数: **{n_races}R**\n'
                    f'> 的中: **{len(hits)}件**  外れ: {len(misses)}件'
                    + (f'  未確定: {len(pending)}件' if pending else '') + '\n'
                    f'> 的中率: **{hit_rate}%**\n'
                    f'> 投資合計: ¥{summary["total_bet"]:,}\n'
                    f'> 払戻合計: ¥{summary["payout"]:,}\n'
                    f'> 💰 包括収支: **{sign}¥{profit:,}**\n'
                    f'> ROI: **{summary["roi"]}%**'
                ),
                'inline': False,
            },
            {
                'name': '📈 レース別明細',
                'value': detail_text[:1000],
                'inline': False,
            },
        ],
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'footer': {'text': '※ 投資は自己責任でお願いします'},
    }
    payload = {
        'username': '競輪予想Bot',
        'avatar_url': 'https://cdn-icons-png.flaticon.com/512/3176/3176369.png',
        'embeds': [embed],
    }
    # 日次サマリーは stats チャンネルに送信（DISCORD_WEBHOOK_STATS）
    stats_url = os.environ.get("DISCORD_WEBHOOK_STATS", "") or WEBHOOK_PAID
    return _post_webhook(stats_url, payload)



def test_send():
    """動作確認用テスト送信"""
    dummy_lines  = [
        {'line': 1, 'bibs': [5, 1, 7]},
        {'line': 2, 'bibs': [6, 2]},
        {'line': 3, 'bibs': [4, 3]},
    ]
    dummy_result = {
        'venue': '西武園', 'race_no': 9,
        'top_ev': 114.2,
        'axis': '車番5 河野通孝',
        'bets': [
            ('5-1-7', 200), ('5-1-3', 200), ('5-1-4', 100),
            ('1-5-7', 100), ('1-5-3', 100), ('5-3-1', 100), ('5-7-1', 100),
        ],
        'total': 900,
    }
    ok = send_prediction(
        venue='西武園', race_no=9, race_name='Ｓ級予選',
        start_str='14:44', deadline_str='14:39', mins_left=5,
        lines=dummy_lines, result=dummy_result,
    )
    print(f"送信結果: {'✅ 成功' if ok else '⚠️ 失敗（WEBHOOK URL未設定?）'}")


if __name__ == "__main__":
    test_send()
