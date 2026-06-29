# signals_feed.json — 外部执行端订阅说明

给执行端（如 Hyperliquid 自动交易 agent）订阅的**机器可读信号源**。信号机器人每 20 分钟更新一次，自动 commit 到 GitHub。

**订阅地址（拉这个 raw 文件即可）：**
```
https://raw.githubusercontent.com/Jessieeeeai/btc-doublelines-bot/main/signals_feed.json
```
> 注意：raw 链接有几分钟 CDN 缓存，对 20 分钟一轮的策略足够；要更实时可改用 GitHub API 带 `?ref` 或加 `Cache-Control` 头。

`signals_feed.sample.json` 是覆盖所有事件类型的样例，开发时照着这个结构解析。

---

## 文件结构

```jsonc
{
  "schema": 1,
  "updated_at": "2026-06-21 18:00 UTC",
  "next_event_id": 10,
  "events": [ ... ],          // 事件日志, append-only, 按 event_id 递增
  "open_positions": [ ... ]   // 当前持仓快照, 每轮重建
}
```

## 怎么消费（推荐流程）

1. **冷启动**：第一次先读 `open_positions`，把机器人当前所有持仓在你的执行端对齐（这些仓位是在你订阅之前开的，不会再有 `open_*` 事件）。
2. **跟单**：记住你处理过的最大 `event_id`。每次拉取后，只处理 `event_id` 比它大的新事件，处理完更新水位。
3. **对账（可选但建议）**：定期拿 `open_positions` 和你执行端的实际仓位比对，发现不一致就以 `open_positions` 为准修正（防漏处理事件）。

> 幂等保证：每条事件有唯一 `dedup` 键，机器人即使因并发重跑也不会重复写入同一事件。你按 `event_id` 去重即可，绝不会收到重复开/平仓。

## 事件类型（events[].action）

| action | 含义 | 执行端动作 |
|---|---|---|
| `open_long` | 开多 | 市价/限价开多仓，按 `sl`/`tp` 挂止损止盈 |
| `open_short` | 开空 | 开空仓，同上 |
| `move_stop` | 阶梯锁移动止损 | 把该仓位止损改到新的 `sl`（只会往盈利方向移）|
| `pyramid_add` | 金字塔加仓 | 在 `add_price` 加仓 `add_size`(0.5×) — 仅策略 C |
| `close` | 平仓 | 市价平掉该仓位全部 |

## 字段说明（events[]）

| 字段 | 说明 |
|---|---|
| `event_id` | 全局递增整数，消费水位就看它 |
| `ts` | 事件对应的 K 线时间戳（UTC 秒）|
| `time` | 可读时间（feed 写入时刻）|
| `strategy` | 策略代号 A/B/C |
| `signal_no` | 该策略内的信号编号 |
| `pos_id` | **全局唯一仓位 id**，格式 `策略-编号`，如 `B-019`。开仓和平仓用同一个 `pos_id` 对应 |
| `direction` | `long` / `short` |
| `entry_price` | 进场价 |
| `sl` | 当前止损价（`move_stop` 后是新值）|
| `tp` | 止盈目标价 |
| `size_mult` | 仓位倍数（C 的 Kelly 可能 ≠1.0；A/B 恒为 1.0）|
| `r_dollar` | 1R 对应的 BTC 美元距离（风控用）|
| `notional_usd` | 机器人假设的名义仓位（10000 = $1000 保证金 × 10x）。**你的实际下单量自己按风控决定，这只是参考基准** |
| `reason`（仅 close）| `tp`=真打到止盈目标 / `lock`=阶梯锁价出场 / `sl`=止损 |
| `exit_price`/`result_r`/`dollar_pl`（仅 close）| 出场价 / 盈亏 R / 按 notional 的美元盈亏 |

## 三套策略简述

- **A** baseline：固定 2R 止盈，无锁无加仓，仓位恒定。最简单。
- **B** 阶梯锁：8R 止盈 + 浮盈到 2R/4R 时往上锁止损，连亏 2 笔停 24h。
- **C** 终极 alpha：8R + 阶梯锁 + Kelly 动态仓位 + 1R 时金字塔加 0.5× + 单向冷却。最复杂，`size_mult` 会变。

> 你可以只跟其中一套（建议先 B 或 C），按 `strategy` 字段过滤事件即可。

## ⚠️ 上线前必读

- 这是**喊单**接口，不下单。私钥、下单、风控完全由执行端独立掌控。
- 先在 **Hyperliquid 测试网**空跑至少几周，确认开/平/移止损/加仓全链路不丢不重，再上小资金。
- 策略是慢周期（8R 持仓可达数周）+ 10x 杠杆，**仓位大小和爆仓价务必自己算清楚**，别直接照搬 `notional_usd`。
