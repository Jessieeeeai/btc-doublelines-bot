"""
找真实的"12 个月地狱"期 — 最大滚动回撤窗口
"""
import os, sys, json, csv
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signals import detect_signals
from backtest import (VariantConfig, _resolve_entry, _stop_loss_price,
                        _compute_ema)


def load_bars(path):
    bars = []
    with open(path) as f:
        for r in csv.DictReader(f):
            bars.append({"date": r["date"],
                         "open": float(r["open"]), "high": float(r["high"]),
                         "low": float(r["low"]), "close": float(r["close"])})
    return bars


def apply_ema_only(bars, sig, idx, ema):
    close = bars[idx]["close"]
    ev = ema[idx]
    if ev is None or ev <= 0: return False
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
    tp = entry + 2*r if direction == "long" else entry - 2*r
    for k in range(entry_idx + 1, len(bars)):
        bar = bars[k]
        if direction == "long":
            if bar["low"] <= sl: return {"net_r": -1.0, "exit_date": bar["date"]}
            if bar["high"] >= tp: return {"net_r": 2.0, "exit_date": bar["date"]}
        else:
            if bar["high"] >= sl: return {"net_r": -1.0, "exit_date": bar["date"]}
            if bar["low"] <= tp: return {"net_r": 2.0, "exit_date": bar["date"]}
    return None


def proper_max_drawdown(curve):
    """正确算最大回撤 — 滚动 peak 法"""
    peak_so_far = curve[0][1]
    peak_date = curve[0][0]
    max_dd = 0
    dd_start, dd_bottom = curve[0][0], curve[0][0]
    dd_peak_val, dd_trough_val = peak_so_far, peak_so_far
    for date, val in curve:
        if val > peak_so_far:
            peak_so_far = val
            peak_date = date
        dd = (val - peak_so_far) / peak_so_far
        if dd < max_dd:
            max_dd = dd
            dd_start = peak_date
            dd_bottom = date
            dd_peak_val = peak_so_far
            dd_trough_val = val
    return {"max_dd_pct": max_dd*100, "peak_date": dd_start, "trough_date": dd_bottom,
            "peak_val": dd_peak_val, "trough_val": dd_trough_val}


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    cfg = VariantConfig(
        name="pre_F6", body_ratio=0.5, entanglement_tolerance=0.0,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
    )
    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    ema = _compute_ema(bars, 200)

    trades = []
    for sig in sigs:
        idx = sig["index"]
        if not apply_ema_only(bars, sig, idx, ema):
            continue
        t = simulate(bars, sig, cfg)
        if t is None: continue
        trades.append(t)

    trades.sort(key=lambda x: x["exit_date"])
    n = len(trades)
    wins = sum(1 for t in trades if t["net_r"] > 0)
    print(f"5 轮迭代 (无 F6) · {n} 笔 · 胜率 {wins/n*100:.1f}% · 总 R {sum(t['net_r'] for t in trades):+.1f}\n")

    for risk_pct in [0.02, 0.05, 0.08, 0.10]:
        capital = 1000.0
        curve = [(trades[0]["exit_date"], capital)]
        for t in trades:
            gain = t["net_r"] * risk_pct
            capital = max(capital * (1 + gain), 0.01)
            curve.append((t["exit_date"], capital))

        dd = proper_max_drawdown(curve)
        try:
            d1 = datetime.strptime(dd["peak_date"].split()[0], "%Y-%m-%d")
            d2 = datetime.strptime(dd["trough_date"].split()[0], "%Y-%m-%d")
            months = (d2 - d1).days / 30
        except: months = 0

        print(f"=== Risk {risk_pct*100:.0f}% per trade ===")
        print(f"  起始 $1,000 → 终值 ${curve[-1][1]:,.0f} ({(curve[-1][1]/1000-1)*100:+.0f}%)")
        print(f"  最大回撤: {dd['max_dd_pct']:.1f}%")
        print(f"  从 {dd['peak_date']} (${dd['peak_val']:,.0f}) → {dd['trough_date']} (${dd['trough_val']:,.0f})")
        print(f"  持续 {months:.1f} 个月")
        print()


if __name__ == "__main__":
    main()
