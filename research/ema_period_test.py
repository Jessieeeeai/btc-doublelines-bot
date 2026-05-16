"""
F6 顺势 EMA 过滤, 改 1h 上的 EMA 周期 (不是 200, 试别的)
测试: 50, 100, 150, 200 (baseline), 250, 300, 400, 500, 1000
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


def apply_f6(bars, sig, ema_arr, adx, cfg):
    idx = sig["index"]
    close = bars[idx]["close"]
    ev = ema_arr[idx]
    if ev is None or ev <= 0:
        return False
    dist = abs(close - ev) / ev
    if adx[idx] > cfg.regime_adx_high and dist > cfg.regime_ema_dist_trend:
        return False
    if sig["direction"] == "long" and close > ev:
        return True
    if sig["direction"] == "short" and close < ev:
        return True
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


def run(bars, ema_arr, sigs, adx, cfg, use_filter=True):
    trades = []
    accepted = 0
    for sig in sigs:
        if use_filter:
            if not apply_f6(bars, sig, ema_arr, adx, cfg):
                continue
        accepted += 1
        t = simulate(bars, sig, cfg)
        if t is not None:
            trades.append(t)
    n = len(trades)
    if n == 0:
        return {"n": 0, "accepted": accepted}
    wins = sum(1 for t in trades if t["win"])
    total_r = sum(t["net_r"] for t in trades)
    avg_r = total_r / n
    eq, peak, max_dd = 0, 0, 0
    for t in trades:
        eq += t["net_r"]
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)
    return {"n": n, "wins": wins, "losses": n - wins,
            "win_rate": wins / n, "total_r": total_r,
            "avg_r": avg_r, "max_dd": max_dd, "accepted": accepted}


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    cfg = VariantConfig(
        name="ema_period", body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )
    print(f"3 年 BTC 1h, {len(bars)} 根 K线")
    print("信号在 1h, EMA 也在 1h, 只改 EMA 周期\n")

    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    adx = _compute_adx(bars, 14)

    periods = [50, 100, 150, 200, 250, 300, 400, 500, 1000]
    results = []

    # 无过滤对照组
    s_no_filter = run(bars, None, sigs, adx, cfg, use_filter=False)
    results.append(("无 EMA 过滤 (对照)", 0, s_no_filter))

    for p in periods:
        ema = _compute_ema(bars, p)
        s = run(bars, ema, sigs, adx, cfg)
        label = f"EMA-{p} ({p} 小时 ≈ {p/24:.1f} 天)"
        if p == 200:
            label += " ★baseline"
        results.append((label, p, s))

    print(f"{'方案':<36} {'通过':>5} {'成交':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R':>8} {'回撤R':>8}")
    print("-" * 110)
    for label, p, s in results:
        if s["n"] == 0:
            print(f"{label:<36} {s['accepted']:>5} 无 trade")
            continue
        print(f"{label:<36} {s['accepted']:>5} {s['n']:>5} {s['wins']:>4} {s['losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+8.3f} {s['max_dd']:>+8.2f}")

    # 换 %
    R_pct = 0.026
    print("\n=== 换成 % (每单 $10,000 本金, 不复利, 1R ≈ 2.6%) ===")
    print(f"{'方案':<36} {'胜率':>7} {'3年总%':>10} {'最大回撤%':>11} {'每R($)':>8}")
    print("-" * 90)
    for label, p, s in results:
        if s["n"] == 0: continue
        total_pct = s["total_r"] * R_pct * 100
        dd_pct = s["max_dd"] * R_pct * 100
        print(f"{label:<36} {s['win_rate']*100:>6.1f}% {total_pct:>+9.1f}% {dd_pct:>+10.1f}%   $260")


if __name__ == "__main__":
    main()
