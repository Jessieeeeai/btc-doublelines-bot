"""
亏损单分析: 把 baseline 450 单拆成赢家 vs 输家, 对比 10+ 个特征
找到"输家显著偏离赢家"的特征 → 用它做过滤器
"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
from datetime import datetime
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


def compute_rsi(bars, period=14):
    rsi = [None] * len(bars)
    gains, losses = [], []
    for i in range(1, len(bars)):
        d = bars[i]["close"] - bars[i-1]["close"]
        gains.append(max(d, 0)); losses.append(-min(d, 0))
    if len(gains) < period: return rsi
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    rs = avg_g / avg_l if avg_l > 0 else float("inf")
    rsi[period] = 100 - 100/(1+rs) if avg_l > 0 else 100
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period-1) + gains[i]) / period
        avg_l = (avg_l * (period-1) + losses[i]) / period
        rs = avg_g / avg_l if avg_l > 0 else float("inf")
        rsi[i+1] = 100 - 100/(1+rs) if avg_l > 0 else 100
    return rsi


def compute_dmi_diff(bars, period=14):
    n = len(bars)
    plus_dm = [0.0] * n; minus_dm = [0.0] * n; tr = [0.0] * n
    for i in range(1, n):
        up = bars[i]["high"] - bars[i-1]["high"]
        dn = bars[i-1]["low"] - bars[i]["low"]
        plus_dm[i] = up if (up > dn and up > 0) else 0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0
        tr[i] = max(bars[i]["high"] - bars[i]["low"],
                     abs(bars[i]["high"] - bars[i-1]["close"]),
                     abs(bars[i]["low"] - bars[i-1]["close"]))
    di_diff = [None] * n
    if n <= period: return di_diff
    sp = sum(plus_dm[1:period+1]); sm = sum(minus_dm[1:period+1]); st = sum(tr[1:period+1])
    for i in range(period, n):
        if i > period:
            sp = sp - sp/period + plus_dm[i]
            sm = sm - sm/period + minus_dm[i]
            st = st - st/period + tr[i]
        if st > 0:
            di_diff[i] = 100 * sp / st - 100 * sm / st
    return di_diff


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
            if bar["low"] <= sl: return {"win": False, "net_r": -1.0}
            if bar["high"] >= tp: return {"win": True, "net_r": 2.0}
        else:
            if bar["high"] >= sl: return {"win": False, "net_r": -1.0}
            if bar["low"] <= tp: return {"win": True, "net_r": 2.0}
    return {"win": False, "net_r": -0.5}  # 末日未结


def collect_features(bars, ema, adx, atr, rsi, di_diff, cfg, sigs):
    """收集每笔交易的特征 + 输赢标签"""
    trades = []
    for sig in sigs:
        idx = sig["index"]
        if not apply_f6(bars, sig, idx, ema, adx, cfg): continue
        result = simulate(bars, sig, cfg)
        if result is None: continue

        bar = bars[idx]
        close = bar["close"]
        ev = ema[idx]
        ema_dist = (close - ev) / ev * 100 if ev else 0
        # 过去 20 根的价格变化率 (动量)
        ref_idx = max(0, idx - 20)
        momentum_20 = (close - bars[ref_idx]["close"]) / bars[ref_idx]["close"] * 100 if bars[ref_idx]["close"] > 0 else 0
        # 这根 K 线的范围占 ATR 的比例
        candle_range = bar["high"] - bar["low"]
        atr_val = atr[idx] if atr[idx] else 1
        candle_atr_ratio = candle_range / atr_val
        # 时间维度
        try:
            dt = datetime.strptime(bar["date"], "%Y-%m-%d %H:%M")
            hour = dt.hour
            weekday = dt.weekday()
        except:
            hour, weekday = -1, -1
        # 信号 K 线和 B 之间的"价格变化"
        b_close = sig["B_close"]; c_close = sig["C_close"]
        bc_change_pct = (c_close - b_close) / b_close * 100 if b_close > 0 else 0
        # 重叠宽度占 swing 比例
        overlap_size = sig["overlap_size"]
        swing_range = max(sig["B_high"], sig["C_high"]) - min(sig["B_low"], sig["C_low"])
        overlap_ratio = overlap_size / swing_range if swing_range > 0 else 0

        trades.append({
            "win": result["win"],
            "direction": sig["direction"],
            "ema_dist": ema_dist,                    # 距离 EMA-200 的 %
            "adx": adx[idx],
            "atr_pct": atr_val / close * 100,        # ATR / close (波动率%)
            "rsi": rsi[idx],
            "di_diff": di_diff[idx],                  # +DI - -DI
            "momentum_20": momentum_20,                # 过去 20 根动量 %
            "candle_atr_ratio": candle_atr_ratio,      # 信号 K 范围 / ATR
            "body_ratio_B": sig["body_ratio_B"],
            "body_ratio_C": sig["body_ratio_C"],
            "bc_change_pct": bc_change_pct,
            "overlap_ratio": overlap_ratio,
            "hour": hour,
            "weekday": weekday,
        })
    return trades


def percentile(vals, p):
    if not vals: return None
    s = sorted([v for v in vals if v is not None])
    if not s: return None
    return s[min(len(s)-1, int(len(s) * p))]


def compare_distributions(winners, losers, feature):
    """对比某个特征在赢家/输家上的分布"""
    w = [t[feature] for t in winners if t[feature] is not None]
    l = [t[feature] for t in losers if t[feature] is not None]
    if not w or not l: return None
    return {
        "w_mean": sum(w)/len(w), "l_mean": sum(l)/len(l),
        "w_p25": percentile(w, 0.25), "l_p25": percentile(l, 0.25),
        "w_p50": percentile(w, 0.50), "l_p50": percentile(l, 0.50),
        "w_p75": percentile(w, 0.75), "l_p75": percentile(l, 0.75),
    }


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    cfg = VariantConfig(
        name="analysis", body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )

    print(f"3 年 BTC 1h, {len(bars)} 根 K线\n")
    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    ema = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)
    atr = _compute_atr(bars, 14)
    rsi = compute_rsi(bars, 14)
    di_diff = compute_dmi_diff(bars, 14)

    trades = collect_features(bars, ema, adx, atr, rsi, di_diff, cfg, sigs)
    winners = [t for t in trades if t["win"]]
    losers = [t for t in trades if not t["win"]]
    print(f"总 {len(trades)} 单: {len(winners)} 胜 / {len(losers)} 负 (胜率 {len(winners)/len(trades)*100:.1f}%)\n")

    # 1. 各特征均值/中位数对比
    features = ["ema_dist", "adx", "atr_pct", "rsi", "di_diff", "momentum_20",
                "candle_atr_ratio", "body_ratio_B", "body_ratio_C",
                "bc_change_pct", "overlap_ratio"]
    print("=== 特征分布对比 (赢家 vs 输家) ===")
    print(f"{'特征':<20} {'赢家均值':>10} {'输家均值':>10} {'差异':>8} {'赢家中位':>10} {'输家中位':>10}")
    print("-" * 80)
    for f in features:
        c = compare_distributions(winners, losers, f)
        if c is None: continue
        diff = c["w_mean"] - c["l_mean"]
        print(f"{f:<20} {c['w_mean']:>10.3f} {c['l_mean']:>10.3f} {diff:>+8.3f} "
              f"{c['w_p50']:>10.3f} {c['l_p50']:>10.3f}")

    # 2. 多空分组
    print("\n=== 多 vs 空 ===")
    long_w = sum(1 for t in winners if t["direction"] == "long")
    long_l = sum(1 for t in losers if t["direction"] == "long")
    short_w = sum(1 for t in winners if t["direction"] == "short")
    short_l = sum(1 for t in losers if t["direction"] == "short")
    print(f"多单: {long_w} 胜 / {long_l} 负 → 胜率 {long_w/(long_w+long_l)*100:.1f}%")
    print(f"空单: {short_w} 胜 / {short_l} 负 → 胜率 {short_w/(short_w+short_l)*100:.1f}%")

    # 3. 按小时分布 (UTC)
    print("\n=== 按 UTC 小时 (找有毒时段) ===")
    print(f"{'小时':<6} {'笔数':>5} {'胜率':>7} {'相对baseline':>14}")
    print("-" * 40)
    by_hour = {}
    for t in trades:
        h = t["hour"]
        if h not in by_hour: by_hour[h] = [0, 0]
        if t["win"]: by_hour[h][0] += 1
        else: by_hour[h][1] += 1
    baseline_wr = len(winners) / len(trades)
    for h in sorted(by_hour.keys()):
        w, l = by_hour[h]
        n = w + l
        if n < 5: continue  # 太少不显示
        wr = w / n
        diff = (wr - baseline_wr) * 100
        flag = " 💩" if diff < -10 else (" ✨" if diff > 10 else "")
        print(f"{h:>3}h    {n:>5} {wr*100:>6.1f}% {diff:>+13.1f}%{flag}")

    # 4. 按周几分布
    print("\n=== 按星期 (UTC) ===")
    print(f"{'周几':<8} {'笔数':>5} {'胜率':>7} {'相对baseline':>14}")
    print("-" * 40)
    wd_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    by_wd = {}
    for t in trades:
        w = t["weekday"]
        if w not in by_wd: by_wd[w] = [0, 0]
        if t["win"]: by_wd[w][0] += 1
        else: by_wd[w][1] += 1
    for w in sorted(by_wd.keys()):
        ww, ll = by_wd[w]
        n = ww + ll
        if n < 5: continue
        wr = ww / n
        diff = (wr - baseline_wr) * 100
        flag = " 💩" if diff < -5 else (" ✨" if diff > 5 else "")
        print(f"{wd_name[w]:<8} {n:>5} {wr*100:>6.1f}% {diff:>+13.1f}%{flag}")


if __name__ == "__main__":
    main()
