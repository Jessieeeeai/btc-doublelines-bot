"""
统计 baseline 的信号在时间上重叠的情况
答案: 平均同一时刻挂着多少单? 最多同时挂几单?
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
from signals import detect_signals
from backtest import (VariantConfig, _resolve_entry, _stop_loss_price,
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
    idx = sig["index"]
    close = bars[idx]["close"]
    ev = ema200[idx]
    if ev is None or ev <= 0: return False
    dist = abs(close - ev) / ev
    if adx[idx] > cfg.regime_adx_high and dist > cfg.regime_ema_dist_trend:
        return False
    if sig["direction"] == "long" and close > ev: return True
    if sig["direction"] == "short" and close < ev: return True
    return False


def trade_times(bars, sig, cfg):
    """返回 (entry_idx, exit_idx, direction)"""
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
            if bar["low"] <= sl or bar["high"] >= tp:
                return (entry_idx, k, direction)
        else:
            if bar["high"] >= sl or bar["low"] <= tp:
                return (entry_idx, k, direction)
    return (entry_idx, len(bars) - 1, direction)


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    cfg = VariantConfig(
        name="overlap", body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )

    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    ema200 = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)

    trades = []
    for sig in sigs:
        if not apply_f6(bars, sig, cfg, ema200, adx):
            continue
        t = trade_times(bars, sig, cfg)
        if t is not None:
            trades.append(t)
    n = len(trades)
    print(f"=== 3 年 baseline 共 {n} 笔交易 ===\n")

    # 每个 bar 上有多少单挂着?
    concurrent = [0] * len(bars)
    long_count = [0] * len(bars)
    short_count = [0] * len(bars)
    for entry_idx, exit_idx, direction in trades:
        for k in range(entry_idx, exit_idx + 1):
            concurrent[k] += 1
            if direction == "long":
                long_count[k] += 1
            else:
                short_count[k] += 1

    # 持仓时长分布
    durations = [exit_idx - entry_idx for entry_idx, exit_idx, _ in trades]
    avg_dur = sum(durations) / n
    max_dur = max(durations)

    print(f"持仓时长 (小时):")
    print(f"  平均: {avg_dur:.1f}h")
    print(f"  中位数: {sorted(durations)[n//2]}h")
    print(f"  最长: {max_dur}h ({max_dur/24:.1f} 天)\n")

    # 同时挂多少单
    bars_with_trade = [c for c in concurrent if c > 0]
    if bars_with_trade:
        avg_concurrent = sum(bars_with_trade) / len(bars_with_trade)
        max_concurrent = max(concurrent)
        print(f"同一时刻挂单数 (只看有交易的小时):")
        print(f"  平均: {avg_concurrent:.2f} 单")
        print(f"  最多: {max_concurrent} 单 (这一刻同时挂 {max_concurrent} 个单)\n")

    # 单数分布
    print("同时挂单数分布:")
    from collections import Counter
    counter = Counter(c for c in concurrent if c > 0)
    total_bars = sum(counter.values())
    for k in sorted(counter.keys()):
        v = counter[k]
        bar = "█" * int(v / total_bars * 50)
        print(f"  挂 {k} 单: {v:>5} 小时 ({v/total_bars*100:>5.1f}%) {bar}")

    # 有信号重叠的交易占比
    overlapped = 0
    for i, (ei, xi, _) in enumerate(trades):
        # 看持仓期间 (ei~xi) 是否有其他 trade 也开着
        for j, (ej, xj, _) in enumerate(trades):
            if i == j: continue
            # 区间相交
            if not (xj < ei or ej > xi):
                overlapped += 1
                break
    print(f"\n至少跟另一笔单子重叠的交易: {overlapped}/{n} = {overlapped/n*100:.1f}%")

    # 同向 vs 反向 重叠
    long_short_overlap = 0
    for k in range(len(bars)):
        if long_count[k] > 0 and short_count[k] > 0:
            long_short_overlap += 1
    print(f"同时有多单+空单挂着的小时数: {long_short_overlap} ({long_short_overlap/26280*100:.1f}% of all hours)")


if __name__ == "__main__":
    main()
