"""Trade journal CLI: record trades in one command, Excel-compatible CSV.

Usage:
    python3 -m market_flow.journal add 8035 --side buy --qty 100 --price 25000 \
        --name 東京エレクトロン --sector 半導体 --reason "夜間レポートTOP1セクター"
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
    "qty", "entry_price", "exit_price", "pnl", "pnl_pct", "sector", "reason",
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
        return list(csv.DictReader(f))


def save_trades(trades: list[dict]) -> None:
    path = csv_path()
    tmp = path.with_suffix(".csv.tmp")
    # utf-8-sig so the CSV opens correctly in Excel
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(trades)
    tmp.replace(path)


def next_id(trades: list[dict]) -> int:
    ids = [int(t["id"]) for t in trades if str(t.get("id", "")).isdigit()]
    return max(ids, default=0) + 1


def cmd_add(args) -> int:
    trades = load_trades()
    now = datetime.now(JST)
    trade = {
        "id": str(next_id(trades)),
        "status": "open",
        "opened_at": args.date or now.strftime("%Y-%m-%d %H:%M"),
        "closed_at": "",
        "code": args.code,
        "name": args.name or "",
        "side": args.side,
        "qty": str(args.qty),
        "entry_price": f"{args.price:g}",
        "exit_price": "",
        "pnl": "",
        "pnl_pct": "",
        "sector": args.sector or "",
        "reason": args.reason or "",
    }
    trades.append(trade)
    save_trades(trades)
    label = "買い" if args.side == "buy" else "売り"
    print(f"✅ 記録 #{trade['id']}: {args.code} {trade['name']} {label} "
          f"{args.qty}株 @ {args.price:g}円")
    print(f"   保存先: {csv_path()}")
    return 0


def cmd_close(args) -> int:
    trades = load_trades()
    target = next((t for t in trades if t["id"] == str(args.id)), None)
    if target is None:
        print(f"❌ ID {args.id} の記録が見つかりません。`list` で確認してください。")
        return 1
    if target["status"] == "closed":
        print(f"❌ #{args.id} は決済済みです ({target['closed_at']})。")
        return 1

    now = datetime.now(JST)
    entry = float(target["entry_price"])
    qty = float(target["qty"])
    exit_price = args.price
    if target["side"] == "buy":
        pnl = (exit_price - entry) * qty
    else:
        pnl = (entry - exit_price) * qty
    pnl_pct = (pnl / (entry * qty)) * 100 if entry else 0.0

    target["status"] = "closed"
    target["closed_at"] = args.date or now.strftime("%Y-%m-%d %H:%M")
    target["exit_price"] = f"{exit_price:g}"
    target["pnl"] = f"{pnl:.0f}"
    target["pnl_pct"] = f"{pnl_pct:.2f}"
    save_trades(trades)

    mark = "🟢" if pnl >= 0 else "🔴"
    print(f"{mark} 決済 #{args.id}: {target['code']} {target['name']} "
          f"@ {exit_price:g}円  損益 {pnl:+,.0f}円 ({pnl_pct:+.2f}%)")
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
          f"{'売買':<4} {'数量':>6} {'建値':>9} {'決済':>9} {'損益':>10}  理由")
    for t in trades:
        side = "買" if t["side"] == "buy" else "売"
        status = "保有中" if t["status"] == "open" else "決済済"
        pnl = f"{float(t['pnl']):+,.0f}" if t["pnl"] else "-"
        exit_p = t["exit_price"] or "-"
        print(f"{t['id']:>3} {status:<5} {t['opened_at']:<16} {t['code']:<6} "
              f"{t['name'][:12]:<12} {side:<3} {t['qty']:>6} {t['entry_price']:>9} "
              f"{exit_p:>9} {pnl:>10}  {t['reason'][:30]}")
    return 0


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

    pnls = [float(t["pnl"]) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total = sum(pnls)
    win_rate = len(wins) / len(pnls) * 100

    print(f"- 決済数: {len(pnls)}件 (勝ち {len(wins)} / 負け {len(losses)})")
    print(f"- 勝率: {win_rate:.1f}%")
    print(f"- 合計損益: {total:+,.0f}円")
    if wins:
        print(f"- 平均利益: {sum(wins)/len(wins):+,.0f}円")
    if losses:
        print(f"- 平均損失: {sum(losses)/len(losses):+,.0f}円")
    if wins and losses:
        pf = sum(wins) / abs(sum(losses)) if sum(losses) != 0 else float("inf")
        print(f"- プロフィットファクター: {pf:.2f}")
    print(f"- 保有中: {open_count}件")

    by_sector: dict[str, list[float]] = {}
    for t in closed:
        sector = t["sector"] or "(未分類)"
        by_sector.setdefault(sector, []).append(float(t["pnl"]))
    if len(by_sector) > 1 or "(未分類)" not in by_sector:
        print("\n### セクター別損益")
        for sector, pnl_list in sorted(by_sector.items(), key=lambda x: -sum(x[1])):
            print(f"- {sector}: {sum(pnl_list):+,.0f}円 ({len(pnl_list)}件)")
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

    p_sum = sub.add_parser("summary", help="成績サマリー (勝率/損益/セクター別)")
    p_sum.add_argument("--month", help="対象月 (例: 2026-07)")
    p_sum.set_defaults(func=cmd_summary)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
