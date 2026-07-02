# 運用手順書(OPERATIONS)

Market Flow の日次・週次の定型手順。**考えることを減らすための手順書**なので、この通りに回す。

---

## 推奨: Webアプリで完全自動化(v2)

```bash
export ANTHROPIC_API_KEY=your_key
python3 -m market_flow.webapp     # http://127.0.0.1:8035
```

これ1プロセスを起動しておくだけで、以下がすべて自動で回る:

| ジョブ | スケジュール | 課金 |
|---|---|---|
| 🌙 夜間分析 | 平日 22:00 | あり(1回数円) |
| ☀️ 朝の確認+監視リスト+ダッシュボード | 平日 08:00 | あり(1回数円) |
| 🎯 予測の答え合わせ | 平日 16:30 | なし |
| 📝 週次レビュー | 土 10:00 | あり(1回数円) |

- 画面から **トレード記録・決済・手動実行・過去レポート閲覧** ができる
- **キャッチアップ実行**: PCが止まっていても、予定時刻から4時間以内に起動すれば未実行分が走る(systemd timer の `Persistent=true` 相当)
- **ハートビート**: 各ジョブの最終実行と成否が画面最上部に出る。「自動化が静かに死んでいた」を毎朝検知できる
- 時刻・有効/無効の変更: `market_flow/config.example.json` を `market_flow/config.json` にコピーして編集
- 自動実行なしで画面だけ使う: `MARKET_FLOW_NO_SCHEDULER=1 python3 -m market_flow.webapp`
- **127.0.0.1 のみにバインド**している。外部公開(0.0.0.0や公開サーバー)にしないこと(認証なしのため)

### 常駐させる(macOS/Linux)

ログイン時に自動起動したい場合は systemd (Linux) / launchd (macOS) に登録する。Linux例:

```ini
# ~/.config/systemd/user/market-flow.service
[Unit]
Description=Market Flow webapp

[Service]
Environment=ANTHROPIC_API_KEY=your_key
WorkingDirectory=/home/user/claudecode-usage-
ExecStart=/usr/bin/python3 -m market_flow.webapp
Restart=on-failure

[Install]
WantedBy=default.target
```
`systemctl --user enable --now market-flow` で常駐。cron派は下記「cron設定」も引き続き使える。

---

## 毎日の流れ

### 夜(22:00) — 自動実行(cron設定済みの場合)/手動なら3分

```bash
cd /home/user/claudecode-usage- && python3 -m market_flow.analyze_night
```

- やること: **なし**(自動)。寝る前に見たければ `reports/dashboard.html` を開く。

### 朝(8:00) — 自動実行 + 人間5分

```bash
cd /home/user/claudecode-usage- && python3 -m market_flow.morning_check
```

朝チェックには自動で以下が付く:
- 🔍 監視リスト(注目セクターの主要銘柄を前日比順)
- 📒 保有中ポジションのリマインダー

**人間のチェックリスト(5分):**
1. [ ] `reports/dashboard.html` を開く(またはClaude Codeで「朝の確認」と言う)
2. [ ] 方向感(強気/弱気/中立)と自分の感覚が合っているか
3. [ ] 監視リスト上位3銘柄の板・ニュースだけ証券アプリで確認
4. [ ] 保有中ポジションに影響するニュースがないか
5. [ ] **発注する/しないを自分で決める**(システムは推奨しない)

### 引け後(15:30以降) — 人間1分

売買した日だけ。Webアプリのフォームから記録するか、CLIで:
```bash
python3 -m market_flow.journal add 8035 --side buy --qty 100 --price 25000 \
  --stop 24500 --setup "セクター順張り" --grade A --plan on \
  --name 東京エレクトロン --sector 半導体 --reason "夜間TOP1・寄りギャップ小"
# 決済した場合
python3 -m market_flow.journal close <ID> --price 25800
```
Claude Code なら「東京エレクトロン100株25000円で買ったのを記録して」でOK(trade-journal Skill)。

**記録のコツ(トレードジャーナルの定石):**
- **--reason は必ず書く。** 週次振り返りで一番効く項目。
- **--stop(損切りライン)を書くと R-multiple が自動計算される。** 損益を「リスク1単位あたり何倍か」で標準化でき、銘柄や株数が違うトレード同士を比較できる。
- **--plan on/off**(事前計画どおりか、衝動エントリーか)を付けると、summary で計画外トレードの損失比率が見える。多くのトレーダーは損失の6〜7割が計画外トレードから出る。
- **--setup + --grade(A/B/C)** を続けると「A評価セットアップだけ期待値プラス」のような発見ができる(目安50トレード以上)。

## 毎週の流れ(週末15分)

```bash
python3 -m market_flow.scorecard score     # 1. 今週の予測を答え合わせ
python3 -m market_flow.weekly_review       # 2. 振り返り下書き生成
python3 -m market_flow.dashboard           # 3. ダッシュボード更新
```
Claude Code なら「今週の振り返りやろう」の一言(weekly-review Skill)。

**人間のチェックリスト:**
1. [ ] スコアカードの的中率を確認(ランダム期待値0.75/3を上回っているか)
2. [ ] 週次レビューの「本人が追記すべき問い」に答えて追記
3. [ ] 負けトレードの reason と結果の食い違いを1つ言語化する

## 月次(月初5分)

```bash
python3 -m market_flow.journal summary --month 2026-06
```

---

## cron 設定(任意・API課金が発生する点に注意)

夜間分析・朝チェックは1回ごとにAnthropic APIを呼ぶ(Sonnet/Haiku、1回あたり数円程度)。
自動化する場合は自分の環境の crontab に:

```cron
# 夜間分析 (月〜金 22:00 JST)
0 22 * * 1-5 cd /home/user/claudecode-usage- && ANTHROPIC_API_KEY=... python3 -m market_flow.analyze_night >> /tmp/market_night.log 2>&1
# 朝の確認 (月〜金 08:00 JST)
0 8 * * 1-5 cd /home/user/claudecode-usage- && ANTHROPIC_API_KEY=... python3 -m market_flow.morning_check >> /tmp/market_morning.log 2>&1
# スコアカード採点 (月〜金 16:30 JST、API課金なし)
30 16 * * 1-5 cd /home/user/claudecode-usage- && python3 -m market_flow.scorecard score >> /tmp/market_score.log 2>&1
```
(サーバーのタイムゾーンがUTCなら時刻を-9hすること。`setup_cron.py` 参照)

---

## ファイル・命名ルール

| ファイル | 内容 | 生成タイミング |
|---|---|---|
| `reports/YYYYMMDD_night_report.md/.json` | 夜間分析 | 毎晩 |
| `reports/YYYYMMDD_morning_check.md` | 朝チェック+監視リスト | 毎朝 |
| `reports/YYYYMMDD_weekly_review.md` | 週次振り返り | 週末 |
| `reports/scorecard.csv` | 予測採点の蓄積(追記のみ) | scorecard score 実行時 |
| `reports/dashboard.html` | 統合ビュー(毎回上書き) | 朝チェック後/手動 |
| `journal/trades.csv` | トレード記録(Excelで直接開ける) | journal コマンド実行時 |

**運用ルール:**
- `scorecard.csv` と `trades.csv` は**手で編集しない**(壊れたらExcelでコピーを開く)。
- レポートmdは読み取り専用扱い。追記するのは weekly_review の「本人メモ」のみ。
- 3ヶ月以上前の日次レポートは `reports/archive/YYYY-MM/` に移動してよい(scorecard.csv は残す)。
- `universe.py` のセクター構成銘柄は**1月・7月に見直す**(上場廃止・入替チェック)。

## 障害時の対応

| 症状 | 対応 |
|---|---|
| レポートが「取得失敗」だらけ | yfinance側の一時障害が多い。1時間後に手動再実行。続くなら `pip install -U yfinance`。恒常的に不安定なら日本株はJPX公式の [J-Quants API](https://jpx-jquants.com/)(無料プランあり)への移行を検討(KAIZEN_PLAN候補) |
| Webアプリのジョブが「未実行」のまま | アプリが落ちていないか確認。予定時刻から4時間超は安全のため自動キャッチアップしない→「今すぐ実行」で手動実行 |
| `ANTHROPIC_API_KEY が設定されていません` | `export ANTHROPIC_API_KEY=...` を設定。キーは**このリポジトリに書かない**(.envは.gitignore済み) |
| scorecard score が「翌営業日のデータ未達」 | 正常。翌営業日の引け後に再実行すれば採点される |
| 監視リストが「ユニバース未登録」 | `universe.py` にセクターが無い。`match_sector` のエイリアスに追加 |
| journal close でID不明 | `python3 -m market_flow.journal list --open` |

## セキュリティ・安全ルール

- APIキー・口座情報をリポジトリにコミットしない(コミット前に `git diff --cached` で確認)。
- このシステムの出力は**監視候補の提示まで**。発注の自動化はしない。
- 外部への投稿・送信機能は現状なし。追加する場合は誤送信対策(ドライラン・確認プロンプト)を必須にする。
