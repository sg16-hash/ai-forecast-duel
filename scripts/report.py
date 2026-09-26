"""根据 data/results.csv 生成对比报告 reports/latest.md 和走势图 reports/accuracy.png。"""
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULTS_CSV = ROOT / "data" / "results.csv"
PRICES_CSV = ROOT / "data" / "prices.csv"
REPORT_DIR = ROOT / "reports"
MIN_DAYS = 60  # 少于这个交易日数时，结论只作参考

NAMES = {"claude": "Claude", "chatgpt": "ChatGPT",
         "always_up": "基准·永远猜涨", "momentum": "基准·照搬昨天"}


def binom_two_sided(k: int, n: int) -> float:
    """精确二项检验（p=0.5），用于判断 k/n 是否显著偏离五五开。"""
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def add_baselines(res: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """在与模型相同的 (日期, 标的) 上构造两个笨办法基准。"""
    prices = prices.sort_values(["ticker", "date"]).copy()
    prices["prev_pct"] = prices.groupby("ticker")["actual_pct"].shift(1)
    keys = res[["date", "ticker", "actual_pct", "actual_up"]].drop_duplicates()
    keys = keys.merge(prices[["date", "ticker", "prev_pct"]], on=["date", "ticker"], how="left")

    rows = []
    for _, r in keys.iterrows():
        rows.append({"date": r.date, "ticker": r.ticker, "model": "always_up",
                     "p_up": 0.5, "hit": int(r.actual_up == 1), "brier": 0.25,
                     "abs_err": abs(r.actual_pct)})
        if pd.notna(r.prev_pct):
            up = int(r.prev_pct > 0)
            rows.append({"date": r.date, "ticker": r.ticker, "model": "momentum",
                         "p_up": 0.5, "hit": int(up == r.actual_up), "brier": 0.25,
                         "abs_err": abs(r.actual_pct)})
    return pd.DataFrame(rows)


def summary_table(df: pd.DataFrame) -> str:
    g = df.groupby("model").agg(n=("hit", "size"), hit=("hit", "mean"),
                                brier=("brier", "mean"), mae=("abs_err", "mean"))
    order = [m for m in NAMES if m in g.index]
    lines = ["| 选手 | 样本数 | 方向准确率 | Brier ↓ | 涨跌幅误差 ↓ |",
             "|---|---|---|---|---|"]
    for m in order:
        r = g.loc[m]
        brier = "—" if m in ("always_up", "momentum") else f"{r.brier:.3f}"
        mae = f"{r.mae:.2f}%" if m in ("claude", "chatgpt") else f"{r.mae:.2f}%（猜 0%）"
        lines.append(f"| {NAMES[m]} | {int(r.n)} | {r.hit:.1%} | {brier} | {mae} |")
    return "\n".join(lines)


def head_to_head(res: pd.DataFrame) -> str:
    p = res.pivot_table(index=["date", "ticker"], columns="model",
                        values=["hit", "brier", "abs_err", "direction"], aggfunc="first")
    if "claude" not in p["hit"].columns or "chatgpt" not in p["hit"].columns:
        return "目前还没有两边同时有效的预测。"
    p = p.dropna(subset=[("hit", "claude"), ("hit", "chatgpt")])
    n = len(p)
    disagree = p[p[("direction", "claude")] != p[("direction", "chatgpt")]]
    c_win = int(disagree[("hit", "claude")].sum())
    g_win = int(disagree[("hit", "chatgpt")].sum())
    pval = binom_two_sided(c_win, c_win + g_win)

    b_c = p[("brier", "claude")].astype(float)
    b_g = p[("brier", "chatgpt")].astype(float)
    brier_better_c = int((b_c < b_g).sum())
    brier_better_g = int((b_g < b_c).sum())
    brier_p = binom_two_sided(brier_better_c, brier_better_c + brier_better_g)

    lines = [
        f"- 同场比较样本：**{n}** 条（同一天、同一标的，两边都有有效预测）",
        f"- 两边方向判断**不一致**的有 {len(disagree)} 条：Claude 对了 {c_win} 次，ChatGPT 对了 {g_win} 次"
        f"（二项检验 p = {pval:.3f}）",
        f"- 逐条比 Brier：Claude 更好 {brier_better_c} 次，ChatGPT 更好 {brier_better_g} 次（p = {brier_p:.3f}）",
        f"- 平均 Brier：Claude {b_c.mean():.3f} vs ChatGPT {b_g.mean():.3f}",
    ]
    if pval < 0.05 or brier_p < 0.05:
        lines.append("- 至少一项差异在 5% 水平上显著。")
    else:
        lines.append("- 目前两项差异都**不显著**，还不能说谁更准。")
    return "\n".join(lines)


def per_ticker(df: pd.DataFrame) -> str:
    g = df[df["model"].isin(["claude", "chatgpt"])].groupby(["ticker", "model"]).agg(
        n=("hit", "size"), hit=("hit", "mean"), brier=("brier", "mean"), mae=("abs_err", "mean"))
    lines = ["| 标的 | 选手 | 样本 | 准确率 | Brier | 误差 |", "|---|---|---|---|---|---|"]
    for (t, m), r in g.iterrows():
        lines.append(f"| {t} | {NAMES[m]} | {int(r.n)} | {r.hit:.1%} | {r.brier:.3f} | {r.mae:.2f}% |")
    return "\n".join(lines)


def recent_table(res: pd.DataFrame, days: int = 10) -> str:
    recent_dates = sorted(res["date"].unique())[-days:]
    r = res[res["date"].isin(recent_dates)].sort_values(["date", "ticker"], ascending=[False, True])
    if r.empty:
        return "暂无数据"
    lines = ["| 日期 | 标的 | 实际 | Claude | ChatGPT |", "|---|---|---|---|---|"]
    for (d, t), g in r.groupby(["date", "ticker"], sort=False):
        actual = g["actual_pct"].iloc[0]
        cell = {}
        for m in ("claude", "chatgpt"):
            x = g[g["model"] == m]
            if x.empty:
                cell[m] = "—"
            else:
                x = x.iloc[0]
                mark = "✅" if x["hit"] else "❌"
                cell[m] = f"{mark} {x['pct_change']:+.1f}%（{x['p_up']:.0%}涨）"
        lines.append(f"| {d} | {t} | {actual:+.2f}% | {cell['claude']} | {cell['chatgpt']} |")
    return "\n".join(lines)


def plot(allrows: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=120)
    styles = {"claude": ("#D97757", "-", "Claude"), "chatgpt": ("#10A37F", "-", "ChatGPT"),
              "always_up": ("#888888", "--", "Baseline: always up"),
              "momentum": ("#BBBBBB", ":", "Baseline: yesterday's direction")}
    for m, (color, ls, label) in styles.items():
        x = allrows[allrows["model"] == m].groupby("date")["hit"].agg(["sum", "count"]).sort_index()
        if x.empty:
            continue
        cum = x["sum"].cumsum() / x["count"].cumsum()
        ax.plot(pd.to_datetime(cum.index), cum.values, ls, color=color, label=label, lw=2)
    ax.axhline(0.5, color="#cccccc", lw=1)
    ax.set_ylim(0, 1)
    ax.set_ylabel("Cumulative direction accuracy")
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.legend(loc="lower left", frameon=False, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(REPORT_DIR / "accuracy.png")


def main() -> int:
    if not RESULTS_CSV.exists():
        print("还没有打分结果，跳过")
        return 0
    res = pd.read_csv(RESULTS_CSV, dtype={"date": str})
    res = res[res["late"] == 0]
    if res.empty:
        print("没有有效（开盘前提交）的预测")
        return 0
    prices = pd.read_csv(PRICES_CSV, dtype={"date": str})
    base = add_baselines(res, prices)
    allrows = pd.concat([res[["date", "ticker", "model", "p_up", "hit", "brier", "abs_err"]], base],
                        ignore_index=True)

    n_days = res["date"].nunique()
    first, last = res["date"].min(), res["date"].max()
    REPORT_DIR.mkdir(exist_ok=True)
    plot(allrows)

    warn = (f"> ⚠️ 目前只有 {n_days} 个交易日，少于 {MIN_DAYS} 天，胜负主要是噪音，仅供参考。\n\n"
            if n_days < MIN_DAYS else "")
    md = f"""# Claude vs ChatGPT 预测对比

统计区间：{first} ~ {last}，共 {n_days} 个交易日（只统计开盘前提交的预测）

{warn}## 总成绩

{summary_table(allrows)}

- **方向准确率**：猜对涨跌的比例。要明显高于两个基准才算有真本事。
- **Brier**：概率预测的误差，越低越好；每次都报 50% 的得分是 0.250。
- **涨跌幅误差**：预测涨跌幅和实际的平均绝对差，越低越好。基准一栏是"每天都猜 0%"的误差。

## 正面对决

{head_to_head(res)}

## 分标的

{per_ticker(res)}

## 走势

![累计准确率](accuracy.png)

## 最近 10 个交易日

{recent_table(res)}
"""
    (REPORT_DIR / "latest.md").write_text(md, encoding="utf-8")
    print(f"报告已生成：reports/latest.md（{n_days} 个交易日）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
