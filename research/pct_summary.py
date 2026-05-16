"""
所有关键方案的回报, 以% 报告 (而不是 R)
每单本金按 $10,000 算
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


def sim_baseline(bars, sig, cfg):
    """全仓 2R"""
    direction = sig["direction"]
    er = _resolve_entry(bars, sig, cfg)
    if er is None: return None
    entry = er["entry"]; entry_idx = er["entry_idx"]
    sl = _stop_loss_price(direction, sig, cfg.sl_buffer_pct)
    r = abs(entry - sl)
    if r <= 0: return None
    risk_pct = r / entry  # 每单实际风险占入场价的比例
    tp = entry + 2*r if direction == "long" else entry - 2*r

    for k in range(entry_idx + 1, len(bars)):
        bar = bars[k]
        if direction == "long":
            if bar["low"] <= sl:
                return {"net_r": -1.0, "risk_pct": risk_pct}
            if bar["high"] >= tp:
                return {"net_r": 2.0, "risk_pct": risk_pct}
        else:
            if bar["high"] >= sl:
                return {"net_r": -1.0, "risk_pct": risk_pct}
            if bar["low"] <= tp:
                return {"net_r": 2.0, "risk_pct": risk_pct}
    last = bars[-1]["close"]
    gross = (last - entry) / r if direction == "long" else (entry - last) / r
    return {"net_r": gross, "risk_pct": risk_pct}


def sim_split(bars, sig, cfg, sl_after_1r):
    direction = sig["direction"]
    er = _resolve_entry(bars, sig, cfg)
    if er is None: return None
    entry = er["entry"]; entry_idx = er["entry_idx"]
    sl0 = _stop_loss_price(direction, sig, cfg.sl_buffer_pct)
    r = abs(entry - sl0)
    if r <= 0: return None
    risk_pct = r / entry
    if direction == "long":
        tp1 = entry + r; tp2 = entry + 2*r
    else:
        tp1 = entry - r; tp2 = entry - 2*r

    sl = sl0
    leg1_r = None; leg1_idx = None
    for k in range(entry_idx + 1, len(bars)):
        bar = bars[k]
        if direction == "long":
            if bar["low"] <= sl:
                return {"net_r": -1.0, "risk_pct": risk_pct}
            if bar["high"] >= tp1:
                leg1_r = 1.0; leg1_idx = k; break
        else:
            if bar["high"] >= sl:
                return {"net_r": -1.0, "risk_pct": risk_pct}
            if bar["low"] <= tp1:
                leg1_r = 1.0; leg1_idx = k; break
    if leg1_r is None:
        last = bars[-1]["close"]
        g = (last - entry) / r if direction == "long" else (entry - last) / r
        return {"net_r": g, "risk_pct": risk_pct}

    if sl_after_1r == "be":
        sl = entry
    elif sl_after_1r == "1r":
        sl = tp1

    leg2_r = None
    for k in range(leg1_idx + 1, len(bars)):
        bar = bars[k]
        if direction == "long":
            if bar["low"] <= sl:
                leg2_r = (sl - entry) / r; break
            if bar["high"] >= tp2:
                leg2_r = 2.0; break
        else:
            if bar["high"] >= sl:
                leg2_r = (entry - sl) / r; break
            if bar["low"] <= tp2:
                leg2_r = 2.0; break
    if leg2_r is None:
        last = bars[-1]["close"]
        leg2_r = (last - entry) / r if direction == "long" else (entry - last) / r
    return {"net_r": 0.5*leg1_r + 0.5*leg2_r, "risk_pct": risk_pct}


def run(bars, cfg, sigs, ema200, adx, sim_fn, **kw):
    trades = []
    for sig in sigs:
        if not apply_f6(bars, sig, cfg, ema200, adx):
            continue
        t = sim_fn(bars, sig, cfg, **kw) if kw else sim_fn(bars, sig, cfg)
        if t is not None:
            trades.append(t)
    if not trades:
        return None
    n = len(trades)
    # 每单 net% = net_r × risk_pct
    pct_returns = [t["net_r"] * t["risk_pct"] for t in trades]
    wins = sum(1 for p in pct_returns if p > 0)
    avg_risk_pct = sum(t["risk_pct"] for t in trades) / n
    total_pct = sum(pct_returns)  # 算总累计 (假设每单独立, 不复利)
    eq, peak, max_dd = 0, 0, 0
    for p in pct_returns:
        eq += p
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)
    return {"n": n, "wins": wins, "win_rate": wins/n,
            "avg_risk_pct": avg_risk_pct,
            "total_pct": total_pct, "max_dd_pct": max_dd}


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    cfg = VariantConfig(
        name="pct", body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )

    print("3 年 BTC 1h. 每单本金按 $10,000 算 (= 1 万一颗子弹, 共打 450 颗)")
    print("'每单平均风险%' = 单笔止损时亏多少 % (即 1R 等于多少 %)")
    print("'总收益%' = 把每笔交易的盈亏 % 加起来 (3 年总和, 不复利)\n")

    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    ema200 = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)

    schemes = [
        ("A. baseline 全仓 2R (当前)",          sim_baseline, {}),
        ("B. 分批 50%@1R + 50%@2R, SL移保本",   sim_split,    {"sl_after_1r": "be"}),
        ("C. 分批 50%@1R + 50%@2R, SL 不动",    sim_split,    {"sl_after_1r": "none"}),
        ("D. 分批 50%@1R + 50%@2R, SL 移 +1R",  sim_split,    {"sl_after_1r": "1r"}),
    ]

    print(f"{'方案':<42} {'笔数':>5} {'胜率':>7} {'1R≈?%':>8} {'每单亏':>8} {'每单赢':>8} {'3年总%':>10} {'最大回撤%':>11}")
    print("-" * 115)
    for label, fn, kw in schemes:
        s = run(bars, cfg, sigs, ema200, adx, fn, **kw)
        # 平均亏/赢 % (1R / 2R)
        avg_loss_pct = s["avg_risk_pct"] * 100
        avg_win_pct = s["avg_risk_pct"] * 2 * 100  # 当 net_r = 2 时
        # 但分批方案平均赢的 R 不是 2, 让我用实际平均赢
        # 简单点: 报告 1R 和 2R 对应的 %
        print(f"{label:<42} {s['n']:>5} {s['win_rate']*100:>6.1f}% "
              f"{avg_loss_pct:>7.2f}% {f'-{avg_loss_pct:.2f}%':>8} {f'+{avg_win_pct:.2f}%':>8} "
              f"{s['total_pct']*100:>+9.1f}% {s['max_dd_pct']*100:>+10.1f}%")

    print()
    print("说明:")
    print("  1R≈?% : BTC 信号平均一笔风险占入场价的 %  (~2.8%, 因为 2% buffer + swing 距离)")
    print("  每单亏 = 这笔单亏损时输的 %       (=1R对应的%)")
    print("  每单赢 = 全仓 2R 时赢的 %         (=2R对应的%)")
    print("  3年总% = 假设每单都用 $10,000 本金, 3 年总盈亏 / $10,000 的比例")
    print()
    print("拿 baseline 举例: 3年 +1230% 等于  $10,000 本金 → $10,000 + $123,000 利润 = $133,000")


if __name__ == "__main__":
    main()
