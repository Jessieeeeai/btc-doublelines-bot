"""重叠颈线赛马 · 信号源 feed (机器可读)

与 F6 的 signals_feed.json 同规范 (append-only 事件 + 持仓快照 + dedup 幂等),
但输出到独立文件 neckline_feed.json —— 绝不写入 signals_feed.json,
避免 Hyperliquid 执行端误消费纸面验证信号。

⚠️ 纸面验证阶段: 所有事件带 "paper": true 标记。执行端在红线通过前不应消费。

事件字段:
  event_id, ts, time, strategy(N-A/N-C/N-D/N-E), signal_no, pos_id, paper,
  action: open_long | open_short | move_stop | close
  direction, entry_price, sl, tp(可为null=跟踪出场), L, neck_lo, neck_hi, notional_usd
  close 额外: reason(tp|sl|trail), exit_price, pnl_usd
"""
import json
import os
from datetime import datetime

FEED_FILE = "neckline_feed.json"
SCHEMA = 1
MAX_EVENTS = 1000
_buffer = []


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def pos_id(code, seq):
    return f"{code}-{seq:03d}"


def emit(code, action, payload, **extra):
    """payload = pos 或 trade dict。永不抛异常。"""
    try:
        seq = payload.get("seq")
        pid = pos_id(code, seq)
        ev = {
            "ts": payload.get("exit_ts") if action == "close" else payload.get("entry_ts"),
            "time": _now(),
            "strategy": code,
            "signal_no": seq,
            "pos_id": pid,
            "paper": True,
            "action": action,
            "direction": payload.get("direction"),
            "entry_price": payload.get("entry"),
            "sl": payload.get("sl"),
            "tp": payload.get("tp"),
            "L": payload.get("L"),
            "neck_lo": payload.get("neck_lo"),
            "neck_hi": payload.get("neck_hi"),
            "notional_usd": payload.get("notional"),
        }
        ev.update(extra)
        if action in ("open_long", "open_short"):
            ev["dedup"] = f"{pid}:open"
        elif action == "close":
            ev["dedup"] = f"{pid}:close"
        elif action == "move_stop":
            ev["dedup"] = f"{pid}:stop:{extra.get('sl') or payload.get('sl')}"
        else:
            ev["dedup"] = f"{pid}:{action}"
        _buffer.append(ev)
    except Exception as e:
        print(f"  [feed] emit 失败({action}): {e}")


def _load(path):
    if not os.path.exists(path):
        return {"schema": SCHEMA, "paper": True, "updated_at": None,
                "next_event_id": 1, "events": [], "open_positions": []}
    try:
        with open(path) as f:
            d = json.load(f)
        d.setdefault("next_event_id", (d["events"][-1]["event_id"] + 1) if d.get("events") else 1)
        return d
    except Exception:
        return {"schema": SCHEMA, "paper": True, "updated_at": None,
                "next_event_id": 1, "events": [], "open_positions": []}


def _horse_feed_path(code):
    """单马feed文件名: N-A -> neckline_feed_N_A.json"""
    return f"neckline_feed_{code.replace('-', '_')}.json"


def flush(states_by_code, path=FEED_FILE):
    """缓冲事件去重后追加进总feed, 重建持仓快照, 落盘;
    并按马拆分写出单马feed (总feed的过滤视图, event_id全局一致)。
    返回新增事件数。永不抛异常。"""
    try:
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
        snap = []
        for code, state in states_by_code:
            pos = state.get("position")
            if pos:
                snap.append({
                    "strategy": code, "signal_no": pos.get("seq"),
                    "pos_id": pos_id(code, pos.get("seq") or 0),
                    "paper": True,
                    "direction": pos.get("direction"),
                    "entry_price": pos.get("entry"),
                    "sl": pos.get("sl"), "tp": pos.get("tp"),
                    "L": pos.get("L"),
                    "neck_lo": pos.get("neck_lo"), "neck_hi": pos.get("neck_hi"),
                    "notional_usd": pos.get("notional"),
                })
        feed["open_positions"] = snap
        feed["updated_at"] = _now()
        feed["schema"] = SCHEMA
        with open(path, "w") as f:
            json.dump(feed, f, indent=2, ensure_ascii=False)

        # 单马feed: 总feed的过滤视图 (event_id 与总feed一致, 消费端按各自文件记id即可)
        for code, state in states_by_code:
            sub = {
                "schema": SCHEMA, "paper": True, "strategy": code,
                "updated_at": feed["updated_at"],
                "events": [e for e in feed["events"] if e.get("strategy") == code],
                "open_positions": [p for p in snap if p.get("strategy") == code],
            }
            with open(_horse_feed_path(code), "w") as f:
                json.dump(sub, f, indent=2, ensure_ascii=False)

        _buffer.clear()
        return added
    except Exception as e:
        print(f"  [feed] flush 失败: {e}")
        _buffer.clear()
        return 0
