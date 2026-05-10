"""
分析最深回撤期 2024-03-20 到 2025-04-01 的具体情况:
1) 比较 B2 (无趋势过滤) vs W4 (EMA200 过滤) 在该窗口的表现
2) 看那段时间到底是震荡还是趋势
3) 看 EMA-200 是否反向运作了
"""
import os
import csv
from datetime import datetime
from backtest import run_backtest, VariantConfig, _compute_ema
from equity_backtest import load_bars
from hedge_simulator import simulate_hedge

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

WINDOW_START = "2024-03-20"
WINDOW_END = "2025-04-01"


def filter_bars(bars, start, end):
    return [b for b in bars if start <= b["date"][:10] <= end]


def filter_trades(trades, start, end):
    return [t for t in trades if start <= t["entry_date"][:10] <= end]


def main():
    bars = load_bars(os.path.join(DATA_DIR, "BTCUSDT_1h.csv"))
    window_bars = filter_bars(bars, WINDOW_START, WINDOW_END)
    print(f"分析窗口: {WINDOW_START} ~ {WINDOW_END}")
    print(f"窗口内K线: {len(window_bars)} 根\n")

    # ===== 1. 该段时间到底是震荡还是趋势? =====
    btc_start = window_bars[0]["close"]
    btc_end = window_bars[-1]["close"]
    btc_high = max(b["high"] for b in window_bars)
    btc_low = min(b["low"] for b in window_bars)
    net_move = (btc_end - btc_start) / btc_start * 100
    amplitude = (btc_high - btc_low) / btc_start * 100
    # "震荡度" 评估: 高振幅 + 低净涨跌 = 震荡; 高振幅 + 高净涨跌 = 趋势
    chop_ratio = amplitude / max(abs(net_move), 1)

    print(f"=== BTC 窗口表现 ===")
    print(f"  起 ${btc_start:.0f} -> 止 ${btc_end:.0f} (净 {net_move:+.1f}%)")
    print(f"  最低 ${btc_low:.0f}, 最高 ${btc_high:.0f}, 振幅 {amplitude:.1f}%")
    print(f"  震荡比 (振幅/净涨跌): {chop_ratio:.1f}x")
    if chop_ratio > 3:
        print(f"  -> 是高震荡市 (典型反转策略友好)")
    elif chop_ratio < 1.5:
        print(f"  -> 是强趋势市")
    else:
        print(f"  -> 混合(部分震荡部分趋势)")

    # ===== 2. 对比 B2 (无过滤) vs W4 (EMA-200) 在该窗口的表现 =====
    cfgs = {
        "B2_无过滤": VariantConfig(name="B2", body_ratio=0.5, r_multiple=2.0, sl_buffer_pct=0.02,
                                    entry_mode="breakout_confirm", entry_wait_bars=3),
        "W4_EMA200": VariantConfig(name="W4", body_ratio=0.5, r_multiple=2.0, sl_buffer_pct=0.02,
                                     entry_mode="breakout_confirm", entry_wait_bars=3,
                                     ema_filter_period=200),
    }

    print(f"\n=== 该窗口对比 (R-multiple 统计) ===")
    print(f"{'策略':<14} {'信号':>5} {'胜率':>7} {'TotalR':>9} {'AvgR':>8} {'MaxDD':>7}")
    print("-" * 55)
    for name, cfg in cfgs.items():
        bt = run_backtest(bars, cfg)
        wnd_trades = filter_trades(bt["trades"], WINDOW_START, WINDOW_END)
        n = len(wnd_trades)
        wins = sum(1 for t in wnd_trades if t["win"])
        wr = wins / n if n else 0
        tot = sum(t["net_r"] for t in wnd_trades)
        avg = tot / n if n else 0
        # 最大回撤
        equity = 0; peak = 0; dd = 0
        for t in sorted(wnd_trades, key=lambda x: x["entry_date"]):
            equity += t["net_r"]
            peak = max(peak, equity)
            dd = max(dd, peak - equity)
        print(f"{name:<14} {n:>5} {wr*100:>6.1f}% {tot:>+8.2f} {avg:>+8.3f} {dd:>7.2f}")

    # ===== 3. 看 EMA-200 是不是反向运作 =====
    # 比较窗口内: 价格高于 EMA-200 时的多单 vs 低于时的多单
    # 也就是看"顺势"反转 vs "逆势"反转哪个真的赚钱
    print(f"\n=== 拆开看: EMA-200 顺势 vs 逆势 在该窗口的真实表现 ===")
    ema = _compute_ema(bars, 200)
    bt_b2 = run_backtest(bars, cfgs["B2_无过滤"])
    wnd_b2 = filter_trades(bt_b2["trades"], WINDOW_START, WINDOW_END)

    # 给每笔交易标记: 入场时 close vs EMA
    date_to_idx = {b["date"]: i for i, b in enumerate(bars)}

    cats = {
        "long_above_EMA (顺势多)": [],
        "long_below_EMA (逆势多)": [],
        "short_above_EMA (逆势空)": [],
        "short_below_EMA (顺势空)": [],
    }
    for t in wnd_b2:
        idx = date_to_idx.get(t["entry_date"])
        if idx is None:
            continue
        close = bars[idx]["close"]
        ema_val = ema[idx]
        if t["direction"] == "long":
            key = "long_above_EMA (顺势多)" if close > ema_val else "long_below_EMA (逆势多)"
        else:
            key = "short_above_EMA (逆势空)" if close > ema_val else "short_below_EMA (顺势空)"
        cats[key].append(t["net_r"])

    print(f"{'分类':<28} {'笔数':>5} {'胜率':>7} {'Total R':>9} {'Avg R':>8}")
    print("-" * 64)
    for k, lst in cats.items():
        if not lst:
            print(f"{k:<28} {0:>5} {'-':>7} {'-':>9} {'-':>8}")
            continue
        wins = sum(1 for r in lst if r > 0)
        tot = sum(lst)
        avg = tot / len(lst)
        print(f"{k:<28} {len(lst):>5} {wins/len(lst)*100:>6.1f}% {tot:>+8.2f} {avg:>+8.3f}")

    # ===== 4. 再分一下: 在 W4 视角下, 被它拒绝的信号是不是其实更赚钱? =====
    print(f"\n=== 顺势 vs 逆势 (合并: 即 EMA 过滤保留的 vs 过滤掉的) ===")
    kept = cats["long_above_EMA (顺势多)"] + cats["short_below_EMA (顺势空)"]
    rejected = cats["long_below_EMA (逆势多)"] + cats["short_above_EMA (逆势空)"]
    for label, lst in [("EMA 保留 (顺势)", kept), ("EMA 拒绝 (逆势)", rejected)]:
        if not lst:
            continue
        wins = sum(1 for r in lst if r > 0)
        tot = sum(lst)
        avg = tot / len(lst)
        print(f"  {label}: {len(lst)}笔, 胜率 {wins/len(lst)*100:.1f}%, Total {tot:+.2f}R, Avg {avg:+.3f}R")


if __name__ == "__main__":
    main()
