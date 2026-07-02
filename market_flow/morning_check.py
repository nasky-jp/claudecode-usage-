"""Morning check: compare current market with previous night's prediction."""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent))
from market_flow.fetch_market import fetch_all, format_market_summary
from market_flow.paths import reports_dir

JST = timezone(timedelta(hours=9))
REPORTS_DIR = reports_dir()

MORNING_PROMPT = """昨夜の分析予測と、現在の朝の市場データを比較してください。

## 昨夜の予測レポート
{night_analysis}

## 現在の朝の市場データ
{morning_summary}

以下の形式で朝の確認サマリーを作成してください：

## ✅ 朝の確認サマリー

### 予測との比較
（昨夜の予測が当たっているか、外れているか簡潔に）

### 今日の注目ポイント（3つだけ）
1.
2.
3.

### 朝イチのアクション候補
（具体的に「○○セクターの△△を確認」「××円以上で△△」など）

### ⚠️ 変化した点・注意事項
（昨夜から状況が変わった点があれば）
"""


def build_extras(night_report: dict | None) -> str:
    """監視リスト(スクリーナー)と保有ポジションのリマインダーを組み立てる。

    どちらも失敗しても朝チェック本体は止めない。
    """
    parts = []

    try:
        sectors = (night_report or {}).get("top_sectors")
        if not sectors and night_report:
            from market_flow.analyze_night import parse_top_sectors
            sectors = parse_top_sectors(night_report.get("analysis", ""))
        if sectors:
            from market_flow.screener import build_watchlist
            parts.append(build_watchlist(sectors))
    except Exception as e:
        parts.append(f"## 🔍 朝の監視リスト\n\n生成に失敗しました: {e}")

    try:
        from market_flow.journal import load_trades
        open_trades = [t for t in load_trades() if t["status"] == "open"]
        if open_trades:
            lines = ["## 📒 保有中ポジション(日誌より)"]
            for t in open_trades:
                side = "買" if t["side"] == "buy" else "売"
                lines.append(f"- #{t['id']} {t['code']} {t['name']} {side} "
                             f"{t['qty']}株 @ {t['entry_price']}円  ({t['reason']})")
            lines.append("")
            lines.append("> 決済したら `python3 -m market_flow.journal close <ID> --price <価格>`")
            parts.append("\n".join(lines))
    except Exception:
        pass

    return "\n\n---\n\n".join(parts)


def load_last_night_report() -> dict | None:
    now = datetime.now(JST)
    for days_back in range(3):
        check_date = now - timedelta(days=days_back)
        date_str = check_date.strftime("%Y%m%d")
        report_path = REPORTS_DIR / f"{date_str}_night_report.json"
        if report_path.exists():
            with open(report_path, encoding="utf-8") as f:
                return json.load(f)
    return None


def run_morning_check():
    now = datetime.now(JST)
    print(f"[{now.strftime('%H:%M JST')}] 朝の確認を開始します...")

    night_report = load_last_night_report()
    if not night_report:
        print("⚠️  昨夜のレポートが見つかりません。まず analyze_night.py を実行してください。")
        print("\n現在の市場データのみ表示します:\n")
        morning_data = fetch_all()
        print(format_market_summary(morning_data))
        return

    print(f"昨夜のレポート読込: {night_report['analyzed_at']}")
    print("現在の市場データを取得中...")
    morning_data = fetch_all()
    morning_summary = format_market_summary(morning_data)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("⚠️  ANTHROPIC_API_KEY未設定。データのみ表示します。\n")
        print(morning_summary)
        return

    client = anthropic.Anthropic(api_key=api_key)
    prompt = MORNING_PROMPT.format(
        night_analysis=night_report["analysis"],
        morning_summary=morning_summary,
    )

    print("Claude で朝の確認サマリーを作成中...")
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    morning_summary_text = message.content[0].text

    date_str = now.strftime("%Y%m%d")
    md_path = REPORTS_DIR / f"{date_str}_morning_check.md"
    md_content = f"# 朝の確認サマリー\n**確認日時**: {now.strftime('%Y-%m-%d %H:%M JST')}\n\n"
    md_content += morning_summary + "\n\n---\n\n"
    md_content += morning_summary_text

    extras = build_extras(night_report)
    if extras:
        md_content += "\n\n---\n\n" + extras

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"\n{'='*60}")
    print(md_content)
    print(f"{'='*60}")
    print(f"\nレポート保存: {md_path}")

    try:
        from market_flow.dashboard import generate_dashboard
        dash_path = generate_dashboard()
        print(f"ダッシュボード更新: {dash_path}")
    except Exception as e:
        print(f"⚠️  ダッシュボード生成に失敗: {e}")


if __name__ == "__main__":
    run_morning_check()
