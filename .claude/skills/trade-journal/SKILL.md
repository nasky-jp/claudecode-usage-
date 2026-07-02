---
name: trade-journal
description: トレード日誌の記録・決済・確認。ユーザーが「〜を買った/売った を記録して」「ポジション決済して」「今月の成績は?」「日誌見せて」などトレード記録に関する依頼をしたときに使う。
---

# トレード日誌 Skill

ユーザーの自然文から売買情報を抜き出し、`market_flow.journal` CLI で記録する。

## コマンド(リポジトリルートで実行)

新規記録:
```bash
python3 -m market_flow.journal add <銘柄コード> --side buy|sell --qty <株数> --price <建値> \
  --name <銘柄名> --sector <セクター名> --reason "<エントリー理由>"
```

決済:
```bash
python3 -m market_flow.journal list --open          # IDを確認
python3 -m market_flow.journal close <ID> --price <決済価格>
```

確認:
```bash
python3 -m market_flow.journal list
python3 -m market_flow.journal summary [--month YYYY-MM]
```

## 実行ルール

1. **銘柄コードが不明な場合**: 銘柄名から4桁コードを推定してよいが、実行前に「8035 東京エレクトロンで記録します」と確認を挟むこと。
2. **--reason は必ず埋める**: ユーザーが理由を言わなければ「なぜ入りましたか?(振り返りで一番効く項目です)」と聞く。夜間レポートのセクター予測に基づくなら「夜間レポート YYYY-MM-DD TOP1セクター」のように書く。
3. **--sector** は `market_flow/universe.py` のセクター名(半導体、AI/テクノロジー、金融など)に合わせる。
4. 記録後は保存結果(ID・内容)をそのまま報告する。CSVを直接編集しない。
5. 過去日付の記録は `--date "YYYY-MM-DD HH:MM"` を使う。
