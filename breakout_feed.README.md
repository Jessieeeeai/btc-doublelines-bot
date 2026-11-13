# 强突破跟进四马 · 信号源订阅说明（给 TokenBeep 接入用）

⚠️ **纸面验证阶段**：所有事件带 `"paper": true`，仅供订阅展示与对账，**不是实盘指令**。
格式与颈线赛马 `neckline_feed.json` 相同，**多一个 `symbol` 字段**（7 个币：BTC ETH SOL BNB XRP DOGE ADA）。

## 订阅链接（raw，公开仓库直接轮询）

总表（五马合流）：
```
https://raw.githubusercontent.com/Jessieeeeai/btc-doublelines-bot/main/breakout_feed.json
```
单马（文件内 event_id 从 1 连续递增，无断档）：
```
https://raw.githubusercontent.com/Jessieeeeai/btc-doublelines-bot/main/breakout_feed_N_H1.json   # N-H1 基准马：全做，2R 止盈
https://raw.githubusercontent.com/Jessieeeeai/btc-doublelines-bot/main/breakout_feed_N_H2.json   # N-H2 纽约顺势马：美东 7-13 点 + 顺 BTC，2R
https://raw.githubusercontent.com/Jessieeeeai/btc-doublelines-bot/main/breakout_feed_N_H3.json   # N-H3 强弱马：顺 BTC + 强弱排名，不设止盈，吊灯止损
https://raw.githubusercontent.com/Jessieeeeai/btc-doublelines-bot/main/breakout_feed_N_H4.json   # N-H4 奔跑马：顺 BTC，不设止盈，吊灯止损
https://raw.githubusercontent.com/Jessieeeeai/btc-doublelines-bot/main/breakout_feed_AMD.json   # AMD马（单独一类，代号 AMD）：4h 横盘→扫一侧→收回箱体，三段止盈（open 事件带 tp1/tp2/tp3/stop_after_tp1；tp 字段=第三止盈）
```

## 文件结构
```json
{ "schema": 1, "paper": true, "strategy": "N-H2", "updated_at": "2026-11-13 02:00 UTC",
  "next_event_id": 7, "events": [ ... ], "open_positions": [ ... ] }
```

## 事件字段
| 字段 | 说明 |
|---|---|
| event_id | 文件内递增，消费端去重锚点；单马文件另带 master_event_id（总表里的编号） |
| ts / time | 事件发生的 K 线时间戳（UTC 秒）/ 写入时间 |
| strategy / symbol | 马代号 / 交易对（如 `BTCUSDT`） |
| signal_no / pos_id | 该马的单号 / 持仓 ID（如 `N-H2-012`） |
| action | `open_long` / `open_short` / `move_stop` / `close` |
| direction / entry_price / sl / tp | 方向 / 进场价 / 止损 / 止盈（N-H4 的 tp 为 null） |
| notional_usd / risk_usd | 名义仓位 / 打到止损的亏损额（固定 $40） |
| close 附加 | reason（tp 止盈 / sl 止损 / trail 吊灯止损 / time 72 小时到时）、exit_price、pnl_usd、pnl_pct（占每币本金 $1,000 的百分比，已扣滑点和资金费） |

`move_stop`：N-H3 / N-H4 的吊灯止损首次推过进场价（保本）时发一条；AMD 在第一止盈到手、止损上移时发一条。AMD 的 `close` 是整笔结束时发一条，pnl_usd 为三份合计。

## 消费端要点
1. 机器人每 15 分钟跑一轮，轮询 ≥1 分钟一次即可。
2. 以 `event_id` 去重；怀疑漏事件时用 `open_positions` 快照对账，以快照为准。
3. **同一匹马在不同币上可以同时持仓**（最多 7 单），展示时要按 `symbol` 区分——这是和颈线马（只有 BTC）最大的不同。
4. 仓位口径：每币本金 $1,000、每单风险 $40、每匹马账户 $7,000。
