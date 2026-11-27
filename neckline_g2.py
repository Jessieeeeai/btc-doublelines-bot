"""
两线反转 · 马G 第 2 版 (纸面, 非实盘指令) — 2026-11-28 起

第 1 版 (11-09 ~ 11-27) 用的是"两根实体重叠 > 70%"的旧定义, 和教程视频讲的不是一个形态, 已封存 (state_N_G.json)。
第 2 版按用户教程视频《裸K交易之兩線反轉形態》的定义重写, 回测见项目文档《第22轮》。

形态 (1h, K0 = 形态前一根, K1/K2 = 两线; 典型价 = (高+低+收)/3):
  1. 两根颜色相反; 阴接阳看涨, 阳接阴看跌
  2. 突变: K1 典型价低于 K0 最低 (看涨) / 高于 K0 最高 (看跌)
  3. 双线都强势: 两根实体都 > 全长 50%
  4. 大面积重合: 两根的典型价互相落在对方高低范围内
两匹马 (同一信号, 只有进场不同):
  N-G1 突破马: 形态后 3 根内, 价格突破两线最高点 (看跌: 最低点) → 按突破价进
  N-G2 回踩马: 形态后 3 根内突破颈线 (两根实体最高点), 之后 2 根内回踩到 颈线-0.2L 挂限价进; 没回踩放弃
止损: 较长那根 (含影线) 的极值外 0.2L (L = 两根实体重叠高度)        止盈: 2 倍风险, 不跟踪
仓位: 每单打到止损亏 $20, 名义封顶 $12,500, 本金 $500/单; 每匹马每个币同时 1 单; 出场当小时不开新单
币种: BTC ETH SOL BNB XRP DOGE ADA (OKX 永续 5 分钟 K 线, 1h 由 5m 聚合; 按 5m 真实路径判成交)
记账: 基准口径 (滑点 0.04% 来回 + 资金费 0.01%/8h) 与 保守口径 (滑点 0.08% + 止损再滑 0.05% + 资金费) 并列
同一根 5m 里先进场又到止损 → 按止损算; 同一根里止损和止盈都碰到 → 按止损算

独立文件 / 独立 state (state_N_G_v2.json) / 独立 workflow, 不碰其它马。消息格式按《赛马机器人_消息SOP》。
"""
import os, sys, json, time, io
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg_notify
from tg_notify import send_message

tg_notify.public_paused = lambda: False     # 照常发群
EXTRA_BROADCAST_GROUPS = ["-1003953373413"]
_g = [x.strip() for x in (os.environ.get("TELEGRAM_GROUP_CHAT_ID") or "").split(",") if x.strip()]
os.environ["TELEGRAM_GROUP_CHAT_ID"] = ",".join(_g + [x for x in EXTRA_BROADCAST_GROUPS if x not in _g])

STATE_FILE = "state_N_G_v2.json"
H = 3600
SYMS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA"]
HORSES = [{"code": "N-G1", "name": "两线反转·突破马", "entry": "brk"},
          {"code": "N-G2", "name": "两线反转·回踩马", "entry": "pb"}]
HMAP = {h["code"]: h for h in HORSES}

# ===== 策略参数 (与第22轮回测一致, 不要调) =====
BODY, PB, SB, WAIT, BREAK, TP_R = 0.5, 0.2, 0.2, 2, 3, 2.0
RISK_USD, NOTIONAL_CAP, PRINCIPAL_USD = 20.0, 12500.0, 500.0
ACCOUNT_USD = PRINCIPAL_USD * len(SYMS)
SLIP_BASE, SLIP_CONS, STOP_SLIP_CONS, FUND_8H = 0.0004, 0.0008, 0.0005, 0.0001
PAPER_MARK = "\n🧪 <i>纸面验证 · 实盘记账口径 — 非实盘指令</i>"


# ===== 数据 =====

def _okx_page(sym, after_ms=None):
    url = f"https://www.okx.com/api/v5/market/candles?instId={sym}-USDT-SWAP&bar=5m&limit=300"
    if after_ms:
        url += f"&after={after_ms}"
    req = urllib.request.Request(url, headers={"accept": "application/json", "User-Agent": "twoline-g/2.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = json.loads(resp.read().decode())
    bars = []
    for it in raw.get("data") or []:
        if len(it) >= 9 and str(it[8]) != "1":
            continue
        bars.append({"ts": int(it[0]) // 1000, "open": float(it[1]), "high": float(it[2]),
                     "low": float(it[3]), "close": float(it[4])})
    return bars


def fetch_5m(sym, since_ts=0):
    """OKX 永续 5m, 只取已确认收盘的 K 线, 按时间升序。
    一页 300 根 (25 小时)。如果上次处理到的时间比这一页还早 (机器人停过), 往前多翻几页补上, 最多 5 页 (约 5 天)。"""
    bars = _okx_page(sym)
    try:
        pages = 1
        while since_ts and bars and min(b["ts"] for b in bars) > since_ts - 3 * H and pages < 5:
            more = _okx_page(sym, min(b["ts"] for b in bars) * 1000)
            if not more:
                break
            bars += more; pages += 1; time.sleep(0.15)
    except Exception as e:
        print(f"  [{sym}] 补历史失败 (只用最近一页): {e}")
    uniq = {b["ts"]: b for b in bars}
    return [uniq[k] for k in sorted(uniq)]


def hours_of(m5):
    """把 5m 聚合成 1h; 只保留 12 根齐全的小时。返回 {小时ts: bar}。"""
    tmp = {}
    for b in m5:
        k = b["ts"] // H * H
        x = tmp.get(k)
        if x is None:
            tmp[k] = {"ts": k, "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"], "n": 1, "first": b["ts"]}
        else:
            x["high"] = max(x["high"], b["high"]); x["low"] = min(x["low"], b["low"]); x["close"] = b["close"]; x["n"] += 1
    return {k: v for k, v in tmp.items() if v["n"] == 12 and v["first"] == k}


def tstr(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M")


def px(p):
    return f"${p:,.1f}" if p >= 1000 else (f"${p:,.3f}" if p >= 1 else f"${p:.5f}")


# ===== 形态 =====

def _tp(b):
    return (b["high"] + b["low"] + b["close"]) / 3


def pat2(k0, k1, k2):
    up1, up2 = k1["close"] > k1["open"], k2["close"] > k2["open"]
    if k1["close"] == k1["open"] or k2["close"] == k2["open"] or up1 == up2:
        return None
    side = 1 if up2 else -1
    r1, r2 = k1["high"] - k1["low"], k2["high"] - k2["low"]
    if r1 <= 0 or r2 <= 0:
        return None
    if not ((_tp(k1) < k0["low"]) if side == 1 else (_tp(k1) > k0["high"])):
        return None
    if not (abs(k1["close"] - k1["open"]) / r1 > BODY and abs(k2["close"] - k2["open"]) / r2 > BODY):
        return None
    if not ((k2["low"] <= _tp(k1) <= k2["high"]) and (k1["low"] <= _tp(k2) <= k1["high"])):
        return None
    lo1, hi1 = min(k1["open"], k1["close"]), max(k1["open"], k1["close"])
    lo2, hi2 = min(k2["open"], k2["close"]), max(k2["open"], k2["close"])
    L = min(hi1, hi2) - max(lo1, lo2)
    if L <= 0:
        return None
    lb = k1 if r1 >= r2 else k2
    return {"side": side, "L": L, "hi": max(k1["high"], k2["high"]), "lo": min(k1["low"], k2["low"]),
            "neck": max(hi1, hi2) if side == 1 else min(lo1, lo2), "ext": lb["low"] if side == 1 else lb["high"],
            "sig_ts": k2["ts"], "h_from": k2["ts"] + H, "h_until": k2["ts"] + (1 + BREAK) * H}


# ===== 成本 =====

def costs(n, hold_sec, by_stop):
    fund = n * FUND_8H * (hold_sec / 28800)
    return round(n * SLIP_BASE + fund, 2), round(n * (SLIP_CONS + (STOP_SLIP_CONS if by_stop else 0)) + fund, 2), round(fund, 2)


# ===== state =====

def blank_slot():
    return {"active": [], "pend": None, "pos": None, "block": 0}


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"version": 2, "started": False, "syms": {}, "horses": {h["code"]: {"seq": 0, "trades": []} for h in HORSES},
                "n_pat": 0, "notices": []}
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(st):
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, indent=1, ensure_ascii=False)


# ===== 状态机 (与回测引擎 eng2.run 同构) =====

def _open(code, st, sym, d, price, sl, ts, s):
    dist = (price - sl) * d
    if dist <= 0:
        return None
    n = round(min(RISK_USD / (dist / price), NOTIONAL_CAP), 4)
    st["horses"][code]["seq"] += 1
    return {"seq": st["horses"][code]["seq"], "sym": sym, "d": d, "e": price, "sl": sl, "tp": price + TP_R * dist * d,
            "D0": dist, "n": n, "ts": ts, "sig_ts": s["sig_ts"], "hi": s["hi"], "lo": s["lo"], "neck": s["neck"], "L": s["L"]}


def _close(code, st, slot, pos, price, ts, why, msgs):
    gross = (price - pos["e"]) * pos["d"] / pos["e"] * pos["n"]
    cb, cc, fund = costs(pos["n"], ts - pos["ts"], why == "sl")
    t = dict(pos); t.update({"x": price, "xts": ts, "why": why, "gross": round(gross, 2), "cost_base": cb, "cost_cons": cc, "fund": fund,
                             "net_base": round(gross - cb, 2), "net_cons": round(gross - cc, 2), "hold_h": round((ts - pos["ts"]) / 3600, 1)})
    st["horses"][code]["trades"].append(t)
    slot["pos"] = None; slot["active"] = []; slot["block"] = ts // H * H + H
    msgs.append(("exit", code, t))


def step_5m(code, st, sym, slot, b, msgs):
    entry_mode = HMAP[code]["entry"]
    ts = b["ts"]; hour = ts // H * H
    slot["active"] = [s for s in slot["active"] if s["h_until"] > hour]
    pos = slot["pos"]
    if pos:
        d = pos["d"]
        if (d == 1 and b["low"] <= pos["sl"]) or (d == -1 and b["high"] >= pos["sl"]):
            p = pos["sl"]
            if (d == 1 and b["open"] < p) or (d == -1 and b["open"] > p):
                p = b["open"]
            _close(code, st, slot, pos, p, ts, "sl", msgs); return
        if (d == 1 and b["high"] >= pos["tp"]) or (d == -1 and b["low"] <= pos["tp"]):
            p = pos["tp"]
            if (d == 1 and b["open"] > p) or (d == -1 and b["open"] < p):
                p = b["open"]
            _close(code, st, slot, pos, p, ts, "tp", msgs); return
        return
    pend = slot["pend"]
    if pend:
        if ts >= pend["wait_until"]:
            slot["pend"] = None; pend = None
        elif ts > pend["brk_ts"]:
            d, E, sl = pend["side"], pend["entry"], pend["sl"]
            if (d == 1 and b["low"] <= E) or (d == -1 and b["high"] >= E):
                fill = min(E, b["open"]) if d == 1 else max(E, b["open"])
                slot["pend"] = None
                pos = _open(code, st, sym, d, fill, sl, ts, pend["s"])
                if pos:
                    slot["pos"] = pos; msgs.append(("entry", code, dict(pos)))
                    if (d == 1 and b["low"] <= sl) or (d == -1 and b["high"] >= sl):
                        _close(code, st, slot, pos, sl, ts, "sl", msgs)
                return
        if pend:
            return
    if ts < slot["block"]:
        return
    for s in reversed(slot["active"]):
        if not (s["h_from"] <= ts < s["h_until"]):
            continue
        d, L = s["side"], s["L"]
        trig = (s["hi"] if d == 1 else s["lo"]) if entry_mode == "brk" else s["neck"]
        if (d == 1 and b["high"] > trig) or (d == -1 and b["low"] < trig):
            sl = s["ext"] - SB * L * d
            if entry_mode == "brk":
                fill = max(trig, b["open"]) if d == 1 else min(trig, b["open"])
                pos = _open(code, st, sym, d, fill, sl, ts, s)
                slot["active"] = []
                if pos:
                    slot["pos"] = pos; msgs.append(("entry", code, dict(pos)))
                    if (d == 1 and b["low"] <= sl) or (d == -1 and b["high"] >= sl):
                        _close(code, st, slot, pos, sl, ts, "sl", msgs)
            else:
                slot["pend"] = {"side": d, "entry": trig - PB * L * d, "sl": sl, "brk_ts": ts,
                                "wait_until": (ts // H + 1 + WAIT) * H, "s": s}
                slot["active"] = []
            break


def advance(st, sym, m5, msgs):
    """用最新一批已收盘 5m 推进某个币的两匹马。"""
    ss = st["syms"].setdefault(sym, {"last_5m_ts": 0, "slots": {h["code"]: blank_slot() for h in HORSES}})
    hrs = hours_of(m5)
    if ss["last_5m_ts"] == 0:           # 首次: 从当前时刻开始, 不回补
        ss["last_5m_ts"] = m5[-1]["ts"]
        return
    new = [b for b in m5 if b["ts"] > ss["last_5m_ts"]]
    if new and new[0]["ts"] - ss["last_5m_ts"] > 300:
        print(f"  [{sym}] ⚠️ 数据断档: {tstr(ss['last_5m_ts'])} → {tstr(new[0]['ts'])}")
    for b in new:
        for h in HORSES:
            step_5m(h["code"], st, sym, ss["slots"][h["code"]], b, msgs)
        ss["last_5m_ts"] = b["ts"]
        if b["ts"] % H == H - 300:      # 这根是整点前最后一根 → 该小时收盘, 检测新形态
            hr = b["ts"] // H * H
            k0, k1, k2 = hrs.get(hr - 2 * H), hrs.get(hr - H), hrs.get(hr)
            if k0 and k1 and k2:
                s = pat2(k0, k1, k2)
                if s:
                    st["n_pat"] += 1
                    for h in HORSES:
                        slot = ss["slots"][h["code"]]
                        if slot["pos"] is None and slot["pend"] is None:
                            slot["active"].append(dict(s))


# ===== 消息 (SOP) =====

def hstats(st, code):
    tr = st["horses"][code]["trades"]; n = len(tr)
    wins = sum(1 for t in tr if t["net_base"] > 0)
    return {"n": n, "wins": wins, "wr": wins / n if n else 0, "base": sum(t["net_base"] for t in tr),
            "cons": sum(t["net_cons"] for t in tr), "gross": sum(t["gross"] for t in tr)}


def footer(st, code):
    s = hstats(st, code)
    line = (f"\n━━━━━━━━━━━━━━━\n📊 <b>[{code}] 前向战绩</b> 已完成 {s['n']} 笔 · {s['wins']}胜{s['n']-s['wins']}败 "
            f"(胜率 {s['wr']*100:.0f}%) · 累计 <b>${s['base']:+,.2f}</b> (<b>{s['base']/ACCOUNT_USD*100:+.1f}%</b>)"
            f"\n💵 每单本金 ${PRINCIPAL_USD:,.0f} · 单均 {(s['base']/s['n'] if s['n'] else 0)/PRINCIPAL_USD*100:+.2f}% · 账户 ${ACCOUNT_USD:,.0f} ({len(SYMS)} 币)"
            f"\n🧮 保守口径累计 ${s['cons']:+,.2f} · 毛利 ${s['gross']:+,.2f}")
    held = []
    for sym in SYMS:
        p = (st["syms"].get(sym) or {}).get("slots", {}).get(code, {}).get("pos")
        if p:
            held.append(f"{sym} {'📈多' if p['d']==1 else '📉空'} @{px(p['e'])}")
    if held:
        line += "\n⏳ 持仓: " + " · ".join(held)
    return line + PAPER_MARK


def send(code, text):
    send_message(f"[{code}] {text}")
    time.sleep(0.4)


def fmt_entry(st, code, p):
    name = HMAP[code]["name"]; n = p["n"]; d = p["d"]
    cb, cc, _ = costs(n, 6 * H, True)
    how = ("突破两线" + ("最高点" if d == 1 else "最低点")) if HMAP[code]["entry"] == "brk" else "突破颈线后回踩 颈线∓0.2L 限价成交"
    return (f"✅ <b>两线反转单 #{p['seq']:03d} 已入场 — {name}</b>\n━━━━━━━━━━━━━━━\n"
            f"币种: <b>{p['sym']}</b>\n"
            f"方向: {'📈 做多' if d == 1 else '📉 做空'}\n"
            f"形态: 两线反转 {tstr(p['sig_ts'] - H)}~{tstr(p['sig_ts'])} UTC (两线区间 {px(p['lo'])}~{px(p['hi'])})\n"
            f"入场: <code>{px(p['e'])}</code> ({tstr(p['ts'])} UTC · {how})\n"
            f"🛑 止损: <code>{px(p['sl'])}</code> · 距离 {p['D0']/p['e']*100:.2f}% · 输约 <b>${-RISK_USD:,.0f}</b> ({-RISK_USD/PRINCIPAL_USD*100:.1f}%)\n"
            f"🎯 止盈: <code>{px(p['tp'])}</code> · 2 倍风险 · 赚约 <b>${RISK_USD*TP_R:+,.0f}</b> ({RISK_USD*TP_R/PRINCIPAL_USD*100:+.1f}%)\n"
            f"⚖️ 仓位: <b>${n:,.0f}</b> 名义 · 杠杆 {n/PRINCIPAL_USD:.1f}× · 本金 ${PRINCIPAL_USD:,.0f}\n"
            f"💸 成本: 基准约 ${cb:,.2f} (滑点 0.04% + 资金费) / 保守约 ${cc:,.2f} (滑点 0.08% + 止损再滑 0.05% + 资金费)"
            + footer(st, code))


def fmt_exit(st, code, t):
    name = HMAP[code]["name"]
    icon = "🟢 止盈" if t["why"] == "tp" else "🔴 止损"
    return (f"{icon} <b>#{t['seq']:03d} 出场 — {name}</b>\n━━━━━━━━━━━━━━━\n"
            f"币种: <b>{t['sym']}</b>\n"
            f"{'📈多' if t['d'] == 1 else '📉空'} @{px(t['e'])} → {px(t['x'])} ({tstr(t['xts'])} UTC)\n"
            f"结果: <b>${t['net_base']:+,.2f}</b> ({t['net_base']/PRINCIPAL_USD*100:+.2f}%) · 持仓 {t['hold_h']:.1f} 小时\n"
            f"💸 毛利 ${t['gross']:+,.2f} · 成本 基准 ${t['cost_base']:,.2f} / 保守 ${t['cost_cons']:,.2f} · 保守口径净 ${t['net_cons']:+,.2f}"
            + footer(st, code))


def send_report(st, code, t, hrs):
    """关单复盘图 (SOP 第 6 条)。失败自动降级为纯文字, 不影响主流程。"""
    name = HMAP[code]["name"]
    cap = (f"🧾 <b>[{code}] #{t['seq']:03d} 关单复盘 — {name}</b>\n"
           f"{t['sym']} · {'📈多' if t['d'] == 1 else '📉空'} · 名义 ${t['n']:,.0f}\n"
           f"形态区间 {px(t['lo'])}~{px(t['hi'])} · 进场 {px(t['e'])}\n"
           f"出场原因: {'止盈 (2 倍风险)' if t['why'] == 'tp' else '止损'} · 出场 {px(t['x'])}\n"
           f"💰 <b>${t['net_base']:+,.2f}</b> ({t['net_base']/PRINCIPAL_USD*100:+.2f}%) · 持仓 {t['hold_h']:.1f} 小时"
           + footer(st, code))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        lo_ts, hi_ts = t["sig_ts"] - 9 * H, t["xts"] // H * H + 3 * H
        bars = [hrs[k] for k in sorted(hrs) if lo_ts <= k <= hi_ts]
        if len(bars) < 4:
            raise RuntimeError("K线不足")
        fig, ax = plt.subplots(figsize=(9, 5), dpi=110)
        idx = {b["ts"]: i for i, b in enumerate(bars)}
        for i, b in enumerate(bars):
            up = b["close"] >= b["open"]; col = "#1D9E75" if up else "#D85A30"
            ax.plot([i, i], [b["low"], b["high"]], color=col, lw=1)
            ax.add_patch(Rectangle((i - 0.3, min(b["open"], b["close"])), 0.6, max(abs(b["close"] - b["open"]), 1e-9), color=col))
        i1 = idx.get(t["sig_ts"] - H); i2 = idx.get(t["sig_ts"])
        if i1 is not None and i2 is not None:
            ax.add_patch(Rectangle((i1 - 0.5, t["lo"]), i2 - i1 + 1, t["hi"] - t["lo"], fill=False, ec="#185FA5", lw=1.2, ls="--"))
            ax.text(i1 - 0.4, t["hi"], " two-line reversal", color="#185FA5", fontsize=8, va="bottom")
        n = len(bars)                    # 出场那个小时通常还没收盘, 不在 bars 里 → 画在最后一根右边
        xe = idx.get(t["ts"] // H * H, n) + (t["ts"] % H) / H - 0.5
        xx = idx.get(t["xts"] // H * H, n) + (t["xts"] % H) / H - 0.5
        ax.hlines(t["e"], xe, n + 0.5, color="#185FA5", lw=1); ax.text(n + 0.55, t["e"], "entry", color="#185FA5", fontsize=8, va="center")
        ax.hlines(t["sl"], xe, n + 0.5, color="#A32D2D", lw=1, ls="--"); ax.text(n + 0.55, t["sl"], "stop", color="#A32D2D", fontsize=8, va="center")
        ax.hlines(t["tp"], xe, n + 0.5, color="#0F6E56", lw=1, ls="--"); ax.text(n + 0.55, t["tp"], "TP 2R", color="#0F6E56", fontsize=8, va="center")
        ax.scatter([xe], [t["e"]], color="#185FA5", zorder=5, s=40, marker="^" if t["d"] == 1 else "v")
        ax.scatter([xx], [t["x"]], color="#0F6E56" if t["why"] == "tp" else "#A32D2D", zorder=5, s=50, marker="x")
        ax.set_xlim(-1, n + 3)
        ticks = list(range(0, n, max(1, n // 8)))
        ax.set_xticks(ticks); ax.set_xticklabels([tstr(bars[i]["ts"])[6:] for i in ticks], fontsize=8)
        ax.set_title(f"[{code}] #{t['seq']:03d} {t['sym']} {'LONG' if t['d'] == 1 else 'SHORT'}  "
                     f"{'TP' if t['why'] == 'tp' else 'STOP'}  net ${t['net_base']:+.2f}  (1h, UTC, paper)", fontsize=10)
        ax.grid(alpha=0.2)
        buf = io.BytesIO(); fig.tight_layout(); fig.savefig(buf, format="png"); plt.close(fig)
        if not tg_notify.send_photo(buf.getvalue(), caption=cap):
            raise RuntimeError("sendPhoto 失败")
    except Exception as e:
        print(f"  [{code}] 复盘图失败, 降级文字: {e}")
        send_message(cap)
    time.sleep(0.4)


def main():
    st = load_state()
    first = not st["started"]
    msgs, hrs_by_sym, prices = [], {}, {}
    for sym in SYMS:
        try:
            m5 = fetch_5m(sym, (st["syms"].get(sym) or {}).get("last_5m_ts", 0))
            if len(m5) < 40:
                print(f"[{sym}] K线不足 {len(m5)}"); continue
            hrs_by_sym[sym] = hours_of(m5); prices[sym] = m5[-1]["close"]
            advance(st, sym, m5, msgs)
            print(f"[{sym}] ok 最新 {tstr(m5[-1]['ts'])} close={m5[-1]['close']}")
        except Exception as e:
            print(f"[{sym}] ERROR: {e}")
    if first:
        if not prices:
            print("首次运行没拿到任何行情, 不启动"); sys.exit(1)
        st["started"] = True
    save_state(st)
    if first:
        for h in HORSES:
            how = ("形态后 3 根内, 价格突破两线最高点 (看跌: 最低点) 就进" if h["entry"] == "brk"
                   else "形态后 3 根内突破颈线, 再等 2 根内回踩到 颈线∓0.2L 挂单进; 没回踩放弃")
            send(h["code"], (f"🤖 <b>{h['name']} 已启动 (马G 第 2 版)</b>\n━━━━━━━━━━━━━━━\n"
                             f"形态改按教程视频的两线反转定义: 两根颜色相反 · 突变 (第一根典型价越过前一根的高/低点) · "
                             f"两根实体都过半 · 两根典型价互相包含\n"
                             f"进场: {how}\n"
                             f"止损: 较长那根的极值外 0.2L · 止盈: 2 倍风险\n"
                             f"币种: {' '.join(SYMS)} (1h 形态, 5 分钟真实路径记账)\n"
                             f"仓位: 每单本金 ${PRINCIPAL_USD:,.0f} · 风险 ${RISK_USD:,.0f} · 账户 ${ACCOUNT_USD:,.0f}\n"
                             f"旧版马G (11-09~11-27, 旧形态定义, 只做 BTC) 已封存: 25 笔 8 胜 17 败 · 净 $-84.34 (-16.9%) · 保守口径 $-138.83; 这里从 0 开始\n"
                             f"<i>等待形态...</i>" + PAPER_MARK))
        return
    for kind, code, p in msgs[-16:]:
        try:
            if kind == "entry":
                send(code, fmt_entry(st, code, p))
            else:
                send(code, fmt_exit(st, code, p))
                send_report(st, code, p, hrs_by_sym.get(p["sym"], {}))
        except Exception as e:
            print(f"消息失败 {kind} {code}: {e}")
    for h in HORSES:
        s = hstats(st, h["code"])
        print(f"[{h['code']}] 已完成 {s['n']} 笔 基准净 {s['base']:+.2f} 保守净 {s['cons']:+.2f}")
    print(f"累计形态 {st['n_pat']}")


if __name__ == "__main__":
    main()
