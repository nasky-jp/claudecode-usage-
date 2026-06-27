"""Night analysis: fetch market data and predict next-day sectors with Claude."""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent))
from market_flow.fetch_market import fetch_all, format_market_summary

JST = timezone(timedelta(hours=9))
REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

SYSTEM_PROMPT = """あなたは経験豊富な日本株式市場のトレーダー兼アナリストです。
米国市場の動向から翌日の日本株市場を予測するプロフェッショナルとして、
簡潔で実践的な分析を日本語で提供してください。
初心者にも分かりやすく、かつ上級者が実際に使える洞察を提供します。"""

ANALYSIS_PROMPT = """以下の米国市場データを分析し、明日の日本株市場について予測してください。

{market_summary}

以下の形式で分析してください：

## 1. 市場全体の概況
（NASDAQ・S&P500・ダウ・ドル円・GOLDの動きを1-2文で）

## 2. 翌日の日本株への影響
（強気/弱気/中立、その理由）

## 3. 注目セクター（TOP3）
各セクターについて：
- セクター名
- 注目理由（米国市場の動きとの連動性）
- 関連日本株の例（ティッカーでなく企業名で）

## 4. リスク要因
（明日注意すべき点を箇条書きで2-3個）

## 5. 朝の確認ポイント
（翌朝8時に確認すべき具体的なチェックリスト）
"""


def analyze_with_claude(market_data: dict, market_summary: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "ERROR: ANTHROPIC_API_KEY が設定されていません。"

    client = anthropic.Anthropic(api_key=api_key)

    prompt = ANALYSIS_PROMPT.format(market_summary=market_summary)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text


def run_night_analysis():
    now = datetime.now(JST)
    print(f"[{now.strftime('%H:%M JST')}] 夜間分析を開始します...")

    print("市場データを取得中...")
    market_data = fetch_all()
    market_summary = format_market_summary(market_data)

    print("Claude で分析中...")
    analysis = analyze_with_claude(market_data, market_summary)

    report = {
        "date": now.strftime("%Y-%m-%d"),
        "analyzed_at": now.strftime("%Y-%m-%d %H:%M JST"),
        "market_data": market_data,
        "analysis": analysis,
    }

    date_str = now.strftime("%Y%m%d")
    json_path = REPORTS_DIR / f"{date_str}_night_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    md_path = REPORTS_DIR / f"{date_str}_night_report.md"
    md_content = f"# 夜間マーケット分析レポート\n**分析日時**: {report['analyzed_at']}\n\n"
    md_content += market_summary + "\n\n---\n\n"
    md_content += "## Claude の分析・予測\n\n" + analysis
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"\n{'='*60}")
    print(md_content)
    print(f"{'='*60}")
    print(f"\nレポート保存: {md_path}")

    return report


if __name__ == "__main__":
    run_night_analysis()
