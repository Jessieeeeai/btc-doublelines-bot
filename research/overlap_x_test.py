"""
用"重叠部分 x"做 SL/TP 基准
入场 = 下一根 K 开盘价 (next_bar_open)
TP   = overlap_hi + 2x     ← 重叠顶 + 2 倍重叠宽
SL   = overlap_hi − 1.1x   ← 重叠顶 − 1.1 倍重叠宽 (略低于 overlap_lo)
其中 x = overlap_hi − overlap_lo

(多单。空单镜像: TP=overlap_lo−2x, SL=overlap_lo+1.1x)

并搜邻居参数, 看有没有更好的甜点
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


def simulate(bars, sig, sl_x_mult, tp_x_mult):
    """next_bar_open 入场 + overlap-based SL/TP"""
    i = sig["index"]
    if i + 1 >= len(bars):
        return None
    entry_bar = bars[i + 1]
    entry = entry_bar["open"]
    entry_idx = i + 1

    overlap_hi = sig["overlap_hi"]
    overlap_lo = sig["overlap_lo"]
    x = overlap_hi - overlap_lo
    if x <= 0:
        return None

    direction = sig["direction"]
    if direction == "long":
        tp = overlap_hi + tp_x_mult * x
        sl = overlap_hi - sl_x_mult * x
        # 健全性
        if sl >= entry or tp <= entry:
            return None
    else:
        tp = overlap_lo - tp_x_mult * x
        sl = overlap_lo + sl_x_mult * x
        if sl <= entry or tp >= entry:
            return None

    r_dollar = abs(entry - sl)
    if r_dollar <= 0:
        return None

    exit_price = None
    exit_index = None
    # 同根入场 K (i+1) 也要扫 — 因为 K 收完才知道一根内是否触及 TP/SL
    # 但开盘价就 SL, 立刻止损; 开盘价就 TP, 立刻止盈
    # 这里按"同根入场 K 也参与" 处理: 从 entry_idx 开始扫
    for k in range(entry_idx, len(bars)):
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
        gross_r = (exit_price - entry) / r_dollar
    else:
        gross_r = (entry - exit_price) / r_dollar
    fee = (entry + exit_price) * 0.0005 / r_dollar
    net_r = gross_r - fee
    return {"net_r": net_r, "win": net_r > 0,
            "entry": entry, "sl": sl, "tp": tp, "x": x}


def run(bars, cfg, sigs, ema200, adx, sl_x, tp_x):
    trades = []
    for sig in sigs:
        if not apply_f6(bars, sig, cfg, ema200, adx):
            continue
        t = simulate(bars, sig, sl_x, tp_x)
        if t is not None:
            trades.append(t)
    if not trades:
        return None
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
        name="overlap_x", body_ratio=0.5, entanglement_tolerance=0.005,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )

    print(f"3 年 BTC 1h, {len(bars)} 根 K线")
    print("入场 = 下一根 K 开盘价")
    print("TP = overlap_hi + tp_mult × x  (多)")
    print("SL = overlap_hi − sl_mult × x  (多)")
    print("x = overlap_hi − overlap_lo (B、C 实体重叠宽度)\n")

    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    ema200 = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)
    print(f"原始 {len(sigs)} 个信号, 跑测试...\n")

    combos = [
        (1.1, 2.0, "★ 你要的 (1.1 SL / 2 TP)"),
        (0.5, 2.0, "0.5 SL / 2 TP (赔率拉大)"),
        (0.8, 2.0, "0.8 SL / 2 TP"),
        (1.0, 2.0, "1.0 SL / 2 TP"),
        (1.5, 2.0, "1.5 SL / 2 TP (保守)"),
        (2.0, 2.0, "2.0 SL / 2 TP (1:1)"),
        (1.1, 1.5, "1.1 SL / 1.5 TP"),
        (1.1, 3.0, "1.1 SL / 3 TP"),
        (1.1, 4.0, "1.1 SL / 4 TP"),
        (0.5, 3.0, "0.5 SL / 3 TP"),
        (0.8, 3.0, "0.8 SL / 3 TP"),
    ]

    print(f"{'组合':<35} {'赔率':>9} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R':>8} {'回撤':>8}")
    print("-" * 115)
    for sl_x, tp_x, desc in combos:
        s = run(bars, cfg, sigs, ema200, adx, sl_x, tp_x)
        if s is None:
            continue
        # 多单时, 入场 ≈ overlap_hi, 所以实际 R 距离 ≈ sl_x × x, 实际 reward ≈ (tp_x − 0) × x = tp_x × x
        # 真实赔率取决于 entry vs overlap_hi 的差, 这里大致按 tp_x / sl_x 估算
        rr = f"~1:{tp_x/sl_x:.2f}"
        print(f"{desc:<35} {rr:>9} {s['n']:>5} {s['wins']:>4} {s['losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+8.3f} {s['max_dd']:>+8.2f}")

    # 拿 #002 实际数据演示
    print("\n=== 信号 #002 (5/12 17:00 多单) 用 1.1 SL / 2 TP 还原 ===")
    target_idx = None
    for j, sig in enumerate(sigs):
        if bars[sig["index"]]["date"] == "2026-05-12 17:00":
            target_idx = j
            break
    if target_idx is not None and apply_f6(bars, sigs[target_idx], cfg, ema200, adx):
        sig = sigs[target_idx]
        t = simulate(bars, sig, 1.1, 2.0)
        x = sig["overlap_hi"] - sig["overlap_lo"]
        print(f"  overlap_hi  = ${sig['overlap_hi']:.2f}")
        print(f"  overlap_lo  = ${sig['overlap_lo']:.2f}")
        print(f"  x (重叠宽)   = ${x:.2f}")
        print(f"  入场 (下根 K 开盘) = ${t['entry']:.2f}")
        print(f"  SL = overlap_hi − 1.1x = ${t['sl']:.2f}")
        print(f"  TP = overlap_hi + 2x   = ${t['tp']:.2f}")
        loss_pct = abs(t['entry'] - t['sl']) / t['entry'] * 100
        win_pct = abs(t['tp'] - t['entry']) / t['entry'] * 100
        print(f"  → 1 万本金: 输 ${loss_pct*100:.0f} ({loss_pct:.2f}%), 赢 ${win_pct*100:.0f} ({win_pct:.2f}%)")
    else:
        print("  (信号 #002 在本地 3 年数据范围之外, 跳过)")

    print(f"\nBaseline 对比 (当前线上 bot 2R + 2% buffer):")
    print(f"  450 笔, 47.1% 胜率, +167.0R, -18.2R 回撤")


if __name__ == "__main__":
    main()
