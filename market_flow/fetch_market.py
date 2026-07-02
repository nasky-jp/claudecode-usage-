"""Market data fetcher: NASDAQ, USD/JPY, Nikkei Futures, GOLD"""

import time

import yfinance as yf
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

SYMBOLS = {
    "NASDAQ":        ("^IXIC",   "NASDAQ総合指数"),
    "USDJPY":        ("USDJPY=X", "ドル円"),
    "NIKKEI_FUTURES":("^N225",   "日経225(現物参考)"),
    "NIKKEI_FUT_CME":("NKD=F",   "日経225先物(CME)"),
    "GOLD":          ("GC=F",    "GOLD先物"),
    "SP500":         ("^GSPC",   "S&P500"),
    "DOW":           ("^DJI",    "NYダウ"),
}

SECTOR_ETFS = {
    "半導体":       "SOXX",
    "AI/テクノロジー": "QQQ",
    "エネルギー":   "XLE",
    "金融":         "XLF",
    "ヘルスケア":   "XLV",
    "不動産(REIT)": "IYR",
    "公共事業":     "XLU",
    "素材":         "XLB",
    "生活必需品":   "XLP",
    "一般消費財":   "XLY",
    "通信":         "XLC",
    "資本財":       "XLI",
}


def fetch_ticker(symbol: str, period: str = "5d", retries: int = 2) -> dict:
    last_error = None
    for attempt in range(retries + 1):
        try:
            t = yf.Ticker(symbol)
            hist = t.fast_info
            info = {
                "last_price": getattr(hist, "last_price", None),
                "previous_close": getattr(hist, "previous_close", None),
            }
            # fallback via history
            if info["last_price"] is None:
                df = t.history(period=period, interval="1d")
                if not df.empty:
                    info["last_price"] = float(df["Close"].iloc[-1])
                    info["previous_close"] = float(df["Close"].iloc[-2]) if len(df) >= 2 else None
            if info["last_price"] is not None:
                return info
            last_error = "no data returned"
        except Exception as e:
            last_error = str(e)
        if attempt < retries:
            time.sleep(2 ** attempt)  # 1s, 2s
    return {"last_price": None, "previous_close": None, "error": last_error}


def fetch_daily_history(symbol: str, period: str = "1mo", retries: int = 2) -> list[dict]:
    """日足履歴を [{date, open, close, volume}, ...] で返す(古い順)。

    スコアカード/スクリーナー用。失敗時は空リスト。
    """
    last_error = None
    for attempt in range(retries + 1):
        try:
            df = yf.Ticker(symbol).history(period=period, interval="1d")
            if not df.empty:
                return [
                    {
                        "date": idx.strftime("%Y-%m-%d"),
                        "open": float(row["Open"]),
                        "close": float(row["Close"]),
                        "volume": float(row.get("Volume", 0) or 0),
                    }
                    for idx, row in df.iterrows()
                ]
            last_error = "empty history"
        except Exception as e:
            last_error = str(e)
        if attempt < retries:
            time.sleep(2 ** attempt)
    return []


def calc_change(current, prev) -> tuple[float | None, str]:
    if current is None or prev is None or prev == 0:
        return None, "N/A"
    change_pct = (current - prev) / prev * 100
    sign = "+" if change_pct >= 0 else ""
    return change_pct, f"{sign}{change_pct:.2f}%"


def fetch_all() -> dict:
    now = datetime.now(JST)
    result = {
        "fetched_at": now.strftime("%Y-%m-%d %H:%M JST"),
        "markets": {},
        "sectors": {},
    }

    for name, (symbol, label) in SYMBOLS.items():
        data = fetch_ticker(symbol)
        pct, pct_str = calc_change(data["last_price"], data["previous_close"])
        result["markets"][name] = {
            "label": label,
            "symbol": symbol,
            "price": data["last_price"],
            "change_pct": pct,
            "change_str": pct_str,
        }

    for sector, symbol in SECTOR_ETFS.items():
        data = fetch_ticker(symbol)
        pct, pct_str = calc_change(data["last_price"], data["previous_close"])
        result["sectors"][sector] = {
            "symbol": symbol,
            "price": data["last_price"],
            "change_pct": pct,
            "change_str": pct_str,
        }

    return result


def format_market_summary(data: dict) -> str:
    lines = [f"## 市場データ ({data['fetched_at']})\n"]

    lines.append("### 主要指数・為替")
    for name, m in data["markets"].items():
        price_str = f"{m['price']:,.2f}" if m["price"] else "取得失敗"
        lines.append(f"- **{m['label']}** ({m['symbol']}): {price_str}  {m['change_str']}")

    lines.append("\n### セクターETF")
    sectors_sorted = sorted(
        data["sectors"].items(),
        key=lambda x: x[1]["change_pct"] if x[1]["change_pct"] is not None else -999,
        reverse=True,
    )
    for sector, s in sectors_sorted:
        price_str = f"{s['price']:.2f}" if s["price"] else "取得失敗"
        lines.append(f"- **{sector}** ({s['symbol']}): {price_str}  {s['change_str']}")

    return "\n".join(lines)


if __name__ == "__main__":
    data = fetch_all()
    print(format_market_summary(data))
