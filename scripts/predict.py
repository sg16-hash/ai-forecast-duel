"""每个交易日开盘前运行：让 Claude 和 ChatGPT 用同一份提示词分别预测，写入 data/predictions.csv。

- 两个模型互相看不到对方的输出
- 原始回复存档在 data/raw/，便于事后审计
- 同一天同一模型只记录一次（重复运行会跳过），预测一旦提交就不再修改
- 若在美东 9:30 之后才运行，该行标记 late=1，统计时剔除
"""
import csv
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PRED_CSV = DATA_DIR / "predictions.csv"

PROMPT_VERSION = os.getenv("PROMPT_VERSION") or "v1"
PROMPT_FILE = ROOT / "prompts" / f"prompt_{PROMPT_VERSION}.md"
TICKERS = [t.strip().upper() for t in (os.getenv("TICKERS") or "MU,SNDK").split(",") if t.strip()]
ET = ZoneInfo("America/New_York")

FIELDS = ["date", "model", "model_version", "ticker", "direction", "p_up",
          "pct_change", "reason", "created_utc", "late", "prompt_version"]


# ---------- 工具函数 ----------

def is_trading_day(d: dt.date) -> bool:
    import pandas_market_calendars as mcal
    return not mcal.get_calendar("NYSE").schedule(start_date=d, end_date=d).empty


def existing_keys() -> set:
    if not PRED_CSV.exists():
        return set()
    with PRED_CSV.open(newline="", encoding="utf-8") as f:
        return {(r["date"], r["model"]) for r in csv.DictReader(f)}


def append_rows(rows: list) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    new_file = not PRED_CSV.exists()
    with PRED_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        w.writerows(rows)


def build_prompt(d: dt.date) -> str:
    text = PROMPT_FILE.read_text(encoding="utf-8")
    return text.replace("{date}", d.isoformat()).replace("{tickers}", ", ".join(TICKERS))


def extract_json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    s = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(s)


def validate(obj: dict) -> dict:
    out = {}
    for p in obj["predictions"]:
        t = str(p["ticker"]).upper().strip()
        if t not in TICKERS:
            continue
        p_up = float(p["p_up"])
        pct = float(p["pct_change"])
        if not 0.0 <= p_up <= 1.0:
            raise ValueError(f"{t} 的 p_up 超出 0-1：{p_up}")
        out[t] = {
            "p_up": round(p_up, 4),
            "pct_change": round(pct, 3),
            "reason": str(p.get("reason", "")).replace("\n", " ")[:400],
        }
    missing = set(TICKERS) - set(out)
    if missing:
        raise ValueError(f"回复里缺少标的：{sorted(missing)}")
    return out


# ---------- 两个模型 ----------

def ask_claude(prompt: str):
    from anthropic import Anthropic
    client = Anthropic()  # 读取环境变量 ANTHROPIC_API_KEY
    model = os.getenv("CLAUDE_MODEL") or "claude-opus-5-5"
    tools = [{"type": "web_search_20250305", "name": "web_search",
              "max_uses": int(os.getenv("MAX_SEARCHES") or 8)}]
    messages = [{"role": "user", "content": prompt}]
    texts = []
    for _ in range(5):  # 长时间搜索时 API 可能返回 pause_turn，需要续跑
        resp = client.messages.create(model=model, max_tokens=8000, tools=tools, messages=messages)
        texts += [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        if resp.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": resp.content})
    return model, "".join(texts)


def ask_chatgpt(prompt: str):
    from openai import OpenAI
    client = OpenAI()  # 读取环境变量 OPENAI_API_KEY
    model = os.getenv("OPENAI_MODEL") or "gpt-5"
    search_tool = os.getenv("OPENAI_SEARCH_TOOL") or "web_search"
    resp = client.responses.create(model=model, tools=[{"type": search_tool}], input=prompt)
    return model, resp.output_text


MODELS = {"claude": ask_claude, "chatgpt": ask_chatgpt}


# ---------- 主流程 ----------

def main() -> int:
    now_et = dt.datetime.now(ET)
    forced = os.getenv("FORCE_DATE")
    if forced:
        d = dt.date.fromisoformat(forced)
        late = False
    else:
        d = now_et.date()
        if not is_trading_day(d):
            print(f"{d} 非美股交易日，跳过")
            return 0
        late = now_et.time() >= dt.time(9, 30)
        if late:
            print("警告：已过美东 9:30 开盘时间，本次预测将标记为 late，不计入成绩")

    prompt = build_prompt(d)
    done = existing_keys()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    failures = []

    for name, fn in MODELS.items():
        if (d.isoformat(), name) in done:
            print(f"{name} 今天已有预测，跳过")
            continue
        last_err = None
        for attempt in range(1, 4):
            try:
                version, text = fn(prompt)
                (RAW_DIR / f"{d}_{name}.txt").write_text(text, encoding="utf-8")
                preds = validate(extract_json(text))
                created = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
                rows = [{
                    "date": d.isoformat(), "model": name, "model_version": version,
                    "ticker": t, "direction": "up" if v["p_up"] >= 0.5 else "down",
                    "p_up": v["p_up"], "pct_change": v["pct_change"], "reason": v["reason"],
                    "created_utc": created, "late": int(late), "prompt_version": PROMPT_VERSION,
                } for t, v in preds.items()]
                append_rows(rows)
                print(f"{name} ✓ {preds}")
                last_err = None
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                print(f"{name} 第 {attempt} 次失败：{e!r}")
                time.sleep(20 * attempt)
        if last_err:
            failures.append(name)

    if failures:
        print(f"以下模型今天没有成功记录：{failures}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
