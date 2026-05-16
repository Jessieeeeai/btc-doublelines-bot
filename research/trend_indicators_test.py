"""
4 个趋势指标单测 (替换 EMA-200 作为顺势过滤)
1. MACD signal cross
2. Supertrend
3. DMI 方向 (+DI vs -DI)
4. HMA (Hull MA)
"""
import os, sys, math
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


# ========== 指标实现 ==========

def compute_macd(bars, fast=12, slow=26, signal_period=9):
    """返回每根 K 线的 bullish 状态 (MACD > Signal)"""
    closes = [b["close"] for b in bars]
    ema_fast = _compute_ema(bars, fast)
    ema_slow = _compute_ema(bars, slow)
    macd_line = [None] * len(bars)
    for i in range(len(bars)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]
    # Signal: EMA of macd_line
    signal = [None] * len(bars)
    valid_idx = [i for i, v in enumerate(macd_line) if v is not None]
    if valid_idx:
        start = valid_idx[0]
        k = 2 / (signal_period + 1)
        cur = macd_line[start]
        signal[start] = cur
        for i in range(start + 1, len(bars)):
            if macd_line[i] is None: continue
            cur = macd_line[i] * k + cur * (1 - k)
            signal[i] = cur
    # 返回 +1 / -1 / 0
    state = [0] * len(bars)
    for i in range(len(bars)):
        if macd_line[i] is None or signal[i] is None:
            state[i] = 0
        elif macd_line[i] > signal[i]:
            state[i] = 1
        else:
            state[i] = -1
    return state


def compute_supertrend(bars, period=10, factor=3.0):
    """返回每根 K 线的趋势状态 +1/-1"""
    atr = _compute_atr(bars, period)
    state = [0] * len(bars)
    upper = [None] * len(bars)
    lower = [None] * len(bars)
    prev_dir = 1
    prev_up, prev_low = None, None
    for i in range(len(bars)):
        if atr[i] is None:
            continue
        hl2 = (bars[i]["high"] + bars[i]["low"]) / 2
        basic_up = hl2 + factor * atr[i]
        basic_low = hl2 - factor * atr[i]
        # 平滑 final band
        if prev_up is None:
            final_up = basic_up
        else:
            final_up = basic_up if (basic_up < prev_up or bars[i-1]["close"] > prev_up) else prev_up
        if prev_low is None:
            final_low = basic_low
        else:
            final_low = basic_low if (basic_low > prev_low or bars[i-1]["close"] < prev_low) else prev_low

        # 方向切换
        close = bars[i]["close"]
        if prev_dir == 1:
            if close < final_low:
                cur_dir = -1
            else:
                cur_dir = 1
        else:
            if close > final_up:
                cur_dir = 1
            else:
                cur_dir = -1
        state[i] = cur_dir
        prev_dir = cur_dir
        prev_up, prev_low = final_up, final_low
        upper[i], lower[i] = final_up, final_low
    return state


def compute_dmi(bars, period=14):
    """返回每根 K 线的 +1 (+DI>-DI) / -1"""
    n = len(bars)
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    tr_list = [0.0] * n
    for i in range(1, n):
        up_move = bars[i]["high"] - bars[i-1]["high"]
        down_move = bars[i-1]["low"] - bars[i]["low"]
        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0
        tr = max(bars[i]["high"] - bars[i]["low"],
                 abs(bars[i]["high"] - bars[i-1]["close"]),
                 abs(bars[i]["low"] - bars[i-1]["close"]))
        tr_list[i] = tr

    state = [0] * n
    if n <= period:
        return state
    smooth_pdm = sum(plus_dm[1:period+1])
    smooth_mdm = sum(minus_dm[1:period+1])
    smooth_tr = sum(tr_list[1:period+1])
    for i in range(period, n):
        if i > period:
            smooth_pdm = smooth_pdm - smooth_pdm/period + plus_dm[i]
            smooth_mdm = smooth_mdm - smooth_mdm/period + minus_dm[i]
            smooth_tr = smooth_tr - smooth_tr/period + tr_list[i]
        if smooth_tr > 0:
            pdi = 100 * smooth_pdm / smooth_tr
            mdi = 100 * smooth_mdm / smooth_tr
            state[i] = 1 if pdi > mdi else -1
    return state


def _wma(values, period):
    """加权移动均线"""
    out = [None] * len(values)
    if len(values) < period: return out
    weights = list(range(1, period + 1))
    wsum = sum(weights)
    for i in range(period - 1, len(values)):
        s = sum(values[i - period + 1 + j] * weights[j] for j in range(period))
        out[i] = s / wsum
    return out


def compute_hma(bars, period=200):
    """Hull MA, 返回每根 K 线的 close > HMA → +1, else -1"""
    closes = [b["close"] for b in bars]
    half = period // 2
    sqp = int(math.sqrt(period))
    wma_half = _wma(closes, half)
    wma_full = _wma(closes, period)
    raw = []
    for i in range(len(bars)):
        if wma_half[i] is None or wma_full[i] is None:
            raw.append(None)
        else:
            raw.append(2 * wma_half[i] - wma_full[i])
    # 再 WMA(sqrt(period))
    # 跳过 None
    state = [0] * len(bars)
    valid = [(i, v) for i, v in enumerate(raw) if v is not None]
    if len(valid) < sqp:
        return state
    # 简单点: 对 raw 直接做 wma(sqp)
    cleaned = [v if v is not None else 0 for v in raw]
    hma = _wma(cleaned, sqp)
    for i in range(len(bars)):
        if hma[i] is None or raw[i] is None:
            continue
        state[i] = 1 if closes[i] > hma[i] else -1
    return state


# ========== 通用框架 ==========

def apply_filter(sig, idx, state, adx, ema, cfg, bars):
    # ADX-EMA 强趋势跳过 (这一段保留)
    if ema is not None:
        ev = ema[idx]
        if ev is not None and ev > 0:
            dist = abs(bars[idx]["close"] - ev) / ev
            if adx[idx] > cfg.regime_adx_high and dist > cfg.regime_ema_dist_trend:
                return False
    # 趋势指标方向
    s = state[idx]
    if s == 0:  # 无效
        return False
    if sig["direction"] == "long":
        return s > 0
    else:
        return s < 0


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


def run(bars, sigs, state, adx, ema, cfg):
    trades = []
    accepted = 0
    for sig in sigs:
        if not apply_filter(sig, sig["index"], state, adx, ema, cfg, bars):
            continue
        accepted += 1
        t = simulate(bars, sig, cfg)
        if t is not None:
            trades.append(t)
    n = len(trades)
    if n == 0: return {"n": 0, "accepted": accepted}
    wins = sum(1 for t in trades if t["win"])
    total_r = sum(t["net_r"] for t in trades)
    avg_r = total_r / n
    eq, peak, max_dd = 0, 0, 0
    for t in trades:
        eq += t["net_r"]; peak = max(peak, eq); max_dd = min(max_dd, eq - peak)
    return {"n": n, "wins": wins, "losses": n - wins,
            "win_rate": wins / n, "total_r": total_r,
            "avg_r": avg_r, "max_dd": max_dd, "accepted": accepted}


def baseline_run(bars, sigs, ema, adx, cfg):
    """EMA-200 顺势"""
    state = [0] * len(bars)
    for i in range(len(bars)):
        if ema[i] is not None and ema[i] > 0:
            state[i] = 1 if bars[i]["close"] > ema[i] else -1
    return run(bars, sigs, state, adx, ema, cfg)


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    cfg = VariantConfig(
        name="trend_ind", body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )
    print(f"3 年 BTC 1h, {len(bars)} 根 K线\n")

    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    ema = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)

    print("预计算各指标...")
    macd_state = compute_macd(bars)
    print("  MACD 完成")
    st_state = compute_supertrend(bars, 10, 3.0)
    print("  Supertrend 完成")
    dmi_state = compute_dmi(bars, 14)
    print("  DMI 完成")
    hma_state = compute_hma(bars, 200)
    print("  HMA 完成\n")

    schemes = [
        ("EMA-200 ★baseline", "baseline"),
        ("MACD (12,26,9)", macd_state),
        ("Supertrend (10, 3.0)", st_state),
        ("DMI 方向 (+DI vs -DI)", dmi_state),
        ("HMA-200", hma_state),
    ]

    print(f"{'方案':<28} {'通过':>5} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R':>8} {'回撤R':>8} {'3年%':>8}")
    print("-" * 110)
    R_pct = 0.026
    for label, st in schemes:
        if st == "baseline":
            s = baseline_run(bars, sigs, ema, adx, cfg)
        else:
            s = run(bars, sigs, st, adx, ema, cfg)
        if s["n"] == 0:
            print(f"{label:<28} {s['accepted']:>5} 无 trade")
            continue
        total_pct = s["total_r"] * R_pct * 100
        print(f"{label:<28} {s['accepted']:>5} {s['n']:>5} {s['wins']:>4} {s['losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+8.3f} "
              f"{s['max_dd']:>+8.2f} {total_pct:>+7.0f}%")


if __name__ == "__main__":
    main()
