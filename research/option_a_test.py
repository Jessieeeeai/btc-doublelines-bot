"""
Option A: SL = swing low 完全不加 buffer
对比 baseline (SL = swing low × 0.98, 即 2% buffer)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
from backtest import VariantConfig, run_backtest


def _cfg(name, buf):
    return VariantConfig(
        name=name, body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=buf,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )


VARIANTS = [
    ("OptionA_0%_buffer_(SL=swing_low)", 0.000),
    ("Current_2%_buffer (baseline)",     0.020),
]


def load_bars(path):
    bars = []
    with open(path) as f:
        for r in csv.DictReader(f):
            bars.append({"date": r["date"],
                         "open": float(r["open"]), "high": float(r["high"]),
                         "low": float(r["low"]), "close": float(r["close"])})
    return bars


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    print(f"3 年 BTC 1h, {len(bars)} 根 K线\n")

    print(f"{'变体':<38} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R/单':>9} {'最大回撤R':>10}")
    print("-" * 110)
    for name, buf in VARIANTS:
        cfg = _cfg(name, buf)
        s = run_backtest(bars, cfg)
        print(f"{name:<38} {s['n_trades']:>5} {s['n_wins']:>4} {s['n_losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+9.3f} {s['max_drawdown_r']:>+10.2f}")

    # 还原成最近这笔 #002 的具体 SL/TP 数字
    print("\n=== 拿你最近这笔 #002 (5/12 17:00 多) 还原一遍 ===")
    print("  入场触发: $80,492.90")
    print("  B/C swing low: $79,800 (推算: SL_2% = swing_low × 0.98 = 78,205 → swing_low ≈ 79,801)\n")

    swing_low = 78204.98 / 0.98  # 反推
    trigger = 80492.90

    for name, buf in VARIANTS:
        sl = swing_low * (1 - buf)
        r = trigger - sl
        tp = trigger + 2 * r
        loss_pct = r / trigger * 100
        win_pct = (tp - trigger) / trigger * 100
        print(f"{name}")
        print(f"   SL = ${sl:,.0f}  (距入场 {loss_pct:.2f}%, 1 万本金亏 ${10000*loss_pct/100:.0f})")
        print(f"   TP = ${tp:,.0f}  (距入场 {win_pct:.2f}%, 1 万本金赚 ${10000*win_pct/100:.0f})")
        print()


if __name__ == "__main__":
    main()
