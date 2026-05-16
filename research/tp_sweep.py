"""
TP 倍数 (R-multiple) 灵敏度测试
基于 F6 + T5 容差 + 2% buffer (上一轮选出的最优), 只改 r_multiple
跑 3 年 BTC 1h, 看胜率 / 总R / 最大回撤怎么变

测试: 1.0R / 1.5R / 2.0R (baseline) / 2.5R / 3.0R / 4.0R / 5.0R
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
        sl_buffer_pct=0.020,            # 上一轮选出的最优
        entry_mode="breakout_confirm",
        entry_wait_bars=3,
        regime_mode="optimal",
        regime_adx_high=25,
        regime_ema_dist_trend=0.02,
    )


VARIANTS = [
    ("TP_1.0R",          1.0),
    ("TP_1.5R",          1.5),
    ("TP_2.0R_baseline", 2.0),
    ("TP_2.5R",          2.5),
    ("TP_3.0R",          3.0),
    ("TP_4.0R",          4.0),
    ("TP_5.0R",          5.0),
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
    print("加载 3 年 BTC 1h 数据...")
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    print(f"  {len(bars)} 根 K线\n")

    rows = []
    for name, r_mult in VARIANTS:
        cfg = _cfg(name, r_mult)
        s = run_backtest(bars, cfg)
        rows.append((name, r_mult, s))

    print(f"{'变体':<22} {'TP':>5} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R/单':>9} {'最大回撤R':>10}")
    print("-" * 100)
    for name, r, s in rows:
        print(f"{name:<22} {r:>4.1f}R {s['n_trades']:>5} {s['n_wins']:>4} {s['n_losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+9.3f} {s['max_drawdown_r']:>+10.2f}")

    print()
    # 简化美元换算: 2% buffer 下平均 1R ≈ $200 (因为 R = trigger - SL, SL 离 swing_low 2%, 加上 swing 自身范围)
    # 实际单笔 R 美元 = 入场价 × R% (R% 约 2-4%)。这里取 $200 作粗略代表。
    print("=== 翻译成 $10,000/单 的近似盈亏 (1R 美金 ≈ $200~$400) ===")
    print(f"  说明: 实际 1R 美元 = 入场价 × R%, R% 约 2-4% (浮动)")
    print(f"{'变体':<22} {'1R按$300估算':>14} {'总盈亏($)':>13}")
    print("-" * 60)
    for name, r, s in rows:
        dollar_per_R = 300
        total = s["total_r"] * dollar_per_R
        print(f"{name:<22} {dollar_per_R:>13.0f} {total:>+13.0f}")


if __name__ == "__main__":
    main()
