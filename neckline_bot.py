"""
重叠颈线策略 · 3马赛马信号机器人 (纸面验证)

马A "FINAL_R完全体":  跟踪止损出场 + 等风险仓位$40/单 (名义上限$100k)
马B "固定仓跟踪":     跟踪止损出场 + 固定$10,000名义     → A vs B 隔离仓位层
马C "固定TP保守版":   TP=3L/SL=1.5L 固定出场 + $10,000   → B vs C 隔离出场层

三匹马共享同一信号源: second模式 ratio=0.7, L>=0.1%价格, 突破缓冲0.25L,
形态确认后3根K线内有效, 串行单持仓 (与回测口径完全一致)。

⚠️ 全部输出为纸面验证, 非实盘指令。
与 F6 双线反战机器人完全独立: 不同文件、不同state、不同workflow。
"""
import os, sys, json, time
import urllib.request, urllib.parse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tg_notify import send_message
import neckline_feed

COINGLASS_BASE = "https://open-api-v4.coinglass.com"
N_BARS = 300

# ===== 策略参数 (与回测 FINAL_R 一致, 不要改动 — 改动即偏离已验证配置) =====
RATIO = 0.7           # 交集 > 0.7 x 第二根实体
MIN_L_PCT = 0.001     # L >= 0.1% 价格
BUFFER_L = 0.25       # 突破缓冲: 触发价 = 颈线 ± 0.25L
SL_MULT = 1.5         # 止损/跟踪距离 = 1.5L (从触发价起算)
TP_MULT = 3.0         # 马C固定止盈 = 3L
EXPIRE_BARS = 3       # 形态确认后3根内未触发作废
RISK_USD = 40.0       # 马A每单风险
NOTIONAL_CAP = 100000.0
NOTIONAL_FIXED = 10000.0

HORSES = [
    {"code": "N-A", "name": "FINAL_R完全体 (跟踪+等风险)", "state_file": "state_N_A.json",
     "exit": "trail", "sizing": "risk", "min_l": MIN_L_PCT},
    {"code": "N-B", "name": "固定仓跟踪 (跟踪+$10k)", "state_file": "state_N_B.json",
     "exit": "trail", "sizing": "fixed", "min_l": MIN_L_PCT},
    {"code": "N-C", "name": "固定TP保守版 (3L/1.5L+$10k)", "state_file": "state_N_C.json",
     "exit": "fixed", "sizing": "fixed", "min_l": MIN_L_PCT},
    # 野马: 原始P3+P5合体, 不带微型L门槛。63%回测利润来自止损距离<0.1%的微型单,
    # 纸面成交假设在那些单子上不可信 — 成绩仅供观察, 不作实盘决策依据。
    {"code": "N-D", "name": "野马 (原始合体·仅观察)", "state_file": "state_N_D.json",
     "exit": "trail", "sizing": "risk", "min_l": 0.0, "observe": True},
    # 白马: FINAL_R + 前置冲击 (重叠对前一根A为大实体, |A实体|>=2L)。
    # 第七轮T4: 回测719笔 wr59.8% 每笔$45.63 总+$32,809 — 质量王配置。
    {"code": "N-E", "name": "白马 (前置冲击+完全体)", "state_file": "state_N_E.json",
     "exit": "trail", "sizing": "risk", "min_l": MIN_L_PCT, "big_a": True},
]

PAPER_MARK = "\n🧪 <i>纸面验证 — 非实盘指令</i>"


# ===== 数据 =====

def fetch_btc_1h_bars(api_key, n=N_BARS):
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (n + 5) * 3600 * 1000
    params = {"exchange": "Binance", "symbol": "BTCUSDT", "interval": "1h",
              "limit": 1000, "start_time": start_ms, "end_time": end_ms}
    url = f"{COINGLASS_BASE}/api/futures/price/history?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"CG-API-KEY": api_key, "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = json.loads(resp.read().decode())
    items = raw.get("data") or raw.get("result") or []
    bars = []
    for it in items:
        if isinstance(it, dict):
            ts = int(it.get("time") or it.get("t") or it.get("timestamp"))
            o, h = float(it.get("open") or it.get("o")), float(it.get("high") or it.get("h"))
            l, c = float(it.get("low") or it.get("l")), float(it.get("close") or it.get("c"))
        else:
            ts, o, h, l, c = int(it[0]), float(it[1]), float(it[2]), float(it[3]), float(it[4])
        if ts > 1e12:
            ts //= 1000
        bars.append({"date": datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M"),
                     "ts": ts, "open": o, "high": h, "low": l, "close": c})
    bars.sort(key=lambda x: x["ts"])
    return bars


# ===== 形态检测 (与 neckline_signals.py 同口径, 内联以便自包含) =====

def pair_signal(b1, b2, min_l_pct=MIN_L_PCT):
    """检查相邻两根K线是否构成重叠形态 (second模式)。返回信号dict或None。"""
    lo1, hi1 = min(b1["open"], b1["close"]), max(b1["open"], b1["close"])
    lo2, hi2 = min(b2["open"], b2["close"]), max(b2["open"], b2["close"])
    h1, h2 = hi1 - lo1, hi2 - lo2
    if h1 <= 0 or h2 <= 0:
        return None
    ov_lo, ov_hi = max(lo1, lo2), min(hi1, hi2)
    L = ov_hi - ov_lo
    if L <= 0 or L <= RATIO * h2:            # second模式: 参照第二根实体
        return None
    if min_l_pct > 0 and L / b2["close"] < min_l_pct:  # 微型L门槛 (野马=0关闭)
        return None
    return {"signal_ts": b2["ts"], "signal_time": b2["date"] + " UTC",
            "overlap_lo": round(ov_lo, 2), "overlap_hi": round(ov_hi, 2),
            "L": round(L, 2),
            "trigger_up": round(ov_hi + BUFFER_L * L, 2),
            "trigger_dn": round(ov_lo - BUFFER_L * L, 2),
            "expire_ts": b2["ts"] + EXPIRE_BARS * 3600}  # 形态bar后第3根仍有效, 第4根起过期(与回测j<=index+3一致)


# ===== state =====

def load_state(path):
    if not os.path.exists(path):
        return {"started": False, "anchor_ts": None, "last_bar_ts": 0,
                "active": [], "forming": None, "position": None,
                "trades": [], "seq": 0, "n_skipped": 0, "n_expired": 0, "n_ambiguous": 0}
    with open(path) as f:
        return json.load(f)


def save_state(state, path):
    with open(path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def horse_notional(horse, level, L):
    if horse["sizing"] == "risk":
        sl_frac = (SL_MULT * L) / level
        if sl_frac > 0:
            return round(min(RISK_USD / sl_frac, NOTIONAL_CAP), 0)
    return NOTIONAL_FIXED


# ===== 统计 & 消息 =====

def stats(state):
    tr = state["trades"]
    n = len(tr)
    wins = sum(1 for t in tr if t["pnl_usd"] > 0)
    total = sum(t["pnl_usd"] for t in tr)
    return {"n": n, "wins": wins, "wr": wins / n if n else 0, "total": total}


def footer(horse, state):
    s = stats(state)
    pos = state["position"]
    line = (f"\n━━━━━━━━━━━━━━━\n📊 <b>[{horse['code']}] 前向战绩</b> "
            f"已完成 {s['n']} 笔 · {s['wins']}胜{s['n']-s['wins']}败 "
            f"(胜率 {s['wr']*100:.0f}%) · 累计 <b>${s['total']:+,.2f}</b>")
    if pos:
        line += f"\n⏳ 持仓: {'📈多' if pos['direction']=='long' else '📉空'} @${pos['entry']:,.0f}"
    if horse.get("observe"):
        line += "\n⚠️ <i>野马含微型L单, 纸面成交假设不可信, 成绩仅供观察</i>"
    return line + PAPER_MARK


def send(horse, text):
    send_message(f"[{horse['code']}] {text}")
    time.sleep(0.4)


def fmt_entry(horse, pos, state):
    tp_txt = (f"🎯 止盈: <code>${pos['tp']:,.2f}</code>" if pos["tp"] else
              f"🎯 止盈: 无固定TP · 跟踪止损 (峰值∓1.5L=${SL_MULT*pos['L']:,.0f})")
    risk_usd = pos["notional"] * (SL_MULT * pos["L"]) / pos["entry"]
    return (f"✅ <b>颈线单 #{pos['seq']:03d} 已入场 — {horse['name']}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"方向: {'📈 做多' if pos['direction']=='long' else '📉 做空'}\n"
            f"形态: 重叠K线 L=${pos['L']:,.0f} (颈线 {pos['neck_lo']:,.0f}~{pos['neck_hi']:,.0f})\n"
            f"入场: <code>${pos['entry']:,.2f}</code> ({pos['entry_time']})\n"
            f"🛑 止损: <code>${pos['sl']:,.2f}</code> · 输约 <b>${-risk_usd:,.0f}</b>\n"
            f"{tp_txt}\n"
            f"⚖️ 仓位: <b>${pos['notional']:,.0f}</b> 名义"
            + footer(horse, state))


def fmt_exit(horse, t, state):
    icon = {"TP": "🟢 止盈", "SL": "🔴 止损", "TRAIL": "🔒 跟踪止损"}.get(t["exit_reason"], t["exit_reason"])
    return (f"{icon} <b>#{t['seq']:03d} 出场 — {horse['name']}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{'📈多' if t['direction']=='long' else '📉空'} "
            f"@${t['entry']:,.2f} → ${t['exit']:,.2f} ({t['exit_time']})\n"
            f"结果: <b>${t['pnl_usd']:+,.2f}</b> · 持仓 {t['bars_held']} 根K线"
            + footer(horse, state))


# ===== 单马状态机 (逐收盘bar推进, 与回测循环同构) =====

def process_horse(horse, bars):
    state = load_state(horse["state_file"])
    closed = bars[:-1]  # 最后一根可能未收盘, 不处理

    if not state["started"]:
        state["started"] = True
        state["anchor_ts"] = closed[-1]["ts"]
        state["last_bar_ts"] = closed[-1]["ts"]
        save_state(state, horse["state_file"])
        send(horse, (f"🤖 <b>{horse['name']} 已启动</b>\n"
                     f"━━━━━━━━━━━━━━━\n"
                     f"标的: BTCUSDT 1h · 重叠颈线突破\n"
                     f"当前 BTC: <code>${bars[-1]['close']:,.2f}</code>\n"
                     f"<i>等待重叠形态...</i>" + PAPER_MARK))
        return

    msgs = []
    for j in range(len(closed)):
        bar = closed[j]
        if bar["ts"] <= state["last_bar_ts"]:
            continue

        # 1) 上一根形成的形态进入活跃窗口 (持仓中则跳过, 与回测口径一致)
        if state["forming"] is not None:
            if state["position"] is None:
                state["active"].append(state["forming"])
            else:
                state["n_skipped"] += 1
            state["forming"] = None

        # 2) 持仓管理: 先用旧止损判出场, 再更新跟踪线 (保守, 与回测一致)
        pos = state["position"]
        exited = False
        if pos is not None:
            d, sl, tp = pos["direction"], pos["sl"], pos["tp"]
            exit_price = exit_reason = None
            if d == "long":
                if bar["low"] <= sl:
                    exit_price, exit_reason = sl, ("TRAIL" if pos.get("trailed") else "SL")
                elif tp and bar["high"] >= tp:
                    exit_price, exit_reason = tp, "TP"
            else:
                if bar["high"] >= sl:
                    exit_price, exit_reason = sl, ("TRAIL" if pos.get("trailed") else "SL")
                elif tp and bar["low"] <= tp:
                    exit_price, exit_reason = tp, "TP"
            if exit_price is not None:
                gross = (exit_price - pos["entry"]) if d == "long" else (pos["entry"] - exit_price)
                pnl = gross / pos["entry"] * pos["notional"]
                t = {"seq": pos["seq"], "direction": d, "entry": pos["entry"],
                     "entry_time": pos["entry_time"], "entry_ts": pos["entry_ts"],
                     "exit": round(exit_price, 2),
                     "exit_time": bar["date"] + " UTC", "exit_ts": bar["ts"],
                     "exit_reason": exit_reason,
                     "pnl_usd": round(pnl, 2), "notional": pos["notional"],
                     "L": pos["L"], "level": pos["level"], "tp": pos.get("tp"),
                     "neck_lo": pos.get("neck_lo"), "neck_hi": pos.get("neck_hi"),
                     "bars_held": max(1, (bar["ts"] - pos["entry_ts"]) // 3600)}
                state["trades"].append(t)
                state["position"] = None
                state["active"] = []
                msgs.append(("exit", t))
                neckline_feed.emit(horse["code"], "close", t,
                                   reason=exit_reason.lower(), exit_price=t["exit"],
                                   pnl_usd=t["pnl_usd"])
                exited = True
            elif horse["exit"] == "trail":
                fav = bar["high"] if d == "long" else bar["low"]
                pos["peak"] = max(pos["peak"], fav) if d == "long" else min(pos["peak"], fav)
                dist = SL_MULT * pos["L"]
                new_sl = pos["peak"] - dist if d == "long" else pos["peak"] + dist
                if (d == "long" and new_sl > pos["sl"]) or (d == "short" and new_sl < pos["sl"]):
                    pos["sl"] = round(new_sl, 2)
                    pos["trailed"] = True
                    # 跟踪线首次越过入场价 = 该单已保本, 通知一次 + 记feed
                    crossed = pos["sl"] >= pos["entry"] if d == "long" else pos["sl"] <= pos["entry"]
                    if crossed and not pos.get("be_notified"):
                        pos["be_notified"] = True
                        msgs.append(("bemove", {"seq": pos["seq"], "sl": pos["sl"],
                                                "entry": pos["entry"], "direction": d}))
                        neckline_feed.emit(horse["code"], "move_stop", pos, sl=pos["sl"])

        # 3) 空仓: 清过期 + 找触发 (最新形态优先); 出场当根不开新仓 (与回测一致)
        if state["position"] is None and not exited:
            still = []
            for s in state["active"]:
                if bar["ts"] > s["expire_ts"]:
                    state["n_expired"] += 1
                else:
                    still.append(s)
            state["active"] = still
            for s in reversed(state["active"]):
                up, dn = s["trigger_up"], s["trigger_dn"]
                o = bar["open"]
                gap_up, gap_dn = o > up, o < dn
                hit_up, hit_dn = bar["high"] >= up, bar["low"] <= dn
                if gap_up:
                    d, entry, level = "long", o, up
                elif gap_dn:
                    d, entry, level = "short", o, dn
                elif hit_up and hit_dn:
                    state["n_ambiguous"] += 1
                    state["active"].remove(s)
                    continue
                elif hit_up:
                    d, entry, level = "long", up, up
                elif hit_dn:
                    d, entry, level = "short", dn, dn
                else:
                    continue
                L = s["L"]
                notional = horse_notional(horse, level, L)
                state["seq"] += 1
                pos = {"seq": state["seq"], "direction": d, "entry": round(entry, 2),
                       "entry_ts": bar["ts"], "entry_time": bar["date"] + " UTC",
                       "level": level, "L": L,
                       "neck_lo": s["overlap_lo"], "neck_hi": s["overlap_hi"],
                       "sl": round(level - SL_MULT * L, 2) if d == "long" else round(level + SL_MULT * L, 2),
                       "tp": (round(level + TP_MULT * L, 2) if d == "long" else round(level - TP_MULT * L, 2))
                             if horse["exit"] == "fixed" else None,
                       "peak": round(entry, 2), "trailed": False,
                       "notional": notional}
                state["position"] = pos
                state["active"] = []
                msgs.append(("entry", pos))
                neckline_feed.emit(horse["code"],
                                   "open_long" if d == "long" else "open_short", pos)
                break

        # 4) 本根K线与上一根是否构成新形态 (下一根起可触发)
        if j >= 1:
            sig = pair_signal(closed[j - 1], closed[j], horse.get("min_l", MIN_L_PCT))
            # 白马: 前置冲击条件 — 重叠对前一根A必须是大实体 (|A实体| >= 2L)
            if sig is not None and horse.get("big_a"):
                if j < 2 or abs(closed[j - 2]["close"] - closed[j - 2]["open"]) < 2 * sig["L"]:
                    sig = None
            state["forming"] = sig

        state["last_bar_ts"] = bar["ts"]

    # 先存state再发消息 (发送失败下轮也不会重算; 消息带去重标记)
    save_state(state, horse["state_file"])
    for kind, payload in msgs[-8:]:   # 单轮最多补发8条, 防止久停后刷屏
        if kind == "entry":
            send(horse, fmt_entry(horse, payload, state))
        elif kind == "bemove":
            send(horse, (f"🔒 <b>#{payload['seq']:03d} 已保本 — {horse['name']}</b>\n"
                         f"跟踪止损推到 <code>${payload['sl']:,.2f}</code>"
                         f" (入场 ${payload['entry']:,.2f}), 此单最差打平"
                         + footer(horse, state)))
        else:
            send(horse, fmt_exit(horse, payload, state))
            # 关单图文战报 (matplotlib缺失或失败自动降级, 不影响主流程)
            try:
                import neckline_report
                neckline_report.send_trade_report(horse["code"], horse["name"],
                                                  payload, closed,
                                                  footer=footer(horse, state),
                                                  sl_mult=SL_MULT)
            except Exception as e:
                print(f"  [{horse['code']}] 战报失败: {e}")


def main():
    api_key = os.environ.get("COINGLASS_API_KEY")
    if not api_key:
        print("缺少 COINGLASS_API_KEY")
        sys.exit(1)
    bars = fetch_btc_1h_bars(api_key)
    if len(bars) < 50:
        print(f"K线不足: {len(bars)}")
        sys.exit(1)
    print(f"拉到 {len(bars)} 根, 最新 {bars[-1]['date']} UTC close={bars[-1]['close']}")
    for horse in HORSES:
        try:
            process_horse(horse, bars)
            print(f"[{horse['code']}] ok")
        except Exception as e:
            print(f"[{horse['code']}] ERROR: {e}")
    # 信号源落盘 (独立文件, 不碰 F6 的 signals_feed.json)
    states = [(h["code"], load_state(h["state_file"])) for h in HORSES]
    added = neckline_feed.flush(states)
    print(f"feed: +{added} events -> {neckline_feed.FEED_FILE}")
    print("done")


if __name__ == "__main__":
    main()
