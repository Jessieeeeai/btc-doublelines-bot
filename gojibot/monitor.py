#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GojiBot 前向验证扫描器（纸面模式，不下单）— 云端版（GitHub Actions）
CoinGlass key 从环境变量 COINGLASS_API_KEY 读取（Secrets），config.json 里不再存 key。
每小时运行一次（GitHub Actions cron），流程：
  拉数据（CoinGlass + Coinbase）→ 特征 → 评估重构版S01 → 记录
产出（gojibot/forward/）：
  monitor_log.jsonl   每次运行的市场快照+条件状态
  signals.csv         触发的信号
  paper_trades.csv    纸面持仓的完整生命周期（含成本的净盈亏）
  state.json          当前持仓/冷却状态
信号定义（回测双正候选）：
  SHORT = 近阻力(<1.5%/美股开盘2%) + 现货CVD24h<0 + 费率>=0
  止损 L01二步法，TP1=1.1R平半仓移保本，TP2=2R，最长72h，止损后冷却6h
"""
import csv
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
FWD = os.path.join(HERE, "forward")
os.makedirs(FWD, exist_ok=True)
STATE_F = os.path.join(FWD, "state.json")
COST_SIDE = (CFG["costs"]["taker_fee_pct"] + CFG["costs"]["slippage_pct"]) / 100.0
PAIR = f"{CFG['symbol']}USDT"
CG_KEY = os.environ.get("COINGLASS_API_KEY") or CFG.get("coinglass_api_key") or ""
if not CG_KEY:
    print("[WARN] 未配置 COINGLASS_API_KEY，CoinGlass 数据将拉取失败")


def get_json(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "gojibot-monitor"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception:
            time.sleep(3)
    return None


def cg(path, **params):
    url = f"https://open-api-v4.coinglass.com{path}?" + urllib.parse.urlencode(params)
    resp = get_json(url, headers={"CG-API-KEY": CG_KEY, "accept": "application/json"})
    time.sleep(1.2)
    return (resp or {}).get("data") or []


def fetch():
    """返回按小时对齐的最近~30天数据。"""
    now = int(time.time())
    # Coinbase 1h K线（3页×300）
    kl = {}
    for k in range(3):
        end = now - k * 300 * 3600
        start = end - 300 * 3600
        iso = lambda s: datetime.fromtimestamp(s, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = get_json("https://api.exchange.coinbase.com/products/BTC-USD/candles?"
                        + urllib.parse.urlencode({"granularity": 3600, "start": iso(start), "end": iso(end)}))
        if isinstance(data, list):
            for c in data:  # [t, low, high, open, close, vol]
                kl[int(c[0])] = {"o": c[3], "h": c[2], "l": c[1], "c": c[4]}
    ts = sorted(kl)
    # CoinGlass：现货taker、费率
    taker = {int(d["time"]) // 1000: float(d.get("taker_buy_volume_usd", 0)) - float(d.get("taker_sell_volume_usd", 0))
             for d in cg("/api/spot/taker-buy-sell-volume/history",
                         exchange="Bybit", symbol=PAIR, interval="1h", limit=800)}
    fund = sorted((int(d["time"]) // 1000, float(d["close"]) / 100.0)  # percent→decimal
                  for d in cg("/api/futures/funding-rate/history",
                              exchange="Bybit", symbol=PAIR, interval="8h", limit=100))
    ob = cg("/api/futures/orderbook/ask-bids-history",
            exchange="Bybit", symbol=PAIR, interval="1h", limit=2, range="1")
    print(f"[fetch] coinbase K线={len(kl)}  taker={len(taker)}  funding={len(fund)}  ob={len(ob)}")
    return kl, ts, taker, fund, ob


def features(kl, ts, taker, fund):
    """在最后一根已完成1h bar上计算特征。ts升序，最后一根可能未完成——丢弃当前小时。"""
    cur_hour = int(time.time()) // 3600 * 3600
    ts = [t for t in ts if t < cur_hour]
    if len(ts) < 24 * 7:
        print(f"[features] 已完成K线仅 {len(ts)} 根（需≥168）——价格源没拉到数据")
        return None
    t0 = ts[-1]
    close = kl[t0]["c"]

    # 现货CVD 24h（USD→BTC）
    cvd24 = sum(taker.get(t, 0.0) for t in ts[-24:]) / close
    # 费率（<=t0 的最近一期）
    fr = None
    for ft, fv in reversed(fund):
        if ft <= t0 + 3600:
            fr = fv
            break
    # 4H 结构（用完整4h桶）
    h4 = {}
    for t in ts:
        b = t // 14400 * 14400
        h4.setdefault(b, {"h": -1e18, "l": 1e18})
        h4[b]["h"] = max(h4[b]["h"], kl[t]["h"])
        h4[b]["l"] = min(h4[b]["l"], kl[t]["l"])
    h4keys = sorted(h4)
    done4 = [b for b in h4keys if b + 14400 <= t0 + 3600]  # 已完成
    res = max(h4[b]["h"] for b in done4[-20:]) if len(done4) >= 20 else None
    h4h3 = max(h4[b]["h"] for b in done4[-3:]) if len(done4) >= 3 else None
    # 1D
    d1 = {}
    for t in ts:
        b = t // 86400 * 86400
        d1.setdefault(b, -1e18)
        d1[b] = max(d1[b], kl[t]["h"])
    d1keys = [b for b in sorted(d1) if b + 86400 <= t0 + 3600]
    d1h5 = max(d1[b] for b in d1keys[-5:]) if len(d1keys) >= 5 else None
    h1h6 = max(kl[t]["h"] for t in ts[-7:-1])

    hour = datetime.fromtimestamp(t0, tz=timezone.utc).hour
    us_open = hour in (13, 14, 15)
    atr_pct = sum(kl[t]["h"] - kl[t]["l"] for t in ts[-24:]) / 24 / close
    sma_flt = sum(kl[t]["c"] for t in ts[-168:]) / min(len(ts), 168)  # MA7（用户定稿：上行段清零优先，接受边界参数风险）
    return {"t0": t0, "close": close, "high": kl[t0]["h"], "low": kl[t0]["l"],
            "cvd24": cvd24, "funding": fr, "resistance": res, "atr_pct": atr_pct,
            "sma_flt": sma_flt,
            "h4_high3": h4h3, "d1_high5": d1h5, "h1_high6": h1h6, "us_open": us_open}


def l01_short(f):
    entry = f["close"]
    h4, d1v, h1 = f["h4_high3"], f["d1_high5"], f["h1_high6"]
    if h4 is None:
        return h1 * 1.002 if h1 else None
    if h4 > entry * 1.002:
        if d1v and d1v > h4 and (d1v / entry - 1) < 0.05:
            return d1v * 1.003
        return h4 * 1.002
    return h4 * 1.002 if h4 > entry else entry * 1.008


def notify(title, msg):
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{msg}" with title "{title}"'],
                       timeout=10, capture_output=True)
    except Exception:
        pass


def append_csv(path, row, header):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(header)
        w.writerow(row)


def csv_count(path):
    if not os.path.exists(path):
        return 0
    with open(path) as fh:
        return max(sum(1 for _ in fh) - 1, 0)


def paper_stats(path, expect_wr, expect_r):
    """从纸面账CSV汇总战绩（R按 pnl/止损距离 折算）。"""
    out = {"wins": 0, "losses": 0, "wr": 0.0, "total_r": 0.0, "total_pct": 0.0,
           "expect_wr": expect_wr, "expect_r": expect_r}
    if not os.path.exists(path):
        return out
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        pnl = float(r["pnl_pct"])
        entry, stop = float(r["entry"]), float(r["stop"])
        risk = abs(stop - entry) / entry * 100
        out["total_pct"] += pnl
        out["total_r"] += pnl / risk if risk > 0 else 0
        if pnl > 0:
            out["wins"] += 1
        else:
            out["losses"] += 1
    n = out["wins"] + out["losses"]
    out["wr"] = out["wins"] / n if n else 0.0
    return out


# ======================================================================
# 多头跟踪（2026-07新增第二候选）：抛售衰竭反转 + 4h RSI>50
#   LONG = 现货CVD24h < 滚动30日p15（恐慌抛售）+ 6h净流转正（衰竭）+ 4h RSI14>50
#   L01多头止损，1.5R单目标，72h上限，止损后冷却6h。主战场ETH，BTC顺带。
# ======================================================================
def fetch_symbol_light(product, pair):
    now = int(time.time())
    kl = {}
    for k in range(3):
        end = now - k * 300 * 3600
        start = end - 300 * 3600
        iso = lambda s: datetime.fromtimestamp(s, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = get_json(f"https://api.exchange.coinbase.com/products/{product}/candles?"
                        + urllib.parse.urlencode({"granularity": 3600, "start": iso(start), "end": iso(end)}))
        if isinstance(data, list):
            for c in data:
                kl[int(c[0])] = {"o": c[3], "h": c[2], "l": c[1], "c": c[4]}
    taker = {int(d["time"]) // 1000: float(d.get("taker_buy_volume_usd", 0)) - float(d.get("taker_sell_volume_usd", 0))
             for d in cg("/api/spot/taker-buy-sell-volume/history",
                         exchange="Bybit", symbol=pair, interval="1h", limit=800)}
    return kl, sorted(kl), taker


def rsi_wilder(vals, period=14):
    if len(vals) < period + 2:
        return None
    r = None
    au = ad = 0.0
    for i in range(1, len(vals)):
        d = vals[i] - vals[i - 1]
        u, dn = max(d, 0), max(-d, 0)
        if i <= period:
            au += u / period; ad += dn / period
        else:
            au = (au * (period - 1) + u) / period
            ad = (ad * (period - 1) + dn) / period
    return 100 - 100 / (1 + au / ad) if ad > 0 else 100.0


def track_long(sym, kl, ts, taker, state):
    st = state.setdefault("long", {}).setdefault(
        sym, {"position": None, "cooldown_until": 0, "last_bar": 0})
    cur_hour = int(time.time()) // 3600 * 3600
    ts = [t for t in ts if t < cur_hour]
    if len(ts) < 24 * 8:
        return
    t0 = ts[-1]
    if t0 <= st["last_bar"]:
        return
    close = kl[t0]["c"]

    # 30日滚动 cvd24 序列 → p15 阈值
    deltas = [taker.get(t, 0.0) for t in ts]
    cvd24 = []
    for i in range(24, len(ts)):
        cvd24.append(sum(deltas[i - 24:i]) / kl[ts[i]]["c"])
    if len(cvd24) < 100:
        return
    cvd_now = cvd24[-1]
    p15 = sorted(cvd24)[int(len(cvd24) * 0.15)]
    slope6 = sum(deltas[-6:]) / close
    # 4h RSI14（只用已完成4h桶）
    h4c = {}
    for t in ts:
        b = t // 14400 * 14400
        h4c[b] = kl[t]["c"]
    done = [h4c[b] for b in sorted(h4c) if b + 14400 <= t0 + 3600]
    r4 = rsi_wilder(done[-80:])

    # 持仓管理
    pos = st["position"]
    if pos:
        h, l = kl[t0]["h"], kl[t0]["l"]
        closed, reason, pnl = False, "", 0.0
        if l <= pos["stop"]:
            pnl = (pos["stop"] - pos["entry"]) / pos["entry"] - 2 * COST_SIDE
            closed, reason = True, "stop"
            st["cooldown_until"] = t0 + 6 * 3600
        elif h >= pos["tp"]:
            pnl = (pos["tp"] - pos["entry"]) / pos["entry"] - 2 * COST_SIDE
            closed, reason = True, "tp"
        elif t0 - pos["t_entry"] >= 72 * 3600:
            pnl = (close - pos["entry"]) / pos["entry"] - 2 * COST_SIDE
            closed, reason = True, "time"
        if closed:
            lev = pos.get("lev", 1.0)
            append_csv(os.path.join(FWD, "paper_trades_long.csv"),
                       [sym, datetime.fromtimestamp(pos["t_entry"], tz=timezone.utc).isoformat(),
                        datetime.fromtimestamp(t0, tz=timezone.utc).isoformat(),
                        pos["entry"], pos["stop"], pos["tp"], reason, round(pnl * 100, 3),
                        lev, round(pnl * lev * 100, 3)],
                       ["symbol", "t_entry", "t_exit", "entry", "stop", "tp", "reason",
                        "pnl_pct", "lev", "equity_ret_pct"])
            notify(f"GojiBot多头纸面 {sym}", f"{reason} 净{pnl*100:+.2f}%")
            risk = abs(pos["stop"] - pos["entry"]) / pos["entry"]
            stats = paper_stats(os.path.join(FWD, "paper_trades_long.csv"), "45-50", "+0.35R")
            tg.send(tg.msg_close(pos.get("no", 0), "S20·恐慌衰竭做多", sym, reason,
                                 pos["stop"] if reason == "stop" else (pos["tp"] if reason == "tp" else close),
                                 pnl * 100, (pnl / risk) if risk > 0 else None,
                                 (t0 - pos["t_entry"]) / 3600, stats))
            st["position"] = None

    # 信号
    c_flush = cvd_now < p15
    c_slope = slope6 > 0
    c_rsi = r4 is not None and r4 > 50
    fired = c_flush and c_slope and c_rsi and st["position"] is None and t0 >= st["cooldown_until"]
    if fired:
        # L01 多头止损（近3根4H低点 / 5日低点升级）
        h4l = {}
        for t in ts:
            b = t // 14400 * 14400
            h4l.setdefault(b, 1e18); h4l[b] = min(h4l[b], kl[t]["l"])
        done4 = [b for b in sorted(h4l) if b + 14400 <= t0 + 3600]
        l4 = min(h4l[b] for b in done4[-3:]) if len(done4) >= 3 else None
        d1l = {}
        for t in ts:
            b = t // 86400 * 86400
            d1l.setdefault(b, 1e18); d1l[b] = min(d1l[b], kl[t]["l"])
        dk = [b for b in sorted(d1l) if b + 86400 <= t0 + 3600]
        d5 = min(d1l[b] for b in dk[-5:]) if len(dk) >= 5 else None
        stop = None
        if l4:
            if l4 < close * 0.998:
                stop = d5 * 0.997 if (d5 and d5 < l4 and 1 - d5 / close < 0.05) else l4 * 0.998
            else:
                stop = l4 * 0.998 if l4 < close else close * 0.992
        if stop and stop < close and (1 - stop / close) <= 0.05:
            r = close - stop
            # 仓位 C01+C02（含策略分级：多头证据弱，风险预算减半至0.5%）
            atrs = [kl[t]["h"] - kl[t]["l"] for t in ts[-24:]]
            atr_pct = sum(atrs) / 24 / close
            lev = round(min(0.005 / (1 - stop / close), 0.006 / atr_pct, 5.0), 2) if atr_pct > 0 else 1.0
            st["position"] = {"t_entry": t0, "entry": close, "stop": stop,
                              "tp": close + 1.5 * r, "lev": lev}
            append_csv(os.path.join(FWD, "signals_long.csv"),
                       [sym, datetime.fromtimestamp(t0, tz=timezone.utc).isoformat(),
                        "S20", close, stop, st["position"]["tp"],
                        round(cvd_now, 1), round(p15, 1), round(r4, 1)],
                       ["symbol", "time", "strategy", "entry", "stop", "tp", "cvd24", "p15_thr", "rsi4h"])
            no = csv_count(os.path.join(FWD, "signals_long.csv"))
            st["position"]["no"] = no
            notify(f"GojiBot多头信号 {sym}", f"S20 LONG @{close:.0f} SL {stop:.0f}")
            cond = (f"CVD24h {cvd_now:.0f} < p15({p15:.0f}) · 6h净流转正 · 4hRSI {r4:.0f}>50")
            tg.send(tg.msg_open(no, "S20·恐慌衰竭做多", sym, "LONG",
                                close, stop, st["position"]["tp"],
                                st["position"].get("lev", 1.0), cond))

    with open(os.path.join(FWD, "monitor_log_long.jsonl"), "a") as fh:
        fh.write(json.dumps({
            "run_at": datetime.now(timezone.utc).isoformat(), "symbol": sym,
            "bar": datetime.fromtimestamp(t0, tz=timezone.utc).isoformat(),
            "close": close, "cvd24": round(cvd_now, 1), "p15": round(p15, 1),
            "slope6": round(slope6, 2), "rsi4h": round(r4, 1) if r4 else None,
            "c_flush": bool(c_flush), "c_slope": bool(c_slope), "c_rsi": bool(c_rsi),
            "signal": bool(fired), "position_open": st["position"] is not None,
        }, ensure_ascii=False) + "\n")
    st["last_bar"] = t0


def main():
    state = json.load(open(STATE_F)) if os.path.exists(STATE_F) else {
        "position": None, "cooldown_until": 0, "last_bar": 0}

    kl, ts, taker, fund, ob = fetch()
    f = features(kl, ts, taker, fund)
    if f is None:
        print("数据不足，跳过"); return
    if f["t0"] <= state["last_bar"]:
        print("该bar已处理"); return

    # ---- 纸面持仓管理（用最新已完成bar检查）----
    pos = state["position"]
    if pos:
        h, l, c = f["high"], f["low"], f["close"]
        closed, reason, pnl = False, "", 0.0
        if h >= pos["stop"]:
            pnl = (pos["entry"] - pos["stop"]) / pos["entry"] - 2 * COST_SIDE
            closed, reason = True, "stop"
            state["cooldown_until"] = f["t0"] + 6 * 3600
        elif l <= pos["tp"]:
            pnl = (pos["entry"] - pos["tp"]) / pos["entry"] - 2 * COST_SIDE
            closed, reason = True, "tp"
        elif f["t0"] - pos["t_entry"] >= 72 * 3600:
            pnl = (pos["entry"] - c) / pos["entry"] - 2 * COST_SIDE
            closed, reason = True, "time"
        if closed:
            lev = pos.get("lev", 1.0)
            append_csv(os.path.join(FWD, "paper_trades.csv"),
                       [datetime.fromtimestamp(pos["t_entry"], tz=timezone.utc).isoformat(),
                        datetime.fromtimestamp(f["t0"], tz=timezone.utc).isoformat(),
                        pos["entry"], pos["stop"], pos["tp"],
                        reason, round(pnl * 100, 3), lev, round(pnl * lev * 100, 3)],
                       ["t_entry", "t_exit", "entry", "stop", "tp", "reason",
                        "pnl_pct", "lev", "equity_ret_pct"])
            notify("GojiBot纸面平仓", f"{reason} 净{pnl*100:+.2f}%")
            risk = abs(pos["stop"] - pos["entry"]) / pos["entry"]
            stats = paper_stats(os.path.join(FWD, "paper_trades.csv"), "55-62", "+0.29R")
            tg.send(tg.msg_close(pos.get("no", 0), "S10·阻力衰竭做空", "BTC", reason,
                                 pos["stop"] if reason == "stop" else (pos["tp"] if reason == "tp" else c),
                                 pnl * 100, (pnl / risk) if risk > 0 else None,
                                 (f["t0"] - pos["t_entry"]) / 3600, stats))
            state["position"] = None
        else:
            state["position"] = pos

    # ---- 信号评估 ----
    px, res, fr = f["close"], f["resistance"], f["funding"]
    near_thr = 0.02 if f["us_open"] else 0.015
    c1 = res is not None and (res / px - 1) < near_thr and px < res * 1.005
    c3 = f["cvd24"] < 0
    c5 = fr is not None and fr >= 0
    c6 = px < f["sma_flt"]  # MA7趋势过滤（11个月BTC+14.1%/ETH+9.8%，上行段+0.4%；注意MA6即翻负的边界风险）
    ob_imb = None
    if ob and len(ob) >= 1:
        b = ob[-1]
        bv, av = float(b.get("bids_usd", 0)), float(b.get("asks_usd", 0))
        ob_imb = (bv - av) / (bv + av) if bv + av else None
    fired = c1 and c3 and c5 and c6 and state["position"] is None and f["t0"] >= state["cooldown_until"]

    if fired:
        stop = l01_short(f)
        # MIN_STOP过滤已撤销：事后剔除显示有效，但串行重放下样本外变差（2026-07优化⑤复核）
        if stop and stop > px and (stop / px - 1) <= 0.05:
            r = stop - px
            # 出场结构（2026-07优化③采纳）：单目标1.5R全仓出场，不分批不移保本
            # 仓位 C01+C02（2026-07组合层定稿）：min(1%风险预算/止损距离, 0.6%/ATR, 5x)
            risk_frac = stop / px - 1
            lev = round(min(0.01 / risk_frac, 0.006 / f["atr_pct"], 5.0), 2) if f["atr_pct"] > 0 else 1.0
            pos = {"t_entry": f["t0"], "entry": px, "stop": stop, "tp": px - 1.5 * r,
                   "lev": lev}
            state["position"] = pos
            append_csv(os.path.join(FWD, "signals.csv"),
                       [datetime.fromtimestamp(f["t0"], tz=timezone.utc).isoformat(),
                        "S10", "SHORT", px, stop, pos["tp"],
                        round(f["cvd24"], 1), fr, ob_imb],
                       ["time", "strategy", "dir", "entry", "stop", "tp",
                        "spot_cvd24", "funding", "ob_imb"])
            no = csv_count(os.path.join(FWD, "signals.csv"))
            pos["no"] = no
            notify("GojiBot信号", f"S10 SHORT @{px:.0f} SL {stop:.0f}")
            cond = (f"距阻力{(res / px - 1) * 100:.2f}% · CVD24h {f['cvd24']:.0f} · "
                    f"FR {fr * 100:+.4f}% · MA7下方")
            tg.send(tg.msg_open(no, "S10·阻力衰竭做空", "BTC", "SHORT",
                                px, stop, pos["tp"], lev, cond))
        else:
            fired = False

    # ---- 快照日志 ----
    with open(os.path.join(FWD, "monitor_log.jsonl"), "a") as fh:
        fh.write(json.dumps({
            "run_at": datetime.now(timezone.utc).isoformat(),
            "bar": datetime.fromtimestamp(f["t0"], tz=timezone.utc).isoformat(),
            "close": px, "funding": fr, "spot_cvd24": round(f["cvd24"], 1),
            "resistance": res, "res_dist_pct": round((res / px - 1) * 100, 3) if res else None,
            "ob_imb": round(ob_imb, 4) if ob_imb is not None else None,
            "c1_near_res": bool(c1), "c3_cvd_neg": bool(c3), "c5_fr_pos": bool(c5),
            "c6_below_ma9": bool(c6), "sma9d": round(f["sma_flt"], 2),
            "signal": bool(fired),
            "position_open": state["position"] is not None,
        }, ensure_ascii=False) + "\n")

    state["last_bar"] = f["t0"]

    # ---- 多头跟踪：BTC复用已拉数据，ETH独立轻量拉取 ----
    try:
        track_long("BTC", kl, ts, taker, state)
        ekl, ets, etaker = fetch_symbol_light("ETH-USD", "ETHUSDT")
        track_long("ETH", ekl, ets, etaker, state)
    except Exception as e:
        print(f"long tracker err: {e}")

    json.dump(state, open(STATE_F, "w"), indent=2)
    print(f"bar={datetime.fromtimestamp(f['t0'], tz=timezone.utc)} close={px:.0f} "
          f"c1={c1} c3={c3} c5={c5} signal={fired} pos={'有' if state['position'] else '无'}")


if __name__ == "__main__":
    main()
