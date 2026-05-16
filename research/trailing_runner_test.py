"""
"Let your winners run" 测试组
不再分批, 而是把 TP 拉很远 (4R/6R/8R), 中途用 trailing stop 锁利

变体:
  A. baseline 全仓 2R (当前)
  B. 全仓 4R + 触及 1R 后 SL 移到入场
  C. 全仓 4R + 触及 2R 后 SL 移到 +1R
  D. 全仓 4R + 触及 1R 后 trailing SL (1×ATR 距离)
  E. 全仓 4R + 触及 1R 后 trailing SL (2×ATR 距离)
  F. 全仓 6R + 触及 2R 后 trailing SL (1.5×ATR)
  G. 全仓 6R + 触及 2R 后 trailing SL (2×ATR)
  H. 全仓 8R + 多级 SL 阶梯
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


def apply_f6(bars, sig, ema, adx, cfg):
    idx = sig["index"]
    close = bars[idx]["close"]
    ev = ema[idx]
    if ev is None or ev <= 0: return False
    dist = abs(close - ev) / ev
    if adx[idx] > cfg.regime_adx_high and dist > cfg.regime_ema_dist_trend:
        return False
    if sig["direction"] == "long" and close > ev: return True
    if sig["direction"] == "short" and close < ev: return True
    return False


def simulate_with_runner(bars, sig, cfg, atr, tp_mult, sl_rules):
    """
    sl_rules 是 (trigger_R, action) 列表, e.g.
      [(1.0, "be"), (2.0, "lock_1r")]  → 到 1R 移保本, 到 2R 锁 +1R
      [(1.0, "trail_1atr")] → 到 1R 后, SL 每根 K 跟 1×ATR 距离最高价
    """
    direction = sig["direction"]
    er = _resolve_entry(bars, sig, cfg)
    if er is None: return None
    entry = er["entry"]; entry_idx = er["entry_idx"]
    sl = _stop_loss_price(direction, sig, cfg.sl_buffer_pct)
    r = abs(entry - sl)
    if r <= 0: return None
    tp = entry + tp_mult * r if direction == "long" else entry - tp_mult * r

    triggered_levels = [False] * len(sl_rules)
    running_extreme = entry  # 多: 最高价; 空: 最低价

    for k in range(entry_idx + 1, len(bars)):
        bar = bars[k]
        # 更新极值
        if direction == "long":
            if bar["high"] > running_extreme:
                running_extreme = bar["high"]
        else:
            if bar["low"] < running_extreme:
                running_extreme = bar["low"]

        # 检查各阶段 SL 移动规则
        for j, (trig_r, action) in enumerate(sl_rules):
            if triggered_levels[j]: continue
            if direction == "long":
                trig_price = entry + trig_r * r
                if running_extreme >= trig_price:
                    triggered_levels[j] = True
                    if action == "be":
                        sl = max(sl, entry)
                    elif action == "lock_1r":
                        sl = max(sl, entry + 1 * r)
                    elif action == "lock_2r":
                        sl = max(sl, entry + 2 * r)
                    elif action.startswith("trail_") and action.endswith("atr"):
                        atr_mult = float(action.replace("trail_", "").replace("atr", ""))
                        a = atr[k] if atr[k] is not None else r
                        sl = max(sl, running_extreme - atr_mult * a)
            else:
                trig_price = entry - trig_r * r
                if running_extreme <= trig_price:
                    triggered_levels[j] = True
                    if action == "be":
                        sl = min(sl, entry)
                    elif action == "lock_1r":
                        sl = min(sl, entry - 1 * r)
                    elif action == "lock_2r":
                        sl = min(sl, entry - 2 * r)
                    elif action.startswith("trail_") and action.endswith("atr"):
                        atr_mult = float(action.replace("trail_", "").replace("atr", ""))
                        a = atr[k] if atr[k] is not None else r
                        sl = min(sl, running_extreme + atr_mult * a)

        # 持续 trailing 类规则 (每根 K 都重算)
        for j, (trig_r, action) in enumerate(sl_rules):
            if not triggered_levels[j]: continue
            if not action.startswith("trail_"): continue
            atr_mult = float(action.replace("trail_", "").replace("atr", ""))
            a = atr[k] if atr[k] is not None else r
            if direction == "long":
                new_sl = running_extreme - atr_mult * a
                sl = max(sl, new_sl)
            else:
                new_sl = running_extreme + atr_mult * a
                sl = min(sl, new_sl)

        # 检查 TP/SL 触发
        if direction == "long":
            if bar["low"] <= sl:
                gross = (sl - entry) / r
                fee = (entry + sl) * cfg.fee_rate / r
                return {"net_r": gross - fee, "win": gross > 0}
            if bar["high"] >= tp:
                gross = (tp - entry) / r
                fee = (entry + tp) * cfg.fee_rate / r
                return {"net_r": gross - fee, "win": gross > 0}
        else:
            if bar["high"] >= sl:
                gross = (entry - sl) / r
                fee = (entry + sl) * cfg.fee_rate / r
                return {"net_r": gross - fee, "win": gross > 0}
            if bar["low"] <= tp:
                gross = (entry - tp) / r
                fee = (entry + tp) * cfg.fee_rate / r
                return {"net_r": gross - fee, "win": gross > 0}

    # 末日强平
    last = bars[-1]["close"]
    if direction == "long":
        gross = (last - entry) / r
    else:
        gross = (entry - last) / r
    fee = (entry + last) * cfg.fee_rate / r
    return {"net_r": gross - fee, "win": gross > 0}


def run(bars, sigs, ema, adx, atr, cfg, tp_mult, sl_rules):
    trades = []
    for sig in sigs:
        if not apply_f6(bars, sig, ema, adx, cfg):
            continue
        t = simulate_with_runner(bars, sig, cfg, atr, tp_mult, sl_rules)
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
        name="runner", body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )
    print(f"3 年 BTC 1h, {len(bars)} 根 K线\n")

    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    ema = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)
    atr = _compute_atr(bars, 14)

    schemes = [
        ("A. 全仓 2R 直接关 ★baseline",   2.0, []),
        ("B. 全仓 4R + 1R 到了移保本",     4.0, [(1.0, "be")]),
        ("C. 全仓 4R + 2R 到了锁+1R",      4.0, [(2.0, "lock_1r")]),
        ("D. 全仓 4R + 1R 后 trail 1×ATR", 4.0, [(1.0, "trail_1.0atr")]),
        ("E. 全仓 4R + 1R 后 trail 2×ATR", 4.0, [(1.0, "trail_2.0atr")]),
        ("F. 全仓 6R + 2R 后 trail 1.5ATR", 6.0, [(2.0, "trail_1.5atr")]),
        ("G. 全仓 6R + 2R 后 trail 2×ATR",  6.0, [(2.0, "trail_2.0atr")]),
        ("H. 全仓 8R + 多级阶梯 SL",       8.0, [(2.0, "lock_1r"), (4.0, "lock_2r")]),
        ("I. 全仓 10R + 4R 后锁+2R",      10.0, [(4.0, "lock_2r")]),
        ("J. 全仓 4R 直接 (无 trailing)",   4.0, []),
        ("K. 全仓 6R 直接",               6.0, []),
    ]

    print(f"{'方案':<38} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R':>8} {'回撤':>9} {'3年%':>8}")
    print("-" * 110)
    R_pct = 0.026
    for label, tp_m, rules in schemes:
        s = run(bars, sigs, ema, adx, atr, cfg, tp_m, rules)
        if s["n"] == 0: continue
        total_pct = s["total_r"] * R_pct * 100
        print(f"{label:<38} {s['n']:>5} {s['wins']:>4} {s['losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+8.3f} "
              f"{s['max_dd']:>+9.2f} {total_pct:>+7.0f}%")


if __name__ == "__main__":
    main()
