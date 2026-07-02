"""Weekly review: 1週間分のスコアカード+日誌+レポートを集約し、振り返り下書きを生成。

APIキーがあればClaudeが「今週の勝ちパターン/負けパターン」を下書きする。
なければデータ集約(ダイジェスト)のみ出力し、止まらない。

Usage (週末に1回、手動実行を推奨):
    python3 -m market_flow.weekly_review
"""

import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from market_flow.paths import reports_dir

JST = timezone(timedelta(hours=9))

REVIEW_PROMPT = """あなたは日本株の兼業トレーダーの振り返りを支援するコーチです。
以下は今週の(1)予測スコアカード、(2)トレード日誌、(3)日次レポートの一覧です。

{digest}

以下の形式で週次振り返りの「下書き」を日本語で作成してください。
本人が15分で読んで追記できる分量(全体で600字程度)に収めること。

## 今週の振り返り(下書き)

### 予測システムの調子
(スコアカードから: 当たっているか、どのセクターで外れやすいか)

### トレードの勝ちパターン
(日誌から: 利益が出たトレードの共通点。データが少なければ「まだ判断材料不足」と正直に)

### トレードの負けパターン / 改善点
(損失トレードの共通点、エントリー理由と結果の食い違い)

### 来週の方針(提案)
(2-3個の具体的な行動提案)

### 本人が追記すべき問い
(数字からは読めない、感情・裁量部分への質問を2つ)
"""


def build_digest(days: int = 7) -> str:
    now = datetime.now(JST)
    since = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    parts = [f"# 週次ダイジェスト ({since} 〜 {now.strftime('%Y-%m-%d')})\n"]

    # 1. scorecard
    try:
        from market_flow.scorecard import load_scorecard, summarize
        rows = [r for r in load_scorecard() if r["pred_date"] >= since]
        parts.append("## 1. 予測スコアカード(今週)")
        if rows:
            for r in rows:
                parts.append(f"- {r['pred_date']} 予測[{r['predicted_sectors']}] → "
                             f"的中 {r['hits_top3']}/3 (平均順位 {r['avg_rank_of_predicted']})")
            parts.append("\n通算: " + summarize().replace("\n", " / "))
        else:
            parts.append("- 今週の採点データなし(`python3 -m market_flow.scorecard score` を実行)")
    except Exception as e:
        parts.append(f"- スコアカード読込エラー: {e}")

    # 2. journal
    try:
        from market_flow.journal import load_trades
        trades = load_trades()
        weekly_closed = [t for t in trades
                         if t["status"] == "closed" and t["closed_at"] >= since]
        open_trades = [t for t in trades if t["status"] == "open"]
        parts.append("\n## 2. トレード日誌(今週決済分)")
        if weekly_closed:
            for t in weekly_closed:
                side = "買" if t["side"] == "buy" else "売"
                parts.append(f"- {t['closed_at']} {t['code']} {t['name']} {side} "
                             f"{t['qty']}株 建{t['entry_price']}→決{t['exit_price']} "
                             f"損益{float(t['pnl']):+,.0f}円 理由:「{t['reason']}」")
            total = sum(float(t["pnl"]) for t in weekly_closed)
            parts.append(f"- 今週合計: {total:+,.0f}円 ({len(weekly_closed)}件)")
        else:
            parts.append("- 今週の決済記録なし")
        if open_trades:
            parts.append(f"- 保有中: {len(open_trades)}件 "
                         f"({', '.join(t['code'] for t in open_trades)})")
    except Exception as e:
        parts.append(f"- 日誌読込エラー: {e}")

    # 3. reports generated this week
    parts.append("\n## 3. 今週生成されたレポート")
    week_files = sorted(p.name for p in reports_dir().glob("*.md")
                        if p.name[:8].isdigit()
                        and p.name[:8] >= since.replace("-", ""))
    if week_files:
        parts.extend(f"- {name}" for name in week_files)
    else:
        parts.append("- なし")

    return "\n".join(parts)


def run_weekly_review():
    now = datetime.now(JST)
    print(f"[{now.strftime('%Y-%m-%d %H:%M JST')}] 週次レビューを作成します...")

    digest = build_digest()
    md_content = f"# 週次レビュー\n**作成日時**: {now.strftime('%Y-%m-%d %H:%M JST')}\n\n"

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        print("Claude で振り返り下書きを作成中...")
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1536,
            messages=[{"role": "user",
                       "content": REVIEW_PROMPT.format(digest=digest)}],
        )
        md_content += message.content[0].text + "\n\n---\n\n" + digest
    else:
        print("⚠️  ANTHROPIC_API_KEY未設定。ダイジェストのみ生成します。")
        md_content += digest

    md_path = reports_dir() / f"{now.strftime('%Y%m%d')}_weekly_review.md"
    md_path.write_text(md_content, encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(md_content)
    print(f"{'=' * 60}")
    print(f"\nレポート保存: {md_path}")


if __name__ == "__main__":
    run_weekly_review()
