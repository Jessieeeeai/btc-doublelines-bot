# 两线反转 · 马G 第 2 版 · 信号源订阅说明（给 TokenBeep 接入用）

⚠️ **纸面验证阶段**：所有事件带 `"paper": true`，仅供订阅展示与对账，**不是实盘指令**。
格式与 `breakout_feed` 相同（schema 1），字段说明见 `breakout_feed.README.md`。

## 两匹马
- **N-G1 两线反转·突破马**：1h 两线反转形态出现后 3 根内，价格突破两线最高点（看跌：最低点）进场。
- **N-G2 两线反转·回踩马**：形态后 3 根内突破颈线，之后 2 根内回踩到 颈线∓0.2L 限价进场。
- 两匹共用：止损 = 较长那根（含影线）极值外 0.2L；止盈 = 2 倍风险，不跟踪。所以 `action` 只有 `open_long` / `open_short` / `close`，没有 `move_stop`、`partial_close`。
- 形态定义：两根颜色相反；第一根典型价越过前一根的最低/最高点；两根实体都大于全长 50%；两根典型价互相落在对方高低范围内。

## 订阅链接（每马每币一个文件，文件内 event_id 从 1 连续递增）
```
https://raw.githubusercontent.com/Jessieeeeai/btc-doublelines-bot/main/twoline_feed_N_G1_{BTC|ETH|SOL|BNB|XRP|DOGE|ADA}.json
https://raw.githubusercontent.com/Jessieeeeai/btc-doublelines-bot/main/twoline_feed_N_G2_{BTC|ETH|SOL|BNB|XRP|DOGE|ADA}.json
```

## 口径
- 每单本金 $500，每单风险 $20（`risk_usd`），名义封顶 $12,500。
- `close.reason`：`tp` 止盈 / `sl` 止损。`pnl_usd` 已扣滑点 0.04% 和资金费；`pnl_pct` 是占每单本金 $500 的百分比。
- `signal_no` / `pos_id` 按马编号（7 个币共用一个序列），所以单币文件里的单号不连续，`event_id` 连续。
- `ts` 是事件发生的那根 5 分钟 K 线的时间；机器人每 15 分钟跑一轮，`time`（写入时间）会比 `ts` 晚 1–20 分钟。
- 同一根 5 分钟里先进场又到止损的单，`open` 和 `close` 会在同一轮写入。
