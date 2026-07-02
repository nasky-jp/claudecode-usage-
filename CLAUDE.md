# Market Analysis Flow

日本株トレーダー(兼業)向け定期マーケット分析システム。
運用手順の詳細は `docs/OPERATIONS.md`、改善ロードマップは `docs/KAIZEN_PLAN.md` を参照。

## Webアプリ(推奨・完全自動化)

```bash
python3 -m market_flow.webapp    # http://127.0.0.1:8035 (127.0.0.1限定バインド)
```
起動しておくだけで夜間分析(平日22時)→朝チェック(平日8時)→答え合わせ(平日16:30)→週次レビュー(土10時)が自動実行される(キャッチアップ・ハートビート付き)。画面からトレード記録・手動実行・レポート閲覧が可能。設定は `market_flow/config.example.json` を `config.json` にコピーして変更。自動実行を止める: `MARKET_FLOW_NO_SCHEDULER=1`。

## 定期実行コマンド(CLI単体でも可)

### 夜間分析（平日22時）
```bash
cd /home/user/claudecode-usage- && ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY python3 -m market_flow.analyze_night
```
NASDAQ・ドル円・日経先物・GOLDを取得し、Claude が翌日の強いセクターを予測してレポートを `market_flow/reports/` に保存する。レポートJSONには機械可読の `top_sectors` が入る。

### 朝の確認（平日8時）
```bash
cd /home/user/claudecode-usage- && ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY python3 -m market_flow.morning_check
```
前夜のレポートと現在のデータを比較し、今日の注目ポイントを3つにまとめる。
自動で 🔍監視リスト(注目セクターの日本株ランキング)と 📒保有ポジションが付き、`reports/dashboard.html` が更新される。

### 予測の答え合わせ（引け後、API課金なし）
```bash
python3 -m market_flow.scorecard score    # 未採点の夜間予測を採点しCSVに蓄積
python3 -m market_flow.scorecard summary  # 的中率サマリー
```

### 週次レビュー（週末）
```bash
python3 -m market_flow.weekly_review
```

## 補助ツール

```bash
python3 -m market_flow.journal add <code> --side buy --qty 100 --price 25000 \
  --stop 24500 --setup "セクター順張り" --grade A --plan on --reason "..."  # トレード記録(R計算対応)
python3 -m market_flow.journal close <ID> --price <価格>   # 決済(R-multiple自動計算)
python3 -m market_flow.journal summary                     # 成績(期待値/R/セットアップ別/計画内外)
python3 -m market_flow.screener                            # 監視リスト単体生成
python3 -m market_flow.dashboard                           # ダッシュボード再生成
python3 -m market_flow.selftest                            # オフライン回帰テスト(ネットワーク・API不要)
```

## Claude Code Skills

- `trade-journal` — 「トヨタ200株3100円で買ったのを記録して」
- `morning-brief` — 「今日の注目は?」
- `weekly-review` — 「今週の振り返りやろう」

## セットアップ

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
```

## レポート保存先

`market_flow/reports/YYYYMMDD_night_report.md` - 夜間分析
`market_flow/reports/YYYYMMDD_morning_check.md` - 朝の確認
`market_flow/reports/YYYYMMDD_weekly_review.md` - 週次レビュー
`market_flow/reports/scorecard.csv` - 予測採点の蓄積(手編集禁止)
`market_flow/reports/dashboard.html` - 統合ダッシュボード(毎回上書き)
`market_flow/journal/trades.csv` - トレード日誌(Excel互換・手編集禁止)

## 開発時の注意

- コード変更後は `python3 -m market_flow.selftest` を実行すること(ネットワーク不要)。
- `scorecard.csv` / `trades.csv` を書き換えるコードは追記のみ・一時ファイル経由にする。
- `universe.py` のセクター名は `fetch_market.SECTOR_ETFS` のキーと一致させる(下流の共通語彙)。
- APIキーをコミットしない。発注の自動化は実装しない。
