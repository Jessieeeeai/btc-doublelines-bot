"""强突破跟进四马 · 信号源 feed (机器可读)

与颈线赛马 neckline_feed.json 同规范 (append-only 事件 + 持仓快照 + dedup 幂等 + 单马文件内连续编号),
多一个 symbol 字段 (7 个币)。输出到独立文件 breakout_feed.json / breakout_feed_N_H1.json ...,
不写入任何已有 feed。⚠️ 纸面验证阶段: 所有事件带 "paper": true。

事件字段:
  event_id, ts, time, strategy(N-H1..N-H4, AMD), symbol, signal_no, pos_id, paper,
  action: open_long | open_short | move_stop | partial_close | close
  direction, entry_price, sl, tp(N-H3/N-H4 为 null=吊灯止损出场; AMD 为第三止盈, 另带 tp1/tp2/tp3/stop_after_tp1), notional_usd, risk_usd
  close 额外: reason(tp|sl|trail|time), exit_price, pnl_usd, pnl_pct(占每币本金 $1,000)
  partial_close (只有 AMD): 某一档止盈到手、先出掉原始仓位的一部分。带 leg(第几档), exit_price,
      close_fraction(这次出掉的占原始仓位, 0.3333) / close_fraction_text("1/3"), remaining_fraction(出完还剩多少),
      pnl_usd_gross(这一份的毛利, 未扣成本)。AMD 的 close 也带 close_fraction (最后一次出掉的份额) 和 legs (三份各自的出场明细)。
"""
import json, os
from datetime import datetime, timezone

FEED_FILE = "breakout_feed.json"
SCHEMA, MAX_EVENTS, PRINCIPAL = 1, 1000, 1000.0
CODES = ["N-H1", "N-H2", "N-H3", "N-H4", "AMD"]
TB_SYMS = ["BTC", "ETH", "SOL"]   # 接入 TokenBeep 量化机器人的币 (每马每币一个文件)
_buffer = []


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _pid(code, seq):
    return f"{code}-{seq:03d}"


def _r(x):
    return None if x is None else float(f"{x:.8g}")


def _ev(code, sym, seq, action, ts, d, e, sl, tp, n, dedup, **extra):
    e, sl, tp = _r(e), _r(sl), _r(tp)
    if "exit_price" in extra:
        extra["exit_price"] = _r(extra["exit_price"])
    ev = {"ts": ts, "time": _now(), "strategy": code, "symbol": f"{sym}USDT", "signal_no": seq, "pos_id": _pid(code, seq),
          "paper": True, "action": action, "direction": "long" if d == 1 else "short", "entry_price": e, "sl": sl, "tp": tp,
          "notional_usd": n, "risk_usd": 40.0, "dedup": f"{_pid(code, seq)}:{dedup}"}
    ev.update(extra)
    _buffer.append(ev)


def _frac(k):
    return round(k / 3.0, 4), f"{k}/3"


def _partial(p, leg, px, ts, left_after):
    """AMD 某一档止盈到手: 出掉原始仓位的 1/3。left_after = 出完之后还剩几份 (0~2)。"""
    f, ft = _frac(1)
    _ev("AMD", p["sym"], p["seq"], "partial_close", ts, p["d"], p["e"], p["sl"], None, p["n"], f"partial:{leg}",
        reason="tp", leg=leg, exit_price=px, close_fraction=f, close_fraction_text=ft,
        remaining_fraction=_frac(left_after)[0], pnl_usd_gross=round(p["n"] / 3.0 * (px - p["e"]) * p["d"] / p["e"], 2))


def emit(kind, p):
    """kind/p 就是机器人 msgs 里的条目。永不抛异常。"""
    try:
        if kind == "entry":
            for code in p["horses"]:
                pos = p["pos"][code]
                _ev(code, p["sym"], pos["seq"], "open_long" if p["d"] == 1 else "open_short", p["ts"], p["d"], p["e"], p["sl"],
                    pos["tp"], pos["n"], "open")
        elif kind == "entry5":
            _ev("AMD", p["sym"], p["seq"], "open_long" if p["d"] == 1 else "open_short", p["ts"], p["d"], p["e"], p["sl"],
                p["tg"][2], p["n"], "open", tp1=_r(p["tg"][0]), tp2=_r(p["tg"][1]), tp3=_r(p["tg"][2]), stop_after_tp1=_r(p["s1"]))
        elif kind == "tp5":
            done = p.get("done", None)
            for k, (leg, px) in enumerate(zip(p["which"], p["px"])):
                left = (3 - done + len(p["which"]) - k - 1) if done is not None else None
                _partial(p, leg, px, p["ts"], left if left is not None else 0)
            if p.get("first"):
                _ev("AMD", p["sym"], p["seq"], "move_stop", p["ts"], p["d"], p["e"], p["sl"], None, p["n"], f"stop:{_r(p['sl'])}")
        elif kind == "bemove":
            _ev(p["code"], p["sym"], p["seq"], "move_stop", p["ts"], p["d"], p["e"], p["sl"], None, p["n"], f"stop:{_r(p['sl'])}")
        elif kind == "exit":
            reason = "trail" if (p["why"] == "sl" and p["sl"] != p["sl0"]) else p["why"]
            extra = {}
            if p["code"] == "AMD" and p.get("legs"):
                legs = sorted(p["legs"], key=lambda g: (g[3], g[0]))
                last = [g for g in legs if g[3] == legs[-1][3] and g[1] == legs[-1][1]]   # 最后一次一起出掉的那几份
                early = [g for g in legs if g not in last]
                for k, g in enumerate(early):      # 同一根里先到的止盈档 (没单独发过 tp5 的) 在这里补发; 已发过的靠 dedup 跳过
                    _partial(p, g[0], g[1], g[3], 3 - k - 1)
                f, ft = _frac(len(last))
                extra = dict(close_fraction=f, close_fraction_text=ft, remaining_fraction=0.0,
                             legs=[{"leg": g[0], "exit_price": _r(g[1]), "reason": g[2], "ts": g[3], "fraction": _frac(1)[0]} for g in legs])
            _ev(p["code"], p["sym"], p["seq"], "close", p["xts"], p["d"], p["e"], p["sl"], p["tp"], p["n"], "close",
                reason=reason, exit_price=p["x"], pnl_usd=p["net_base"], pnl_pct=round(p["net_base"] / PRINCIPAL * 100, 2), **extra)
    except Exception as e:
        print(f"  [feed] emit 失败({kind}): {e}")


def _load(path):
    blank = {"schema": SCHEMA, "paper": True, "updated_at": None, "next_event_id": 1, "events": [], "open_positions": []}
    if not os.path.exists(path):
        return blank
    try:
        with open(path) as f:
            d = json.loads(f.read().replace("N-H5", "AMD"))   # 早期 AMD马 记在 N-H5 名下
        d["next_event_id"] = (d["events"][-1]["event_id"] + 1) if d.get("events") else 1
        return d
    except Exception:
        return blank


def flush(st, path=FEED_FILE):
    """缓冲事件去重后追加进总表, 重建持仓快照; 再按马拆成单马文件 (各自连续编号)。返回新增事件数。"""
    try:
        feed = _load(path)
        seen = {e.get("dedup") for e in feed["events"]}
        added = []
        for ev in _buffer:
            if ev["dedup"] in seen:
                continue
            ev["event_id"] = feed["next_event_id"]; feed["next_event_id"] += 1
            feed["events"].append(ev); seen.add(ev["dedup"]); added.append(ev)
        feed["events"] = feed["events"][-MAX_EVENTS:]
        snap = []
        for sym, ss in st["syms"].items():
            for code, pos in ss["pos"].items():
                snap.append({"strategy": code, "symbol": f"{sym}USDT", "signal_no": pos["seq"], "pos_id": _pid(code, pos["seq"]),
                             "paper": True, "direction": "long" if pos["d"] == 1 else "short", "entry_price": pos["e"],
                             "sl": pos["sl"], "tp": pos["tp"], "notional_usd": pos["n"]})
        feed.update(open_positions=snap, updated_at=_now(), schema=SCHEMA, paper=True)
        with open(path, "w") as f:
            json.dump(feed, f, indent=2, ensure_ascii=False)
        # 单马文件 (7 币合在一起) + 单马单币文件 (TokenBeep 量化机器人一个接入只能绑一个币)
        targets = [(f"breakout_feed_{c.replace('-', '_')}.json", c, None) for c in CODES]
        targets += [(f"breakout_feed_{c.replace('-', '_')}_{y}.json", c, f"{y}USDT") for c in CODES for y in TB_SYMS]
        for sp, code, symbol in targets:
            hit = lambda x: x["strategy"] == code and (symbol is None or x["symbol"] == symbol)
            sub = _load(sp); sub["strategy"] = code
            if symbol:
                sub["symbol"] = symbol
            sseen = {e.get("dedup") for e in sub["events"]}
            for ev in (feed["events"] if not os.path.exists(sp) else added):   # 新文件: 把总表里已有的事件补进来
                if not hit(ev) or ev["dedup"] in sseen:
                    continue
                e2 = dict(ev); e2["master_event_id"] = ev["event_id"]; e2["event_id"] = sub["next_event_id"]
                sub["next_event_id"] += 1; sub["events"].append(e2); sseen.add(ev["dedup"])
            sub["events"] = sub["events"][-MAX_EVENTS:]
            sub.update(open_positions=[p for p in snap if hit(p)], updated_at=feed["updated_at"], schema=SCHEMA, paper=True)
            with open(sp, "w") as f:
                json.dump(sub, f, indent=2, ensure_ascii=False)
        _buffer.clear()
        return len(added)
    except Exception as e:
        print(f"  [feed] flush 失败: {e}")
        _buffer.clear()
        return 0
