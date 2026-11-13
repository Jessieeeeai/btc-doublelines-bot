"""
强突破跟进 · 四马赛马 (纸面, 非实盘指令) — 2026-11-12 第 6 轮确认阵容

共同信号 (1h, 7 个币各跑各的):
  突破K:  收盘越过之前 20 根最高(低)点; 实体 >= 整根 70%; 振幅 >= 1.5 x ATR14 (ATR 只用它之前的K线)
  跟进K:  下一根同向收盘且越过突破K收盘 → 再下一根 5m 开盘价进
  止损:   突破K另一端外 0.03%; 每单打到止损亏 $40; 最多拿 72 小时
四匹马只在"做不做"和"怎么出"上不同:
  N-H1 基准马    全做                               2R 止盈
  N-H2 纽约顺势马 只做美东 7-13 点 且 顺 BTC 大势        2R 止盈
  N-H3 强弱马    顺 BTC 大势 且 7日涨幅前3才多/后3才空   2R 止盈
  N-H4 奔跑马    顺 BTC 大势                          不设止盈, 吊灯止损 (最高点 - 4 x ATR, 只紧不松)
  顺 BTC 大势 = BTC 1h 收盘在自己 200 均线(EMA)上方只做多, 下方只做空
记账: 5m 真实路径, 同一根里止损止盈都碰到按止损; 基准口径 (滑点 0.04% + 资金费 0.01%/8h) 与
      保守口径 (滑点 0.08% + 止损再滑 0.05% + 资金费) 并列。每匹马账户 $7,000 (7 币 x $1,000)。
参数与回测一致, 不要调。state: state_N_H.json; 订阅源: breakout_feed*.json。
"""
import os, sys, json, time
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STATE_FILE = "state_N_H.json"
SYMS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA"]
HORSES = {"N-H1": "基准马", "N-H2": "纽约顺势马", "N-H3": "强弱马", "N-H4": "奔跑马"}
RULE = {"N-H1": "全做 · 2R", "N-H2": "美东7-13点+顺BTC · 2R", "N-H3": "顺BTC+强弱排名 · 2R", "N-H4": "顺BTC · 吊灯止损"}
H = 3600
LOOK, BODY, K_ATR, RR, HOLD_H, BUF, CHAND = 20, 0.7, 1.5, 2.0, 72, 0.0003, 4.0
RISK_USD, NOTIONAL_CAP, PRINCIPAL_USD = 40.0, 25000.0, 1000.0
ACCOUNT_USD = PRINCIPAL_USD * len(SYMS)
SLIP_BASE, SLIP_CONS, STOP_SLIP_CONS, FUND_8H = 0.0004, 0.0008, 0.0005, 0.0001
PAPER_MARK = "\n🧪 <i>纸面验证 · 实盘记账口径 — 非实盘指令</i>"


# ===== 行情 (OKX 永续公共接口, 只取已收盘) =====

def fetch_okx(sym, bar, pages=1):
    bars, after = {}, None
    for _ in range(pages):
        url = f"https://www.okx.com/api/v5/market/candles?instId={sym}-USDT-SWAP&bar={bar}&limit=300" + (f"&after={after}" if after else "")
        req = urllib.request.Request(url, headers={"accept": "application/json", "User-Agent": "breakout-race/1.0"})
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


def is_ny(ts):
    return 7 <= datetime.fromtimestamp(ts, tz=ZoneInfo("America/New_York")).hour < 13


def fp(x):
    if x >= 1000: return f"{x:,.1f}"
    if x >= 10: return f"{x:,.2f}"
    if x >= 1: return f"{x:,.4f}"
    return f"{x:.5f}"


def pct(x, base=ACCOUNT_USD):
    return f"{x / base * 100:+.2f}%"


# ===== 信号与过滤特征 =====

def atr14(HB, j):
    """到第 j 根为止最近 14 根的平均真实波幅。"""
    trs = []
    for i in range(j - 13, j + 1):
        x, p = HB[i], HB[i - 1]
        trs.append(max(x["high"] - x["low"], abs(x["high"] - p["close"]), abs(x["low"] - p["close"])))
    return sum(trs) / 14


def signal(HB, j):
    """第 j 根 1h 刚收盘。j-1 是突破K、j 是跟进K → (side, stop)。"""
    t = j - 1
    if t < LOOK + 15:
        return None
    b, f = HB[t], HB[j]
    rng = b["high"] - b["low"]
    if rng <= 0 or rng < K_ATR * atr14(HB, t - 1) or abs(b["close"] - b["open"]) < BODY * rng:
        return None
    prev = HB[t - LOOK:t]
    if b["close"] > max(x["high"] for x in prev) and f["close"] > f["open"] and f["close"] > b["close"]:
        return 1, b["low"] * (1 - BUF)
    if b["close"] < min(x["low"] for x in prev) and f["close"] < f["open"] and f["close"] < b["close"]:
        return -1, b["high"] * (1 + BUF)
    return None


class Feats:
    """跨币特征: BTC 大势、7 日涨幅排名。只用 <= h 的已收盘 1h K线。"""
    def __init__(self, HBS):
        self.HBS = HBS
        self.idx = {s: {b["ts"]: i for i, b in enumerate(hb)} for s, hb in HBS.items()}
        self.cache = {}

    def at(self, h):
        if h in self.cache:
            return self.cache[h]
        out = {"btc": 0, "rank": {}}
        hb, ix = self.HBS.get("BTC"), self.idx.get("BTC", {})
        j = ix.get(h)
        if hb and j is not None and j >= 150:
            a, num, den, w = 2.0 / 201.0, 0.0, 0.0, 1.0
            for i in range(j, max(-1, j - 900), -1):     # EMA200, 与 pandas ewm(span=200) 同式
                num += w * hb[i]["close"]; den += w; w *= (1 - a)
            ema = num / den
            out["btc"] = 1 if hb[j]["close"] > ema else (-1 if hb[j]["close"] < ema else 0)
        rets = {}
        for s, hb in self.HBS.items():
            ix = self.idx[s]; j, k = ix.get(h), ix.get(h - 168 * H)
            if j is not None and k is not None:
                rets[s] = hb[j]["close"] / hb[k]["close"] - 1
        if len(rets) == len(SYMS):
            for r, s in enumerate(sorted(rets, key=lambda z: -rets[z]), 1):
                out["rank"][s] = r
        self.cache[h] = out
        return out


def eligible(code, sym, side, h, ft):
    """这匹马做不做这个信号 → (bool, 不做的原因)。"""
    if code == "N-H1":
        return True, ""
    if ft["btc"] != side:
        return False, "逆BTC大势"
    if code == "N-H2" and not is_ny(h + H):
        return False, "非美东7-13点"
    if code == "N-H3":
        r = ft["rank"].get(sym)
        if r is None:
            return False, "排名数据不全"
        if not ((r <= 3) if side == 1 else (r >= 5)):
            return False, f"7日涨幅排第{r}"
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
        st = json.load(f)
    if "pos" not in next(iter(st.get("syms", {"x": {"pos": 1}}).values())):   # 旧单马 state → 重新开始
        return new_state()
    return st


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
        if dist > 0 and ts < p["from_ts"] + H:       # 开盘已在止损外 / 数据断档超 1 小时 → 放弃
            opened = []
            for code in p["horses"]:
                if code in ss["pos"]:
                    continue
                st["seq"][code] += 1
                ss["pos"][code] = {"seq": st["seq"][code], "d": d, "e": px, "sl": sl, "sl0": sl,
                                   "tp": None if code == "N-H4" else px + d * RR * dist,
                                   "n": round(min(RISK_USD / (dist / px), NOTIONAL_CAP), 0), "ts": ts,
                                   "x_ts": ts + HOLD_H * H, "pk": px, "ch": CHAND * p["atr"] if code == "N-H4" else None}
                opened.append(code); fresh.add(code)
            if opened:
                msgs.append(("entry", {"sym": sym, "d": d, "e": px, "sl": sl, "ts": ts, "dist": dist, "horses": opened,
                                       "skipped": p.get("skipped", {}), "pos": {c: dict(ss["pos"][c]) for c in opened}}))
    for code in list(ss["pos"]):
        pos = ss["pos"][code]; d = pos["d"]; fr = code in fresh
        if pos["ch"] is not None and not fr:          # 吊灯止损: 用上一根为止的最高(低)点
            ns = pos["pk"] - d * pos["ch"]
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


def hour_close(st, ss, sym, HB, idx, h, feats):
    j = idx.get(h)
    if j is not None:
        s = signal(HB, j)
        if s:
            st["n_sig"] += 1
            ft = feats.at(h); horses, skipped = [], {}
            for code in HORSES:
                if code in ss["pos"]:
                    skipped[code] = "已有持仓"; continue
                ok, why = eligible(code, sym, s[0], h, ft)
                if ok: horses.append(code)
                else: skipped[code] = why
            if horses:
                ss["pend"] = {"side": s[0], "sl": s[1], "from_ts": h + H, "atr": atr14(HB, j), "horses": horses, "skipped": skipped}
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


# ===== 消息 =====

def board(st):
    rows = []
    for code, name in HORSES.items():
        tr = st["trades"][code]; n = len(tr); w = sum(1 for t in tr if t["net_base"] > 0)
        nb = sum(t["net_base"] for t in tr); nc = sum(t["net_cons"] for t in tr)
        op = sum(1 for v in st["syms"].values() if code in v["pos"])
        rows.append(f"{code[2:]} {name}: {n}笔 {w}胜 · 净 <b>${nb:+,.0f} ({pct(nb)})</b> · 保守 ${nc:+,.0f} ({pct(nc)}) · 持仓{op}")
    return ("\n━━━━━━━━━━━━━━━\n📊 <b>四马前向战绩</b> (每匹账户 $7,000 · 每单风险 $40)\n" + "\n".join(rows) + PAPER_MARK)


def fmt_entry(p, st):
    d = p["d"]; n = next(iter(p["pos"].values()))["n"]
    lines = []
    for c in p["horses"]:
        pos = p["pos"][c]
        tgt = (f"止盈 <code>${fp(pos['tp'])}</code> (赚 ${RISK_USD*RR:,.0f} = 本金 {RISK_USD*RR/PRINCIPAL_USD*100:.0f}%)" if pos["tp"]
               else f"不设止盈 · 吊灯止损距最高点 ${fp(pos['ch'])}")
        lines.append(f"✅ {c[2:]} {HORSES[c]} #{pos['seq']:03d}: {tgt}")
    for c, why in p["skipped"].items():
        lines.append(f"➖ {c[2:]} {HORSES[c]}: 不做 ({why})")
    return (f"🚀 <b>{p['sym']} {'📈 做多' if d==1 else '📉 做空'} — 1h 强突破 + 跟进K</b>\n━━━━━━━━━━━━━━━\n"
            f"进场 <code>${fp(p['e'])}</code> ({tstr(p['ts'])} UTC){' · 🗽纽约时段' if is_ny(p['ts']) else ''}\n"
            f"🛑 止损 <code>${fp(p['sl'])}</code> · 距离 {p['dist']/p['e']*100:.2f}% · 打到亏 ${RISK_USD:,.0f} (本金 {RISK_USD/PRINCIPAL_USD*100:.0f}%)\n"
            f"⚖️ 名义 ${n:,.0f} · 杠杆 {n/PRINCIPAL_USD:.1f}× (每币本金 ${PRINCIPAL_USD:,.0f}) · 最多拿 {HOLD_H}h\n"
            + "\n".join(lines) + board(st))


def fmt_exit(ts_, st):
    t0 = ts_[0]
    icon = {"tp": "🟢 止盈", "sl": "🔴 止损" if t0["sl"] == t0["sl0"] else "🔒 吊灯止损", "time": "⏱ 到时平仓"}[t0["why"]]
    lines = [f"{t['code'][2:]} {HORSES[t['code']]} #{t['seq']:03d}: 净 <b>${t['net_base']:+,.2f} ({pct(t['net_base'], PRINCIPAL_USD)})</b>"
             f" · 保守 ${t['net_cons']:+,.2f} ({pct(t['net_cons'], PRINCIPAL_USD)})" for t in ts_]
    return (f"{icon} <b>{t0['sym']} {'多' if t0['d']==1 else '空'}单出场</b>\n━━━━━━━━━━━━━━━\n"
            f"${fp(t0['e'])} → ${fp(t0['x'])} ({tstr(t0['xts'])} UTC) · 持仓 {t0['hold_h']:.1f}h · 毛利 ${t0['gross']:+,.2f}"
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
    import tg_notify, breakout_feed
    from tg_notify import send_message
    tg_notify.public_paused = lambda: False

    def send(text):
        send_message(text); time.sleep(0.5)

    st = load_state()
    first = not st["started"]
    HBS, M5S = {}, {}
    for sym in SYMS:
        try:
            HBS[sym] = fetch_okx(sym, "1H", pages=3 if sym == "BTC" else 1)
            M5S[sym] = fetch_okx(sym, "5m")
        except Exception as e:
            print(f"{sym} 行情失败: {e}"); HBS.pop(sym, None)
    ok = [s for s in SYMS if len(HBS.get(s, [])) >= 200 and len(M5S.get(s, [])) >= 24]
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
        save_state(st); breakout_feed.flush(st)
        send("🏇 <b>强突破跟进 · 四马赛马 开跑</b>\n━━━━━━━━━━━━━━━\n"
             f"标的: {' '.join(SYMS)} 永续 (OKX 行情, 1h 信号 + 5m 路径记账)\n"
             "信号: 1h 强突破K (收盘破前 20 根高/低点 · 实体≥70% · 振幅≥1.5×ATR) + 下一根跟进K 同向收盘 → 顺势进\n"
             "止损: 突破K另一端 · 每单打到亏 $40 · 最多拿 72 小时 · 每币每马同时 1 单\n"
             + "\n".join(f"{c[2:]} {n}: {RULE[c]}" for c, n in HORSES.items()) +
             "\n回测 (2023-05→2026-10, 7 币, 扣滑点和资金费, 每匹账户 $7,000):\n"
             "H1 +$3,291 (+47%) 回撤 27% · H2 +$3,452 (+49%) 回撤 16%\nH3 +$3,127 (+45%) 回撤 10% · H4 +$6,813 (+97%) 回撤 27%\n"
             "<i>及格线: 每匹前向 ≥40 笔、基准口径净为正</i>" + PAPER_MARK)
        return
    for kind, p in msgs:
        breakout_feed.emit(kind, p)
    save_state(st); breakout_feed.flush(st)
    for kind, p in group_msgs(msgs)[-12:]:
        try:
            if kind == "entry": send(fmt_entry(p, st))
            elif kind == "exit": send(fmt_exit(p, st))
            else: send(f"🔒 <b>{p['sym']} H4 奔跑马 #{p['seq']:03d} 已保本</b>\n吊灯止损推到 <code>${fp(p['sl'])}</code> (进场 ${fp(p['e'])}), 这单最差打平扣成本" + PAPER_MARK)
        except Exception as e:
            print(f"消息失败 {kind}: {e}")
    print(f"ok {len(ok)}/7: 信号 {st['n_sig']} · " + " · ".join(f"{c} {len(st['trades'][c])}笔 {sum(t['net_base'] for t in st['trades'][c]):+.0f}" for c in HORSES))


if __name__ == "__main__":
    main()
