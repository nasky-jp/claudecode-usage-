#!/usr/bin/env bash
# GitHub Actions が market-data ブランチに蓄積したレポートを
# ローカルの market_flow/reports/ に取り込む (ローカルWebアプリで閲覧するため)。
# 注意: 同名ファイルはクラウド側の内容で上書きされる。日誌(journal)には触れない。
set -euo pipefail
cd "$(dirname "$0")/.."

git fetch origin market-data
mkdir -p market_flow/reports
if git ls-tree --name-only FETCH_HEAD | grep -qx reports; then
  git archive --format=tar FETCH_HEAD reports | tar -x --strip-components=1 -C market_flow/reports
  echo "✅ market-data のレポートを market_flow/reports/ に取り込みました"
  ls -t market_flow/reports | head -5
else
  echo "market-data ブランチにまだレポートがありません(最初のジョブ実行後に増えます)"
fi
