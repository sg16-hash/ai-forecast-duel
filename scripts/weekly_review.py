"""每周六运行：把本周的成绩和双方的预测理由交给 Claude，写一份点评。

Claude 在这里是裁判，只能看到已经打完分的数据，不参与当周预测。
为避免"裁判偏袒自己"，提示词要求只依据数字下结论，并在数据不足时直说。
"""
import datetime as dt
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULTS_CSV = ROOT / "data" / "results.csv"
PRED_CSV = ROOT / "data" / "predictions.csv"
REPORT_MD = ROOT / "reports" / "latest.md"
OUT_DIR = ROOT / "reports" / "weekly"

PROMPT = """你是这场预测比赛的中立裁判。参赛者是 Claude 和 ChatGPT，每个交易日开盘前各自预测 MU 和 SNDK 当天收盘涨跌。
你本身也是 Claude，所以必须格外注意不偏袒任何一方：只依据下面的数字和理由下结论，数据不足就明说"还看不出来"。

请用中文写一份周报（600 字以内），包含：
1. 本周谁表现更好，差距是否可能只是运气（结合样本量和报告里的 p 值）
2. 双方判断分歧的日子里，各自的理由有什么规律，谁的逻辑更站得住
3. 双方有没有共同的系统性偏差（例如总是偏乐观、概率给得太满、对某只股票特别不准）
4. 截至目前的累计结论，一句话

【累计报告】
{report}

【本周逐条数据（含理由）】
{week}
"""


def main() -> int:
    if not RESULTS_CSV.exists() or not REPORT_MD.exists():
        print("数据不足，跳过周报")
        return 0
    res = pd.read_csv(RESULTS_CSV, dtype={"date": str})
    pred = pd.read_csv(PRED_CSV, dtype={"date": str})[["date", "model", "ticker", "reason"]]
    since = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    week = res[(res["date"] >= since) & (res["late"] == 0)].merge(
        pred, on=["date", "model", "ticker"], how="left")
    if week.empty:
        print("本周没有已打分的预测，跳过")
        return 0
    cols = ["date", "ticker", "model", "p_up", "pct_change", "actual_pct", "hit", "brier", "reason"]
    prompt = PROMPT.format(report=REPORT_MD.read_text(encoding="utf-8"),
                           week=week[cols].to_csv(index=False))

    from anthropic import Anthropic
    client = Anthropic()
    resp = client.messages.create(model=os.getenv("CLAUDE_MODEL") or "claude-opus-5-5",
                                  max_tokens=3000,
                                  messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in resp.content if b.type == "text")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{dt.date.today().isoformat()}.md"
    out.write_text(f"# 周报 {dt.date.today().isoformat()}\n\n{text}\n", encoding="utf-8")
    print(f"周报已生成：{out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
