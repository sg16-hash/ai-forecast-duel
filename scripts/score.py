"""收盘后运行：拉取实际收盘价，给每条预测打分，重新生成 data/results.csv。

实际涨跌幅 = 当天收盘价 / 上一交易日收盘价 - 1（使用复权价，拆股分红不影响）。
只给已经收盘的交易日打分，每次运行都从 predictions.csv 全量重算，结果可复现。
"""
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
PRED_CSV = ROOT / "data" / "predictions.csv"
RESULTS_CSV = ROOT / "data" / "results.csv"
PRICES_CSV = ROOT / "data" / "prices.csv"
ET = ZoneInfo("America/New_York")


def last_closed_date() -> dt.date:
    now = dt.datetime.now(ET)
    # 收盘后留 30 分钟让行情数据落定
    if now.time() >= dt.time(16, 30):
        return now.date()
    return now.date() - dt.timedelta(days=1)


def fetch_returns(tickers, start: dt.date, end: dt.date) -> pd.DataFrame:
    """返回长表：date, ticker, actual_pct, close"""
    raw = yf.download(
        tickers=list(tickers),
        start=(start - dt.timedelta(days=10)).isoformat(),
        end=(end + dt.timedelta(days=1)).isoformat(),
        auto_adjust=True, progress=False, group_by="column",
    )
    close = raw["Close"]
    if isinstance(close, pd.Series):  # 只有一个标的时
        close = close.to_frame(name=list(tickers)[0])
    pct = close.pct_change() * 100
    out = []
    for t in close.columns:
        df = pd.DataFrame({"close": close[t], "actual_pct": pct[t]}).dropna()
        df["ticker"] = t
        df["date"] = [d.date().isoformat() for d in df.index]
        out.append(df.reset_index(drop=True))
    return pd.concat(out, ignore_index=True)


def main() -> int:
    if not PRED_CSV.exists():
        print("还没有任何预测，跳过")
        return 0
    pred = pd.read_csv(PRED_CSV, dtype={"date": str})
    cutoff = last_closed_date()
    pred = pred[pd.to_datetime(pred["date"]).dt.date <= cutoff]
    if pred.empty:
        print("没有可以打分的预测（当天还未收盘）")
        return 0

    start = pd.to_datetime(pred["date"]).min().date()
    rets = fetch_returns(sorted(pred["ticker"].unique()), start, cutoff)
    rets[["date", "ticker", "close", "actual_pct"]].round(4).to_csv(PRICES_CSV, index=False)

    df = pred.merge(rets, on=["date", "ticker"], how="left")
    missing = df[df["actual_pct"].isna()]
    if not missing.empty:
        print(f"注意：{len(missing)} 条预测暂时拿不到收盘价，本次不打分：")
        print(missing[["date", "model", "ticker"]].to_string(index=False))
    df = df.dropna(subset=["actual_pct"]).copy()

    df["actual_up"] = (df["actual_pct"] > 0).astype(int)
    df["hit"] = ((df["direction"] == "up").astype(int) == df["actual_up"]).astype(int)
    df["brier"] = (df["p_up"] - df["actual_up"]) ** 2
    df["abs_err"] = (df["pct_change"] - df["actual_pct"]).abs()
    df["actual_pct"] = df["actual_pct"].round(3)
    df["close"] = df["close"].round(4)
    df["brier"] = df["brier"].round(4)
    df["abs_err"] = df["abs_err"].round(3)

    cols = ["date", "model", "ticker", "direction", "p_up", "pct_change", "actual_pct",
            "close", "actual_up", "hit", "brier", "abs_err", "late", "prompt_version", "model_version"]
    df.sort_values(["date", "ticker", "model"])[cols].to_csv(RESULTS_CSV, index=False)
    print(f"已打分 {len(df)} 条，写入 {RESULTS_CSV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
