"""
提高胜率的方案探索 (基于 baseline 2R, 不改 TP, 只调入场严格度)
目标: 从 47.1% 提到 55%+ 的同时, 总收益不要塌得太厉害
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
    tp = entry + cfg.r_multiple * r if direction == "long" else entry - cfg.r_multiple * r
    for k in range(entry_idx + 1, len(bars)):
        bar = bars[k]
        if direction == "long":
            if bar["low"] <= sl:
                return {"net_r": -1.0 - 2*entry*cfg.fee_rate/r, "win": False}
            if bar["high"] >= tp:
                return {"net_r": cfg.r_multiple - 2*entry*cfg.fee_rate/r, "win": True}
        else:
            if bar["high"] >= sl:
                return {"net_r": -1.0 - 2*entry*cfg.fee_rate/r, "win": False}
            if bar["low"] <= tp:
                return {"net_r": cfg.r_multiple - 2*entry*cfg.fee_rate/r, "win": True}
    last = bars[-1]["close"]
    gross = (last - entry) / r if direction == "long" else (entry - last) / r
    return {"net_r": gross, "win": gross > 0}


def compute_dmi_strength(bars, period=14):
    """返回每根 K 的 +DI - -DI 差值 (越大越强多头, 越负越强空头)"""
    n = len(bars)
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    tr_list = [0.0] * n
    for i in range(1, n):
        up = bars[i]["high"] - bars[i-1]["high"]
        dn = bars[i-1]["low"] - bars[i]["low"]
        plus_dm[i] = up if (up > dn and up > 0) else 0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0
        tr_list[i] = max(bars[i]["high"] - bars[i]["low"],
                         abs(bars[i]["high"] - bars[i-1]["close"]),
                         abs(bars[i]["low"] - bars[i-1]["close"]))
    di_diff = [None] * n
    if n <= period: return di_diff
    spdm = sum(plus_dm[1:period+1])
    smdm = sum(minus_dm[1:period+1])
    str_ = sum(tr_list[1:period+1])
    for i in range(period, n):
        if i > period:
            spdm = spdm - spdm/period + plus_dm[i]
            smdm = smdm - smdm/period + minus_dm[i]
            str_ = str_ - str_/period + tr_list[i]
        if str_ > 0:
            pdi = 100 * spdm / str_
            mdi = 100 * smdm / str_
            di_diff[i] = pdi - mdi
    return di_diff


def compute_volume_ma(bars, period=20):
    """简单成交量 SMA (用 high-low 当代理, 因为 CSV 可能没 volume)"""
    # 这里我们没真实成交量, 用 candle 范围 (high-low) 作为代理
    n = len(bars)
    out = [None] * n
    for i in range(period - 1, n):
        s = sum(bars[j]["high"] - bars[j]["low"] for j in range(i - period + 1, i + 1))
        out[i] = s / period
    return out


def run(bars, ema, adx, atr, di_diff, vol_ma, cfg, body_ratio_min,
         require_strong_di=False, di_threshold=0,
         require_big_candle=False, candle_mult=1.5):
    """跑一个变体"""
    sigs = detect_signals(bars, body_ratio_min, cfg.entanglement_tolerance)
    trades = []
    for sig in sigs:
        idx = sig["index"]
        if not apply_f6(bars, sig, idx, ema, adx, cfg):
            continue

        # 额外过滤 1: DI 方向强度
        if require_strong_di:
            d = di_diff[idx]
            if d is None: continue
            if sig["direction"] == "long" and d < di_threshold: continue
            if sig["direction"] == "short" and d > -di_threshold: continue

        # 额外过滤 2: 信号 K 线本身波动大于平均
        if require_big_candle:
            rng = bars[idx]["high"] - bars[idx]["low"]
            avg = vol_ma[idx]
            if avg is None or rng < candle_mult * avg: continue

        t = simulate(bars, sig, cfg)
        if t is not None:
            trades.append(t)
    n = len(trades)
    if n == 0: return {"n": 0}
    wins = sum(1 for t in trades if t["win"])
    total_r = sum(t["net_r"] for t in trades)
    eq, peak, max_dd = 0, 0, 0
    for t in trades:
        eq += t["net_r"]; peak = max(peak, eq); max_dd = min(max_dd, eq - peak)
    return {"n": n, "wins": wins, "losses": n - wins,
            "win_rate": wins / n, "total_r": total_r,
            "avg_r": total_r / n, "max_dd": max_dd}


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    cfg = VariantConfig(
        name="winrate", body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )
    print(f"3 年 BTC 1h, {len(bars)} 根 K线\n")

    ema = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)
    atr = _compute_atr(bars, 14)
    di_diff = compute_dmi_strength(bars, 14)
    vol_ma = compute_volume_ma(bars, 20)

    schemes = [
        # 基线
        ("★ baseline (body 0.5)", {"body_ratio_min": 0.5}),

        # 单纯提高 body_ratio
        ("body ≥ 0.6", {"body_ratio_min": 0.6}),
        ("body ≥ 0.7", {"body_ratio_min": 0.7}),
        ("body ≥ 0.8", {"body_ratio_min": 0.8}),

        # 要求 DI 方向强 (多单 +DI 比 -DI 至少强 X)
        ("baseline + DI 差 ≥ 5", {"body_ratio_min": 0.5, "require_strong_di": True, "di_threshold": 5}),
        ("baseline + DI 差 ≥ 10", {"body_ratio_min": 0.5, "require_strong_di": True, "di_threshold": 10}),
        ("baseline + DI 差 ≥ 15", {"body_ratio_min": 0.5, "require_strong_di": True, "di_threshold": 15}),

        # 要求信号 K 线本身波动大 (排除磨人小阴小阳)
        ("baseline + 信号K线 ≥ 1.2×均幅", {"body_ratio_min": 0.5, "require_big_candle": True, "candle_mult": 1.2}),
        ("baseline + 信号K线 ≥ 1.5×均幅", {"body_ratio_min": 0.5, "require_big_candle": True, "candle_mult": 1.5}),
        ("baseline + 信号K线 ≥ 2.0×均幅", {"body_ratio_min": 0.5, "require_big_candle": True, "candle_mult": 2.0}),

        # 组合套餐: 严格 body + DI 强
        ("body ≥ 0.7 + DI ≥ 10", {"body_ratio_min": 0.7, "require_strong_di": True, "di_threshold": 10}),
        ("body ≥ 0.6 + DI ≥ 10", {"body_ratio_min": 0.6, "require_strong_di": True, "di_threshold": 10}),

        # 三重套餐: body + DI + 大 K
        ("body ≥ 0.6 + DI≥10 + K≥1.5×",
         {"body_ratio_min": 0.6, "require_strong_di": True, "di_threshold": 10,
          "require_big_candle": True, "candle_mult": 1.5}),
        ("body ≥ 0.7 + DI≥15 + K≥1.5×",
         {"body_ratio_min": 0.7, "require_strong_di": True, "di_threshold": 15,
          "require_big_candle": True, "candle_mult": 1.5}),
    ]

    print(f"{'方案':<42} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R':>8} {'回撤R':>8} {'3年%':>8}")
    print("-" * 115)
    R_pct = 0.026
    for label, kw in schemes:
        s = run(bars, ema, adx, atr, di_diff, vol_ma, cfg, **kw)
        if s["n"] == 0:
            print(f"{label:<42} 无 trade")
            continue
        total_pct = s["total_r"] * R_pct * 100
        print(f"{label:<42} {s['n']:>5} {s['wins']:>4} {s['losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+8.3f} "
              f"{s['max_dd']:>+8.2f} {total_pct:>+7.0f}%")


if __name__ == "__main__":
    main()
