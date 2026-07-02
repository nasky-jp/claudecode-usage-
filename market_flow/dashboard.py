"""Dashboard generator: 最新レポート・予測精度・日誌を1枚のHTMLに統合。

生成物: reports/dashboard.html (毎回上書き。元データは変更しない)
morning_check の最後に自動生成されるほか、単体でも実行できる。

Usage:
    python3 -m market_flow.dashboard
"""

import html
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from market_flow.paths import reports_dir

JST = timezone(timedelta(hours=9))

CSS = """
body { font-family: 'Hiragino Sans', 'Noto Sans JP', sans-serif; max-width: 960px;
       margin: 0 auto; padding: 16px; background: #f6f7f9; color: #1a202c; }
h1 { font-size: 1.4rem; border-bottom: 3px solid #2b6cb0; padding-bottom: 8px; }
section { background: #fff; border-radius: 8px; padding: 16px 20px; margin: 16px 0;
          box-shadow: 0 1px 3px rgba(0,0,0,.08); overflow-x: auto; }
section h2 { font-size: 1.1rem; margin-top: 0; color: #2b6cb0; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { border: 1px solid #e2e8f0; padding: 6px 10px; text-align: left; }
th { background: #edf2f7; }
td.num { text-align: right; }
.up { color: #c53030; }   /* 日本式: 上昇=赤 */
.down { color: #2b6cb0; } /* 下落=青 */
.meta { color: #718096; font-size: .85rem; }
pre { white-space: pre-wrap; background: #f7fafc; padding: 12px; border-radius: 6px; }
blockquote { border-left: 4px solid #cbd5e0; margin: 8px 0; padding: 4px 12px;
             color: #4a5568; background: #f7fafc; }
"""


def md_to_html(md: str) -> str:
    """依存なしの簡易Markdown→HTML変換(見出し/表/リスト/引用/強調/罫線)。"""
    out = []
    lines = md.splitlines()
    i = 0
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    def inline(text: str) -> str:
        text = html.escape(text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
        # 騰落率に色付け(+2.31% / -0.45%)
        text = re.sub(r"([+＋]\d+(?:\.\d+)?%)", r'<span class="up">\1</span>', text)
        text = re.sub(r"(-\d+(?:\.\d+)?%)", r'<span class="down">\1</span>', text)
        return text

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("|") and stripped.endswith("|"):
            close_list()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            out.append("<table>")
            for j, tl in enumerate(table_lines):
                if re.fullmatch(r"\|[\s:\-|]+\|", tl):
                    continue
                cells = [c.strip() for c in tl.strip("|").split("|")]
                tag = "th" if j == 0 else "td"
                out.append("<tr>" + "".join(
                    f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>")
            out.append("</table>")
            continue

        if stripped.startswith("###"):
            close_list()
            out.append(f"<h3>{inline(stripped.lstrip('#').strip())}</h3>")
        elif stripped.startswith("##"):
            close_list()
            out.append(f"<h3>{inline(stripped.lstrip('#').strip())}</h3>")
        elif stripped.startswith("#"):
            close_list()
            out.append(f"<h3>{inline(stripped.lstrip('#').strip())}</h3>")
        elif stripped.startswith(">"):
            close_list()
            out.append(f"<blockquote>{inline(stripped.lstrip('>').strip())}</blockquote>")
        elif stripped.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(stripped[2:])}</li>")
        elif re.fullmatch(r"-{3,}", stripped):
            close_list()
            out.append("<hr>")
        elif stripped == "":
            close_list()
        else:
            close_list()
            out.append(f"<p>{inline(stripped)}</p>")
        i += 1

    close_list()
    return "\n".join(out)


def _latest(pattern: str) -> Path | None:
    paths = sorted(reports_dir().glob(pattern), reverse=True)
    return paths[0] if paths else None


def _section(title: str, body_html: str, meta: str = "") -> str:
    meta_html = f'<p class="meta">{html.escape(meta)}</p>' if meta else ""
    return f"<section><h2>{html.escape(title)}</h2>{meta_html}{body_html}</section>"


def _journal_html() -> str:
    from market_flow.journal import load_trades
    trades = load_trades()
    if not trades:
        return "<p>記録なし。<code>python3 -m market_flow.journal add</code> で記録を開始。</p>"
    open_trades = [t for t in trades if t["status"] == "open"]
    closed = [t for t in trades if t["status"] == "closed" and t["pnl"]]
    parts = []
    if open_trades:
        rows = "".join(
            f"<tr><td>{html.escape(t['code'])}</td><td>{html.escape(t['name'])}</td>"
            f"<td>{'買' if t['side'] == 'buy' else '売'}</td>"
            f"<td class='num'>{html.escape(t['qty'])}</td>"
            f"<td class='num'>{html.escape(t['entry_price'])}</td>"
            f"<td>{html.escape(t['reason'])}</td></tr>"
            for t in open_trades)
        parts.append("<h3>保有中</h3><table><tr><th>コード</th><th>銘柄</th><th>売買</th>"
                     "<th>数量</th><th>建値</th><th>理由</th></tr>" + rows + "</table>")
    if closed:
        pnls = [float(t["pnl"]) for t in closed]
        total = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        cls = "up" if total >= 0 else "down"
        parts.append(
            f"<p>決済済み {len(closed)}件 / 勝率 {wins / len(closed) * 100:.0f}% / "
            f"合計損益 <strong class='{cls}'>{total:+,.0f}円</strong></p>")
    return "".join(parts) or "<p>保有中・決済済みの記録はありません。</p>"


def build_sections() -> list[str]:
    """ダッシュボードの各セクションHTMLを返す(Webアプリと静的生成の共通実装)。"""
    sections = []

    morning = _latest("*_morning_check.md")
    if morning:
        sections.append(_section("☀️ 朝の確認サマリー(最新)",
                                 md_to_html(morning.read_text(encoding="utf-8")),
                                 meta=morning.name))
    night = _latest("*_night_report.md")
    if night:
        sections.append(_section("🌙 夜間分析レポート(最新)",
                                 md_to_html(night.read_text(encoding="utf-8")),
                                 meta=night.name))
    if not morning and not night:
        sections.append(_section("レポート未生成",
                                 "<p>まず <code>python3 -m market_flow.analyze_night</code> "
                                 "を実行してください。</p>"))

    try:
        from market_flow.scorecard import summarize
        sections.append(_section("🎯 予測スコアカード", md_to_html(summarize())))
    except Exception as e:
        sections.append(_section("🎯 予測スコアカード", f"<p>集計エラー: {html.escape(str(e))}</p>"))

    sections.append(_section("📒 トレード日誌", _journal_html()))
    return sections


def render_page(extra_html: str = "", subtitle: str = "") -> str:
    """完全なHTMLページを組み立てる。extra_html は先頭(タイトル直下)に挿入される。"""
    now = datetime.now(JST)
    sections = build_sections()
    sub = subtitle or "このページは自動生成。元データ: reports/ 内の各ファイル"
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Market Flow ダッシュボード</title>
<style>{CSS}</style>
</head>
<body>
<h1>📈 Market Flow ダッシュボード</h1>
<p class="meta">生成: {now.strftime('%Y-%m-%d %H:%M JST')} — {html.escape(sub)}</p>
{extra_html}
{''.join(sections)}
</body>
</html>
"""


def generate_dashboard() -> Path:
    out = reports_dir() / "dashboard.html"
    out.write_text(render_page(), encoding="utf-8")
    return out


if __name__ == "__main__":
    path = generate_dashboard()
    print(f"✅ ダッシュボード生成: {path}")
    print("   ブラウザで開く: open " + str(path))
