"""
SL buffer 灵敏度测试 — 在 F6 + T5 容差 基础上, 只改 sl_buffer_pct
跑 3 年 BTC 1h, 看胜率 / 总 R / 最大回撤怎么变

测试: 0.3% / 0.5% / 0.7% / 1% / 1.5% / 2% (当前 baseline)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
from backtest import VariantConfig, run_backtest


def _cfg(name, buf):
    return VariantConfig(
        name=name,
        body_ratio=0.5,
        entanglement_tolerance=0.005,  # T5
        r_multiple=2.0,
        sl_buffer_pct=buf,
        entry_mode="breakout_confirm",
        entry_wait_bars=3,
        regime_mode="optimal",
        regime_adx_high=25,
        regime_ema_dist_trend=0.02,
    )


VARIANTS = [
    ("buf_0.3%",  0.003),
    ("buf_0.5%",  0.005),
    ("buf_0.7%",  0.007),
    ("buf_1.0%",  0.010),
    ("buf_1.5%",  0.015),
    ("buf_2.0%_baseline", 0.020),
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
    print(f"  {len(bars)} 根 K线, {bars[0]['date']} ~ {bars[-1]['date']}\n")

    rows = []
    for name, buf in VARIANTS:
        cfg = _cfg(name, buf)
        s = run_backtest(bars, cfg)
        rows.append((name, buf, s))

    # R 维度
    print(f"{'变体':<22} {'buffer':>7} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R/单':>9} {'最大回撤R':>10}")
    print("-" * 100)
    for name, buf, s in rows:
        print(f"{name:<22} {buf*100:>6.2f}% {s['n_trades']:>5} {s['n_wins']:>4} {s['n_losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+9.3f} {s['max_drawdown_r']:>+10.2f}")

    # $10,000/单 换算
    # 每单亏损 ≈ R × $10,000 × buffer (因为 R 是相对入场, 等于 buffer 决定的距离)
    # 实际更精确: 用 avg_r × 总 trades × buffer × $10,000
    # 简化: 假设 1R 的美元损失 ≈ $10,000 × buffer (这是 SL 距离的近似)
    # 实际 R 用的是 trigger-SL, 与 buffer 强相关但不完全等同。这里只做粗略估算。
    print()
    print("=== 翻译成 $10,000/单 的实际盈亏 (粗略) ===")
    print(f"  说明: 1R 美金 ≈ $10,000 × buffer (因为 SL 距离主要由 buffer 决定)")
    print(f"{'变体':<22} {'1R美金':>8} {'每单赢($)':>11} {'每单输($)':>11} {'总盈亏($)':>13}")
    print("-" * 80)
    for name, buf, s in rows:
        dollar_per_R = 10000 * buf
        win_amt = dollar_per_R * 2
        loss_amt = -dollar_per_R
        total = s["total_r"] * dollar_per_R
        print(f"{name:<22} {dollar_per_R:>7.0f} {win_amt:>+11.0f} {loss_amt:>+11.0f} {total:>+13.0f}")


if __name__ == "__main__":
    main()
