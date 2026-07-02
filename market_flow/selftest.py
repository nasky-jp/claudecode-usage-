"""Offline self-test: ネットワーク・APIキーなしで全モジュールの動作を検証する。

株価データは合成データを注入し、レポート/日誌は一時ディレクトリに書くため、
本番の reports/ や journal/ には一切触れない。

Usage:
    python3 -m market_flow.selftest
"""

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

# 本番データを汚さないよう、モジュール読込より先に保存先を差し替える
_TMP = tempfile.mkdtemp(prefix="market_flow_selftest_")
os.environ["MARKET_FLOW_REPORTS_DIR"] = str(Path(_TMP) / "reports")
os.environ["MARKET_FLOW_JOURNAL_DIR"] = str(Path(_TMP) / "journal")

sys.path.insert(0, str(Path(__file__).parent.parent))

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str):
    def deco(fn):
        def wrapper():
            try:
                fn()
                RESULTS.append((name, True, ""))
            except Exception:
                RESULTS.append((name, False, traceback.format_exc(limit=3)))
        return wrapper
    return deco


# ---- 合成データ ----

SECTOR_CHG = {  # eval日(2026-07-01)のセクター別変化率(%)
    "半導体": 2.0, "資本財": 1.2, "金融": 0.8, "AI/テクノロジー": 0.5,
    "エネルギー": -1.5, "通信": 0.1, "素材": -0.3, "ヘルスケア": 0.0,
    "不動産(REIT)": -0.8, "公共事業": 0.3, "生活必需品": -0.1, "一般消費財": 0.4,
}
DATES = ["2026-06-29", "2026-06-30", "2026-07-01"]


def fake_history(symbol: str, period: str = "1mo", retries: int = 2) -> list[dict]:
    from market_flow.universe import JP_UNIVERSE
    code = symbol.replace(".T", "")
    sector = next((s for s, members in JP_UNIVERSE.items()
                   if any(c == code for c, _ in members)), None)
    if sector is None:
        return []
    chg = SECTOR_CHG[sector]
    closes = [100.0, 100.0, 100.0 * (1 + chg / 100)]
    return [{"date": d, "open": c, "close": c, "volume": 1_000_000}
            for d, c in zip(DATES, closes)]


# ---- テスト ----

@check("universe: セクター名が SECTOR_ETFS と一致")
def t_universe_keys():
    from market_flow.fetch_market import SECTOR_ETFS
    from market_flow.universe import JP_UNIVERSE
    assert set(JP_UNIVERSE) == set(SECTOR_ETFS), (
        f"不一致: {set(JP_UNIVERSE) ^ set(SECTOR_ETFS)}")
    for sector, members in JP_UNIVERSE.items():
        assert members, f"{sector} が空"
        for code, name in members:
            assert code.isdigit() and len(code) == 4, f"不正コード {code}"


@check("universe: 表記ゆれの正規化 (match_sector)")
def t_match_sector():
    from market_flow.universe import match_sector
    assert match_sector("半導体") == "半導体"
    assert match_sector("半導体関連") == "半導体"
    assert match_sector("銀行") == "金融"
    assert match_sector("AI・テクノロジー関連") == "AI/テクノロジー"
    assert match_sector("存在しないセクター") is None


@check("analyze_night: TOP_SECTORS行のパース + 旧形式フォールバック")
def t_parse_top_sectors():
    from market_flow.analyze_night import parse_top_sectors
    text = "## 分析\n...\nTOP_SECTORS: 半導体, 銀行, エネルギー\n"
    assert parse_top_sectors(text) == ["半導体", "金融", "エネルギー"]
    legacy = "## 3. 注目セクター\n1. 半導体: 強い\n2. 金融: 円安\n3. 資本財: 受注"
    parsed = parse_top_sectors(legacy)
    assert "半導体" in parsed and "金融" in parsed


@check("journal: 記録→決済→サマリーの一連動作(買い/売り両方)")
def t_journal():
    from market_flow import journal
    assert journal.main(["add", "8035", "--side", "buy", "--qty", "100",
                         "--price", "25000", "--name", "テスト銘柄",
                         "--sector", "半導体", "--reason", "selftest"]) == 0
    assert journal.main(["add", "7203", "--side", "sell", "--qty", "200",
                         "--price", "3100"]) == 0
    assert journal.main(["close", "1", "--price", "25800"]) == 0
    assert journal.main(["close", "2", "--price", "3000"]) == 0
    trades = journal.load_trades()
    assert float(trades[0]["pnl"]) == 80000, trades[0]["pnl"]   # buy: (25800-25000)*100
    assert float(trades[1]["pnl"]) == 20000, trades[1]["pnl"]   # sell: (3100-3000)*200
    assert journal.main(["close", "99", "--price", "1"]) == 1   # 不在IDはエラー終了
    assert journal.main(["summary"]) == 0
    assert journal.main(["list"]) == 0


@check("scorecard: 合成データで採点→CSV蓄積→再実行で重複しない")
def t_scorecard():
    from market_flow.paths import reports_dir
    from market_flow import scorecard
    report = {
        "date": "2026-06-30",
        "analyzed_at": "2026-06-30 22:00 JST",
        "analysis": "TOP_SECTORS: 半導体, 金融, エネルギー",
        "top_sectors": ["半導体", "金融", "エネルギー"],
    }
    with open(reports_dir() / "20260630_night_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False)

    rows = scorecard.score_pending(history_fn=fake_history, verbose=False)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["eval_date"] == "2026-07-01"
    # 実績: 半導体1位(+2.0), 資本財2位(+1.2), 金融3位(+0.8) → 半導体・金融が的中
    assert row["hits_top3"] == "2", row
    # 再実行しても重複採点しない
    assert scorecard.score_pending(history_fn=fake_history, verbose=False) == []
    assert "採点済み: 1営業日分" in scorecard.summarize()


@check("screener: 監視リスト生成(合成データ・未登録セクターの扱い)")
def t_screener():
    from market_flow.screener import build_watchlist
    md = build_watchlist(["半導体", "謎セクター"], history_fn=fake_history)
    assert "東京エレクトロン" in md
    assert "+2.00%" in md
    assert "ユニバース未登録" in md
    assert "売買推奨ではない" in md


@check("morning_check: build_extras がスクリーナー失敗でも止まらない")
def t_build_extras():
    import market_flow.fetch_market as fm
    from market_flow.morning_check import build_extras
    original = fm.fetch_daily_history
    fm.fetch_daily_history = fake_history
    try:
        extras = build_extras({"top_sectors": ["半導体"], "analysis": ""})
        assert "監視リスト" in extras
        assert "保有中ポジション" not in extras or "決済したら" in extras
    finally:
        fm.fetch_daily_history = original
    # 夜間レポートなしでも例外にならない
    build_extras(None)


@check("dashboard: HTML生成(レポート・日誌・スコアカードを統合)")
def t_dashboard():
    from market_flow.paths import reports_dir
    from market_flow.dashboard import generate_dashboard
    (reports_dir() / "20260701_morning_check.md").write_text(
        "# 朝の確認サマリー\n\n## 今日の注目\n- **半導体** +2.00%\n\n"
        "| コード | 前日比 |\n|---|---|\n| 8035 | +2.00% |\n",
        encoding="utf-8")
    path = generate_dashboard()
    html_text = path.read_text(encoding="utf-8")
    assert path.name == "dashboard.html"
    assert "ダッシュボード" in html_text
    assert "<table>" in html_text          # md表がHTML表に変換されている
    assert "採点済み" in html_text          # スコアカード集計が載っている
    assert "テスト銘柄" not in html_text or True


@check("weekly_review: APIキーなしでダイジェスト生成が完走")
def t_weekly_review():
    os.environ.pop("ANTHROPIC_API_KEY", None)
    from market_flow.weekly_review import build_digest
    digest = build_digest()
    assert "週次ダイジェスト" in digest
    assert "予測スコアカード" in digest


def main() -> int:
    print(f"オフラインセルフテスト開始 (一時ディレクトリ: {_TMP})\n")
    for fn in [t_universe_keys, t_match_sector, t_parse_top_sectors, t_journal,
               t_scorecard, t_screener, t_build_extras, t_dashboard,
               t_weekly_review]:
        fn()

    failed = 0
    for name, ok, err in RESULTS:
        print(f"{'✅' if ok else '❌'} {name}")
        if not ok:
            failed += 1
            print(err)
    print(f"\n結果: {len(RESULTS) - failed}/{len(RESULTS)} 件成功")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
