# 加密大漂亮 — 两线反转策略 (BTC 1h)

TradingView Pine 指标 → Python 回测 → Telegram 实盘信号机器人的完整闭环。

当前线上版本: **F6 + T5 容差** (Regime 过滤 + EMA-200 顺势 + 突破入场 + 0.5% 缠绕容差)。

## 目录结构

```
交易/
├── README.md                    # 本文件
├── DEPLOY.md                    # GitHub Actions + cron-job.org 部署说明
├── .env                         # API keys (本地, 不入 git)
├── .gitignore
│
├── state.json                   # 🔴 LIVE 状态文件 (机器人读写, 不要改)
│
├── signal_bot.py                # 🔴 LIVE 实时信号机器人主程序
├── signals.py                   # 🔴 LIVE 两线反转形态检测器
├── backtest.py                  # 🔴 LIVE 回测引擎 (VariantConfig 被 bot 用)
├── tg_notify.py                 # 🔴 LIVE Telegram 消息模板 & 推送
├── variants.py                  # 回测变体定义 (F1-F10)
│
├── .github/workflows/
│   └── signal_bot.yml           # 🔴 LIVE GitHub Actions 调度
│
├── pine/                        # TradingView 指标历史版本
│   ├── 加密大漂亮双线反转_v2.pine
│   ├── 加密大漂亮双线反转_v3.pine
│   ├── 加密大漂亮双线反转_v4.pine
│   ├── 加密大漂亮双线反转_v5.pine
│   └── 加密大漂亮双线反转_v6.pine   ← 最新版, 与 Python live 对齐
│
├── research/                    # 一次性研究脚本 (历史回测/分析)
│   ├── run_backtest.py          # 跑 variants.py 所有变体的赛马
│   ├── fetch_data.py            # 从 Coinglass 拉 K 线 CSV
│   ├── make_report.py           # 生成 results/回测报告.xlsx
│   ├── equity_backtest.py       # 1000u + 10x 杠杆资金曲线
│   ├── hedge_simulator.py       # Hedge 双向持仓模拟器
│   ├── regime_distribution.py   # 各 regime 时间占比分析
│   ├── analyze_direction.py     # 多单 vs 空单胜率对比
│   ├── analyze_drawdown_period.py # 回撤期专项分析
│   ├── find_drawdown.py         # 找最大回撤窗口
│   ├── check_overlap.py         # 信号时间重叠率
│   ├── sizing_comparison.py     # 不同仓位策略对比
│   ├── window_compare.py        # 不同时间窗口胜率
│   ├── _gen_test_data.py        # 单元自检数据生成器
│   └── test_tg.py               # TG 推送本地测试
│
├── data/                        # K线 CSV (gitignore, 跑 fetch_data 生成)
└── results/                     # 回测产出 (gitignore)
    └── 回测报告.xlsx
```

## 三层关系

```
TradingView (pine/v6) ─→ Python live (signal_bot.py) ─→ Telegram
                              ↑
                              └── 由 backtest/research 选出 F6+T5
```

- **pine/** 是给主播肉眼看盘用的指标 (TradingView 上挂)
- **signal_bot.py + signals.py** 是机器人版本, 跟 Pine v6 形态识别完全一致
- **research/** 是历史调参痕迹, 已固化结论, 不需要重跑

## 信号 & 风控逻辑 (F6 + T5)

**形态识别 (signals.py)**
- 3 根 K 线 A/B/C, B 和 C 实体比例 ≥ 0.5
- B、C 典型价互在对方实体内 (允许 0.5% 容差, 这就是 T5)
- 看涨: B 典型价 < A 最低 (急跌后底部缠绕)
- 看跌: B 典型价 > A 最高 (急涨后顶部缠绕)

**F6 过滤 (signal_bot.py)**
- 跳过强趋势期: `ADX > 25 且 |close - EMA200| / EMA200 > 2%`
- 顺势 EMA-200: 多单只在 close > EMA200 时取, 空单反之

**入场 & 出场**
- 入场: 信号确认后突破 `max(B.close, C.close)` 上沿才进场 (3 根 K 内未突破作废)
- 止损: 多 `min(B.low, C.low) × 0.98`; 空 `max(B.high, C.high) × 1.02`
- 止盈: 2R
- 每单本金 $10,000 + 10x 杠杆 = 1 万刀仓位

## 实盘机器人

- 部署: GitHub Actions 跑 `signal_bot.py`, cron-job.org 每 20 分钟外触发
- 状态: `state.json` 持久化, 收满 10 个信号后自动发战报
- 详见 `DEPLOY.md`

## 重新跑研究脚本 (可选)

研究脚本搬到了 `research/`, 顶部加了 sys.path 修复, 从根目录直接跑即可:

```bash
cd "/Users/guoxiaoquandediannao/Desktop/交易"
python3 research/fetch_data.py        # 拉新数据
python3 research/run_backtest.py      # 跑所有变体
python3 research/make_report.py       # 生成 Excel 报告
open results/回测报告.xlsx
```
