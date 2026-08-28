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

def _html_to_md(text):
    """TG HTML caption → Discord Markdown"""
    import re
    text = re.sub(r"</?b>", "**", text)
    text = re.sub(r"</?code>", "`", text)
    text = re.sub(r"</?i>", "*", text)
    return re.sub(r"<[^>]+>", "", text)


def post_photo(url, png_bytes, caption):
    """Discord webhook 发图 (multipart: payload_json + files[0])"""
    boundary = "----dcFormBoundary5a17c3e9b2"
    payload = json.dumps({"content": caption[:1900]})
    parts = [
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
         f"Content-Type: application/json\r\n\r\n{payload}\r\n").encode(),
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; "
         f"filename=\"report.png\"\r\nContent-Type: image/png\r\n\r\n").encode()
        + png_bytes + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)), "User-Agent": "f6-discord-relay"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status in (200, 204)


def try_close_chart(e, url):
    """close 事件: 蜡烛图战报 + Markdown 时间线 (与 TG 同标准)。失败返回 False 降级纯文字。"""
    try:
        api_key = os.environ.get("COINGLASS_API_KEY")
        if not api_key:
            print("  [chart] no COINGLASS_API_KEY, fallback")
            return False
        code = e.get("strategy")
        no = e.get("signal_no") or 0
        state = json.load(open(f"state_{code}.json"))
        sig = state["signals"][no - 1]
        if sig.get("status") not in ("tp_hit", "sl_hit") or not sig.get("exit_ts"):
            return False
        if abs((sig.get("exit_price") or 0) - (e.get("exit_price") or -1)) >= 1:
            return False
        import signal_bot_race as sbr
        from trade_report import render_chart, build_caption_en
        hours = int((time.time() - (sig["entry_ts"] - 24 * 3600)) // 3600) + 8
        bars = sbr.fetch_btc_1h_bars(api_key, min(hours, 990))
        pl = e.get("dollar_pl") or 0
        png = render_chart(code, no, sig, bars, pl)
        cap = _html_to_md(build_caption_en(code, no, sig, bars, pl))
        return post_photo(url, png, cap)
    except Exception as ex:
        print(f"  [chart] failed, fallback: {type(ex).__name__}: {ex}")
        return False


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
            ok = False
            if e.get("action") == "close":
                ok = try_close_chart(e, url)  # 图版战报优先
            if not ok:
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
