# 两线反转 — 加密大漂亮 v2 回测项目 (BTC 1h)

基于你 TradingView 脚本改写的 Python 回测工具。
**只跑 BTC、1 小时周期**，赛马 10 个策略变体。

## 一次性配置（首次只做一次）

```bash
cd "/Users/guoxiaoquandediannao/Desktop/交易"
echo 'COINGLASS_API_KEY=ff66d7caa15b48838401901a48d7e70d' > .env
pip3 install openpyxl
```

## 跑一次回测（一条命令）

```bash
cd "/Users/guoxiaoquandediannao/Desktop/交易"
python3 fetch_data.py && python3 run_backtest.py && python3 make_report.py && open results/回测报告.xlsx
```

- 拉数据约 30 秒（近 1 年 = ~8760 根 1h K 线，自动分页）
- 回测约 3 秒（10 个变体）
- 自动打开 Excel 报告

## 信号 & 风控逻辑

**入场（来自 Pine Script v2）**：
- 3 根 K 线 A/B/C：B 和 C 实体比例 ≥ 阈值，且两者典型价互在对方实体内
- 看涨：B 的典型价 < A 的最低（急跌后底部缠绕）
- 看跌：B 的典型价 > A 的最高（急涨后顶部缠绕）

**出场（你定的规则）**：
- 入场价：信号 K 线**下一根**开盘价
- 止损：
  - 空：`SL = max(B.high, C.high) × (1 + buffer)` 默认 buffer = 2%
  - 多：`SL = min(B.low, C.low) × (1 − buffer)`
- R = |入场 − SL|
- 止盈：入场 ± N×R（变体里测 1.5/2/2.5/3）
- 手续费：单边 0.05%（合约 taker）
- 同根 K 线 SL+TP 都触及时保守按 SL 算

## 10 个策略变体

| 变体 | body阈值 | TP倍数 | SL缓冲 | 时间止损 |
|------|--------|-------|-------|---------|
| V1 | 0.5 | 1.5R | 2% | - |
| V2 (baseline) | 0.5 | 2.0R | 2% | - |
| V3 | 0.5 | 2.5R | 2% | - |
| V4 | 0.5 | 3.0R | 2% | - |
| V5 | 0.4 | 2.0R | 2% | - |
| V6 | 0.6 | 2.0R | 2% | - |
| V7 | 0.7 | 2.0R | 2% | - |
| V8 | 0.5 | 2.0R | 1% | - |
| V9 | 0.5 | 2.0R | 3% | - |
| V10 | 0.5 | 2.0R | 2% | 24根(=1天) |

- V1-V4 扫盈亏比、V5-V7 扫 body 严格度、V8-V9 扫止损缓冲、V10 加时间止损
- 想加新变体或改参数 → 改 `variants.py`

## 项目结构

```
交易/
├── .env                    # Coinglass API key (你创建)
├── fetch_data.py           # 拉 BTC 1h，自动分页
├── signals.py              # 两线反转形态检测 (复刻 Pine Script)
├── backtest.py             # R-Multiple 回测引擎
├── variants.py             # 10 个策略变体定义 ← 改这里调参
├── run_backtest.py         # 主回测脚本
├── make_report.py          # xlsx 报告生成器
├── data/                   # K线 CSV (运行后生成)
└── results/                # 回测结果 (运行后生成)
    ├── summary.csv
    ├── winrate_matrix.csv
    ├── all_trades.csv
    └── 回测报告.xlsx
```
