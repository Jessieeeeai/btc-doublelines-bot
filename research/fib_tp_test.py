"""
用 Fib R = swing 顶 − swing 底 (B/C 高低差) 算止盈, 看实际数据怎样
SL 仍然用 2% buffer (因为前面证明过 0% buffer 会被插针扫死)
扫一遍多个 Fib R 倍数 (1~10), 找最优解

R 报告口径: 用 bot R (= 入场到 SL 的距离) 作为单位, 这样总 R 跟 baseline 直接可比
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
from signals import detect_signals
from backtest import (VariantConfig, _stop_loss_price, _resolve_entry,
                        _compute_ema, _compute_adx)


def load_bars(path):
    bars = []
    with open(path) as f:
        for r in csv.DictReader(f):
            bars.append({"date": r["date"],
                         "open": float(r["open"]), "high": float(r["high"]),
                         "low": float(r["low"]), "close": float(r["close"])})
    return bars


def apply_f6(bars, sig, cfg, ema200, adx):
    """F6 regime + EMA200 顺势过滤 (ema/adx 预算好传入)"""
    idx = sig["index"]
    close = bars[idx]["close"]
    ev = ema200[idx]
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


def simulate_with_fib_tp(bars, sig, cfg, fib_multiplier):
    """SL 用 buffer 算法, TP 用 Fib R (swing_high - swing_low) × multiplier"""
    direction = sig["direction"]
    er = _resolve_entry(bars, sig, cfg)
    if er is None:
        return None
    entry = er["entry"]
    entry_idx = er["entry_idx"]

    sl = _stop_loss_price(direction, sig, cfg.sl_buffer_pct)
    swing_high = max(sig["B_high"], sig["C_high"])
    swing_low = min(sig["B_low"], sig["C_low"])
    fib_r = swing_high - swing_low  # 纯 swing 范围

    if direction == "long":
        if sl >= entry: return None
        tp = entry + fib_multiplier * fib_r
    else:
        if sl <= entry: return None
        tp = entry - fib_multiplier * fib_r

    bot_r = abs(entry - sl)  # 这才是实际承担风险
    if bot_r <= 0: return None

    exit_price = None
    exit_index = None
    for j in range(entry_idx + 1, len(bars)):
        bar = bars[j]
        if direction == "long":
            if bar["low"] <= sl:
                exit_price = sl; exit_index = j; break
            if bar["high"] >= tp:
                exit_price = tp; exit_index = j; break
        else:
            if bar["high"] >= sl:
                exit_price = sl; exit_index = j; break
            if bar["low"] <= tp:
                exit_price = tp; exit_index = j; break
    if exit_price is None:
        exit_price = bars[-1]["close"]
        exit_index = len(bars) - 1

    # 用 bot_r 作单位 (与 baseline 同口径)
    if direction == "long":
        gross_r = (exit_price - entry) / bot_r
    else:
        gross_r = (entry - exit_price) / bot_r
    fee = (entry + exit_price) * 0.0005 / bot_r
    net_r = gross_r - fee
    return {"net_r": net_r, "win": net_r > 0}


def run_fib_test(bars, cfg, fib_mult, sigs, ema200, adx):
    trades = []
    for sig in sigs:
        if not apply_f6(bars, sig, cfg, ema200, adx):
            continue
        t = simulate_with_fib_tp(bars, sig, cfg, fib_mult)
        if t is not None:
            trades.append(t)
    if not trades:
        return {"n": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_r": 0, "max_dd": 0}
    n = len(trades)
    wins = sum(1 for t in trades if t["win"])
    losses = n - wins
    total_r = sum(t["net_r"] for t in trades)
    equity, peak, max_dd = 0, 0, 0
    for t in trades:
        equity += t["net_r"]
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return {"n": n, "wins": wins, "losses": losses,
            "win_rate": wins / n, "total_r": total_r,
            "max_dd": max_dd, "avg_r": total_r / n}


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    print(f"3 年 BTC 1h, {len(bars)} 根 K 线")
    print("规则: SL = swing_low × 0.98 (保留 2% buffer)")
    print("     TP = entry + N × (swing_high - swing_low)  ← Fib R, 你画图那个")
    print("     R 单位 = bot R (入场到 SL), 跟 baseline 同口径可比\n")

    cfg = VariantConfig(
        name="fib_tp", body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )

    print("预计算 signals / EMA200 / ADX ...")
    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    ema200 = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)
    print(f"  共 {len(sigs)} 个原始信号\n")

    print(f"{'TP':<20} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R/单':>9} {'最大回撤R':>10}")
    print("-" * 95)

    multipliers = [1, 2, 3, 4, 5, 6, 8, 10]
    rows = []
    for n in multipliers:
        s = run_fib_test(bars, cfg, n, sigs, ema200, adx)
        rows.append((n, s))
        label = f"Fib_{n}×swing"
        print(f"{label:<20} {s['n']:>5} {s['wins']:>4} {s['losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s.get('avg_r', 0):>+9.3f} {s['max_dd']:>+10.2f}")

    print()
    print("=== Baseline 对比 (当前线上配置) ===")
    print("bot_2R (TP=entry+2×bot_R) → 450笔, 47.1% 胜率, +167.0R, -18.2R 回撤")
    print()
    print("说明: Fib R ≈ bot R 的 0.3 倍 (= swing_range / 实际风险), 所以 Fib 2R 大致等价 bot 0.6R")
    print("      要跟 bot 2R 公平比较, 大概需要 Fib 6-8R 这个量级")


if __name__ == "__main__":
    main()
