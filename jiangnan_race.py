"""
江南4马 · 四根K线结构赛马 (纸面, 非实盘指令) — 2026-11-12 第 12-14 轮确认

共同信号 (日线定方向, 1h 进场, 7 个币各跑各的; 日线 = UTC 0 点开, 即北京时间早 8 点):
  K1/K2:  昨天(K2)的最高价 > 前天(K1)的最高价, 但收盘收回 K1 最高价之下 → 今天(K3)看空 (做多镜像: 破 K1 最低后收回)
  K3 内:  价格先冲到今天开盘价上方 (进影线区); 任何一根 1h 收盘站上 K2 腰线 (K2 最高最低的正中间) 当天作废
  改派信号: 最近一串 1h 阳线的起点开盘价被 1h 收盘跌破 → 下一根 5m 开盘价做空 (每天只取第一个)
  止损:   K2 最高点外 0.03%; 每单打到止损亏 $40; 最晚拿到 K4 (明天) 收盘平仓
四匹马只在"做不做"和"怎么出"上不同 (都要求 顺日线20均: 进场价在前 20 根日线收盘均价下方才空 / 上方才多):
  JN1 顺势马    顺日线20均                      跟踪止损 (浮盈到 1R 后, 止损跟在最低点上方 1R)
  JN2 大势马    顺日线20均 + 顺 BTC 大势          3R 止盈
  JN3 工作日马  顺日线20均 + 只在周一到周五进场      跟踪止损
  JN4 精选马    顺日线20均 + 顺 BTC 大势 + 工作日   3R 止盈
  顺 BTC 大势 = BTC 1h 收盘在自己 200 均线(EMA)上方只做多, 下方只做空; 工作日按美东时间算
记账: 5m 真实路径, 同一根里止损止盈都碰到按止损; 基准口径 (滑点 0.04% + 资金费 0.01%/8h) 与
      保守口径 (滑点 0.08% + 止损再滑 0.05% + 资金费) 并列。每匹马账户 $7,000 (7 币 x $1,000)。
参数与回测 (research/round_ict/k4.py + run28.py) 一致, 不要调。state: state_JN.json; 订阅源: jiangnan_feed.json。
"""
import os, sys, json, time
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STATE_FILE, FEED_FILE = "state_JN.json", "jiangnan_feed.json"
SYMS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA"]
HORSES = {"JN1": "顺势马", "JN2": "大势马", "JN3": "工作日马", "JN4": "精选马"}
CFG = {"JN1": dict(btc=False, wd=False, trail=True), "JN2": dict(btc=True, wd=False, trail=False),
       "JN3": dict(btc=False, wd=True, trail=True), "JN4": dict(btc=True, wd=True, trail=False)}
RULE = {"JN1": "顺日线20均 · 跟踪止损", "JN2": "顺日线20均+顺BTC · 3R", "JN3": "顺日线20均+工作日 · 跟踪止损", "JN4": "顺日线20均+顺BTC+工作日 · 3R"}
lab = lambda c: f"{c} {HORSES[c]}"
H, D = 3600, 86400
RR, BUF, SMA_N = 3.0, 0.0003, 20
RISK_USD, NOTIONAL_CAP, PRINCIPAL_USD = 40.0, 25000.0, 1000.0
ACCOUNT_USD = PRINCIPAL_USD * len(SYMS)
SLIP_BASE, SLIP_CONS, STOP_SLIP_CONS, FUND_8H = 0.0004, 0.0008, 0.0005, 0.0001
PAPER_MARK = "\n🧪 <i>纸面验证 · 实盘记账口径 — 非实盘指令</i>"


# ===== 行情 (OKX 永续公共接口, 只取已收盘) =====

def fetch_okx(sym, bar, pages=1):
    bars, after = {}, None
    for _ in range(pages):
        url = f"https://www.okx.com/api/v5/market/candles?instId={sym}-USDT-SWAP&bar={bar}&limit=300" + (f"&after={after}" if after else "")
        req = urllib.request.Request(url, headers={"accept": "application/json", "User-Agent": "jiangnan-race/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode()).get("data") or []
        if not data:
            break
        for it in data:
            if len(it) >= 9 and str(it[8]) != "1":
                continue
            bars[int(it[0]) // 1000] = {"ts": int(it[0]) // 1000, "open": float(it[1]), "high": float(it[2]),
                                        "low": float(it[3]), "close": float(it[4])}
        after = data[-1][0]
        time.sleep(0.15)
    return [bars[k] for k in sorted(bars)]


def tstr(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M")


def is_weekday(ts):
    return datetime.fromtimestamp(ts, tz=ZoneInfo("America/New_York")).weekday() < 5


def fp(x):
    if x >= 1000: return f"{x:,.1f}"
    if x >= 10: return f"{x:,.2f}"
    if x >= 1: return f"{x:,.4f}"
    return f"{x:.5f}"


def usd(x, nd=0):
    return f"{'-' if x < 0 else '+'}${abs(x):,.{nd}f}"


def pct(x, base=ACCOUNT_USD):
    return f"{x / base * 100:+.2f}%"


# ===== 信号 =====

def _day(HB, idx, t0):
    return [HB[idx[t]] for t in range(t0, t0 + D, H) if t in idx]


def k_signal(HB, idx, h):
    """第 h 根 1h 刚收盘 (h = 它的开盘时间)。今天是 K3 → 返回 dict(side, sl, ...) 或 None。
    与 research/round_ict/k4.py g_k4(cisd='latest', hold=2) + 止损放 K2 极值 同构。"""
    d0 = h // D * D
    i = (h - d0) // H
    if i > 22:                                    # 当天最后一根 1h 不出信号
        return None
    k1, k2 = _day(HB, idx, d0 - 2 * D), _day(HB, idx, d0 - D)
    if len(k1) < 3 or len(k2) < 3:
        return None
    h1, l1 = max(b["high"] for b in k1), min(b["low"] for b in k1)
    h2, l2, c2 = max(b["high"] for b in k2), min(b["low"] for b in k2), k2[-1]["close"]
    bear, bull = (h2 > h1 and c2 < h1), (l2 < l1 and c2 > l1)
    if bear == bull or h2 - l2 <= 0:
        return None
    side = -1 if bear else 1
    eq = (h2 + l2) / 2
    today = [HB[idx[t]] for t in range(d0, h + H, H) if t in idx]
    if len(today) != i + 1:
        return None
    o0, lvl, run_ts, prev, viol, ext = today[0]["open"], None, None, False, False, None
    for q, b in enumerate(today):
        up = (b["close"] > b["open"]) if side == -1 else (b["close"] < b["open"])
        cis = False
        if up:
            if not prev:
                lvl, run_ts = b["open"], b["ts"]
        elif lvl is not None and ((b["close"] < lvl) if side == -1 else (b["close"] > lvl)):
            cis, broke, broke_ts = True, lvl, run_ts
            lvl = None
        prev = up
        if side == -1:
            ext = b["high"] if ext is None else max(ext, b["high"])
        else:
            ext = b["low"] if ext is None else min(ext, b["low"])
        viol = viol or ((b["close"] > eq) if side == -1 else (b["close"] < eq))
        if cis:
            if viol:
                return None                       # 有 1h 收盘越过腰线 → 当天作废
            if (side == -1 and ext <= o0) or (side == 1 and ext >= o0):
                continue                          # 还没冲进影线区, 等下一个改派信号
            if q != i:
                return None                       # 今天的信号已经在更早的一根出过了
            closes = []
            for t in range(d0 - SMA_N * D, d0, D):
                dd = _day(HB, idx, t)
                if not dd:
                    return None
                closes.append(dd[-1]["close"])
            return {"side": side, "sl": h2 * (1 + BUF) if side == -1 else l2 * (1 - BUF), "x_ts": d0 + 2 * D - 300,
                    "sma": sum(closes) / SMA_N, "k1": h1 if side == -1 else l1, "k2": h2 if side == -1 else l2, "eq": eq,
                    "k3ext": ext, "lvl": broke, "run_ts": broke_ts}
    return None


class Feats:
    """BTC 大势。只用 <= h 的已收盘 1h K线。"""
    def __init__(self, HBS):
        self.HBS = HBS
        self.idx = {s: {b["ts"]: i for i, b in enumerate(hb)} for s, hb in HBS.items()}
        self.cache = {}

    def btc(self, h):
        if h in self.cache:
            return self.cache[h]
        out = 0
        hb, j = self.HBS.get("BTC"), self.idx.get("BTC", {}).get(h)
        if hb and j is not None and j >= 150:
            a, num, den, w = 2.0 / 201.0, 0.0, 0.0, 1.0
            for i in range(j, max(-1, j - 900), -1):     # EMA200, 与 pandas ewm(span=200) 同式
                num += w * hb[i]["close"]; den += w; w *= (1 - a)
            ema = num / den
            out = 1 if hb[j]["close"] > ema else (-1 if hb[j]["close"] < ema else 0)
        self.cache[h] = out
        return out


def eligible(code, d, px, ts, p):
    """这匹马做不做 → (bool, 不做的原因)。在进场那根 5m 上判断。"""
    c = CFG[code]
    if not (px - p["sma"]) * d > 0:
        return False, "逆日线20均"
    if c["btc"] and p["btc"] != d:
        return False, "逆BTC大势"
    if c["wd"] and not is_weekday(ts):
        return False, "周末"
    return True, ""


def costs(notional, hold_sec, by_stop):
    fund = notional * FUND_8H * (hold_sec / 28800)
    return (round(notional * SLIP_BASE + fund, 2),
            round(notional * (SLIP_CONS + (STOP_SLIP_CONS if by_stop else 0)) + fund, 2), round(fund, 2))


# ===== state =====

def new_sym():
    return {"last_5m_ts": 0, "hour_done_ts": 0, "pend": None, "pos": {}}


def new_state():
    return {"started": False, "syms": {}, "trades": {c: [] for c in HORSES}, "seq": {c: 0 for c in HORSES}, "n_sig": 0}


def load_state():
    if not os.path.exists(STATE_FILE):
        return new_state()
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(st):
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, indent=1, ensure_ascii=False)


# ===== 状态机 =====

def close_pos(st, ss, sym, code, px, ts, why, msgs):
    pos = ss["pos"].pop(code)
    gross = (px - pos["e"]) * pos["d"] / pos["e"] * pos["n"]
    cb, cc, fund = costs(pos["n"], ts - pos["ts"], why == "sl")
    t = {"seq": pos["seq"], "code": code, "sym": sym, "d": pos["d"], "e": pos["e"], "x": px, "ts": pos["ts"], "xts": ts,
         "n": pos["n"], "why": why, "gross": round(gross, 2), "cost_base": cb, "cost_cons": cc, "fund": fund,
         "net_base": round(gross - cb, 2), "net_cons": round(gross - cc, 2),
         "hold_h": round((ts - pos["ts"]) / 3600, 1), "sl": pos["sl"], "sl0": pos["sl0"], "tp": pos["tp"]}
    st["trades"][code].append(t)
    msgs.append(("exit", t))


def process_5m(st, ss, sym, b, msgs):
    ts = b["ts"]
    p = ss["pend"]
    fresh = set()
    if p and ts >= p["from_ts"]:
        ss["pend"] = None
        px, d, sl = b["open"], p["side"], p["sl"]
        dist = (px - sl) * d
        if dist > 0 and ts < p["from_ts"] + H and ts < p["x_ts"]:    # 开盘已在止损外 / 数据断档超 1 小时 → 放弃
            opened, skipped = [], {}
            for code in HORSES:
                if code in ss["pos"]:
                    skipped[code] = "已有持仓"; continue
                ok, why = eligible(code, d, px, ts, p)
                if not ok:
                    skipped[code] = why; continue
                tr = CFG[code]["trail"]
                st["seq"][code] += 1
                ss["pos"][code] = {"seq": st["seq"][code], "d": d, "e": px, "sl": sl, "sl0": sl,
                                   "tp": None if tr else px + d * RR * dist, "dist": dist, "trail": tr, "armed": False,
                                   "n": round(min(RISK_USD / (dist / px), NOTIONAL_CAP), 0), "ts": ts, "x_ts": p["x_ts"], "pk": px}
                opened.append(code); fresh.add(code)
            if opened:
                msgs.append(("entry", {"sym": sym, "d": d, "e": px, "sl": sl, "ts": ts, "dist": dist, "horses": opened,
                                       "skipped": skipped, "pos": {c: dict(ss["pos"][c]) for c in opened}, "k": p}))
    for code in list(ss["pos"]):
        pos = ss["pos"][code]; d = pos["d"]; fr = code in fresh
        if pos["trail"] and pos["armed"]:             # 跟踪止损: 用上一根为止的最高(低)点, 只紧不松
            ns = pos["pk"] - d * pos["dist"]
            if (ns - pos["sl"]) * d > 0:
                pos["sl"] = ns
                if not pos.get("be") and (ns - pos["e"]) * d >= 0:
                    pos["be"] = True
                    msgs.append(("bemove", {"code": code, "sym": sym, "seq": pos["seq"], "d": d, "e": pos["e"], "sl": ns, "ts": ts, "n": pos["n"]}))
        hit_sl = b["low"] <= pos["sl"] if d == 1 else b["high"] >= pos["sl"]
        hit_tp = pos["tp"] is not None and (b["high"] >= pos["tp"] if d == 1 else b["low"] <= pos["tp"])
        if hit_sl:
            px = pos["sl"]
            if not fr and ((d == 1 and b["open"] < px) or (d == -1 and b["open"] > px)):
                px = b["open"]
            close_pos(st, ss, sym, code, px, ts, "sl", msgs)
        elif hit_tp:
            close_pos(st, ss, sym, code, pos["tp"], ts, "tp", msgs)
        elif ts >= pos["x_ts"]:
            close_pos(st, ss, sym, code, b["close"], ts, "time", msgs)
        else:
            pos["pk"] = max(pos["pk"], b["high"]) if d == 1 else min(pos["pk"], b["low"])
            if pos["trail"] and not pos["armed"] and (b["high"] >= pos["e"] + pos["dist"] if d == 1 else b["low"] <= pos["e"] - pos["dist"]):
                pos["armed"] = True


def hour_close(st, ss, sym, HB, idx, h, feats):
    if h in idx:
        s = k_signal(HB, idx, h)
        if s:
            st["n_sig"] += 1
            s.update(from_ts=h + H, btc=feats.btc(h))
            ss["pend"] = s
    ss["hour_done_ts"] = h


def run(HB, M5, st, sym, msgs, feats):
    ss = st["syms"].setdefault(sym, new_sym())
    idx = feats.idx[sym]
    for b in M5:
        if b["ts"] <= ss["last_5m_ts"]:
            continue
        hour = b["ts"] // H * H
        h = ss["hour_done_ts"] + H
        while h < hour:
            if h in idx: hour_close(st, ss, sym, HB, idx, h, feats)
            else: ss["hour_done_ts"] = h
            h += H
        process_5m(st, ss, sym, b, msgs)
        ss["last_5m_ts"] = b["ts"]
        if b["ts"] % H == H - 300 and hour in idx and hour > ss["hour_done_ts"]:
            hour_close(st, ss, sym, HB, idx, hour, feats)


# ===== 订阅源 (机器可读, 与 breakout_feed.json 同规范) =====

def feed_flush(st, msgs):
    try:
        feed = {"schema": 1, "paper": True, "events": [], "next_event_id": 1}
        if os.path.exists(FEED_FILE):
            with open(FEED_FILE) as f:
                feed = json.load(f)
        seen = {e["dedup"] for e in feed["events"]}
        r = lambda x: None if x is None else float(f"{x:.8g}")
        def ev(code, sym, seq, action, ts, d, e, sl, tp, n, tag, **extra):
            dd = f"{code}-{seq:03d}:{tag}"
            if dd in seen:
                return
            seen.add(dd)
            x = {"event_id": feed["next_event_id"], "ts": ts, "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                 "strategy": code, "symbol": f"{sym}USDT", "signal_no": seq, "pos_id": f"{code}-{seq:03d}", "paper": True,
                 "action": action, "direction": "long" if d == 1 else "short", "entry_price": r(e), "sl": r(sl), "tp": r(tp),
                 "notional_usd": n, "risk_usd": RISK_USD, "dedup": dd}
            x.update(extra); feed["events"].append(x); feed["next_event_id"] += 1
        for kind, p in msgs:
            if kind == "entry":
                for c in p["horses"]:
                    pos = p["pos"][c]
                    ev(c, p["sym"], pos["seq"], "open_long" if p["d"] == 1 else "open_short", p["ts"], p["d"], p["e"], p["sl"], pos["tp"], pos["n"], "open")
            elif kind == "bemove":
                ev(p["code"], p["sym"], p["seq"], "move_stop", p["ts"], p["d"], p["e"], p["sl"], None, p["n"], f"stop:{r(p['sl'])}")
            elif kind == "exit":
                ev(p["code"], p["sym"], p["seq"], "close", p["xts"], p["d"], p["e"], p["sl"], p["tp"], p["n"], "close",
                   reason="trail" if (p["why"] == "sl" and p["sl"] != p["sl0"]) else p["why"], exit_price=r(p["x"]),
                   pnl_usd=p["net_base"], pnl_pct=round(p["net_base"] / PRINCIPAL_USD * 100, 2))
        feed["events"] = feed["events"][-1000:]
        feed["open_positions"] = [{"strategy": c, "symbol": f"{s}USDT", "signal_no": pos["seq"], "pos_id": f"{c}-{pos['seq']:03d}", "paper": True,
                                   "direction": "long" if pos["d"] == 1 else "short", "entry_price": pos["e"], "sl": pos["sl"], "tp": pos["tp"],
                                   "notional_usd": pos["n"]} for s, ss in st["syms"].items() for c, pos in ss["pos"].items()]
        feed["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(FEED_FILE, "w") as f:
            json.dump(feed, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"  [feed] 失败: {e}")


# ===== 消息 =====

def board(st):
    rows = []
    for code in HORSES:
        tr = st["trades"][code]; n = len(tr); w = sum(1 for t in tr if t["net_base"] > 0)
        nb = sum(t["net_base"] for t in tr); nc = sum(t["net_cons"] for t in tr)
        op = sum(1 for v in st["syms"].values() if code in v["pos"])
        rows.append(f"{lab(code)}: {n}笔 {w}胜 · 净 <b>{usd(nb, 0)} ({pct(nb)})</b> · 保守 {usd(nc, 0)} ({pct(nc)}) · 持仓{op}")
    return ("\n━━━━━━━━━━━━━━━\n📊 <b>江南4马 前向战绩</b> (每匹账户 $7,000 · 每单风险 $40)\n" + "\n".join(rows) + PAPER_MARK)


def fmt_entry(p, st):
    d = p["d"]; n = next(iter(p["pos"].values()))["n"]; k = p["k"]; hl = "高" if d == -1 else "低"
    lines = []
    for c in p["horses"]:
        pos = p["pos"][c]
        tgt = (f"止盈 <code>${fp(pos['tp'])}</code> (3R, 赚 ${RISK_USD*RR:,.0f} = 本金 {RISK_USD*RR/PRINCIPAL_USD*100:.0f}%)" if pos["tp"]
               else f"不设止盈 · 浮盈到 1R (<code>${fp(p['e'] + d * p['dist'])}</code>) 后跟踪止损")
        lines.append(f"✅ {lab(c)} #{pos['seq']:03d}: {tgt}")
    for c, why in p["skipped"].items():
        lines.append(f"➖ {lab(c)}: 不做 ({why})")
    return (f"🏮 <b>{p['sym']} {'📈 做多' if d==1 else '📉 做空'} — 四根K线: K2 扫前{hl}收回 → K3 改派信号</b>\n━━━━━━━━━━━━━━━\n"
            f"K1 最{hl} <code>${fp(k['k1'])}</code> · K2 最{hl} <code>${fp(k['k2'])}</code> · K2 腰线 <code>${fp(k['eq'])}</code>\n"
            f"进场 <code>${fp(p['e'])}</code> ({tstr(p['ts'])} UTC) · 1h 收盘{'跌破' if d==-1 else '站上'} <code>${fp(k['lvl'])}</code>\n"
            f"🛑 止损 <code>${fp(p['sl'])}</code> (K2 最{hl}点外) · 距离 {p['dist']/p['e']*100:.2f}% · 打到亏 ${RISK_USD:,.0f} (本金 {RISK_USD/PRINCIPAL_USD*100:.0f}%)\n"
            f"⚖️ 名义 ${n:,.0f} · 杠杆 {n/PRINCIPAL_USD:.1f}× (每币本金 ${PRINCIPAL_USD:,.0f}) · 最晚 {tstr(k['x_ts'] + 300)} UTC (K4 收盘) 平仓\n"
            + "\n".join(lines) + board(st))


def fmt_exit(ts_, st):
    t0 = ts_[0]
    icon = {"tp": "🟢 止盈", "sl": "🔴 止损" if t0["sl"] == t0["sl0"] else "🔒 跟踪止损", "time": "⏱ K4 收盘平仓"}[t0["why"]]
    lines = [f"{lab(t['code'])} #{t['seq']:03d}: 净 <b>{usd(t['net_base'], 2)} ({pct(t['net_base'], PRINCIPAL_USD)})</b>"
             f" · 保守 {usd(t['net_cons'], 2)} ({pct(t['net_cons'], PRINCIPAL_USD)})" for t in ts_]
    return (f"{icon} <b>{t0['sym']} {'多' if t0['d']==1 else '空'}单出场</b>\n━━━━━━━━━━━━━━━\n"
            f"${fp(t0['e'])} → ${fp(t0['x'])} ({tstr(t0['xts'])} UTC) · 持仓 {t0['hold_h']:.1f}h · 毛利 {usd(t0['gross'], 2)}"
            f" · 成本 ${t0['cost_base']:,.2f}/${t0['cost_cons']:,.2f}\n" + "\n".join(lines) + board(st))


def group_msgs(msgs):
    """同一币、同一时间、同价出场的几匹马合成一条。"""
    out, key_ix = [], {}
    for kind, p in msgs:
        if kind == "exit":
            k = (p["sym"], p["xts"], round(p["x"], 8), p["why"], p["ts"])
            if k in key_ix: out[key_ix[k]][1].append(p)
            else: key_ix[k] = len(out); out.append(("exit", [p]))
        else:
            out.append((kind, p))
    return out


def main():
    import tg_notify
    from tg_notify import send_message
    tg_notify.public_paused = lambda: False

    def send(text):
        send_message(text); time.sleep(0.5)

    st = load_state()
    first = not st["started"]
    HBS, M5S = {}, {}
    for sym in SYMS:
        try:
            HBS[sym] = fetch_okx(sym, "1H", pages=3)
            M5S[sym] = fetch_okx(sym, "5m")
        except Exception as e:
            print(f"{sym} 行情失败: {e}"); HBS.pop(sym, None)
    ok = [s for s in SYMS if len(HBS.get(s, [])) >= 560 and len(M5S.get(s, [])) >= 24]
    if not ok:
        print("全部行情失败"); sys.exit(1)
    feats = Feats({s: HBS[s] for s in ok})
    msgs = []
    for sym in ok:
        if first or sym not in st["syms"]:
            ss = st["syms"].setdefault(sym, new_sym()); last = M5S[sym][-1]["ts"]
            ss["last_5m_ts"] = last
            ss["hour_done_ts"] = last // H * H if last % H == H - 300 else last // H * H - H
            continue
        run(HBS[sym], M5S[sym], st, sym, msgs, feats)
    if first:
        st["started"] = True
        save_state(st); feed_flush(st, [])
        send("🏮 <b>江南4马 开跑</b> (四根K线结构)\n━━━━━━━━━━━━━━━\n"
             f"标的: {' '.join(SYMS)} 永续 (OKX 行情, 日线定方向 + 1h 进场 + 5m 路径记账)\n"
             "信号: 昨天(K2)冲过前天(K1)最高又收回 → 今天(K3)先冲高但 1h 收盘不过 K2 腰线 → 1h 改派信号 (收盘跌破最近一串阳线的起点) 做空; 做多镜像\n"
             "止损: K2 最高/最低点外 · 每单打到亏 $40 · 最晚拿到 K4 收盘 · 每币每马同时 1 单\n"
             + "\n".join(f"{lab(c)}: {RULE[c]}" for c in HORSES) +
             "\n回测 (2023-05→2026-10, 7 币, 扣滑点和资金费, 每匹账户 $7,000):\n"
             "JN1 +$3,753 (+53.6%) 回撤 15% · JN2 +$3,434 (+49.1%) 回撤 12%\nJN3 +$3,581 (+51.2%) 回撤 6% · JN4 +$2,833 (+40.5%) 回撤 6%\n"
             "<i>回测里钱主要是做多赚的 (样本期是上涨市); 及格线: 每匹前向 ≥40 笔、基准口径净为正</i>" + PAPER_MARK)
        return
    save_state(st); feed_flush(st, msgs)
    for kind, p in group_msgs(msgs)[-12:]:
        try:
            if kind == "entry": send(fmt_entry(p, st))
            elif kind == "exit": send(fmt_exit(p, st))
            elif kind == "bemove": send(f"🔒 <b>{p['sym']} {lab(p['code'])} #{p['seq']:03d} 已保本</b>\n跟踪止损推到 <code>${fp(p['sl'])}</code> (进场 ${fp(p['e'])}), 这单最差打平扣成本" + PAPER_MARK)
        except Exception as e:
            print(f"消息失败 {kind}: {e}")
    print(f"ok {len(ok)}/7: 信号 {st['n_sig']} · " + " · ".join(f"{c} {len(st['trades'][c])}笔 {sum(t['net_base'] for t in st['trades'][c]):+.0f}" for c in HORSES))


if __name__ == "__main__":
    main()
