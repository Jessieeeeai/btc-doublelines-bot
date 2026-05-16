"""
EMA-200 反向过滤测试
原逻辑 (顺势): close > EMA → 多, close < EMA → 空
反向 (逆势): close < EMA → 多 (抄底), close > EMA → 空 (摸顶)

思路: 反转策略本身就是"逆主流方向", 也许"价格被打到 EMA 下方"才是真正的底部
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
from datetime import datetime
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


def apply_filter(bars, sig, idx, ema, adx, cfg, mode):
    """
    mode:
      'forward'  → close > EMA 才接受多 (当前 baseline)
      'reverse'  → close < EMA 才接受多 (反向)
      'none'     → 不用 EMA 方向, 只跑 regime 强趋势跳过
    """
    close = bars[idx]["close"]
    ev = ema[idx]
    if ev is None or ev <= 0: return False
    dist = abs(close - ev) / ev
    if adx[idx] > cfg.regime_adx_high and dist > cfg.regime_ema_dist_trend:
        return False

    if mode == 'none': return True
    if mode == 'forward':
        if sig["direction"] == "long": return close > ev
        else: return close < ev
    if mode == 'reverse':
        if sig["direction"] == "long": return close < ev
        else: return close > ev
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
            if bar["low"] <= sl: return {"win": False, "net_r": -1.0 - 2*entry*cfg.fee_rate/r}
            if bar["high"] >= tp: return {"win": True, "net_r": 2.0 - 2*entry*cfg.fee_rate/r}
        else:
            if bar["high"] >= sl: return {"win": False, "net_r": -1.0 - 2*entry*cfg.fee_rate/r}
            if bar["low"] <= tp: return {"win": True, "net_r": 2.0 - 2*entry*cfg.fee_rate/r}
    return None


def run(bars, sigs, ema, adx, cfg, mode,
         only_long=False, only_short=False,
         skip_bad_hours=False):
    BAD_HOURS = {9, 13, 17, 18, 20}
    trades = []
    for sig in sigs:
        idx = sig["index"]
        if not apply_filter(bars, sig, idx, ema, adx, cfg, mode):
            continue
        if only_long and sig["direction"] != "long": continue
        if only_short and sig["direction"] != "short": continue
        if skip_bad_hours:
            try:
                dt = datetime.strptime(bars[idx]["date"], "%Y-%m-%d %H:%M")
                if dt.hour in BAD_HOURS: continue
            except: pass
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
        name="reverse", body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )
    print(f"3 年 BTC 1h, {len(bars)} 根 K线\n")
    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    adx = _compute_adx(bars, 14)

    print(f"{'方案':<50} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R':>8} {'回撤R':>8} {'3年%':>8}")
    print("-" * 125)
    R_pct = 0.026

    def render(label, kw):
        s = run(bars, sigs, ema, adx, cfg, **kw)
        if s["n"] == 0:
            print(f"{label:<50} 无 trade")
            return
        total_pct = s["total_r"] * R_pct * 100
        print(f"{label:<50} {s['n']:>5} {s['wins']:>4} {s['losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+8.3f} "
              f"{s['max_dd']:>+8.2f} {total_pct:>+7.0f}%")

    # 用 EMA-200 测三种 mode
    ema = _compute_ema(bars, 200)
    print("=== EMA-200 ===")
    render("forward (★ baseline 顺势)",       {"mode": "forward"})
    render("reverse (反向: 价格越逆 EMA 越接)", {"mode": "reverse"})
    render("none (无 EMA 方向过滤)",           {"mode": "none"})

    print("\n=== EMA-200 反向 + 多空过滤 ===")
    render("reverse + 仅多",     {"mode": "reverse", "only_long": True})
    render("reverse + 仅空",     {"mode": "reverse", "only_short": True})

    print("\n=== EMA-200 反向 + 跳毒时段 ===")
    render("reverse + 跳毒时段", {"mode": "reverse", "skip_bad_hours": True})
    render("reverse + 仅多 + 跳毒时段", {"mode": "reverse", "only_long": True, "skip_bad_hours": True})
    render("reverse + 仅空 + 跳毒时段", {"mode": "reverse", "only_short": True, "skip_bad_hours": True})

    # 用其他 EMA 周期测反向
    print("\n=== 不同 EMA 周期的 reverse ===")
    for p in [50, 100, 150, 250, 300, 500]:
        ema = _compute_ema(bars, p)
        render(f"EMA-{p} reverse", {"mode": "reverse"})


if __name__ == "__main__":
    main()
