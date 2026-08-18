"""
策略 A (baseline) 止盈倍数细扫描
配置: F6 + T5 容差 + 2% buffer + 突破入场, 只改 r_multiple
找精确甜点 — 比之前测得更细
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
from backtest import VariantConfig, run_backtest


def _cfg(name, r_mult):
    return VariantConfig(
        name=name,
        body_ratio=0.5,
        entanglement_tolerance=0.005,
        r_multiple=r_mult,
        sl_buffer_pct=0.020,
        entry_mode="breakout_confirm",
        entry_wait_bars=3,
        regime_mode="optimal",
        regime_adx_high=25,
        regime_ema_dist_trend=0.02,
    )


# 细扫: 0.5R 到 10R, 重点放在 1.5R - 4R 之间
VARIANTS = [
    ("TP_0.5R",  0.5),
    ("TP_1.0R",  1.0),
    ("TP_1.25R", 1.25),
    ("TP_1.5R",  1.5),
    ("TP_1.75R", 1.75),
    ("TP_2.0R★",  2.0),   # 当前 baseline
    ("TP_2.25R", 2.25),
    ("TP_2.5R",  2.5),
    ("TP_2.75R", 2.75),
    ("TP_3.0R",  3.0),
    ("TP_3.5R",  3.5),
    ("TP_4.0R",  4.0),
    ("TP_5.0R",  5.0),
    ("TP_6.0R",  6.0),
    ("TP_8.0R",  8.0),
    ("TP_10.0R", 10.0),
]


def load_bars(path):
    bars = []
    with open(path) as f:
        rd = csv.DictReader(f)
        for r in rd:
            bars.append({
                "date": r["date"],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            })
    return bars


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    print(f"3 年 BTC 1h, {len(bars)} 根 K线 (策略 A baseline 配置)")
    print(f"配置: 2% buffer / 突破入场 / F6 regime / T5 容差 0.5%\n")

    rows = []
    for name, r_mult in VARIANTS:
        cfg = _cfg(name, r_mult)
        s = run_backtest(bars, cfg)
        rows.append((name, r_mult, s))

    print(f"{'方案':<14} {'TP':>5} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R':>8} {'回撤R':>8} {'收益/回撤':>10}")
    print("-" * 100)
    R_pct = 0.026  # 1R ≈ 2.6%
    best_total = max(r[2]['total_r'] for r in rows)
    best_ratio = max(r[2]['total_r']/abs(r[2]['max_drawdown_r']) if r[2]['max_drawdown_r'] != 0 else 0 for r in rows)
    for name, r_mult, s in rows:
        dd = s['max_drawdown_r']
        ratio = s['total_r']/abs(dd) if dd != 0 else 0
        flag = ""
        if s['total_r'] == best_total: flag = " 🏆 总收益王"
        if ratio == best_ratio and ratio > 0: flag += " ⭐ 性价比王"
        print(f"{name:<14} {r_mult:>4.2f}R {s['n_trades']:>5} {s['n_wins']:>4} {s['n_losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+8.3f} "
              f"{dd:>+8.2f} {ratio:>9.2f}x{flag}")

    print("\n=== 换算成 3 年总收益 % (按 1R ≈ 2.6%, 每单 $10,000) ===")
    print(f"{'方案':<14} {'胜率':>7} {'3年总%':>10} {'最大回撤%':>11}")
    print("-" * 55)
    for name, r_mult, s in rows:
        total_pct = s['total_r'] * R_pct * 100
        dd_pct = s['max_drawdown_r'] * R_pct * 100
        print(f"{name:<14} {s['win_rate']*100:>6.1f}% {total_pct:>+9.1f}% {dd_pct:>+10.1f}%")


if __name__ == "__main__":
    main()
