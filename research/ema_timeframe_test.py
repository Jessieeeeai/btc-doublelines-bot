"""
F6 的 EMA-200 顺势过滤, 测试 3 个时间周期:
  A. 1h EMA-200  (当前 baseline, 8.3 天)
  B. 4h EMA-200  (33 天)
  C. 1D EMA-200  (200 天 ≈ 6.5 个月)

信号检测仍然在 1h 上, 只是把"顺势 EMA"换成更慢的均线
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


def aggregate(bars, factor):
    """把 1h 聚合成 N×1h 一根 (factor=4 → 4h, factor=24 → 1D)"""
    agg = []
    for i in range(0, len(bars) - factor + 1, factor):
        chunk = bars[i:i+factor]
        agg.append({
            "ts": chunk[0].get("ts", i),
            "date": chunk[0]["date"],
            "open": chunk[0]["open"],
            "high": max(b["high"] for b in chunk),
            "low": min(b["low"] for b in chunk),
            "close": chunk[-1]["close"],
            "start_idx": i,
            "end_idx": i + factor - 1,
        })
    return agg


def map_ema_to_1h(bars_1h, agg_bars, ema_agg):
    """把高级别 EMA 映射回每根 1h K 线"""
    out = [None] * len(bars_1h)
    for j, ab in enumerate(agg_bars):
        # 这个高级别 K 线已收盘后, 它的 EMA 才生效 (避免未来函数)
        # 所以 1h 的 [end_idx+1 : 下一个 end_idx+1] 区间使用这个 EMA
        if ema_agg[j] is None: continue
        start_1h = ab["end_idx"] + 1
        end_1h = agg_bars[j+1]["end_idx"] + 1 if j + 1 < len(agg_bars) else len(bars_1h)
        for k in range(start_1h, min(end_1h, len(bars_1h))):
            out[k] = ema_agg[j]
    return out


def apply_f6_custom(bars, sig, ema_arr, adx, cfg):
    idx = sig["index"]
    close = bars[idx]["close"]
    ev = ema_arr[idx]
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


def run_with_ema(bars, ema_arr, sigs, adx, cfg):
    trades = []
    accepted = 0
    rejected = 0
    for sig in sigs:
        if apply_f6_custom(bars, sig, ema_arr, adx, cfg):
            accepted += 1
            t = simulate(bars, sig, cfg)
            if t is not None:
                trades.append(t)
        else:
            rejected += 1
    n = len(trades)
    if n == 0:
        return {"n": 0, "accepted": accepted, "rejected": rejected}
    wins = sum(1 for t in trades if t["win"])
    total_r = sum(t["net_r"] for t in trades)
    avg_r = total_r / n
    eq, peak, max_dd = 0, 0, 0
    for t in trades:
        eq += t["net_r"]
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)
    return {"n": n, "wins": wins, "losses": n - wins,
            "win_rate": wins / n, "total_r": total_r,
            "avg_r": avg_r, "max_dd": max_dd,
            "accepted": accepted, "rejected": rejected}


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    cfg = VariantConfig(
        name="ema_test", body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )
    print(f"3 年 BTC 1h, {len(bars)} 根 K线\n")

    print("预计算 ...")
    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    adx = _compute_adx(bars, 14)

    # A: 1h EMA-200 (baseline)
    ema_1h = _compute_ema(bars, 200)

    # B: 4h EMA-200
    bars_4h = aggregate(bars, 4)
    ema_4h_agg = _compute_ema(bars_4h, 200)
    ema_4h = map_ema_to_1h(bars, bars_4h, ema_4h_agg)

    # C: 1D EMA-200
    bars_1d = aggregate(bars, 24)
    ema_1d_agg = _compute_ema(bars_1d, 200)
    ema_1d = map_ema_to_1h(bars, bars_1d, ema_1d_agg)

    print(f"  原始信号 {len(sigs)} 个")
    print(f"  1h EMA-200 序列长度 {sum(1 for e in ema_1h if e is not None)}")
    print(f"  4h EMA-200 映射到 1h 后有效格子数 {sum(1 for e in ema_4h if e is not None)}")
    print(f"  1D EMA-200 映射到 1h 后有效格子数 {sum(1 for e in ema_1d if e is not None)}\n")

    results = []
    for label, ema in [("A. 1h EMA-200 (当前baseline)", ema_1h),
                        ("B. 4h EMA-200 (33 天)", ema_4h),
                        ("C. 1D EMA-200 (200 天)", ema_1d)]:
        s = run_with_ema(bars, ema, sigs, adx, cfg)
        results.append((label, s))

    print(f"{'方案':<30} {'通过':>5} {'被挡':>5} {'成交':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R':>8} {'回撤':>8}")
    print("-" * 110)
    for label, s in results:
        if s["n"] == 0:
            print(f"{label:<30} {s['accepted']:>5} {s['rejected']:>5} 无 trade")
            continue
        print(f"{label:<30} {s['accepted']:>5} {s['rejected']:>5} {s['n']:>5} "
              f"{s['wins']:>4} {s['losses']:>4} {s['win_rate']*100:>6.1f}% "
              f"{s['total_r']:>+9.2f} {s['avg_r']:>+8.3f} {s['max_dd']:>+8.2f}")

    # 换成 %
    print("\n=== 换成 % (每单 $10,000 本金, 不复利) ===")
    print(f"{'方案':<30} {'胜率':>7} {'每单亏':>8} {'每单赢':>8} {'3年总%':>10} {'最大回撤%':>11}")
    print("-" * 90)
    # 假设 1R ≈ 2.6%
    R_pct = 0.026
    for label, s in results:
        if s["n"] == 0: continue
        loss = R_pct * 100
        win = R_pct * 2 * 100
        total_pct = s["total_r"] * R_pct * 100
        dd_pct = s["max_dd"] * R_pct * 100
        print(f"{label:<30} {s['win_rate']*100:>6.1f}% {f'-{loss:.2f}%':>8} {f'+{win:.2f}%':>8} "
              f"{total_pct:>+9.1f}% {dd_pct:>+10.1f}%")


if __name__ == "__main__":
    main()
