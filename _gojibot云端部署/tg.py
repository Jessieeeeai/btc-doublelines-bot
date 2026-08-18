#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GojiBot-R Telegram 推送（播报样式对齐 F6 机器人）
配置优先级：环境变量 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID → gojibot/tg_config.json
测试：python3 tg.py test
"""
import html as html_module
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def _cfg():
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    cid = os.environ.get("TELEGRAM_CHAT_ID")
    p = os.path.join(HERE, "tg_config.json")
    if (not tok or not cid) and os.path.exists(p):
        c = json.load(open(p))
        tok = tok or c.get("bot_token")
        cid = cid or c.get("chat_id")
    return tok, cid


def _esc(s):
    return html_module.escape(str(s), quote=False)


def send(text, parse_mode="HTML"):
    tok, cid = _cfg()
    if not tok or not cid:
        print(f"[TG WARN] 未配置 token/chat_id，消息转 stdout:\n{text}\n")
        return False
    payload = json.dumps({"chat_id": cid, "text": text, "parse_mode": parse_mode,
                          "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                                 data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = json.loads(r.read().decode()).get("ok", False)
            if not ok:
                print("[TG ERROR] api returned not ok")
            return ok
    except Exception as e:
        print(f"[TG FAIL] {type(e).__name__}: {e}")
        return False


# ============ 消息模板（对齐 F6 样式，HTML） ============

BRAND = "大漂亮资金流秘籍"


def msg_open(no, strat, sym, direction, entry, sl, tp, lev, cond_desc):
    d = "📉 做空" if direction == "SHORT" else "📈 做多"
    side = "Short" if direction == "SHORT" else "Long"
    sl_pct = abs(sl - entry) / entry * 100
    tp_pct = abs(tp - entry) / entry * 100
    return (
        f"💅 <b>{BRAND}</b>\n"
        f"🔔 <b>新信号 #{no:03d}</b> — {_esc(strat)}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"品种: <b>{_esc(sym)}</b>\n"
        f"方向: {d} ({side})\n"
        f"触发: {_esc(cond_desc)}\n\n"
        f"📍 <b>入场</b>: <code>${entry:,.2f}</code> (信号K线收盘市价)\n"
        f"🛑 <b>止损</b>: <code>${sl:,.2f}</code> ({sl_pct:.2f}%, L01结构位)\n"
        f"🎯 <b>止盈</b>: <code>${tp:,.2f}</code> ({tp_pct:.2f}%, 1.5R单目标)\n\n"
        f"⚙️ 仓位: 名义杠杆 <b>{lev:.2f}x</b>（C层: min(风险预算/止损距离, 0.6%/ATR, 5x)）\n"
        f"⏱ 最长持仓 72h，超时强平\n\n"
        f"<i>📋 纸面验证模式 — 非实盘指令</i>"
    )


def msg_close(no, strat, sym, reason, exit_price, pnl_pct, r_mult, hold_h, stats):
    head = {"tp": "🎯 <b>止盈触发", "stop": "🛑 <b>止损触发", "time": "⏱ <b>超时平仓"}[reason]
    r_txt = f"{r_mult:+.2f}R" if r_mult is not None else "—"
    return (
        f"💅 <b>{BRAND}</b>\n"
        f"{head} #{no:03d}</b> — {_esc(strat)} {_esc(sym)}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"出场: <code>${exit_price:,.2f}</code>\n"
        f"盈亏: <b>{r_txt}</b>（净 {pnl_pct:+.2f}%）{'✅' if pnl_pct > 0 else '❌'}\n"
        f"持仓: {hold_h:.1f} 小时\n\n"
        f"📊 战绩: {stats['wins']}胜 {stats['losses']}败 / "
        f"胜率 {stats['wr']*100:.1f}% / 累计 <b>{stats['total_r']:+.2f}R</b>（{stats['total_pct']:+.2f}%）\n\n"
        f"<i>📋 纸面验证 vs 回测预期: 胜率 {stats['expect_wr']}% / 均R {stats['expect_r']}</i>"
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        ok1 = send("【演示】" + msg_open(
            0, "S10·阻力衰竭做空", "BTC", "SHORT", 59961.45, 60789.12, 58720.33, 1.85,
            "距阻力1.38% · CVD24h -495 · FR +0.0067% · MA7下方"))
        ok2 = send("【演示】" + msg_close(
            0, "S10·阻力衰竭做空", "BTC", "tp", 58720.33, 1.93, 1.5, 14.0,
            {"wins": 1, "losses": 0, "wr": 1.0, "total_r": 1.5, "total_pct": 1.93,
             "expect_wr": "55-62", "expect_r": "+0.29R"}))
        print(f"开单卡: {'✓' if ok1 else '✗'}  平仓卡: {'✓' if ok2 else '✗'}")
    elif len(sys.argv) > 1 and sys.argv[1] == "test":
        ok = send(f"💅 <b>{BRAND}</b>\n━━━━━━━━━━━━━━━\n✅ TG 通道打通\n"
                  f"S10·阻力衰竭做空（BTC）与 S20·恐慌衰竭做多（BTC/ETH）信号将从此推送。\n"
                  f"<i>📋 纸面验证模式 — 未过实盘红线前不构成交易指令</i>")
        print("发送成功" if ok else "发送失败（检查 tg_config.json）")
