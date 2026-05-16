"""
用 RSI / CCI 超卖超买代替 EMA-200, 看会不会更好
逻辑: 反转策略本来就是"反向"思路 — 价格被打到超卖时做多, 超买时做空

测试:
  - 单独 RSI 过滤 (不同阈值)
  - 单独 CCI 过滤 (不同阈值)
  - RSI + EMA-200 叠加
  - CCI + EMA-200 叠加
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
from signals import detect_signals
from backtest import (VariantConfig, _resolve_entry, _stop_loss_price,
                        _compute_ema, _compute_adx)


def load_bars(path):
    bars = []
    with open(path) as f:
        for r in csv.DictReader(f):
            bars.append({"date": r["date"],
                         "open": float(r["open"]), "high": float(r["high"]),
                         "low": float(r["low"]), "close": float(r["close"])})
    return bars


def compute_rsi(bars, period=14):
    """Wilder RSI"""
    rsi = [None] * len(bars)
    gains, losses = [], []
    for i in range(1, len(bars)):
        d = bars[i]["close"] - bars[i-1]["close"]
        gains.append(max(d, 0))
        losses.append(-min(d, 0))
    if len(gains) < period:
        return rsi
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    if avg_l == 0:
        rsi[period] = 100.0
    else:
        rs = avg_g / avg_l
        rsi[period] = 100 - 100/(1+rs)
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period-1) + gains[i]) / period
        avg_l = (avg_l * (period-1) + losses[i]) / period
        if avg_l == 0:
            rsi[i+1] = 100.0
        else:
            rs = avg_g / avg_l
            rsi[i+1] = 100 - 100/(1+rs)
    return rsi


def compute_cci(bars, period=20):
    cci = [None] * len(bars)
    tp = [(b["high"] + b["low"] + b["close"]) / 3 for b in bars]
    for i in range(period - 1, len(bars)):
        window = tp[i - period + 1 : i + 1]
        sma = sum(window) / period
        md = sum(abs(t - sma) for t in window) / period
        if md == 0:
            cci[i] = 0
        else:
            cci[i] = (tp[i] - sma) / (0.015 * md)
    return cci


def passes(sig, idx, ema, adx, rsi, cci, mode, cfg,
            rsi_oversold=30, rsi_overbought=70,
            cci_oversold=-100, cci_overbought=100):
    """根据 mode 决定过滤逻辑"""
    bars = passes.__globals__.get('__bars_cache__')

    # ADX-EMA 强趋势跳过 (这一段保留, 所有方案共用)
    if ema is not None:
        ev = ema[idx]
        if ev is not None and ev > 0:
            dist = abs(bars[idx]["close"] - ev) / ev
            if adx[idx] > cfg.regime_adx_high and dist > cfg.regime_ema_dist_trend:
                return False

    close = bars[idx]["close"]
    direction = sig["direction"]

    if mode == "ema_only":
        # 当前 baseline: 顺势 EMA-200
        ev = ema[idx]
        if ev is None or ev <= 0: return False
        return (direction == "long" and close > ev) or (direction == "short" and close < ev)

    if mode == "rsi_only":
        rv = rsi[idx]
        if rv is None: return False
        if direction == "long":
            return rv <= rsi_oversold
        else:
            return rv >= rsi_overbought

    if mode == "cci_only":
        cv = cci[idx]
        if cv is None: return False
        if direction == "long":
            return cv <= cci_oversold
        else:
            return cv >= cci_overbought

    if mode == "rsi_plus_ema":
        ev = ema[idx]
        rv = rsi[idx]
        if ev is None or rv is None or ev <= 0: return False
        ema_ok = (direction == "long" and close > ev) or (direction == "short" and close < ev)
        rsi_ok = (direction == "long" and rv <= rsi_oversold) or (direction == "short" and rv >= rsi_overbought)
        return ema_ok and rsi_ok

    if mode == "cci_plus_ema":
        ev = ema[idx]
        cv = cci[idx]
        if ev is None or cv is None or ev <= 0: return False
        ema_ok = (direction == "long" and close > ev) or (direction == "short" and close < ev)
        cci_ok = (direction == "long" and cv <= cci_oversold) or (direction == "short" and cv >= cci_overbought)
        return ema_ok and cci_ok

    return False


def simulate(bars, sig, cfg):
    direction = sig["direction"]
    er = _resolve_entry(bars, sig, cfg)
    if er is None: return None
    entry = er["entry"]; entry_idx = er["entry_idx"]
    sl = _stop_loss_price(direction, sig, cfg.sl_buffer_pct)
    r = abs(entry - sl)
    if r <= 0: return None
    tp = entry + 2*r if direction == "long" else entry - 2*r
    for k in range(entry_idx + 1, len(bars)):
        bar = bars[k]
        if direction == "long":
            if bar["low"] <= sl:
                return {"net_r": -1.0 - 2*entry*cfg.fee_rate/r, "win": False}
            if bar["high"] >= tp:
                return {"net_r": 2.0 - 2*entry*cfg.fee_rate/r, "win": True}
        else:
            if bar["high"] >= sl:
                return {"net_r": -1.0 - 2*entry*cfg.fee_rate/r, "win": False}
            if bar["low"] <= tp:
                return {"net_r": 2.0 - 2*entry*cfg.fee_rate/r, "win": True}
    last = bars[-1]["close"]
    gross = (last - entry) / r if direction == "long" else (entry - last) / r
    return {"net_r": gross, "win": gross > 0}


def run(bars, sigs, ema, adx, rsi, cci, cfg, mode, **thresh):
    trades = []
    for sig in sigs:
        if not passes(sig, sig["index"], ema, adx, rsi, cci, mode, cfg, **thresh):
            continue
        t = simulate(bars, sig, cfg)
        if t is not None:
            trades.append(t)
    n = len(trades)
    if n == 0: return None
    wins = sum(1 for t in trades if t["win"])
    total_r = sum(t["net_r"] for t in trades)
    avg_r = total_r / n
    eq, peak, max_dd = 0, 0, 0
    for t in trades:
        eq += t["net_r"]; peak = max(peak, eq); max_dd = min(max_dd, eq - peak)
    return {"n": n, "wins": wins, "losses": n - wins,
            "win_rate": wins / n, "total_r": total_r,
            "avg_r": avg_r, "max_dd": max_dd}


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    passes.__globals__['__bars_cache__'] = bars
    cfg = VariantConfig(
        name="rsi_cci", body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )
    print(f"3 年 BTC 1h, {len(bars)} 根 K线\n")

    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    ema = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)
    rsi = compute_rsi(bars, 14)
    cci = compute_cci(bars, 20)
    print(f"原始信号 {len(sigs)}, 跑测试...\n")

    schemes = [
        # 单独 RSI
        ("EMA-200 (★baseline)",       "ema_only",  {}),
        ("RSI 30/70",                 "rsi_only",  {"rsi_oversold": 30, "rsi_overbought": 70}),
        ("RSI 35/65",                 "rsi_only",  {"rsi_oversold": 35, "rsi_overbought": 65}),
        ("RSI 25/75",                 "rsi_only",  {"rsi_oversold": 25, "rsi_overbought": 75}),
        ("RSI 40/60",                 "rsi_only",  {"rsi_oversold": 40, "rsi_overbought": 60}),
        # 单独 CCI
        ("CCI -100/+100",             "cci_only",  {"cci_oversold": -100, "cci_overbought": 100}),
        ("CCI -150/+150",             "cci_only",  {"cci_oversold": -150, "cci_overbought": 150}),
        ("CCI -200/+200",             "cci_only",  {"cci_oversold": -200, "cci_overbought": 200}),
        ("CCI -50/+50",               "cci_only",  {"cci_oversold": -50, "cci_overbought": 50}),
        # 叠加 EMA + RSI
        ("EMA + RSI 30/70",           "rsi_plus_ema", {"rsi_oversold": 30, "rsi_overbought": 70}),
        ("EMA + RSI 35/65",           "rsi_plus_ema", {"rsi_oversold": 35, "rsi_overbought": 65}),
        ("EMA + RSI 40/60",           "rsi_plus_ema", {"rsi_oversold": 40, "rsi_overbought": 60}),
        ("EMA + RSI 45/55",           "rsi_plus_ema", {"rsi_oversold": 45, "rsi_overbought": 55}),
        # 叠加 EMA + CCI
        ("EMA + CCI -100/+100",       "cci_plus_ema", {"cci_oversold": -100, "cci_overbought": 100}),
        ("EMA + CCI -50/+50",         "cci_plus_ema", {"cci_oversold": -50, "cci_overbought": 50}),
        ("EMA + CCI 0/0 (即顺势)",     "cci_plus_ema", {"cci_oversold": 0, "cci_overbought": 0}),
    ]

    print(f"{'方案':<28} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R':>8} {'回撤R':>8} {'3年%':>8}")
    print("-" * 105)
    R_pct = 0.026
    for label, mode, kw in schemes:
        s = run(bars, sigs, ema, adx, rsi, cci, cfg, mode, **kw)
        if s is None:
            print(f"{label:<28} 无 trade")
            continue
        total_pct = s["total_r"] * R_pct * 100
        print(f"{label:<28} {s['n']:>5} {s['wins']:>4} {s['losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+8.3f} "
              f"{s['max_dd']:>+8.2f} {total_pct:>+7.0f}%")


if __name__ == "__main__":
    main()
