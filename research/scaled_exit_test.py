"""
分批止盈测试 (scaled exit)
入场: 突破确认 (跟 baseline 一致)
止损: swing low × 0.98 (2% buffer, 跟 baseline 一致)

测三套:
  A. baseline_2R   一次全部 2R 止盈 (当前)
  B. split_BE      50% 仓位 1R 止盈 → 剩 50% 把 SL 移到入场价 (保本)→ 等 2R 止盈
  C. split_noBE    50% 仓位 1R 止盈 → 剩 50% SL 不动, 继续等 2R
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


def simulate_baseline(bars, sig, cfg):
    """一次全部 2R 止盈"""
    direction = sig["direction"]
    er = _resolve_entry(bars, sig, cfg)
    if er is None:
        return None
    entry = er["entry"]; entry_idx = er["entry_idx"]
    sl = _stop_loss_price(direction, sig, cfg.sl_buffer_pct)
    r = abs(entry - sl)
    if r <= 0: return None
    if direction == "long":
        if sl >= entry: return None
        tp = entry + 2 * r
    else:
        if sl <= entry: return None
        tp = entry - 2 * r

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
    # 末日强平
    last = bars[-1]["close"]
    if direction == "long":
        gross = (last - entry) / r
    else:
        gross = (entry - last) / r
    return {"net_r": gross - 2*entry*cfg.fee_rate/r, "win": gross > 0}


def simulate_split(bars, sig, cfg, sl_after_1r):
    """
    50% 仓位 1R 止盈, 剩余 50% SL 移到 sl_after_1r 对应的位置:
      sl_after_1r="be"   → 移到入场价 (保本)
      sl_after_1r="none" → SL 不动 (保持原始)
      sl_after_1r="1r"   → 移到 +1R 价位 (锁 +1R)
    最终 net_r = 0.5×第一段R + 0.5×第二段R
    """
    direction = sig["direction"]
    er = _resolve_entry(bars, sig, cfg)
    if er is None:
        return None
    entry = er["entry"]; entry_idx = er["entry_idx"]
    sl0 = _stop_loss_price(direction, sig, cfg.sl_buffer_pct)
    r = abs(entry - sl0)
    if r <= 0: return None
    if direction == "long":
        if sl0 >= entry: return None
        tp1 = entry + 1 * r
        tp2 = entry + 2 * r
    else:
        if sl0 <= entry: return None
        tp1 = entry - 1 * r
        tp2 = entry - 2 * r

    # 阶段 1: 等 tp1 / sl
    sl = sl0
    leg1_r = None
    leg1_done_idx = None
    for k in range(entry_idx + 1, len(bars)):
        bar = bars[k]
        if direction == "long":
            if bar["low"] <= sl:
                # 全部 -1R (因为第一段都没等到 1R)
                fee = 2*entry*cfg.fee_rate/r
                return {"net_r": -1.0 - fee, "win": False}
            if bar["high"] >= tp1:
                leg1_r = +1.0
                leg1_done_idx = k
                break
        else:
            if bar["high"] >= sl:
                fee = 2*entry*cfg.fee_rate/r
                return {"net_r": -1.0 - fee, "win": False}
            if bar["low"] <= tp1:
                leg1_r = +1.0
                leg1_done_idx = k
                break
    if leg1_r is None:
        # 直到结束都没触及, 末日按市价
        last = bars[-1]["close"]
        if direction == "long":
            gross = (last - entry) / r
        else:
            gross = (entry - last) / r
        fee = 2*entry*cfg.fee_rate/r
        return {"net_r": gross - fee, "win": gross > 0}

    # 阶段 2: 剩 50% 仓位
    if sl_after_1r == "be":
        sl = entry  # 移到保本
    elif sl_after_1r == "1r":
        sl = tp1     # 移到 +1R 位 (锁定 +1R)
    # else: "none" → sl 保持 sl0

    leg2_r = None
    for k in range(leg1_done_idx + 1, len(bars)):
        bar = bars[k]
        if direction == "long":
            if bar["low"] <= sl:
                leg2_r = (sl - entry) / r  # 移BE时=0, 不动时=-1
                break
            if bar["high"] >= tp2:
                leg2_r = +2.0
                break
        else:
            if bar["high"] >= sl:
                leg2_r = (entry - sl) / r
                break
            if bar["low"] <= tp2:
                leg2_r = +2.0
                break
    if leg2_r is None:
        last = bars[-1]["close"]
        if direction == "long":
            leg2_r = (last - entry) / r
        else:
            leg2_r = (entry - last) / r

    # 综合: 一半仓位 ×1R + 一半仓位 ×leg2_r, 手续费按 2 倍入出算
    fee_per_unit = 2*entry*cfg.fee_rate/r  # 每"全仓"的手续费(以R计)
    net_r = 0.5 * leg1_r + 0.5 * leg2_r - fee_per_unit
    return {"net_r": net_r, "win": net_r > 0}


def run(bars, cfg, sigs, ema200, adx, sim_fn, **kw):
    trades = []
    for sig in sigs:
        if not apply_f6(bars, sig, cfg, ema200, adx):
            continue
        t = sim_fn(bars, sig, cfg, **kw)
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
        name="scaled_exit", body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )

    print(f"3 年 BTC 1h, {len(bars)} 根 K线")
    print("入场: 突破确认 / 止损: swing low × 0.98 (2% buffer)\n")

    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    ema200 = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)
    print(f"原始 {len(sigs)} 个信号\n")

    a = run(bars, cfg, sigs, ema200, adx, simulate_baseline)
    b = run(bars, cfg, sigs, ema200, adx, simulate_split, sl_after_1r="be")
    c = run(bars, cfg, sigs, ema200, adx, simulate_split, sl_after_1r="none")
    d = run(bars, cfg, sigs, ema200, adx, simulate_split, sl_after_1r="1r")

    print(f"{'方案':<45} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R':>8} {'回撤':>8}")
    print("-" * 110)
    for label, s in [
        ("A. baseline (全仓 2R, 当前)", a),
        ("B. 分批 (50% @1R + 50% @2R, SL移保本)", b),
        ("C. 分批 (50% @1R + 50% @2R, SL 不动)", c),
        ("D. 分批 (50% @1R + 50% @2R, SL 移到 +1R)", d),
    ]:
        print(f"{label:<42} {s['n']:>5} {s['wins']:>4} {s['losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+8.3f} {s['max_dd']:>+8.2f}")


if __name__ == "__main__":
    main()
