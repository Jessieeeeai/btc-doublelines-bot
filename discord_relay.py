#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
F6 信号 → Discord 转发器（独立于 TG 链路，读 signals_feed.json 增量转发）
状态存 discord_relay_state.json（last_event_id），不碰任何 F6 现有代码。
需要环境变量 DISCORD_WEBHOOK_URL（GitHub Secret）。
"""
import json
import os
import time
import urllib.request

FEED = "signals_feed.json"
STATE = "discord_relay_state.json"

def post(url, text):
    payload = json.dumps({"content": text[:1900]}).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json", "User-Agent": "f6-discord-relay"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status in (200, 204)

def fmt(e):
    s = e.get("strategy", "?")
    no = e.get("signal_no") or 0
    head = f"**[{s}] #{no:03d}**"
    d = "做多 📈" if e.get("direction") == "long" else "做空 📉"
    a = e.get("action")
    t = e.get("time", "")
    if a in ("open_long", "open_short"):
        return (f"🔔 {head} 入场 · {d}\n"
                f"入场 `${e['entry_price']:,.2f}` · 止损 `${e['sl']:,.2f}` · "
                f"止盈 `${e['tp']:,.2f}` · 仓位 {e.get('size_mult', 1.0):.2f}x\n"
                f"🕐 {t} · BTC · F6 策略赛马（纸面验证, 非实盘指令）")
    if a == "close":
        r = {"tp": "🎯 止盈", "stop": "🛑 止损", "lock": "🔒 锁利离场",
             "time": "⏱ 超时平仓"}.get(e.get("reason"), str(e.get("reason")))
        rr = e.get("result_r") or 0.0
        pl = e.get("dollar_pl") or 0.0
        return (f"{r} {head} 平仓\n"
                f"出场 `${e.get('exit_price', 0):,.2f}` · 盈亏 **{rr:+.2f}R**（${pl:+,.2f}）\n"
                f"🕐 {t}")
    if a == "move_stop":
        return f"🔒 {head} 移动止损 → `${e['sl']:,.2f}`（锁 {e.get('lock', '')}）\n🕐 {t}"
    if a == "pyramid_add":
        return (f"➕ {head} 金字塔加仓 @ `${e.get('add_price', 0):,.2f}`"
                f"（+{e.get('add_size', 0)}x）\n🕐 {t}")
    return f"{head} {a} · {t}"

def main():
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        print("[WARN] 未配置 DISCORD_WEBHOOK_URL, 跳过")
        return
    feed = json.load(open(FEED))
    st = json.load(open(STATE)) if os.path.exists(STATE) else {"last_event_id": 0}
    last = st.get("last_event_id", 0)
    new = sorted([e for e in feed.get("events", []) if e.get("event_id", 0) > last],
                 key=lambda x: x["event_id"])
    print(f"feed events={len(feed.get('events', []))} last={last} new={len(new)}")
    for e in new:
        try:
            ok = post(url, fmt(e))
        except Exception as ex:
            print(f"[FAIL] event {e['event_id']}: {type(ex).__name__}: {ex}")
            break  # 保持顺序, 本轮中断, 下轮重试
        if not ok:
            print(f"[FAIL] event {e['event_id']}: webhook 返回异常")
            break
        st["last_event_id"] = e["event_id"]
        print(f"[OK] relayed event {e['event_id']}")
        time.sleep(1)
    json.dump(st, open(STATE, "w"), indent=2)

if __name__ == "__main__":
    main()
