# Agentic Trader

每日期权评分：对 32 只美股打 0–100 分（越高越看涨、越低越看跌），给出进场/退场提示，并每天复盘评分准不准。

**[打开网站](https://howardwhsrun.github.io/Agentic-Trader/)** · 方法和规则见 [OPTIONS.md](OPTIONS.md)

- `scripts/options_scorer.py`：扫描打分、挑合约、跟踪信号
- `scripts/options_watch.py`：盘中定时扫描，出信号时提醒
- `scripts/options_review.py`：收盘复盘（高分是否真涨、低分是否真跌）
- `scripts/options_report.py`：生成每日 PDF 分析报告（含私人持仓，不进仓库）
- `docs/`：网站（GitHub Pages 从 `main` 的 `/docs` 发布），数据在 `docs/data/options/`

```sh
python3 -m unittest discover -s tests
python3 -m http.server 8765 --bind 127.0.0.1 --directory docs
```

旧版的研究日志、买入评分、策略手册等页面已于 2026-11-11 移除，可在 git 历史（提交 `2b8f843` 及之前）中找回。

仅供个人研究参考，不构成投资建议。期权可能损失全部权利金。
