"""
在 EMA-200 baseline 上叠加 ATR 波动率过滤
测多档: 只取 ATR 高/中/低 不同百分位区间的信号
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
from signals import detect_signals
from backtest import (VariantConfig, _resolve_entry, _stop_loss_price,
                        _compute_ema, _compute_adx, _compute_atr)


def load_bars(path):
    bars = []
    with open(path) as f:
        for r in csv.DictReader(f):
            bars.append({"date": r["date"],
                         "open": float(r["open"]), "high": float(r["high"]),
                         "low": float(r["low"]), "close": float(r["close"])})
    return bars


def apply_f6(bars, sig, idx, ema, adx, cfg):
    close = bars[idx]["close"]
    ev = ema[idx]
    if ev is None or ev <= 0: return False
    dist = abs(close - ev) / ev
    if adx[idx] > cfg.regime_adx_high and dist > cfg.regime_ema_dist_trend:
        return False
    if sig["direction"] == "long" and close > ev: return True
    if sig["direction"] == "short" and close < ev: return True
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


def percentile_value(sorted_vals, p):
    if not sorted_vals: return 0
    idx = min(len(sorted_vals) - 1, int(len(sorted_vals) * p))
    return sorted_vals[idx]


def run(bars, sigs, ema, adx, atr, atr_sorted, cfg, atr_min_pct=0, atr_max_pct=1.0):
    """ATR 在 [atr_min_pct, atr_max_pct] 百分位区间内才入场"""
    atr_min = percentile_value(atr_sorted, atr_min_pct)
    atr_max = percentile_value(atr_sorted, atr_max_pct)
    trades = []
    accepted = 0
    for sig in sigs:
        idx = sig["index"]
        if not apply_f6(bars, sig, idx, ema, adx, cfg):
            continue
        av = atr[idx]
        if av is None: continue
        if not (atr_min <= av <= atr_max):
            continue
        accepted += 1
        t = simulate(bars, sig, cfg)
        if t is not None:
            trades.append(t)
    n = len(trades)
    if n == 0: return {"n": 0, "accepted": accepted}
    wins = sum(1 for t in trades if t["win"])
    total_r = sum(t["net_r"] for t in trades)
    avg_r = total_r / n
    eq, peak, max_dd = 0, 0, 0
    for t in trades:
        eq += t["net_r"]; peak = max(peak, eq); max_dd = min(max_dd, eq - peak)
    return {"n": n, "wins": wins, "losses": n - wins,
            "win_rate": wins / n, "total_r": total_r,
            "avg_r": avg_r, "max_dd": max_dd, "accepted": accepted,
            "atr_lo": atr_min, "atr_hi": atr_max}


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    cfg = VariantConfig(
        name="atr", body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )
    print(f"3 年 BTC 1h, {len(bars)} 根 K线\n")

    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    ema = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)
    atr = _compute_atr(bars, 14)

    atr_valid = sorted([a for a in atr if a is not None and a > 0])
    print(f"ATR(14) 历史分布:")
    print(f"  10% 分位: ${percentile_value(atr_valid, 0.10):.0f}")
    print(f"  30% 分位: ${percentile_value(atr_valid, 0.30):.0f}")
    print(f"  50% 分位 (中位数): ${percentile_value(atr_valid, 0.50):.0f}")
    print(f"  70% 分位: ${percentile_value(atr_valid, 0.70):.0f}")
    print(f"  90% 分位: ${percentile_value(atr_valid, 0.90):.0f}\n")

    schemes = [
        # 最低门槛 (避开过低波动)
        ("无 ATR 过滤 ★baseline",          0.0, 1.0),
        ("ATR ≥ 20% 分位 (避太静)",        0.2, 1.0),
        ("ATR ≥ 40% 分位",                0.4, 1.0),
        ("ATR ≥ 50% 分位 (中位以上)",      0.5, 1.0),
        ("ATR ≥ 60% 分位",                0.6, 1.0),
        ("ATR ≥ 70% 分位 (高波动)",        0.7, 1.0),
        # 上限 (避开过高波动)
        ("ATR ≤ 80% 分位 (避太狂)",        0.0, 0.8),
        ("ATR ≤ 70% 分位",                0.0, 0.7),
        # 中段 (掐头去尾)
        ("ATR 30%~80% (黄金中段)",         0.3, 0.8),
        ("ATR 40%~80%",                   0.4, 0.8),
        ("ATR 40%~70%",                   0.4, 0.7),
        ("ATR 30%~70%",                   0.3, 0.7),
    ]

    print(f"{'方案':<32} {'通过':>5} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R':>8} {'回撤':>8} {'3年%':>8}")
    print("-" * 115)
    R_pct = 0.026
    for label, lo, hi in schemes:
        s = run(bars, sigs, ema, adx, atr, atr_valid, cfg, lo, hi)
        if s["n"] == 0:
            print(f"{label:<32} {s['accepted']:>5} 无 trade")
            continue
        total_pct = s["total_r"] * R_pct * 100
        print(f"{label:<32} {s['accepted']:>5} {s['n']:>5} {s['wins']:>4} {s['losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+8.3f} "
              f"{s['max_dd']:>+8.2f} {total_pct:>+7.0f}%")


if __name__ == "__main__":
    main()
