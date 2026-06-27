# Market Analysis Flow

日本株トレーダー向け定期マーケット分析システム。

## 定期実行コマンド

### 夜間分析（平日22時）
```bash
cd /home/user/claudecode-usage- && ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY python3 -m market_flow.analyze_night
```
NASDAQ・ドル円・日経先物・GOLDを取得し、Claude が翌日の強いセクターを予測してレポートを `market_flow/reports/` に保存する。

### 朝の確認（平日8時）
```bash
cd /home/user/claudecode-usage- && ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY python3 -m market_flow.morning_check
```
前夜のレポートと現在のデータを比較し、今日の注目ポイントを3つにまとめる。

## セットアップ

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
```

## レポート保存先
`market_flow/reports/YYYYMMDD_night_report.md` - 夜間分析
`market_flow/reports/YYYYMMDD_morning_check.md` - 朝の確認
