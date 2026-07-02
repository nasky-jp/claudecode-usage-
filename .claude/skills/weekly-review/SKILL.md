---
name: weekly-review
description: 週次振り返り。ユーザーが「今週の振り返り」「週次レビュー」「今週どうだった?」などと言ったときに使う。スコアカード採点→週次レビュー生成→対話での深掘りまで行う。
---

# 週次レビュー Skill

## 手順(週末に1回)

1. まず未採点の予測を採点する(ネットワーク必要):
   ```bash
   python3 -m market_flow.scorecard score
   ```
2. 週次レビューを生成する(ANTHROPIC_API_KEY があればClaude下書き付き):
   ```bash
   python3 -m market_flow.weekly_review
   ```
3. 生成された `market_flow/reports/YYYYMMDD_weekly_review.md` を読み、
   「本人が追記すべき問い」をユーザーに1つずつ質問して、回答をレビューmdの末尾に
   「## 本人の振り返りメモ」として追記する。
4. 最後にダッシュボードを更新する:
   ```bash
   python3 -m market_flow.dashboard
   ```

## ルール

- 数字(勝率・損益・的中率)はスクリプトの出力を使い、自分で計算し直さない。
- データが少ない週は無理に結論を出さず「判断材料不足」と書く。
- ユーザーの回答の追記以外で、過去のレポートファイルを書き換えない。
