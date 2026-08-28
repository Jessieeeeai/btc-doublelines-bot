#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
F6 signals -> English Telegram relay (independent of the Chinese pipeline).
Reads signals_feed.json incrementally, posts English messages to TG_EN_CHAT_ID
using the same bot token. Progress stored in tg_en_relay_state.json.
"""
import json
import os
import time
import urllib.request

FEED = "signals_feed.json"
STATE = "tg_en_relay_state.json"

def post(token, chat_id, text):
    payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                          "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode()).get("ok", False)

def fmt(e):
    s = e.get("strategy", "?")
    no = e.get("signal_no") or 0
    head = f"<b>[{s}] #{no:03d}</b>"
    a = e.get("action")
    t = e.get("time", "")
    footer = "\n<i>\U0001F4CB Paper trading — not financial advice</i>"
    if a in ("open_long", "open_short"):
        d = "LONG \U0001F4C8" if e.get("direction") == "long" else "SHORT \U0001F4C9"
        return (f"\U0001F514 {head} New Signal — {d}\n"
                f"Entry <code>${e['entry_price']:,.2f}</code> · "
                f"Stop <code>${e['sl']:,.2f}</code> · "
                f"Target <code>${e['tp']:,.2f}</code> · "
                f"Size {e.get('size_mult', 1.0):.2f}x\n"
                f"\U0001F550 {t} · BTC 1h · F6 strategy race{footer}")
    if a == "close":
        r = {"tp": "\U0001F3AF Take-profit hit", "stop": "\U0001F6D1 Stopped out",
             "sl": "\U0001F6D1 Stopped out", "lock": "\U0001F512 Profit locked in",
             "time": "⏱ Time exit"}.get(e.get("reason"), str(e.get("reason")))
        rr = e.get("result_r") or 0.0
        pl = e.get("dollar_pl") or 0.0
        mark = "✅" if pl > 0 else "❌"
        return (f"{r} — {head} closed {mark}\n"
                f"Exit <code>${e.get('exit_price', 0):,.2f}</code> · "
                f"P/L <b>{rr:+.2f}R</b> (${pl:+,.2f})\n"
                f"\U0001F550 {t}{footer}")
    if a == "move_stop":
        return (f"\U0001F512 {head} Stop moved → <code>${e['sl']:,.2f}</code>"
                f" (locking {e.get('lock', '')})\n\U0001F550 {t}{footer}")
    if a == "pyramid_add":
        return (f"➕ {head} Pyramid add @ <code>${e.get('add_price', 0):,.2f}</code>"
                f" (+{e.get('add_size', 0)}x)\n\U0001F550 {t}{footer}")
    return f"{head} {a} · {t}"

def try_close_chart(e, token, chat_id):
    """close 事件: 生成蜡烛图战报 + 英文时间线 caption 发图 (与中文侧同标准)。
    任一环节失败返回 False, 调用方降级为纯文字。"""
    try:
        api_key = os.environ.get("COINGLASS_API_KEY")
        if not api_key:
            print("  [chart] no COINGLASS_API_KEY, fallback to text")
            return False
        code = e.get("strategy")
        no = e.get("signal_no") or 0
        state = json.load(open(f"state_{code}.json"))
        sig = state["signals"][no - 1]
        # 确认 state 里这笔确实是该次平仓 (防重开/错位)
        if sig.get("status") not in ("tp_hit", "sl_hit") or not sig.get("exit_ts"):
            return False
        if abs((sig.get("exit_price") or 0) - (e.get("exit_price") or -1)) >= 1:
            return False
        import signal_bot_race as sbr
        from trade_report import render_chart, build_caption_en
        from tg_notify import send_photo
        hours = int((time.time() - (sig["entry_ts"] - 24 * 3600)) // 3600) + 8
        bars = sbr.fetch_btc_1h_bars(api_key, min(hours, 990))
        pl = e.get("dollar_pl") or 0
        png = render_chart(code, no, sig, bars, pl)
        cap = build_caption_en(code, no, sig, bars, pl)
        return send_photo(png, cap, bot_token=token, chat_id=chat_id)
    except Exception as ex:
        print(f"  [chart] failed, fallback to text: {type(ex).__name__}: {ex}")
        return False


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TG_EN_CHAT_ID")
    if not token or not chat_id:
        print("[WARN] TELEGRAM_BOT_TOKEN / TG_EN_CHAT_ID missing, skip")
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
                ok = try_close_chart(e, token, chat_id)  # 图版战报优先
            if not ok:
                ok = post(token, chat_id, fmt(e))
        except Exception as ex:
            print(f"[FAIL] event {e['event_id']}: {type(ex).__name__}: {ex}")
            break
        if not ok:
            print(f"[FAIL] event {e['event_id']}: api not ok")
            break
        st["last_event_id"] = e["event_id"]
        print(f"[OK] relayed event {e['event_id']}")
        time.sleep(1)
    json.dump(st, open(STATE, "w"), indent=2)

if __name__ == "__main__":
    main()
