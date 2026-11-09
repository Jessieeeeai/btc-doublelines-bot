"""
颈线策略 · 马G "实盘口径观察马" (纸面, 非实盘指令)

和 A/D/E 的区别: 这匹马完全按 2026-11-09《实盘层最终审查报告》的最终配置和实盘记账口径跑。
  形态:   两根 1h 实体重叠 > 第二根实体 70%, L 不设下限 (野马形态)
  方向:   顺第二根; 颈线 = 两根实体最高(低)点
  两道门: 第二根收盘时  ① 止损距离 >= 价格 0.3%   ② 1h ATR14/价格 >= 近 30 天中位 x 1.6
  确认:   之后 3 根 1h 内价格突破颈线
  进场:   突破后 2 根内回踩到 颈线 - 0.2L 挂限价 (按 5 分钟真实路径判成交; 没回踩放弃)
  止损:   较长那根(含影线)极值外 0.2L
  出场:   跟踪止损, 距离 = 初始止损距离, 进场下一小时起每小时收盘只收紧; 无固定止盈
  仓位:   打到止损亏 $20, 名义封顶 $12,500; 本金按 $500/单 (杠杆 = 名义/500)
  记账:   每笔同时给 基准口径 (滑点 0.04% 来回 + 资金费 0.01%/8h) 和
          保守口径 (滑点 0.08% + 止损再滑 0.05% + 资金费); Lighter 手续费 0
  同一根 5m 里先到进场价又到止损 -> 按止损算; 出场当小时不再开新单; 不加仓不反手

独立文件、独立 state (state_N_G.json)、独立 workflow; 不碰 A/D/E/F6。
"""
import os, sys, json, time, statistics
import urllib.request, urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg_notify
from tg_notify import send_message

# G 照常发群 (不受 PAUSE_PUBLIC 影响), 并追加福利群
tg_notify.public_paused = lambda: False
EXTRA_BROADCAST_GROUPS = ["-1003953373413"]
_g = [x.strip() for x in (os.environ.get("TELEGRAM_GROUP_CHAT_ID") or "").split(",") if x.strip()]
os.environ["TELEGRAM_GROUP_CHAT_ID"] = ",".join(_g + [x for x in EXTRA_BROADCAST_GROUPS if x not in _g])

COINGLASS_BASE = "https://open-api-v4.coinglass.com"
CODE, NAME = "N-G", "实盘口径马G (两道门+回踩+跟踪)"
STATE_FILE = "state_N_G.json"
H = 3600

# ===== 策略参数 (与审查报告最终配置一致, 不要调) =====
RATIO = 0.7
PB, SB = 0.2, 0.2            # 回踩深度 / 止损外移 (单位 L)
WAIT, BREAK = 2, 3           # 突破后等回踩几根 / 形态后几根内要突破
GATE_SD, GATE_VOL = 0.003, 1.6
RISK_USD, NOTIONAL_CAP, PRINCIPAL_USD = 20.0, 12500.0, 500.0
# ===== 成本口径 =====
SLIP_BASE, SLIP_CONS, STOP_SLIP_CONS, FUND_8H, FEE = 0.0004, 0.0008, 0.0005, 0.0001, 0.0

PAPER_MARK = "\n🧪 <i>纸面验证 · 实盘记账口径 — 非实盘指令</i>"


# ===== 数据 =====

def _fetch(api_key, interval, n):
    end_ms = int(time.time() * 1000)
    sec = 300 if interval == "5m" else 3600
    params = {"exchange": "Binance", "symbol": "BTCUSDT", "interval": interval,
              "limit": 1000, "start_time": end_ms - (n + 5) * sec * 1000, "end_time": end_ms}
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
        bars.append({"ts": ts, "open": o, "high": h, "low": l, "close": c})
    bars.sort(key=lambda x: x["ts"])
    now = int(time.time())
    return [b for b in bars if b["ts"] + sec <= now]   # 只要已收盘的


def tstr(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M")


# ===== 形态 + 门 =====

def pat(b1, b2):
    lo1, hi1 = min(b1["open"], b1["close"]), max(b1["open"], b1["close"])
    lo2, hi2 = min(b2["open"], b2["close"]), max(b2["open"], b2["close"])
    if hi1 - lo1 <= 0 or hi2 - lo2 <= 0:
        return None
    lo, hi = max(lo1, lo2), min(hi1, hi2)
    L = hi - lo
    if L <= 0 or L <= RATIO * (hi2 - lo2):
        return None
    side = 1 if b2["close"] > b2["open"] else (-1 if b2["close"] < b2["open"] else 0)
    if side == 0:
        return None
    lb = b1 if (b1["high"] - b1["low"]) >= (b2["high"] - b2["low"]) else b2
    neck = max(hi1, hi2) if side == 1 else min(lo1, lo2)
    ext = lb["low"] if side == 1 else lb["high"]
    entry = neck - PB * L * side
    sl = ext - SB * L if side == 1 else ext + SB * L
    return {"L": L, "side": side, "neck": neck, "ext": ext, "entry": entry, "sl": sl,
            "sd_pct": abs(entry - sl) / entry, "sig_ts": b2["ts"],
            "h_from": b2["ts"] + H, "h_until": b2["ts"] + (1 + BREAK) * H}


def vol_ratio(HB, j):
    """第 j 根 1h 收盘时: ATR14/价格 ÷ 之前 720 根的中位数。数据不足返回 None。"""
    if j < 120:
        return None
    tr = []
    for i in range(1, j + 1):
        b, p = HB[i], HB[i - 1]
        tr.append(max(b["high"] - b["low"], abs(b["high"] - p["close"]), abs(b["low"] - p["close"])))
    # atrp[i] = SMA14(tr) / close  (i 从 14 起有值)
    atrp = {}
    for i in range(14, j + 1):
        atrp[i] = sum(tr[i - 14:i]) / 14 / HB[i]["close"]
    cur = atrp[j]
    hist = [atrp[i] for i in range(max(14, j - 720), j) if i in atrp]
    if len(hist) < 50:
        return None
    return cur / statistics.median(hist), cur


# ===== 成本 =====

def costs(notional, hold_sec, by_stop):
    fund = notional * FUND_8H * (hold_sec / 28800)
    base = notional * (SLIP_BASE + FEE) + fund
    cons = notional * (SLIP_CONS + FEE + (STOP_SLIP_CONS if by_stop else 0)) + fund
    return round(base, 2), round(cons, 2), round(fund, 2)


# ===== state =====

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"started": False, "last_5m_ts": 0, "hour_done_ts": 0, "active": [], "pend": None,
                "position": None, "trades": [], "seq": 0,
                "n_pat": 0, "n_gate_fail": 0, "n_no_break": 0, "n_no_pullback": 0}
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(st):
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, indent=2, ensure_ascii=False)


# ===== 消息 =====

def stats(st):
    tr = st["trades"]
    n = len(tr)
    nb = sum(t["net_base"] for t in tr); nc = sum(t["net_cons"] for t in tr)
    wins = sum(1 for t in tr if t["net_base"] > 0)
    return {"n": n, "wins": wins, "wr": wins / n if n else 0, "net_base": nb, "net_cons": nc,
            "gross": sum(t["gross"] for t in tr)}


def footer(st):
    s = stats(st)
    line = (f"\n━━━━━━━━━━━━━━━\n📊 <b>[{CODE}] 前向战绩</b> 已完成 {s['n']} 笔 · {s['wins']}胜{s['n']-s['wins']}败"
            f" (胜率 {s['wr']*100:.0f}%)"
            f"\n💰 毛利 ${s['gross']:+,.2f} → 基准口径净 <b>${s['net_base']:+,.2f}</b> ({s['net_base']/PRINCIPAL_USD*100:+.1f}%)"
            f" · 保守口径净 <b>${s['net_cons']:+,.2f}</b> ({s['net_cons']/PRINCIPAL_USD*100:+.1f}%)"
            f"\n💵 每单本金 ${PRINCIPAL_USD:,.0f} · 每单风险 ${RISK_USD:,.0f}")
    pos = st["position"]
    if pos:
        line += f"\n⏳ 持仓: {'📈多' if pos['d']==1 else '📉空'} @${pos['e']:,.2f} 止损 ${pos['sl']:,.2f}"
    elif st["pend"]:
        p = st["pend"]
        line += f"\n📌 挂单: {'📈多' if p['side']==1 else '📉空'} @${p['entry']:,.2f} (有效至 {tstr(p['wait_until'])} UTC)"
    return line + PAPER_MARK


def send(text):
    send_message(f"[{CODE}] {text}")
    time.sleep(0.4)


def fmt_pattern(s):
    return (f"👀 <b>形态成立 · 过两道门 — {NAME}</b>\n━━━━━━━━━━━━━━━\n"
            f"{'📈 看多' if s['side']==1 else '📉 看空'} · 颈线 <code>${s['neck']:,.2f}</code> · L=${s['L']:,.0f}\n"
            f"门① 止损距离 {s['sd_pct']*100:.2f}% (≥0.30%) ✅ · 门② 波动 {s['vr']:.2f}× 30天中位 (≥1.6) ✅\n"
            f"等待: {tstr(s['h_from'])}~{tstr(s['h_until'])} UTC 内突破颈线; 突破后 {WAIT} 根内回踩到 "
            f"<code>${s['entry']:,.2f}</code> 才进场")


def fmt_pend(p):
    n = notional_for(p["entry"], p["sl"])
    cb, cc, _ = costs(n, 9 * H, True)
    return (f"📌 <b>突破确认 · 挂回踩单 — {NAME}</b>\n━━━━━━━━━━━━━━━\n"
            f"{'📈 做多' if p['side']==1 else '📉 做空'} 限价 <code>${p['entry']:,.2f}</code> (颈线 {p['neck']:,.2f} − 0.2L)\n"
            f"🛑 止损 <code>${p['sl']:,.2f}</code> · 距离 {abs(p['entry']-p['sl'])/p['entry']*100:.2f}%\n"
            f"⚖️ 计划名义 ${n:,.0f} · 杠杆 {n/PRINCIPAL_USD:.1f}× · 本金 ${PRINCIPAL_USD:,.0f} · 打到止损亏 ${RISK_USD:,.0f}\n"
            f"💸 预计成本: 基准 ${cb:,.2f} / 保守 ${cc:,.2f} (按持仓 9h 估)\n"
            f"⏱ 突破于 {tstr(p['brk_ts'])} UTC · 挂单有效至 {tstr(p['wait_until'])} UTC, 没回踩就放弃")


def fmt_entry(pos, st):
    n = pos["n"]
    cb, cc, fund = costs(n, 9 * H, True)
    return (f"✅ <b>颈线单 #{pos['seq']:03d} 已成交 — {NAME}</b>\n━━━━━━━━━━━━━━━\n"
            f"方向: {'📈 做多' if pos['d']==1 else '📉 做空'} · 成交 <code>${pos['e']:,.2f}</code> ({tstr(pos['ts'])} UTC, 5m 路径)\n"
            f"🛑 止损 <code>${pos['sl']:,.2f}</code> · 距离 {pos['D0']/pos['e']*100:.2f}% · 打到亏 <b>${-RISK_USD:,.0f}</b> ({-RISK_USD/PRINCIPAL_USD*100:.1f}%)\n"
            f"🎯 止盈: 无固定 · 跟踪止损距离 ${pos['D0']:,.0f}, 下一小时起每小时收盘只收紧\n"
            f"⚖️ 名义 <b>${n:,.0f}</b> · 杠杆 <b>{n/PRINCIPAL_USD:.1f}×</b> · 本金 ${PRINCIPAL_USD:,.0f}\n"
            f"💸 成本 (Lighter 手续费 0):\n"
            f"  · 基准: 滑点 0.04% 来回 ${n*SLIP_BASE:,.2f} + 资金费 ≈ ${n*FUND_8H:,.2f}/8h → 9h 约 ${cb:,.2f}\n"
            f"  · 保守: 滑点 0.08% ${n*SLIP_CONS:,.2f} + 止损再滑 0.05% ${n*STOP_SLIP_CONS:,.2f} + 资金费 → 约 ${cc:,.2f}\n"
            f"  · 要回本至少要走 {cb/n*100:.3f}% (基准) / {cc/n*100:.3f}% (保守)"
            + footer(st))


def fmt_exit(t, st):
    icon = "🔒 跟踪止损" if t["trailed"] else "🔴 止损"
    if t["net_base"] > 0:
        icon = "🟢 " + ("跟踪止损获利" if t["trailed"] else "出场")
    return (f"{icon} <b>#{t['seq']:03d} 出场 — {NAME}</b>\n━━━━━━━━━━━━━━━\n"
            f"{'📈多' if t['d']==1 else '📉空'} @${t['e']:,.2f} → ${t['x']:,.2f} ({tstr(t['xts'])} UTC) · 持仓 {t['hold_h']:.1f}h\n"
            f"毛利 <b>${t['gross']:+,.2f}</b> ({t['gross']/PRINCIPAL_USD*100:+.2f}%)\n"
            f"💸 成本 基准 ${t['cost_base']:,.2f} (含资金费 ${t['fund']:,.2f}) / 保守 ${t['cost_cons']:,.2f}\n"
            f"净 基准 <b>${t['net_base']:+,.2f}</b> ({t['net_base']/PRINCIPAL_USD*100:+.2f}%) · "
            f"保守 <b>${t['net_cons']:+,.2f}</b> ({t['net_cons']/PRINCIPAL_USD*100:+.2f}%)"
            + footer(st))


# ===== 核心状态机 (与审查引擎 eng.run 同构) =====

def notional_for(entry, sl):
    dist = abs(entry - sl)
    return round(min(RISK_USD / (dist / entry), NOTIONAL_CAP), 0) if dist > 0 else 0.0


def close_pos(st, pos, px, ts, msgs):
    gross = (px - pos["e"]) * pos["d"] / pos["e"] * pos["n"]
    cb, cc, fund = costs(pos["n"], ts - pos["ts"], True)
    t = {"seq": pos["seq"], "d": pos["d"], "e": pos["e"], "x": round(px, 2), "ts": pos["ts"], "xts": ts,
         "n": pos["n"], "gross": round(gross, 2), "cost_base": cb, "cost_cons": cc, "fund": fund,
         "net_base": round(gross - cb, 2), "net_cons": round(gross - cc, 2),
         "hold_h": round((ts - pos["ts"]) / 3600, 1), "trailed": pos.get("trailed", False),
         "sl0": pos["sl0"], "D0": pos["D0"]}
    st["trades"].append(t)
    st["position"] = None
    st["active"] = []
    st["block_until"] = ts // H * H + H
    msgs.append(("exit", t))


def process_5m(st, b, msgs):
    ts = b["ts"]
    hour = ts // H * H
    st["active"] = [s for s in st["active"] if s["h_until"] > hour]
    pos = st["position"]
    if pos:
        d = pos["d"]
        if (d == 1 and b["low"] <= pos["sl"]) or (d == -1 and b["high"] >= pos["sl"]):
            px = pos["sl"]
            if (d == 1 and b["open"] < px) or (d == -1 and b["open"] > px):
                px = b["open"]
            close_pos(st, pos, px, ts, msgs)
        return
    p = st["pend"]
    if p:
        if ts >= p["wait_until"]:
            st["pend"] = None
            st["n_no_pullback"] += 1
            msgs.append(("pend_expired", p))
        elif ts > p["brk_ts"]:
            d, E, sl = p["side"], p["entry"], p["sl"]
            if (d == 1 and b["low"] <= E) or (d == -1 and b["high"] >= E):
                fill = min(E, b["open"]) if d == 1 else max(E, b["open"])
                st["pend"] = None
                dist = (fill - sl) * d
                if dist > 0:
                    st["seq"] += 1
                    pos = {"seq": st["seq"], "d": d, "e": round(fill, 2), "sl": round(sl, 2), "sl0": round(sl, 2),
                           "D0": round(dist, 2), "pk": round(fill, 2), "n": notional_for(fill, sl),
                           "ts": ts, "trailed": False, "be_notified": False, "neck": p["neck"], "L": p["L"]}
                    st["position"] = pos
                    msgs.append(("entry", dict(pos)))
                    if (d == 1 and b["low"] <= sl) or (d == -1 and b["high"] >= sl):
                        close_pos(st, pos, sl, ts, msgs)
        return
    if ts < st.get("block_until", 0):
        return
    for s in reversed(st["active"]):
        if not (s["h_from"] <= ts < s["h_until"]):
            continue
        d, N = s["side"], s["neck"]
        if (d == 1 and b["high"] > N) or (d == -1 and b["low"] < N):
            st["pend"] = {"side": d, "entry": round(s["entry"], 2), "sl": round(s["sl"], 2), "neck": N, "L": s["L"],
                          "brk_ts": ts, "wait_until": (ts // H + 1 + WAIT) * H, "sig_ts": s["sig_ts"]}
            st["active"] = []
            msgs.append(("pend", dict(st["pend"])))
            break


def hour_close(st, HB, idx, h, msgs):
    """第 h 小时的 1h K 线收盘后: 先跟踪止损, 再检测新形态。"""
    j = idx.get(h)
    pos = st["position"]
    if pos and j is not None and h > pos["ts"] // H * H:
        hb = HB[j]
        if pos["d"] == 1:
            pos["pk"] = max(pos["pk"], hb["high"]); ns = pos["pk"] - pos["D0"]
            if ns > pos["sl"]:
                pos["sl"] = round(ns, 2); pos["trailed"] = True
        else:
            pos["pk"] = min(pos["pk"], hb["low"]); ns = pos["pk"] + pos["D0"]
            if ns < pos["sl"]:
                pos["sl"] = round(ns, 2); pos["trailed"] = True
        crossed = pos["sl"] >= pos["e"] if pos["d"] == 1 else pos["sl"] <= pos["e"]
        if crossed and not pos.get("be_notified"):
            pos["be_notified"] = True
            msgs.append(("bemove", dict(pos)))
    if j is not None and j >= 1:
        s = pat(HB[j - 1], HB[j])
        if s:
            st["n_pat"] += 1
            vr = vol_ratio(HB, j)
            ok = s["sd_pct"] >= GATE_SD and vr is not None and vr[0] > GATE_VOL
            if not ok:
                st["n_gate_fail"] += 1
            elif st["position"] is None and st["pend"] is None:
                s["vr"] = round(vr[0], 2)
                st["active"].append(s)
                msgs.append(("pattern", dict(s)))
    st["hour_done_ts"] = h


def run(HB, M5, st, msgs):
    """HB: 已收盘 1h; M5: 已收盘 5m。推进 state, 返回消息列表。"""
    idx = {b["ts"]: i for i, b in enumerate(HB)}
    for b in M5:
        if b["ts"] <= st["last_5m_ts"]:
            continue
        hour = b["ts"] // H * H
        # 先把之前已经整小时收盘、还没做收盘任务的小时补上
        h = st["hour_done_ts"] + H
        while h < hour:
            if h in idx:
                hour_close(st, HB, idx, h, msgs)
            else:
                st["hour_done_ts"] = h
            h += H
        process_5m(st, b, msgs)
        st["last_5m_ts"] = b["ts"]
        if b["ts"] % H == H - 300 and hour in idx and hour > st["hour_done_ts"]:
            hour_close(st, HB, idx, hour, msgs)


def main():
    api_key = os.environ.get("COINGLASS_API_KEY")
    if not api_key:
        print("缺少 COINGLASS_API_KEY"); sys.exit(1)
    HB = _fetch(api_key, "1h", 1000)
    M5 = _fetch(api_key, "5m", 1000)
    if len(HB) < 200 or len(M5) < 24:
        print(f"K线不足: 1h {len(HB)} 5m {len(M5)}"); sys.exit(1)
    print(f"1h {len(HB)} 根 (最新 {tstr(HB[-1]['ts'])}), 5m {len(M5)} 根 (最新 {tstr(M5[-1]['ts'])})")
    st = load_state()
    if not st["started"]:
        st["started"] = True
        st["last_5m_ts"] = M5[-1]["ts"]
        st["hour_done_ts"] = M5[-1]["ts"] // H * H if M5[-1]["ts"] % H == H - 300 else M5[-1]["ts"] // H * H - H
        save_state(st)
        send(f"🤖 <b>{NAME} 已启动</b>\n━━━━━━━━━━━━━━━\n"
             f"标的: BTCUSDT 永续 · 1h 形态 · 5m 真实路径记账\n"
             f"规则: 野马形态 + 两道门 (止损≥0.3% · 波动≥1.6×30天中位) + 突破后回踩 颈线−0.2L 进 + 跟踪止损\n"
             f"仓位: 每单本金 ${PRINCIPAL_USD:,.0f} · 风险 ${RISK_USD:,.0f} · 名义≤${NOTIONAL_CAP:,.0f}\n"
             f"记账: 基准口径 (滑点0.04%+资金费) 与 保守口径 (滑点0.08%+止损再滑0.05%+资金费) 并列\n"
             f"当前 BTC: <code>${M5[-1]['close']:,.2f}</code>\n<i>等待形态...</i>" + PAPER_MARK)
        return
    msgs = []
    run(HB, M5, st, msgs)
    save_state(st)
    for kind, p in msgs[-10:]:
        try:
            if kind == "pattern":
                send(fmt_pattern(p))
            elif kind == "pend":
                send(fmt_pend(p))
            elif kind == "pend_expired":
                send(f"⌛ 挂单失效 — {NAME}\n{'📈多' if p['side']==1 else '📉空'} @${p['entry']:,.2f} 在 {WAIT} 根内没回踩到, 放弃" + PAPER_MARK)
            elif kind == "entry":
                send(fmt_entry(p, st))
            elif kind == "bemove":
                send(f"🔒 <b>#{p['seq']:03d} 已保本 — {NAME}</b>\n跟踪止损推到 <code>${p['sl']:,.2f}</code> (成交 ${p['e']:,.2f}), 此单最差打平扣成本" + footer(st))
            elif kind == "exit":
                send(fmt_exit(p, st))
        except Exception as e:
            print(f"消息失败 {kind}: {e}")
    s = stats(st)
    print(f"[{CODE}] ok: 形态 {st['n_pat']} 过门失败 {st['n_gate_fail']} 未回踩 {st['n_no_pullback']} 成交 {s['n']} 净基准 {s['net_base']:+.2f}")


if __name__ == "__main__":
    main()
