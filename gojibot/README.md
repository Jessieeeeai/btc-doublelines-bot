# GojiBot 回测系统 v1.0

按 GojiBot 技术手册 v3.2 框架重建的可回测交易系统（BTC，2年）。

## 使用步骤

**第 1 步（你来做，在自己的终端）：下载数据**

```bash
cd ~/Desktop/交易/gojibot
python3 fetch_data.py
```

- 只用 Python 标准库，无需安装任何东西
- Binance 部分无需 key；CoinGlass 部分用 config.json 里的 key
- 跑完后 `data/` 里会有若干 CSV 和一份 `fetch_report.json`（记录你的套餐能拿到哪些数据）
- 大约需要 5～15 分钟（CoinGlass 有限速，脚本自动控制节奏）

**第 2 步：回到 Cowork 告诉我「数据好了」**，我在沙盒里跑回测并出报告。

## 与原文档的刻意差异（都是修复上次指出的问题）

1. **成本**：每笔双边计 taker 0.05% + 滑点 0.02%（原文档零成本）
2. **阈值**：默认用「训练段分位数」而非绝对值（如 FR>+0.30%），
   避免单位不明与过拟合；也可 `--mode doc_abs` 按原文档跑对照
3. **样本外**：前半段校准、后半段验证（walk-forward 第一步）
4. **保守撮合**：同一根K线内止损与止盈同时可触时，按止损优先
5. **超时强制平仓**（原文档只提醒不平仓，无法回测）
6. **仓位独立层**：文档口径求和 / 固定风险1% / 分级风险 / 0.5% 四种方案对比
7. **订单簿/OI 数据拿不到时条件自动降级**并在报告中注明

## 前向验证扫描器（monitor.py）

纸面模式，不下单。每小时评估重构版 S01（近阻力+现货CVD<0+费率≥0，L01止损，6h冷却），
记录市场快照、信号、纸面持仓生命周期到 `forward/`，信号触发时发 macOS 通知。

安装（每小时第5分钟自动跑）：

```bash
# 先手动跑一次确认正常
python3 ~/Desktop/交易/gojibot/monitor.py

# 挂载 launchd
cp ~/Desktop/交易/gojibot/com.gojibot.monitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.gojibot.monitor.plist

# 卸载
launchctl unload ~/Library/LaunchAgents/com.gojibot.monitor.plist
```

观察 4-8 周后，把 `forward/paper_trades.csv` 拿回来和回测预期对比，再决定下一步。

## 文件结构

```
fetch_data.py   数据下载（本机跑）
strategy.py     特征 + S01/S02×4/S03 + L01止损 + 门控
backtest.py     逐bar撮合执行器
sizing.py       仓位方案与绩效指标
run.py          主入口（--synthetic 冒烟测试 / --mode doc_abs 对照）
config.json     参数（含你的 CoinGlass key，别把这个文件夹分享出去）
results/        报告输出
```
