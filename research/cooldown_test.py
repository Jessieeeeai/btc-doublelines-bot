"""
连亏冷却机制测试
规则: 连亏 N 次后, 暂停 X 小时不开新单, 让市场情绪冷静

测试变体:
  A. baseline (无冷却)
  B. 连亏 2 次后暂停 24h
  C. 连亏 3 次后暂停 24h
  D. 连亏 3 次后暂停 48h
  E. 连亏 3 次后暂停 72h
  F. 连亏 4 次后暂停 24h
  G. 7 天内累计亏 ≥ 3R 暂停 24h (动态规则)
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


def simulate_trade(bars, sig, cfg):
    """跑一笔, 返回 (entry_ts, exit_ts, net_r)"""
    direction = sig["direction"]
    er = _resolve_entry(bars, sig, cfg)
    if er is None: return None
    entry = er["entry"]; entry_idx = er["entry_idx"]
    entry_ts = bars[entry_idx].get("ts", entry_idx * 3600)  # 假 ts (1h 序号 × 3600)
    sl = _stop_loss_price(direction, sig, cfg.sl_buffer_pct)
    r = abs(entry - sl)
    if r <= 0: return None
    tp = entry + 2*r if direction == "long" else entry - 2*r
    for k in range(entry_idx + 1, len(bars)):
        bar = bars[k]
        exit_ts = bar.get("ts", k * 3600)
        if direction == "long":
            if bar["low"] <= sl:
                return (entry_idx, k, -1.0)
            if bar["high"] >= tp:
                return (entry_idx, k, 2.0)
        else:
            if bar["high"] >= sl:
                return (entry_idx, k, -1.0)
            if bar["low"] <= tp:
                return (entry_idx, k, 2.0)
    return None


def run_cooldown(bars, sigs, ema, adx, cfg, cooldown_rule):
    """
    cooldown_rule: 函数, 入参 (trade_history), 返回需要暂停到的 bar_idx
    trade_history: 已完成交易列表, 元素 dict {entry_idx, exit_idx, net_r}
    """
    history = []
    pause_until_idx = -1

    # 按信号 K 线索引排序处理 (但实际是按入场时间)
    # 简化: 按信号顺序遍历, 不严格按时间
    sigs_sorted = sorted(sigs, key=lambda s: s["index"])

    for sig in sigs_sorted:
        idx = sig["index"]
        # 如果当前信号在 pause 期内, 跳过
        if idx < pause_until_idx:
            continue
        if not apply_f6(bars, sig, idx, ema, adx, cfg):
            continue
        t = simulate_trade(bars, sig, cfg)
        if t is None:
            continue
        entry_idx, exit_idx, r = t
        history.append({"entry_idx": entry_idx, "exit_idx": exit_idx, "net_r": r})
        # 计算 cooldown
        new_pause = cooldown_rule(history)
        if new_pause > pause_until_idx:
            pause_until_idx = new_pause

    n = len(history)
    if n == 0: return {"n": 0}
    wins = sum(1 for t in history if t["net_r"] > 0)
    total_r = sum(t["net_r"] for t in history)
    eq, peak, max_dd = 0, 0, 0
    for t in history:
        eq += t["net_r"]; peak = max(peak, eq); max_dd = min(max_dd, eq - peak)
    # 计算最大连亏
    max_streak = cur_streak = 0
    for t in history:
        if t["net_r"] < 0:
            cur_streak += 1; max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 0
    return {"n": n, "wins": wins, "losses": n - wins,
            "win_rate": wins / n, "total_r": total_r,
            "avg_r": total_r / n, "max_dd": max_dd,
            "max_loss_streak": max_streak}


# 各种冷却规则
def no_cooldown(history): return -1


def cooldown_after_N_losses(n_losses, pause_bars):
    def rule(history):
        if len(history) < n_losses: return -1
        recent = history[-n_losses:]
        if all(t["net_r"] < 0 for t in recent):
            last_exit = history[-1]["exit_idx"]
            return last_exit + pause_bars
        return -1
    return rule


def cooldown_by_drawdown(window_bars, r_threshold, pause_bars):
    """过去 window_bars 根 K 内累计亏损 ≥ r_threshold 时暂停"""
    def rule(history):
        if not history: return -1
        last_exit = history[-1]["exit_idx"]
        cutoff = last_exit - window_bars
        recent_r = sum(t["net_r"] for t in history if t["exit_idx"] > cutoff)
        if recent_r <= -r_threshold:
            return last_exit + pause_bars
        return -1
    return rule


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    cfg = VariantConfig(
        name="cooldown", body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )
    print(f"3 年 BTC 1h, {len(bars)} 根 K线\n")

    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    ema = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)

    schemes = [
        ("★ baseline (无冷却)", no_cooldown),
        ("连亏 2 次后停 24h", cooldown_after_N_losses(2, 24)),
        ("连亏 3 次后停 24h", cooldown_after_N_losses(3, 24)),
        ("连亏 3 次后停 48h", cooldown_after_N_losses(3, 48)),
        ("连亏 3 次后停 72h", cooldown_after_N_losses(3, 72)),
        ("连亏 4 次后停 24h", cooldown_after_N_losses(4, 24)),
        ("连亏 4 次后停 48h", cooldown_after_N_losses(4, 48)),
        ("连亏 5 次后停 24h", cooldown_after_N_losses(5, 24)),
        ("7 天内累计 ≤-3R 停 24h", cooldown_by_drawdown(24*7, 3, 24)),
        ("7 天内累计 ≤-3R 停 48h", cooldown_by_drawdown(24*7, 3, 48)),
        ("3 天内累计 ≤-2R 停 24h", cooldown_by_drawdown(24*3, 2, 24)),
        ("7 天内累计 ≤-4R 停 48h", cooldown_by_drawdown(24*7, 4, 48)),
    ]

    print(f"{'方案':<32} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R':>8} {'最大连败':>9} {'回撤':>8} {'3年%':>8}")
    print("-" * 115)
    R_pct = 0.026
    for label, rule in schemes:
        s = run_cooldown(bars, sigs, ema, adx, cfg, rule)
        if s["n"] == 0: continue
        total_pct = s["total_r"] * R_pct * 100
        print(f"{label:<32} {s['n']:>5} {s['wins']:>4} {s['losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+8.3f} "
              f"{s['max_loss_streak']:>9} {s['max_dd']:>+8.2f} {total_pct:>+7.0f}%")


if __name__ == "__main__":
    main()
