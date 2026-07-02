"""Morning screener: 注目セクター → 日本株の監視候補リストを自動生成。

夜間レポートの top_sectors を読み、universe.py の構成銘柄を
前日比・5日騰落・出来高倍率でランク付けした監視リストを作る。
morning_check から自動で呼ばれるほか、単体でも実行できる。

Usage:
    python3 -m market_flow.screener            # 最新の夜間レポートのセクターで実行
    python3 -m market_flow.screener --sectors 半導体 金融
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from market_flow.paths import reports_dir
from market_flow.universe import JP_UNIVERSE, match_sector, to_yf_symbol


def latest_night_sectors() -> tuple[list[str], str | None]:
    """最新の夜間レポートから (top_sectors, レポート日付) を返す。"""
    from market_flow.analyze_night import parse_top_sectors

    paths = sorted(reports_dir().glob("*_night_report.json"), reverse=True)
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                report = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        sectors = report.get("top_sectors") or parse_top_sectors(report.get("analysis", ""))
        if sectors:
            return sectors, report.get("date")
    return [], None


def _stock_metrics(hist: list[dict]) -> dict | None:
    """日足履歴から 前日比/5日騰落/出来高倍率 を計算。データ不足なら None。"""
    if len(hist) < 2:
        return None
    closes = [h["close"] for h in hist]
    volumes = [h.get("volume", 0) for h in hist]
    last, prev = closes[-1], closes[-2]
    if not prev:
        return None
    chg_1d = (last - prev) / prev * 100
    chg_5d = None
    if len(closes) >= 6 and closes[-6]:
        chg_5d = (last - closes[-6]) / closes[-6] * 100
    vol_ratio = None
    prev_vols = [v for v in volumes[-6:-1] if v]
    if prev_vols and volumes[-1]:
        vol_ratio = volumes[-1] / (sum(prev_vols) / len(prev_vols))
    return {
        "date": hist[-1]["date"],
        "close": last,
        "chg_1d": chg_1d,
        "chg_5d": chg_5d,
        "vol_ratio": vol_ratio,
    }


def build_watchlist(sectors: list[str], history_fn=None) -> str:
    """セクターごとの監視リストをMarkdownで返す。

    history_fn: fetch_daily_history 互換 (テストで注入可能)
    """
    if history_fn is None:
        from market_flow.fetch_market import fetch_daily_history
        history_fn = fetch_daily_history

    lines = ["## 🔍 朝の監視リスト(注目セクターの主要銘柄)\n"]
    got_any = False
    for raw in sectors:
        sector = match_sector(raw)
        if sector is None or sector not in JP_UNIVERSE:
            lines.append(f"### {raw}\n- ユニバース未登録のセクターです(universe.py に追加してください)\n")
            continue

        rows = []
        for code, name in JP_UNIVERSE[sector]:
            hist = history_fn(to_yf_symbol(code), period="10d")
            m = _stock_metrics(hist)
            if m:
                rows.append((code, name, m))
        lines.append(f"### {sector}")
        if not rows:
            lines.append("- データ取得に失敗しました(ネットワーク/データソースを確認)\n")
            continue

        got_any = True
        rows.sort(key=lambda r: r[2]["chg_1d"], reverse=True)
        lines.append("| コード | 銘柄 | 終値 | 前日比 | 5日騰落 | 出来高倍率 |")
        lines.append("|---|---|---:|---:|---:|---:|")
        for code, name, m in rows:
            chg5 = f"{m['chg_5d']:+.1f}%" if m["chg_5d"] is not None else "-"
            vol = f"{m['vol_ratio']:.1f}x" if m["vol_ratio"] is not None else "-"
            lines.append(
                f"| {code} | {name} | {m['close']:,.0f} | {m['chg_1d']:+.2f}% "
                f"| {chg5} | {vol} |")
        lines.append("")

    if got_any:
        lines.append("> 見方: 前日比が高い順。出来高倍率 = 直近出来高 ÷ 過去5日平均。")
        lines.append("> ⚠️ これは監視候補であり売買推奨ではない。発注判断は必ず自分で行うこと。")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m market_flow.screener",
        description="注目セクター→日本株監視リストを生成",
    )
    parser.add_argument("--sectors", nargs="*",
                        help="対象セクター (省略時は最新の夜間レポートから)")
    args = parser.parse_args(argv)

    sectors = args.sectors
    if not sectors:
        sectors, report_date = latest_night_sectors()
        if not sectors:
            print("❌ 夜間レポートが見つかりません。--sectors で指定するか、"
                  "先に analyze_night を実行してください。")
            return 1
        print(f"(夜間レポート {report_date} の注目セクターを使用)\n")

    print(build_watchlist(sectors))
    return 0


if __name__ == "__main__":
    sys.exit(main())
