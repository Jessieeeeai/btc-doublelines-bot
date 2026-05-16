"""
SL 和 TP 都用 Fib 算法
SL = entry − N_sl × swing_range
TP = entry + N_tp × swing_range
其中 swing_range = max(B.high, C.high) − min(B.low, C.low)

主要测: SL=1.1 swing, TP=2 swing (用户指定)
附带一些对比组合
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
from signals import detect_signals
from backtest import VariantConfig, _compute_ema, _compute_adx


def load_bars(path):
    bars = []
    with open(path) as f:
        for r in csv.DictReader(f):
            bars.append({"date": r["date"],
                         "open": float(r["open"]), "high": float(r["high"]),
                         "low": float(r["low"]), "close": float(r["close"])})
    return bars


def apply_f6(bars, sig, cfg, ema200, adx):
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


def simulate_fib(bars, sig, cfg, sl_mult, tp_mult):
    """SL/TP 都按 swing range 倍数"""
    i = sig["index"]
    direction = sig["direction"]
    swing_high = max(sig["B_high"], sig["C_high"])
    swing_low = min(sig["B_low"], sig["C_low"])
    swing_range = swing_high - swing_low
    if swing_range <= 0:
        return None

    # 入场: 突破确认 (与 baseline 一致)
    if direction == "long":
        trigger = max(sig["B_close"], sig["C_close"])
    else:
        trigger = min(sig["B_close"], sig["C_close"])

    # 入场前先扫一遍, 等突破或反向触及 SL (作废)
    max_wait = cfg.entry_wait_bars if cfg.entry_wait_bars > 0 else 9999
    entry_idx = None
    entry = None
    for j in range(i + 1, min(len(bars), i + 1 + max_wait)):
        bar = bars[j]
        if direction == "long":
            # 假设 trigger 突破后即入场, SL 用 swing-based, 这里先计算 trial SL
            trial_sl = trigger - sl_mult * swing_range
            if bar["low"] <= trial_sl:
                return None
            if bar["high"] >= trigger:
                entry = max(trigger, bar["open"]) if bar["open"] > trigger else trigger
                entry_idx = j
                break
        else:
            trial_sl = trigger + sl_mult * swing_range
            if bar["high"] >= trial_sl:
                return None
            if bar["low"] <= trigger:
                entry = min(trigger, bar["open"]) if bar["open"] < trigger else trigger
                entry_idx = j
                break
    if entry is None:
        return None

    # 入场后 SL/TP (基于实际 entry 价格)
    if direction == "long":
        sl = entry - sl_mult * swing_range
        tp = entry + tp_mult * swing_range
    else:
        sl = entry + sl_mult * swing_range
        tp = entry - tp_mult * swing_range

    r = abs(entry - sl)
    if r <= 0:
        return None

    exit_price = None
    exit_index = None
    for k in range(entry_idx + 1, len(bars)):
        bar = bars[k]
        if direction == "long":
            if bar["low"] <= sl:
                exit_price = sl; exit_index = k; break
            if bar["high"] >= tp:
                exit_price = tp; exit_index = k; break
        else:
            if bar["high"] >= sl:
                exit_price = sl; exit_index = k; break
            if bar["low"] <= tp:
                exit_price = tp; exit_index = k; break
    if exit_price is None:
        exit_price = bars[-1]["close"]
        exit_index = len(bars) - 1

    if direction == "long":
        gross_r = (exit_price - entry) / r
    else:
        gross_r = (entry - exit_price) / r
    fee = (entry + exit_price) * 0.0005 / r
    net_r = gross_r - fee
    return {"net_r": net_r, "win": net_r > 0}


def run_test(bars, cfg, sigs, ema200, adx, sl_mult, tp_mult):
    trades = []
    for sig in sigs:
        if not apply_f6(bars, sig, cfg, ema200, adx):
            continue
        t = simulate_fib(bars, sig, cfg, sl_mult, tp_mult)
        if t is not None:
            trades.append(t)
    if not trades:
        return {"n": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "total_r": 0, "max_dd": 0, "avg_r": 0}
    n = len(trades)
    wins = sum(1 for t in trades if t["win"])
    total_r = sum(t["net_r"] for t in trades)
    eq, peak, max_dd = 0, 0, 0
    for t in trades:
        eq += t["net_r"]
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)
    return {"n": n, "wins": wins, "losses": n - wins,
            "win_rate": wins / n, "total_r": total_r,
            "max_dd": max_dd, "avg_r": total_r / n}


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    cfg = VariantConfig(
        name="fib_sl_tp", body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )

    print(f"3 年 BTC 1h, {len(bars)} 根 K线")
    print("规则: SL = entry − N_sl × swing_range")
    print("     TP = entry + N_tp × swing_range")
    print("     swing_range = max(B,C).high − min(B,C).low\n")

    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    ema200 = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)
    print(f"原始信号 {len(sigs)} 个, 跑测试...\n")

    # 你要的组合 + 邻居对比
    combos = [
        (1.1, 2.0, "你要的 (1.1 swing SL, 2 swing TP)"),
        (1.0, 2.0, "1.0 swing SL"),
        (0.5, 2.0, "0.5 swing SL"),
        (1.5, 2.0, "1.5 swing SL"),
        (2.0, 2.0, "2.0 swing SL (1:1 R:R)"),
        (1.1, 3.0, "1.1 SL / 3 TP (赔率拉大)"),
        (1.1, 4.0, "1.1 SL / 4 TP"),
        (1.5, 3.0, "1.5 SL / 3 TP"),
        (1.5, 4.0, "1.5 SL / 4 TP"),
    ]

    print(f"{'组合':<42} {'赔率':>7} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R/单':>9} {'最大回撤':>9}")
    print("-" * 120)
    for sl_m, tp_m, desc in combos:
        s = run_test(bars, cfg, sigs, ema200, adx, sl_m, tp_m)
        rr = f"1:{tp_m/sl_m:.2f}"
        print(f"{desc:<42} {rr:>7} {s['n']:>5} {s['wins']:>4} {s['losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+9.3f} {s['max_dd']:>+9.2f}")

    print()
    print("Baseline 对比 (当前线上 bot 2R, 2% buffer):")
    print(f"  → 450 笔, 47.1% 胜率, +167.0R, -18.2R 回撤")


if __name__ == "__main__":
    main()
