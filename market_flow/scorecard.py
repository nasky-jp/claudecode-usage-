"""Prediction scorecard: 夜間レポートの注目セクター予測を翌営業日の実績で自動採点。

セクター実績 = universe.py の構成銘柄の前日比(%)平均。
結果は reports/scorecard.csv に蓄積(1予測=1行、再実行しても重複しない)。

Usage:
    python3 -m market_flow.scorecard score    # 未採点レポートを採点して蓄積
    python3 -m market_flow.scorecard summary  # 的中率サマリー
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from market_flow.paths import reports_dir
from market_flow.universe import JP_UNIVERSE, SECTOR_NAMES, to_yf_symbol

JST = timezone(timedelta(hours=9))

CSV_FIELDS = [
    "pred_date", "eval_date", "predicted_sectors", "actual_ranking",
    "hits_top3", "avg_rank_of_predicted", "scored_at",
]


def scorecard_path() -> Path:
    return reports_dir() / "scorecard.csv"


def load_scorecard() -> list[dict]:
    path = scorecard_path()
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def append_rows(rows: list[dict]) -> None:
    path = scorecard_path()
    exists = path.exists()
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def load_night_reports() -> list[dict]:
    """reports/*_night_report.json を日付順に読む。top_sectors がない旧形式は補完。"""
    from market_flow.analyze_night import parse_top_sectors

    reports = []
    for path in sorted(reports_dir().glob("*_night_report.json")):
        try:
            with open(path, encoding="utf-8") as f:
                report = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if not report.get("top_sectors"):
            report["top_sectors"] = parse_top_sectors(report.get("analysis", ""))
        if report.get("date") and report.get("top_sectors"):
            reports.append(report)
    return reports


def sector_performance(
    eval_date: str, histories: dict[str, list[dict]]
) -> dict[str, float]:
    """eval_date のセクター別 前日比(%) 平均。データが足りないセクターは除外。"""
    perf: dict[str, float] = {}
    for sector, members in JP_UNIVERSE.items():
        changes = []
        for code, _name in members:
            hist = histories.get(code, [])
            closes = [(h["date"], h["close"]) for h in hist]
            idx = next((i for i, (d, _) in enumerate(closes) if d == eval_date), None)
            if idx is None or idx == 0:
                continue
            prev, cur = closes[idx - 1][1], closes[idx][1]
            if prev:
                changes.append((cur - prev) / prev * 100)
        if changes:
            perf[sector] = sum(changes) / len(changes)
    return perf


def _all_dates(histories: dict[str, list[dict]]) -> list[str]:
    dates = set()
    for hist in histories.values():
        dates.update(h["date"] for h in hist)
    return sorted(dates)


def score_pending(history_fn=None, verbose: bool = True) -> list[dict]:
    """未採点の夜間レポートを採点して scorecard.csv に追記する。

    history_fn: fetch_daily_history 互換 (テストで注入可能)
    """
    if history_fn is None:
        from market_flow.fetch_market import fetch_daily_history
        history_fn = fetch_daily_history

    scored_dates = {row["pred_date"] for row in load_scorecard()}
    pending = [r for r in load_night_reports() if r["date"] not in scored_dates]
    if not pending:
        if verbose:
            print("採点待ちのレポートはありません。")
        return []

    if verbose:
        print(f"採点対象: {len(pending)}件。日本株の日足データを取得中...")
    histories: dict[str, list[dict]] = {}
    failed = []
    for sector, members in JP_UNIVERSE.items():
        for code, _name in members:
            if code not in histories:
                hist = history_fn(to_yf_symbol(code), period="1mo")
                if hist:
                    histories[code] = hist
                else:
                    failed.append(code)
    if failed and verbose:
        print(f"⚠️  取得失敗 {len(failed)}銘柄: {', '.join(failed[:10])}")
    if not histories:
        if verbose:
            print("❌ 株価データが1件も取得できませんでした。採点を中止します。")
        return []

    trading_dates = _all_dates(histories)
    now = datetime.now(JST)
    new_rows = []
    for report in pending:
        pred_date = report["date"]
        eval_date = next((d for d in trading_dates if d > pred_date), None)
        if eval_date is None:
            if verbose:
                print(f"- {pred_date}: 翌営業日のデータ未達のためスキップ(明日以降に再実行)")
            continue

        perf = sector_performance(eval_date, histories)
        if len(perf) < 6:
            if verbose:
                print(f"- {pred_date}: {eval_date} のセクターデータ不足のためスキップ")
            continue

        ranking = sorted(perf.items(), key=lambda x: -x[1])
        rank_of = {sector: i + 1 for i, (sector, _) in enumerate(ranking)}
        predicted = [s for s in report["top_sectors"] if s in rank_of][:3]
        if not predicted:
            if verbose:
                print(f"- {pred_date}: 予測セクターを実績と突合できずスキップ")
            continue

        actual_top3 = [s for s, _ in ranking[:3]]
        hits = sum(1 for s in predicted if s in actual_top3)
        avg_rank = sum(rank_of[s] for s in predicted) / len(predicted)

        new_rows.append({
            "pred_date": pred_date,
            "eval_date": eval_date,
            "predicted_sectors": "|".join(predicted),
            "actual_ranking": "|".join(f"{s}:{v:+.2f}%" for s, v in ranking),
            "hits_top3": str(hits),
            "avg_rank_of_predicted": f"{avg_rank:.1f}",
            "scored_at": now.strftime("%Y-%m-%d %H:%M"),
        })
        if verbose:
            print(f"- {pred_date} 予測[{', '.join(predicted)}] → "
                  f"{eval_date} 実績TOP3[{', '.join(actual_top3)}]  "
                  f"的中 {hits}/3, 平均順位 {avg_rank:.1f}")

    if new_rows:
        append_rows(new_rows)
        if verbose:
            print(f"\n✅ {len(new_rows)}件を採点し {scorecard_path()} に追記しました。")
    return new_rows


def summarize(rows: list[dict] | None = None) -> str:
    """スコアカードの集計テキストを返す(ダッシュボードでも利用)。"""
    if rows is None:
        rows = load_scorecard()
    if not rows:
        return ("スコアカードはまだ空です。夜間レポートが1営業日分たまったら "
                "`python3 -m market_flow.scorecard score` を実行してください。")

    n = len(rows)
    hits = [int(r["hits_top3"]) for r in rows]
    avg_ranks = [float(r["avg_rank_of_predicted"]) for r in rows]
    total_sectors = len(SECTOR_NAMES)
    # ランダムに3つ選んだ場合のTOP3的中の期待値 = 3 * 3/12 = 0.75
    random_hits = 3 * 3 / total_sectors
    random_rank = (total_sectors + 1) / 2

    lines = [
        f"採点済み: {n}営業日分",
        f"TOP3的中数: 平均 {sum(hits)/n:.2f}/3 (ランダム期待値 {random_hits:.2f})",
        f"1つ以上的中した日: {sum(1 for h in hits if h >= 1)}/{n}日 "
        f"({sum(1 for h in hits if h >= 1)/n*100:.0f}%)",
        f"予測セクターの平均実績順位: {sum(avg_ranks)/n:.1f}位/{total_sectors}セクター中 "
        f"(ランダム期待値 {random_rank:.1f}位)",
    ]
    recent = rows[-5:]
    lines.append("直近の結果: " + " / ".join(
        f"{r['pred_date']}:{r['hits_top3']}的中" for r in recent))
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m market_flow.scorecard",
        description="夜間予測の的中を自動採点してCSVに蓄積",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("score", help="未採点レポートを採点")
    sub.add_parser("summary", help="的中率サマリーを表示")
    args = parser.parse_args(argv)

    if args.command == "score":
        score_pending()
    elif args.command == "summary":
        print("## 予測スコアカード\n")
        print(summarize())
    return 0


if __name__ == "__main__":
    sys.exit(main())
