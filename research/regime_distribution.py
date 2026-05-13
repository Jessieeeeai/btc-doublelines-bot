import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""
统计 3 年里每个 regime 状态各占多少时间, 各自的信号 / 胜率 / R 贡献
"""
import os
from backtest import (run_backtest, VariantConfig, _compute_ema, _compute_adx,
                      _compute_atr)
from equity_backtest import load_bars
from signals import detect_signals

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def main():
    bars = load_bars(os.path.join(DATA_DIR, "BTCUSDT_1h.csv"))
    ema = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)

    # 标准阈值
    ADX_HIGH = 25
    ADX_LOW = 20
    DIST_TREND = 0.03
    DIST_CHOP = 0.015

    counts = {"trend": 0, "chop": 0, "transition": 0}
    for i in range(len(bars)):
        close = bars[i]["close"]
        ev = ema[i]
        if ev <= 0:
            continue
        dist = abs(close - ev) / ev
        if adx[i] > ADX_HIGH and dist > DIST_TREND:
            counts["trend"] += 1
        elif adx[i] < ADX_LOW and dist < DIST_CHOP:
            counts["chop"] += 1
        else:
            counts["transition"] += 1

    total = sum(counts.values())
    print(f"=== 3 年内 (26280 根 1h K线) regime 时间分布 ===")
    for k, v in counts.items():
        print(f"  {k:<12}: {v:>6} 根 ({v/total*100:.1f}%)")

    # 看每个 regime 下信号数量和 R 贡献
    cfg = VariantConfig(name="probe", body_ratio=0.5, r_multiple=2.0, sl_buffer_pct=0.02,
                        entry_mode="breakout_confirm", entry_wait_bars=3)
    bt = run_backtest(bars, cfg)
    trades = bt["trades"]
    date_to_idx = {b["date"]: i for i, b in enumerate(bars)}

    bins = {"trend": [], "chop": [], "transition": []}
    for t in trades:
        idx = date_to_idx.get(t["entry_date"])
        if idx is None: continue
        close = bars[idx]["close"]
        ev = ema[idx]
        if ev <= 0: continue
        dist = abs(close - ev) / ev
        if adx[idx] > ADX_HIGH and dist > DIST_TREND:
            bins["trend"].append(t)
        elif adx[idx] < ADX_LOW and dist < DIST_CHOP:
            bins["chop"].append(t)
        else:
            bins["transition"].append(t)

    print(f"\n=== 各 regime 信号统计 (无过滤的 B2 baseline 出 {len(trades)} 笔) ===")
    print(f"{'状态':<14} {'信号数':>6} {'占比':>6} {'胜率':>7} {'Total R':>9} {'Avg R':>8}")
    print("-" * 65)
    for k in ["trend", "chop", "transition"]:
        lst = bins[k]
        if not lst:
            print(f"{k:<14} {0:>6} {'-':>6} {'-':>7} {'-':>9} {'-':>8}")
            continue
        wins = sum(1 for t in lst if t["win"])
        tot = sum(t["net_r"] for t in lst)
        avg = tot / len(lst)
        print(f"{k:<14} {len(lst):>6} {len(lst)/len(trades)*100:>5.1f}% {wins/len(lst)*100:>6.1f}% {tot:>+8.2f} {avg:>+8.3f}")

    # 进一步: 在 trend 状态下, 顺势 vs 逆势 信号哪个赚?
    print(f"\n=== 趋势状态下: 顺势 vs 逆势 ===")
    in_trend = bins["trend"]
    for label_dir in ["顺势", "逆势"]:
        sub = []
        for t in in_trend:
            idx = date_to_idx[t["entry_date"]]
            close = bars[idx]["close"]
            ev = ema[idx]
            same_dir = (t["direction"] == "long" and close > ev) or (t["direction"] == "short" and close < ev)
            if (label_dir == "顺势" and same_dir) or (label_dir == "逆势" and not same_dir):
                sub.append(t)
        if not sub: continue
        wins = sum(1 for t in sub if t["win"])
        tot = sum(t["net_r"] for t in sub)
        print(f"  {label_dir}: {len(sub)}笔, 胜率 {wins/len(sub)*100:.1f}%, Total {tot:+.2f}R, Avg {tot/len(sub):+.3f}R")

    print(f"\n=== 震荡状态下: 顺势 vs 逆势 ===")
    in_chop = bins["chop"]
    for label_dir in ["顺势", "逆势"]:
        sub = []
        for t in in_chop:
            idx = date_to_idx[t["entry_date"]]
            close = bars[idx]["close"]
            ev = ema[idx]
            same_dir = (t["direction"] == "long" and close > ev) or (t["direction"] == "short" and close < ev)
            if (label_dir == "顺势" and same_dir) or (label_dir == "逆势" and not same_dir):
                sub.append(t)
        if not sub: continue
        wins = sum(1 for t in sub if t["win"])
        tot = sum(t["net_r"] for t in sub)
        print(f"  {label_dir}: {len(sub)}笔, 胜率 {wins/len(sub)*100:.1f}%, Total {tot:+.2f}R, Avg {tot/len(sub):+.3f}R")


if __name__ == "__main__":
    main()
