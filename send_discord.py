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
COLOR_BET  = 0x00b4d8  # シアン（買い推奨）
COLOR_SKIP = 0x6c757d  # グレー（スキップ）
COLOR_HIT  = 0x2dc653  # グリーン（的中）
COLOR_MISS = 0xe63946  # レッド（ハズレ）


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
) -> bool:
    """
    買い推奨通知を有料チャンネルに送信する。

    lines: [{'line': 1, 'bibs': [1, 5, 7]}, ...]
    result: {'venue','race_no','top_ev','axis','bets':[('5-1-7',200),...],'total':int}
    """
    # ライン情報の整形
    line_text = ""
    for li in lines:
        bibs_str = " → ".join(str(b) for b in li['bibs'])
        line_text += f"> ライン{li['line']}: **{bibs_str}**\n"
    if not line_text:
        line_text = "> (ライン情報なし)\n"

    # 買い目（最大7点表示）
    bets_text = ""
    for i, (combo, amt) in enumerate(result['bets'][:7], 1):
        bets_text += f"> `{combo}`  ¥{amt:,}\n"
    if len(result['bets']) > 7:
        bets_text += f"> ...他{len(result['bets'])-7}点\n"

    embed = {
        "title": f"🎯  {venue}  {race_no}R  {race_name}",
        "color": COLOR_BET,
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
                    f"> EV スコア: `{result['top_ev']:.1f}`"
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


def send_result_summary(hits: list[dict], misses: list[dict]) -> bool:
    """
    当日の予想結果サマリーを無料チャンネルに送る（実績公開）。

    hits  : [{'venue','race_no','combo','odds','profit'}, ...]
    misses: [{'venue','race_no','combo'}, ...]
    """
    total_profit = sum(h.get('profit', 0) for h in hits)
    color = COLOR_HIT if total_profit >= 0 else COLOR_MISS

    hit_text  = "\n".join(f"✅ {h['venue']} {h['race_no']}R  `{h['combo']}`  {h['odds']}倍  +¥{h['profit']:,}" for h in hits) or "なし"
    miss_text = "\n".join(f"❌ {m['venue']} {m['race_no']}R  `{m.get('combo','?')}`" for m in misses) or "なし"

    embed = {
        "title": f"📊 本日の予想結果",
        "color": color,
        "fields": [
            {"name": f"🎯 的中 ({len(hits)}件)", "value": hit_text, "inline": False},
            {"name": f"💀 ハズレ ({len(misses)}件)", "value": miss_text, "inline": False},
            {"name": "💹 収支", "value": f"**{'+'if total_profit>=0 else ''}¥{total_profit:,}**", "inline": False},
        ],
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "footer": {"text": "※ 投資は自己責任でお願いします"},
    }
    payload = {
        "username": "競輪予想Bot",
        "embeds": [embed],
    }
    # 無料チャンネル（実績公開）に投稿
    return _post_webhook(WEBHOOK_FREE or WEBHOOK_PAID, payload)


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
