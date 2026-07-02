"""Trade journal: record trades in one command, Excel-compatible CSV.

トレードジャーナルの定石(R-multiple / セットアップタグ / 計画内外 / 期待値)に対応:
- --stop で損切りラインを記録すると、決済時に R-multiple(リスク1単位あたり損益)を自動計算
- --setup でセットアップ名、--grade で質(A/B/C)、--plan で計画内(on)/計画外(off)をタグ付け
- summary で期待値(円/R)・セットアップ別・計画内外別の成績を集計

Usage:
    python3 -m market_flow.journal add 8035 --side buy --qty 100 --price 25000 \
        --stop 24500 --setup "セクター順張り" --grade A --plan on \
        --name 東京エレクトロン --sector 半導体 --reason "夜間TOP1・ギャップ小"
    python3 -m market_flow.journal close 1 --price 25800
    python3 -m market_flow.journal list [--open]
    python3 -m market_flow.journal summary [--month 2026-07]
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))

FIELDS = [
    "id", "status", "opened_at", "closed_at", "code", "name", "side",
    "qty", "entry_price", "exit_price", "stop_price",
    "pnl", "pnl_pct", "r_multiple",
    "sector", "setup", "grade", "plan", "reason",
]


def journal_dir() -> Path:
    override = os.environ.get("MARKET_FLOW_JOURNAL_DIR")
    d = Path(override) if override else Path(__file__).parent / "journal"
    d.mkdir(parents=True, exist_ok=True)
    return d


def csv_path() -> Path:
    return journal_dir() / "trades.csv"


def load_trades() -> list[dict]:
    path = csv_path()
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    # 旧形式CSV(列が少ない)も新フィールドを空欄として扱う
    for row in rows:
        for field in FIELDS:
            row.setdefault(field, "")
            if row[field] is None:
                row[field] = ""
    return rows


def save_trades(trades: list[dict]) -> None:
    path = csv_path()
    tmp = path.with_suffix(".csv.tmp")
    # utf-8-sig so the CSV opens correctly in Excel
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, restval="", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(trades)
    tmp.replace(path)


def next_id(trades: list[dict]) -> int:
    ids = [int(t["id"]) for t in trades if str(t.get("id", "")).isdigit()]
    return max(ids, default=0) + 1


# ---- programmatic API (CLI と Webアプリの共通実装) ----

def add_trade(code: str, side: str, qty: float, price: float, *,
              name: str = "", sector: str = "", reason: str = "",
              stop: float | None = None, setup: str = "", grade: str = "",
              plan: str = "", date: str = "") -> dict:
    trades = load_trades()
    now = datetime.now(JST)
    trade = {
        "id": str(next_id(trades)),
        "status": "open",
        "opened_at": date or now.strftime("%Y-%m-%d %H:%M"),
        "closed_at": "",
        "code": code,
        "name": name or "",
        "side": side,
        "qty": f"{qty:g}",
        "entry_price": f"{price:g}",
        "exit_price": "",
        "stop_price": f"{stop:g}" if stop is not None else "",
        "pnl": "",
        "pnl_pct": "",
        "r_multiple": "",
        "sector": sector or "",
        "setup": setup or "",
        "grade": (grade or "").upper(),
        "plan": plan or "",
        "reason": reason or "",
    }
    trades.append(trade)
    save_trades(trades)
    return trade


def close_trade(trade_id: int, price: float, *, date: str = "") -> tuple[dict | None, str | None]:
    """決済処理。(trade, error) を返す。errorがNoneなら成功。"""
    trades = load_trades()
    target = next((t for t in trades if t["id"] == str(trade_id)), None)
    if target is None:
        return None, f"ID {trade_id} の記録が見つかりません。"
    if target["status"] == "closed":
        return target, f"#{trade_id} は決済済みです ({target['closed_at']})。"

    now = datetime.now(JST)
    entry = float(target["entry_price"])
    qty = float(target["qty"])
    if target["side"] == "buy":
        pnl = (price - entry) * qty
    else:
        pnl = (entry - price) * qty
    pnl_pct = (pnl / (entry * qty)) * 100 if entry else 0.0

    target["status"] = "closed"
    target["closed_at"] = date or now.strftime("%Y-%m-%d %H:%M")
    target["exit_price"] = f"{price:g}"
    target["pnl"] = f"{pnl:.0f}"
    target["pnl_pct"] = f"{pnl_pct:.2f}"

    # R-multiple: 損切りライン(stop_price)がある場合のみ計算
    stop_raw = target.get("stop_price", "")
    if stop_raw:
        risk_per_share = abs(entry - float(stop_raw))
        if risk_per_share > 0:
            target["r_multiple"] = f"{pnl / (risk_per_share * qty):.2f}"

    save_trades(trades)
    return target, None


# ---- CLI commands ----

def cmd_add(args) -> int:
    if args.plan and args.plan not in ("on", "off"):
        print("❌ --plan は on(計画内) か off(計画外) を指定してください。")
        return 1
    trade = add_trade(
        args.code, args.side, args.qty, args.price,
        name=args.name or "", sector=args.sector or "", reason=args.reason or "",
        stop=args.stop, setup=args.setup or "", grade=args.grade or "",
        plan=args.plan or "", date=args.date or "",
    )
    label = "買い" if args.side == "buy" else "売り"
    print(f"✅ 記録 #{trade['id']}: {args.code} {trade['name']} {label} "
          f"{args.qty:g}株 @ {args.price:g}円")
    if trade["stop_price"]:
        risk = abs(args.price - float(trade["stop_price"])) * args.qty
        print(f"   損切り: {trade['stop_price']}円 (リスク1R = {risk:,.0f}円)")
    else:
        print("   ⚠️ 損切りライン未設定(--stop を付けるとR-multipleが計算できます)")
    print(f"   保存先: {csv_path()}")
    return 0


def cmd_close(args) -> int:
    target, error = close_trade(args.id, args.price, date=args.date or "")
    if error:
        print(f"❌ {error}")
        return 1
    pnl = float(target["pnl"])
    mark = "🟢" if pnl >= 0 else "🔴"
    r_str = f"  R = {target['r_multiple']}R" if target["r_multiple"] else ""
    print(f"{mark} 決済 #{args.id}: {target['code']} {target['name']} "
          f"@ {args.price:g}円  損益 {pnl:+,.0f}円 ({float(target['pnl_pct']):+.2f}%){r_str}")
    return 0


def cmd_list(args) -> int:
    trades = load_trades()
    if args.open:
        trades = [t for t in trades if t["status"] == "open"]
    if not trades:
        print("記録はまだありません。`add` で最初のトレードを記録してください。")
        return 0
    trades = trades[-args.limit:]
    print(f"{'ID':>3} {'状態':<6} {'日付':<16} {'コード':<6} {'銘柄':<12} "
          f"{'売買':<4} {'数量':>6} {'建値':>9} {'決済':>9} {'損益':>10} {'R':>6}  理由")
    for t in trades:
        side = "買" if t["side"] == "buy" else "売"
        status = "保有中" if t["status"] == "open" else "決済済"
        pnl = f"{float(t['pnl']):+,.0f}" if t["pnl"] else "-"
        r = f"{t['r_multiple']}R" if t["r_multiple"] else "-"
        exit_p = t["exit_price"] or "-"
        print(f"{t['id']:>3} {status:<5} {t['opened_at']:<16} {t['code']:<6} "
              f"{t['name'][:12]:<12} {side:<3} {t['qty']:>6} {t['entry_price']:>9} "
              f"{exit_p:>9} {pnl:>10} {r:>6}  {t['reason'][:30]}")
    return 0


def summary_stats(closed: list[dict]) -> dict:
    """決済済みトレードから成績指標を計算(Webアプリ/週次レビューでも利用)。"""
    pnls = [float(t["pnl"]) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    rs = [float(t["r_multiple"]) for t in closed if t.get("r_multiple")]
    stats = {
        "count": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(pnls) * 100 if pnls else 0.0,
        "total": sum(pnls),
        "expectancy": sum(pnls) / len(pnls) if pnls else 0.0,
        "avg_win": sum(wins) / len(wins) if wins else None,
        "avg_loss": sum(losses) / len(losses) if losses else None,
        "profit_factor": (sum(wins) / abs(sum(losses)))
                         if wins and losses and sum(losses) != 0 else None,
        "expectancy_r": sum(rs) / len(rs) if rs else None,
        "r_count": len(rs),
    }
    return stats


def cmd_summary(args) -> int:
    trades = load_trades()
    closed = [t for t in trades if t["status"] == "closed" and t["pnl"]]
    if args.month:
        closed = [t for t in closed if t["closed_at"].startswith(args.month)]
        label = f"{args.month} の成績"
    else:
        label = "全期間の成績"

    open_count = sum(1 for t in trades if t["status"] == "open")
    print(f"## {label}\n")
    if not closed:
        print(f"決済済みトレードがありません。(保有中: {open_count}件)")
        return 0

    s = summary_stats(closed)
    print(f"- 決済数: {s['count']}件 (勝ち {s['wins']} / 負け {s['losses']})")
    print(f"- 勝率: {s['win_rate']:.1f}%")
    print(f"- 合計損益: {s['total']:+,.0f}円")
    print(f"- 期待値(1トレードあたり): {s['expectancy']:+,.0f}円")
    if s["expectancy_r"] is not None:
        print(f"- 期待値(R): {s['expectancy_r']:+.2f}R ({s['r_count']}件で損切り設定あり)")
    if s["avg_win"] is not None:
        print(f"- 平均利益: {s['avg_win']:+,.0f}円")
    if s["avg_loss"] is not None:
        print(f"- 平均損失: {s['avg_loss']:+,.0f}円")
    if s["profit_factor"] is not None:
        print(f"- プロフィットファクター: {s['profit_factor']:.2f}")
    print(f"- 保有中: {open_count}件")

    def breakdown(title: str, key: str, fmt=lambda v: v or "(未設定)"):
        groups: dict[str, list[dict]] = {}
        for t in closed:
            groups.setdefault(fmt(t.get(key, "")), []).append(t)
        if len(groups) <= 1 and "(未設定)" in groups:
            return
        print(f"\n### {title}")
        for g, ts in sorted(groups.items(), key=lambda x: -sum(float(t["pnl"]) for t in x[1])):
            gs = summary_stats(ts)
            r_str = f", {gs['expectancy_r']:+.2f}R" if gs["expectancy_r"] is not None else ""
            print(f"- {g}: {gs['total']:+,.0f}円 ({gs['count']}件, 勝率{gs['win_rate']:.0f}%{r_str})")

    breakdown("セクター別", "sector")
    breakdown("セットアップ別", "setup")
    breakdown("計画内/計画外", "plan",
              fmt=lambda v: {"on": "計画内", "off": "計画外"}.get(v, "(未設定)"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m market_flow.journal",
        description="トレード日誌: 1コマンドで売買を記録しExcel互換CSVに保存",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="新規トレードを記録")
    p_add.add_argument("code", help="銘柄コード (例: 8035)")
    p_add.add_argument("--side", choices=["buy", "sell"], required=True,
                       help="buy=買い(現物/ロング), sell=売り(空売り)")
    p_add.add_argument("--qty", type=float, required=True, help="数量(株)")
    p_add.add_argument("--price", type=float, required=True, help="建値(円)")
    p_add.add_argument("--stop", type=float, help="損切りライン(円)。R計算に必要")
    p_add.add_argument("--setup", help="セットアップ名 (例: セクター順張り)")
    p_add.add_argument("--grade", choices=["A", "B", "C", "a", "b", "c"],
                       help="トレードの質 (A/B/C)")
    p_add.add_argument("--plan", choices=["on", "off"],
                       help="on=事前計画どおり, off=計画外の衝動エントリー")
    p_add.add_argument("--name", help="銘柄名")
    p_add.add_argument("--sector", help="セクター (夜間レポートの分類に合わせる)")
    p_add.add_argument("--reason", help="エントリー理由 (振り返りで最重要)")
    p_add.add_argument("--date", help="日時を指定 (省略時は現在時刻)")
    p_add.set_defaults(func=cmd_add)

    p_close = sub.add_parser("close", help="保有中トレードを決済")
    p_close.add_argument("id", type=int, help="トレードID (`list` で確認)")
    p_close.add_argument("--price", type=float, required=True, help="決済価格(円)")
    p_close.add_argument("--date", help="決済日時を指定 (省略時は現在時刻)")
    p_close.set_defaults(func=cmd_close)

    p_list = sub.add_parser("list", help="記録の一覧表示")
    p_list.add_argument("--open", action="store_true", help="保有中のみ表示")
    p_list.add_argument("--limit", type=int, default=20, help="表示件数 (既定20)")
    p_list.set_defaults(func=cmd_list)

    p_sum = sub.add_parser("summary", help="成績サマリー (勝率/期待値/R/セットアップ別)")
    p_sum.add_argument("--month", help="対象月 (例: 2026-07)")
    p_sum.set_defaults(func=cmd_summary)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
