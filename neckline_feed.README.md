# 重叠颈线赛马 · 信号源订阅说明

⚠️ **纸面验证阶段**：所有事件带 `"paper": true`，仅供订阅测试与对账，**不是实盘指令**。
与 F6 双线反战的 `signals_feed.json` 完全独立，执行端不要混接。

## 订阅链接（raw，公开仓库直接轮询）

总表（四马合流）：
```
https://raw.githubusercontent.com/Jessieeeeai/btc-doublelines-bot/main/neckline_feed.json
```

单马：
```
https://raw.githubusercontent.com/Jessieeeeai/btc-doublelines-bot/main/neckline_feed_N_A.json   # N-A FINAL_R完全体 (主力)
https://raw.githubusercontent.com/Jessieeeeai/btc-doublelines-bot/main/neckline_feed_N_C.json   # N-C 固定TP保守版
https://raw.githubusercontent.com/Jessieeeeai/btc-doublelines-bot/main/neckline_feed_N_D.json   # N-D 野马 (含微型单, 仅观察, 勿接执行)
https://raw.githubusercontent.com/Jessieeeeai/btc-doublelines-bot/main/neckline_feed_N_E.json   # N-E 白马 (前置冲击, 质量王)
```

单马文件是总表的过滤视图：`event_id` 与总表全局一致（单马文件内单调递增但不连续），
消费端只需记住"本文件处理到的最大 event_id"即可不重不漏。

## 文件结构

```json
{
  "schema": 1,
  "paper": true,
  "strategy": "N-A",
  "updated_at": "2026-08-18 22:00 UTC",
  "events": [ ... ],
  "open_positions": [ ... ]
}
```

## 事件字段

| 字段 | 说明 |
|---|---|
| event_id | 全局递增, 消费端去重锚点 |
| ts / time | 事件K线时间戳(UTC秒) / 写入时间 |
| strategy / signal_no / pos_id | 马代号 / 单号 / 全局唯一持仓ID (如 N-A-012) |
| action | `open_long` / `open_short` / `move_stop` / `close` |
| direction / entry_price / sl / tp | 方向 / 入场价 / 当前止损 / 止盈 (跟踪出场的马 tp=null) |
| L / neck_lo / neck_hi | 重叠区高度 / 下颈线 / 上颈线 |
| notional_usd | 名义仓位 (N-A/N-E 等风险仓位逐单不同; N-C 固定 $10,000) |
| close 附加: reason / exit_price / pnl_usd | tp=止盈 sl=止损 trail=跟踪锁利 / 出场价 / 盈亏$ |

`move_stop` 目前只在跟踪线首次推过入场价（保本）时发一条，附带新 sl。

## 消费端要点

1. 轮询频率建议 ≥1分钟一次；机器人每20分钟才跑一轮, 更快没有意义。
2. 以 `event_id` 去重; 怀疑漏事件时用 `open_positions` 快照对账, 两边不一致以快照为准。
3. 红线未过（每马前向样本足够且净期望为正）之前, 一切事件仅作纸面记录。
