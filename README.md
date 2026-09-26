# Claude vs ChatGPT：MU / SNDK 每日预测对决

每个美股交易日，Claude 和 ChatGPT 在开盘前用**同一份提示词**独立预测美光（MU）和闪迪（SNDK）当天收盘涨跌，收盘后自动打分，每周六由 Claude 写一份裁判周报。全部在 GitHub Actions 上运行，不需要你开电脑。

📊 **最新成绩：[reports/latest.md](reports/latest.md)** · 周报：[reports/weekly/](reports/weekly/)

## 每天发生什么（北京时间）

| 时间 | 做什么 | 文件 |
|---|---|---|
| 约 20:00（周一至五） | 两个模型联网搜索后各自给出预测，提交到仓库锁定 | `data/predictions.csv`、`data/raw/` |
| 约 06:30（次日） | 拉取实际收盘价打分，更新报告和图表 | `data/results.csv`、`reports/latest.md` |
| 周六 11:00 | Claude 以裁判身份写本周点评 | `reports/weekly/日期.md` |

美国节假日自动跳过。Git 提交时间就是"开盘前已锁定"的证据；超过美东 9:30 才生成的预测会被标记 `late=1`，不计入成绩。

## 一次性设置（约 15 分钟）

1. **建仓库**：在 GitHub 新建一个仓库（建议设为 Private），把本文件夹全部内容上传。
2. **准备两个 API key**
   - Claude：[console.anthropic.com](https://console.anthropic.com) → API Keys
   - OpenAI：[platform.openai.com](https://platform.openai.com) → API keys
   - 两边都需要先充值少量余额。
3. **填入密钥**：仓库 → Settings → Secrets and variables → Actions → **Secrets** 标签，新建：
   - `ANTHROPIC_API_KEY`
   - `OPENAI_API_KEY`
4. **（可选）改参数**：同一页面 **Variables** 标签，可以新建：

   | 变量 | 默认值 | 说明 |
   |---|---|---|
   | `CLAUDE_MODEL` | `claude-opus-5-5` | Claude 使用的模型 |
   | `OPENAI_MODEL` | `gpt-5` | 换成你想比的 ChatGPT 模型 |
   | `TICKERS` | `MU,SNDK` | 逗号分隔，可加别的标的 |
   | `PROMPT_VERSION` | `v1` | 对应 `prompts/prompt_v1.md` |

5. **允许 Actions 写仓库**：Settings → Actions → General → Workflow permissions → 选 **Read and write permissions** → Save。
6. **试跑一次**：Actions 标签 → 左侧 `predict` → Run workflow。成功后 `data/predictions.csv` 会出现两边的预测。

完成后就不用管了，定时任务会自己跑。

## 怎么看成绩

- **方向准确率**：猜对涨跌的比例。必须**明显高于两个基准**（永远猜涨、照搬昨天方向）才算有真本事。
- **Brier 分数**：衡量概率是否说得准，越低越好；每次都说 50% 的得分是 0.250。
- **涨跌幅误差**：预测幅度和实际的平均差距，越低越好。
- **正面对决**只看两边都有效的同一天同一标的；只有 p 值 < 0.05 才能说差距不是运气。
- 少于 60 个交易日时报告会提示"仅供参考"。

## 规则与公平性

- 两个模型用完全相同的提示词、同一时间运行，互相看不到对方的输出。
- 原始回复全部保存在 `data/raw/`，可以随时核查。
- 预测写入后不会被修改；某个模型当天失败，那天它就没有成绩（不补跑）。
- **想改提示词**：不要改 `prompt_v1.md`，复制成 `prompt_v2.md` 修改，再把变量 `PROMPT_VERSION` 改成 `v2`。每行记录了用的是哪个版本，方便分开统计。
- 周报由 Claude 撰写，存在"裁判也是选手"的利益冲突。周报提示词已要求只依据数字下结论，但判断谁更准请以 `latest.md` 里的数字为准。

## 费用估算

每个交易日每个模型调用 1 次（含几次联网搜索），加上每周 1 次周报，通常每月合计几美元到十几美元，取决于所选模型。GitHub Actions 私有仓库每月有 2000 分钟免费额度，本项目每月用不到 200 分钟。

## 常见问题

- **某天没有预测**：GitHub 定时任务偶尔延迟或漏跑，已设了备用时间自动补。仍然缺失的话，到 Actions 页面看错误日志，常见原因是 API 余额不足。
- **OpenAI 报搜索工具错误**：不同时期工具名可能不同，新建变量 `OPENAI_SEARCH_TOOL` 改成 `web_search_preview` 试试。
- **手动补测**：`predict` 手动运行时可以填日期，但补跑的预测不是开盘前做出的，只能用来测试流程，正式统计前请删掉这些行。

## 文件结构

```
.github/workflows/predict.yml   开盘前出预测
.github/workflows/score.yml     收盘后打分、出报告、周六周报
prompts/prompt_v1.md            两边共用的提示词
scripts/predict.py              调用两个模型并解析结果
scripts/score.py                拉收盘价打分
scripts/report.py               生成 latest.md 和走势图
scripts/weekly_review.py        Claude 裁判周报
scripts/commit.sh               把结果提交回仓库
data/                           预测、成绩、行情（自动生成）
reports/                        报告（自动生成）
```
