"""信号源 feed — 给外部执行端 (如 Hyperliquid 自动交易) 订阅的"机器可读"接口。

设计要点:
- 只输出**可执行事件**: 开多/开空 / 移止损 / 加仓 / 平仓。
- append-only 事件日志 + 当前持仓快照, 双保险:
    events: 每条带全局递增 event_id, 消费端记住"上次处理到哪个 id"即可不重不漏。
    open_positions: 每轮重建的当前持仓全量快照, 用于消费端对账 (万一漏了某条事件)。
- 幂等: flush 时按 dedup key 去重, 即使 bot 因 push race 重跑也不会重复追加同一事件。
- 与机器人解耦: emit 只往内存缓冲塞, 出错不影响主流程; flush 在 main 末尾统一落盘。

事件字段 (executor 关心的):
  event_id, ts(UTC秒), time(可读), strategy, signal_no, pos_id(策略-编号, 全局唯一),
  action: open_long | open_short | move_stop | pyramid_add | close
  direction, entry_price, sl, tp, size_mult, r_dollar, notional_usd
  平仓额外: reason(tp目标 | lock锁价 | sl止损), exit_price, result_r, dollar_pl

⚠️ 这是"喊单"接口, 不下单。执行端凭此自行决策下单/风控, 私钥与下单逻辑由执行端独立掌控。
"""
import json
import os
from datetime import datetime

SCHEMA = 1
MAX_EVENTS = 1000  # 滚动保留最近 N 条, 防文件无限增长
_buffer = []       # 本轮待写事件 (内存)


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def pos_id(strategy_code, signal_no):
    return f"{strategy_code}-{signal_no:03d}"


def emit(strategy_code, signal_no, action, sig, notional_usd, **extra):
    """往本轮缓冲追加一条事件。永不抛异常。"""
    try:
        pid = pos_id(strategy_code, signal_no)
        ev = {
            "ts": sig.get("exit_ts") if action == "close" else sig.get("entry_ts"),
            "time": _now(),
            "strategy": strategy_code,
            "signal_no": signal_no,
            "pos_id": pid,
            "action": action,
            "direction": sig.get("direction"),
            "entry_price": sig.get("entry_price"),
            "sl": sig.get("current_sl"),
            "tp": sig.get("tp"),
            "size_mult": sig.get("size_multiplier", 1.0),
            "r_dollar": sig.get("r_dollar"),
            "notional_usd": notional_usd,
        }
        ev.update(extra)
        # dedup key: 同一持仓的 open/close 各一次; 移止损按目标价区分
        if action in ("open_long", "open_short"):
            ev["dedup"] = f"{pid}:open"
        elif action == "close":
            ev["dedup"] = f"{pid}:close"
        elif action == "move_stop":
            ev["dedup"] = f"{pid}:stop:{extra.get('sl')}"
        elif action == "pyramid_add":
            ev["dedup"] = f"{pid}:pyramid"
        else:
            ev["dedup"] = f"{pid}:{action}"
        _buffer.append(ev)
    except Exception as e:
        print(f"  [feed] emit 失败({action}): {e}")


def _load(path):
    if not os.path.exists(path):
        return {"schema": SCHEMA, "updated_at": None, "next_event_id": 1,
                "events": [], "open_positions": []}
    try:
        with open(path) as f:
            d = json.load(f)
        d.setdefault("next_event_id", (d["events"][-1]["event_id"] + 1) if d.get("events") else 1)
        return d
    except Exception:
        return {"schema": SCHEMA, "updated_at": None, "next_event_id": 1,
                "events": [], "open_positions": []}


def _snapshot_open(states_by_code, notional_usd):
    """从各策略 state 重建当前持仓快照"""
    snap = []
    for code, state in states_by_code:
        for i, sig in enumerate(state.get("signals", []), 1):
            if sig.get("status") == "entered":
                snap.append({
                    "strategy": code, "signal_no": i, "pos_id": pos_id(code, i),
                    "direction": sig.get("direction"),
                    "entry_price": sig.get("entry_price"),
                    "sl": sig.get("current_sl"), "tp": sig.get("tp"),
                    "size_mult": sig.get("size_multiplier", 1.0),
                    "r_dollar": sig.get("r_dollar"),
                    "stair_2r_locked": sig.get("stair_2r_locked", False),
                    "pyramid_entered": sig.get("pyramid_entered", False),
                    "notional_usd": notional_usd,
                })
    return snap


def flush(path, states_by_code, notional_usd):
    """把本轮缓冲事件去重后追加进 feed, 重建持仓快照, 落盘。返回新增事件数。"""
    feed = _load(path)
    existing = {e.get("dedup") for e in feed["events"]}
    added = 0
    for ev in _buffer:
        if ev.get("dedup") in existing:
            continue
        ev["event_id"] = feed["next_event_id"]
        feed["next_event_id"] += 1
        feed["events"].append(ev)
        existing.add(ev.get("dedup"))
        added += 1
    if len(feed["events"]) > MAX_EVENTS:
        feed["events"] = feed["events"][-MAX_EVENTS:]
    feed["open_positions"] = _snapshot_open(states_by_code, notional_usd)
    feed["updated_at"] = _now()
    feed["schema"] = SCHEMA
    with open(path, "w") as f:
        json.dump(feed, f, indent=2, ensure_ascii=False)
    _buffer.clear()
    return added
