# market-data

GitHub Actions (`market-flow.yml`) が自動生成する分析レポートの蓄積ブランチ。
コードブランチとは独立(orphan)。手動でコミットしないこと。

- `reports/YYYYMMDD_*.md` — 夜間分析・朝チェック・週次レビュー
- `reports/scorecard.csv` — 予測採点の蓄積
- `reports/dashboard.html` — 統合ダッシュボード
- `reports/.scheduler_state.json` / `scheduler.log` — ハートビート

ローカルに取り込む: `bash scripts/pull_reports.sh`
