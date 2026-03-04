---
description: 当日競輪予想の実行フロー（データ準備 → 予想実行 → 結果記録）
---

# 競輪予想 実行ワークフロー

## 事前準備（初回のみ）

1. `data/` フォルダに以下が揃っているか確認する
   - `racecard.xlsx`（出走表・ライン情報）
   - `odds.xlsx`（3連単オッズ）
   - `S級選手究極DB(1).xlsx`（旧DB・フォールバック用）
   - `S級DB_slim.xlsx`（新slim DB・あれば優先使用）

---

## 【Oracle Cloud 常駐モード】完全自動

// turbo
2. Oracle Cloud VPS 上で watcher.py を起動する
   ```
   export LINE_NOTIFY_TOKEN="your_token"
   python watcher.py
   ```
   ※ systemd サービスとして常駐させると自動再起動できる（セットアップガイド参照）

3. 通知を受け取る（LINE）
   - 毎朝 7:30 に当日の開催情報が届く
   - 各レース発走10分前に買い判定レースのみ通知が届く
   - 通知が来ないレースはスキップ（カオス・低ROIバンク・EVスコア不足）

4. 通知を見てオッズを確認してから馬券を購入する

---

## 【手動モード】PCで当日予想のみ実行する場合

// turbo
5. 当日の予想を実行する（最新日を自動検出）
   ```
   python predict.py
   ```
   または特定日を指定:
   ```
   python predict.py --date 20260304
   ```

6. 出力ファイルを確認する
   - `predict_{YYYYMMDD}.txt` — レース別詳細レポート
   - `predict_{YYYYMMDD}.csv` — 買い目一覧（馬券購入に使用）

---

## 【DB更新】映像解析 → slim DB追記

7. レース映像をLLMプロンプト（最適化版）で解析する

8. `data/S級DB_slim.xlsx` に出力されたMarkdown表を追記する
   - F1開催 → `F1` シートに追記
   - G3以上 → `G3~1` シートに追記
   - カラム順: 開催日 | 開催場 | レース番号 | 車番 | 選手名 | IP | EP | DP | BP | 直線の伸び | 戦法 | is_monster | is_unreliable

9. VPS の DB を更新して watcher.py を再起動する
   ```
   scp data/S級DB_slim.xlsx ubuntu@<VPS_IP>:~/pdca/data/
   # VPS上で
   sudo systemctl restart keirin-watcher
   ```

---

## ファイル構成まとめ

```
c:\pdca\
├── predict.py              ← 当日予想実行（手動）
├── watcher.py              ← Oracle Cloud 常駐デーモン
├── scraper.py              ← Kdreams スクレイパー
├── hardcore_ev.py          ← バックテスト専用（戦略検証用）
├── plot_pnl.py             ← 収支推移グラフ生成
├── grid_search_ev.py       ← フィルター最適化サーチ
├── requirements_cloud.txt  ← VPS用依存パッケージ
│
└── data/
    ├── racecard.xlsx       ← 出走表（バックテスト用）
    ├── odds.xlsx           ← 3連単オッズ（バックテスト用）
    ├── payouts.xlsx        ← 払戻結果（バックテスト用）
    ├── S級選手究極DB(1).xlsx ← 旧DB（フォールバック用）
    └── S級DB_slim.xlsx     ← 新slim DB（毎開催追記）
```
