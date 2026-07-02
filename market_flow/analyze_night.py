"""Night analysis: fetch market data and predict next-day sectors with Claude."""

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

最後に、機械処理用として次の形式の1行を必ず出力してください（説明文は不要）：
TOP_SECTORS: セクター名1, セクター名2, セクター名3

セクター名は必ず次のリストから選ぶこと：
{sector_list}
"""


def parse_top_sectors(analysis_text: str) -> list[str]:
    """分析テキストから TOP_SECTORS 行を抽出して正規セクター名のリストを返す。

    行がない旧形式レポートは「## 3. 注目セクター」以降の本文から推定する。
    """
    from market_flow.universe import match_sector

    for line in analysis_text.splitlines():
        if line.strip().startswith("TOP_SECTORS:"):
            raw = line.split(":", 1)[1]
            sectors = []
            for token in raw.replace("、", ",").split(","):
                matched = match_sector(token)
                if matched and matched not in sectors:
                    sectors.append(matched)
            if sectors:
                return sectors[:3]

    # fallback: 本文からの推定(旧形式レポート用)
    from market_flow.universe import SECTOR_NAMES
    sectors = []
    body = analysis_text.split("注目セクター", 1)[-1]
    for name in SECTOR_NAMES:
        if name in body and name not in sectors:
            sectors.append(name)
    return sectors[:3]


def analyze_with_claude(market_data: dict, market_summary: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "ERROR: ANTHROPIC_API_KEY が設定されていません。"

    client = anthropic.Anthropic(api_key=api_key)

    from market_flow.universe import SECTOR_NAMES
    prompt = ANALYSIS_PROMPT.format(
        market_summary=market_summary,
        sector_list=", ".join(SECTOR_NAMES),
    )

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
        "top_sectors": parse_top_sectors(analysis),
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
