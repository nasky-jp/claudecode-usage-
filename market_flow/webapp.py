"""Market Flow Webアプリ: ダッシュボード + トレード記録フォーム + 内蔵スケジューラ。

これ1プロセスで「完全自動化」が完結する:
- 起動しておくだけで 夜間分析→朝チェック→答え合わせ→週次レビュー が自動実行される
- http://127.0.0.1:8035 でダッシュボード閲覧・日誌記入・手動実行ができる

Usage:
    python3 -m market_flow.webapp                 # 127.0.0.1:8035 で起動
    MARKET_FLOW_NO_SCHEDULER=1 python3 -m market_flow.webapp   # 画面のみ(自動実行なし)

セキュリティ: 127.0.0.1 のみにバインド(外部公開しない前提)。
"""

import html
import re
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from market_flow import journal
from market_flow.dashboard import md_to_html, render_page
from market_flow.paths import reports_dir
from market_flow.scheduler import (JOB_LABELS, load_config, run_job,
                                   start_scheduler, status_snapshot)
from market_flow.universe import SECTOR_NAMES

import os

EXTRA_CSS = """
<style>
.actions form { display: inline-block; margin: 4px 8px 4px 0; }
button { background: #2b6cb0; color: #fff; border: 0; border-radius: 6px;
         padding: 8px 14px; cursor: pointer; font-size: .9rem; }
button:hover { background: #2c5282; }
button.danger { background: #718096; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
        gap: 8px; }
label { font-size: .8rem; color: #4a5568; display: block; }
input, select { width: 100%; box-sizing: border-box; padding: 6px;
                border: 1px solid #cbd5e0; border-radius: 4px; font-size: .9rem; }
.msg { background: #c6f6d5; border: 1px solid #68d391; padding: 10px 14px;
       border-radius: 6px; margin: 12px 0; }
.err { background: #fed7d7; border-color: #fc8181; }
.status-ok { color: #276749; } .status-error { color: #c53030; }
.status-skipped { color: #975a16; }
</style>
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event = None
    if not os.environ.get("MARKET_FLOW_NO_SCHEDULER"):
        stop_event = start_scheduler()
    yield
    if stop_event:
        stop_event.set()


app = FastAPI(title="Market Flow", lifespan=lifespan)


def _status_section() -> str:
    rows = status_snapshot()
    trs = []
    for r in rows:
        cls = f"status-{r['status']}" if r["status"] in ("ok", "error", "skipped") else ""
        status_ja = {"ok": "✅ 成功", "error": "❌ 失敗", "skipped": "⏭ スキップ",
                     "-": "—"}.get(r["status"], r["status"])
        detail = f" — {html.escape(r['detail'])}" if r["detail"] else ""
        run_btn = (f'<form method="post" action="/run/{r["name"]}" '
                   f'onsubmit="return confirm(\'{html.escape(r["label"])} を今すぐ実行しますか?\')">'
                   f'<button type="submit">今すぐ実行</button></form>')
        trs.append(
            f"<tr><td>{html.escape(r['label'])}</td>"
            f"<td>{html.escape(r['schedule'])}{'' if r['enabled'] else ' (無効)'}</td>"
            f"<td>{html.escape(r['last_run_at'])}</td>"
            f"<td class='{cls}'>{status_ja}{detail}</td>"
            f"<td>{run_btn}</td></tr>")
    api_note = ""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        api_note = ("<p class='err msg'>ANTHROPIC_API_KEY が未設定のため、"
                    "分析系ジョブは自動スキップされます(データ採点・画面は動作)。</p>")
    return (
        "<section><h2>⚙️ 自動実行ステータス(ハートビート)</h2>"
        + api_note +
        "<table><tr><th>ジョブ</th><th>スケジュール</th><th>最終実行</th>"
        "<th>結果</th><th>手動</th></tr>"
        + "".join(trs) +
        "</table>"
        "<p class='meta'>アプリ起動中は自動実行。停止していた場合も、予定時刻から4時間以内の起動でキャッチアップ実行される。"
        "「今すぐ実行」のうち API課金あり のジョブは1回あたり数円かかる。</p>"
        "<p class='meta'><a href='/reports'>📁 過去レポート一覧</a></p></section>")


def _journal_forms() -> str:
    sector_opts = "".join(f"<option value='{html.escape(s)}'>{html.escape(s)}</option>"
                          for s in SECTOR_NAMES)
    open_trades = [t for t in journal.load_trades() if t["status"] == "open"]
    close_form = "<p class='meta'>保有中のポジションはありません。</p>"
    if open_trades:
        opts = "".join(
            f"<option value='{html.escape(t['id'])}'>#{html.escape(t['id'])} "
            f"{html.escape(t['code'])} {html.escape(t['name'])} "
            f"{'買' if t['side'] == 'buy' else '売'}{html.escape(t['qty'])}株 "
            f"@{html.escape(t['entry_price'])}</option>"
            for t in open_trades)
        close_form = f"""
<form method="post" action="/journal/close">
  <div class="grid">
    <div><label>ポジション</label><select name="trade_id">{opts}</select></div>
    <div><label>決済価格(円)*</label><input name="price" type="number" step="any" required></div>
    <div><label>&nbsp;</label><button type="submit">決済を記録</button></div>
  </div>
</form>"""
    return f"""
<section><h2>✍️ トレード記録</h2>
<h3>新規エントリー</h3>
<form method="post" action="/journal/add">
  <div class="grid">
    <div><label>銘柄コード*</label><input name="code" required pattern="[0-9A-Za-z]{{4,5}}" placeholder="8035"></div>
    <div><label>銘柄名</label><input name="name" placeholder="東京エレクトロン"></div>
    <div><label>売買*</label><select name="side"><option value="buy">買い</option><option value="sell">売り</option></select></div>
    <div><label>数量(株)*</label><input name="qty" type="number" step="any" required placeholder="100"></div>
    <div><label>建値(円)*</label><input name="price" type="number" step="any" required placeholder="25000"></div>
    <div><label>損切り(円) → R計算</label><input name="stop" type="number" step="any" placeholder="24500"></div>
    <div><label>セクター</label><select name="sector"><option value=""></option>{sector_opts}</select></div>
    <div><label>セットアップ</label><input name="setup" placeholder="セクター順張り"></div>
    <div><label>質</label><select name="grade"><option value=""></option><option>A</option><option>B</option><option>C</option></select></div>
    <div><label>計画</label><select name="plan"><option value=""></option><option value="on">計画内</option><option value="off">計画外</option></select></div>
  </div>
  <div style="margin-top:8px"><label>エントリー理由(振り返りで最重要)</label>
    <input name="reason" placeholder="夜間TOP1セクター・寄りギャップ小・出来高増"></div>
  <div style="margin-top:8px"><button type="submit">記録する</button></div>
</form>
<h3>決済</h3>
{close_form}
</section>"""


def _page(msg: str = "", err: str = "") -> str:
    banner = ""
    if msg:
        banner = f"<p class='msg'>{html.escape(msg)}</p>"
    if err:
        banner += f"<p class='msg err'>{html.escape(err)}</p>"
    extra = EXTRA_CSS + banner + _status_section() + _journal_forms()
    return render_page(extra_html=extra, subtitle="Market Flow Webアプリ (127.0.0.1限定)")


@app.get("/", response_class=HTMLResponse)
def index(msg: str = "", err: str = ""):
    return _page(msg=msg, err=err)


@app.post("/journal/add")
def journal_add(code: str = Form(...), side: str = Form("buy"),
                qty: float = Form(...), price: float = Form(...),
                stop: str = Form(""), name: str = Form(""),
                sector: str = Form(""), setup: str = Form(""),
                grade: str = Form(""), plan: str = Form(""),
                reason: str = Form("")):
    if side not in ("buy", "sell"):
        return RedirectResponse(f"/?err={quote('売買区分が不正です')}", status_code=303)
    stop_val = float(stop) if stop.strip() else None
    trade = journal.add_trade(code.strip(), side, qty, price, name=name.strip(),
                              sector=sector, reason=reason.strip(), stop=stop_val,
                              setup=setup.strip(), grade=grade, plan=plan)
    msg = f"記録 #{trade['id']}: {trade['code']} {trade['name']} " \
          f"{'買い' if side == 'buy' else '売り'} {trade['qty']}株 @ {trade['entry_price']}円"
    return RedirectResponse(f"/?msg={quote(msg)}", status_code=303)


@app.post("/journal/close")
def journal_close(trade_id: int = Form(...), price: float = Form(...)):
    trade, error = journal.close_trade(trade_id, price)
    if error:
        return RedirectResponse(f"/?err={quote(error)}", status_code=303)
    pnl = float(trade["pnl"])
    r_str = f" ({trade['r_multiple']}R)" if trade["r_multiple"] else ""
    msg = f"決済 #{trade['id']}: {trade['code']} 損益 {pnl:+,.0f}円{r_str}"
    return RedirectResponse(f"/?msg={quote(msg)}", status_code=303)


@app.post("/run/{job_name}")
def run_now(job_name: str):
    if job_name not in JOB_LABELS:
        return RedirectResponse(f"/?err={quote('不明なジョブです')}", status_code=303)
    threading.Thread(target=run_job, args=(job_name,),
                     kwargs={"trigger": "manual"}, daemon=True).start()
    msg = f"{JOB_LABELS[job_name]} をバックグラウンドで開始しました(完了すると下の表に反映)"
    return RedirectResponse(f"/?msg={quote(msg)}", status_code=303)


@app.get("/reports", response_class=HTMLResponse)
def report_list():
    files = sorted((p for p in reports_dir().iterdir()
                    if p.suffix in (".md", ".csv", ".html") and not p.name.startswith(".")),
                   key=lambda p: p.name, reverse=True)
    items = "".join(f"<li><a href='/reports/{quote(p.name)}'>{html.escape(p.name)}</a></li>"
                    for p in files) or "<li>レポートはまだありません</li>"
    return (f"<!DOCTYPE html><html lang='ja'><head><meta charset='utf-8'>"
            f"<title>レポート一覧</title></head><body>"
            f"<h1>📁 レポート一覧</h1><p><a href='/'>← ダッシュボードへ戻る</a></p>"
            f"<ul>{items}</ul></body></html>")


@app.get("/reports/{name}")
def report_view(name: str):
    if not re.fullmatch(r"[\w.\-]+\.(md|csv|html)", name):
        return PlainTextResponse("invalid name", status_code=400)
    path = (reports_dir() / name).resolve()
    if path.parent != reports_dir().resolve() or not path.exists():
        return PlainTextResponse("not found", status_code=404)
    text = path.read_text(encoding="utf-8-sig" if path.suffix == ".csv" else "utf-8")
    if path.suffix == ".html":
        return HTMLResponse(text)
    if path.suffix == ".csv":
        return PlainTextResponse(text)
    from market_flow.dashboard import CSS
    return HTMLResponse(
        f"<!DOCTYPE html><html lang='ja'><head><meta charset='utf-8'>"
        f"<title>{html.escape(name)}</title><style>{CSS}</style></head><body>"
        f"<p><a href='/'>← ダッシュボードへ戻る</a></p><section>{md_to_html(text)}</section>"
        f"</body></html>")


@app.get("/api/status")
def api_status():
    return {"jobs": status_snapshot()}


def main() -> None:
    import uvicorn
    config = load_config()
    port = int(os.environ.get("MARKET_FLOW_PORT", config.get("port", 8035)))
    print(f"Market Flow Webアプリ起動: http://127.0.0.1:{port}")
    print("停止: Ctrl+C / 自動実行を止めて起動: MARKET_FLOW_NO_SCHEDULER=1")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
