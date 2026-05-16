"""
基于亏损单分析的智能过滤器
1. 多空: 只做多 / 只做空 / 都做
2. 时段过滤: 跳过毒时段 (UTC 09/13/17/18/20)
3. 时段过滤: 只取吉时段 (UTC 19/21/22)
4. 周几过滤: 跳过周一/周三
5. 动量过滤: 过去 20 根动量 ≤ 0 (信号前没有强反弹)
6. EMA 距离过滤: 信号 K 距离 EMA-200 > 0.3%
7. 组合套餐
"""
import os, sys
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


def run(bars, sigs, ema, adx, cfg,
         only_long=False, only_short=False,
         skip_bad_hours=False, only_good_hours=False,
         skip_bad_weekdays=False,
         require_neg_momentum=False, momentum_threshold=0,
         require_ema_dist=False, ema_dist_min=0):
    BAD_HOURS = {9, 13, 17, 18, 20}
    GOOD_HOURS = {19, 21, 22}
    BAD_WEEKDAYS = {0, 2}  # Monday, Wednesday
    trades = []
    for sig in sigs:
        idx = sig["index"]
        if not apply_f6(bars, sig, idx, ema, adx, cfg):
            continue

        # 多/空
        if only_long and sig["direction"] != "long": continue
        if only_short and sig["direction"] != "short": continue

        # 时段
        try:
            dt = datetime.strptime(bars[idx]["date"], "%Y-%m-%d %H:%M")
            hour = dt.hour
            weekday = dt.weekday()
        except:
            hour, weekday = -1, -1
        if skip_bad_hours and hour in BAD_HOURS: continue
        if only_good_hours and hour not in GOOD_HOURS: continue
        if skip_bad_weekdays and weekday in BAD_WEEKDAYS: continue

        # 动量
        if require_neg_momentum:
            ref = max(0, idx - 20)
            mom = (bars[idx]["close"] - bars[ref]["close"]) / bars[ref]["close"] * 100
            if mom > momentum_threshold: continue

        # EMA 距离
        if require_ema_dist:
            close = bars[idx]["close"]
            ev = ema[idx]
            dist_pct = (close - ev) / ev * 100 if ev else 0
            if sig["direction"] == "long" and dist_pct < ema_dist_min: continue
            if sig["direction"] == "short" and -dist_pct < ema_dist_min: continue

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
        name="smart", body_ratio=0.5, entanglement_tolerance=0.005,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
        regime_mode="optimal", regime_adx_high=25, regime_ema_dist_trend=0.02,
    )

    print(f"3 年 BTC 1h, {len(bars)} 根 K线\n")
    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    ema = _compute_ema(bars, 200)
    adx = _compute_adx(bars, 14)

    schemes = [
        ("★ baseline (无任何额外过滤)",       {}),
        # 单一过滤
        ("仅做多单 (跳过空单)",              {"only_long": True}),
        ("仅做空单",                       {"only_short": True}),
        ("跳过毒时段 (UTC 9/13/17/18/20)",  {"skip_bad_hours": True}),
        ("只取吉时段 (UTC 19/21/22)",       {"only_good_hours": True}),
        ("跳过周一/周三",                   {"skip_bad_weekdays": True}),
        ("动量 ≤ 0 (过去 20 根没强涨)",      {"require_neg_momentum": True, "momentum_threshold": 0}),
        ("动量 ≤ -0.5%",                  {"require_neg_momentum": True, "momentum_threshold": -0.5}),
        ("离 EMA-200 ≥ 0.3%",             {"require_ema_dist": True, "ema_dist_min": 0.3}),
        ("离 EMA-200 ≥ 0.5%",             {"require_ema_dist": True, "ema_dist_min": 0.5}),

        # 双过滤组合
        ("多 + 跳毒时段",                   {"only_long": True, "skip_bad_hours": True}),
        ("多 + 跳毒时段 + 跳周一三",          {"only_long": True, "skip_bad_hours": True, "skip_bad_weekdays": True}),

        # 三过滤组合
        ("多 + 跳毒时段 + 离 EMA≥0.3%",
         {"only_long": True, "skip_bad_hours": True, "require_ema_dist": True, "ema_dist_min": 0.3}),
        ("多 + 跳毒时段 + 跳周一三 + 离 EMA≥0.3%",
         {"only_long": True, "skip_bad_hours": True, "skip_bad_weekdays": True,
          "require_ema_dist": True, "ema_dist_min": 0.3}),
        ("多 + 跳毒时段 + 动量≤0 + 离 EMA≥0.3%",
         {"only_long": True, "skip_bad_hours": True,
          "require_neg_momentum": True, "momentum_threshold": 0,
          "require_ema_dist": True, "ema_dist_min": 0.3}),

        # 极限版
        ("多 + 只取吉时段 + 离 EMA≥0.3%",
         {"only_long": True, "only_good_hours": True, "require_ema_dist": True, "ema_dist_min": 0.3}),
    ]

    print(f"{'方案':<50} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R':>8} {'回撤R':>8} {'3年%':>8}")
    print("-" * 125)
    R_pct = 0.026
    for label, kw in schemes:
        s = run(bars, sigs, ema, adx, cfg, **kw)
        if s["n"] == 0:
            print(f"{label:<50} 无 trade")
            continue
        total_pct = s["total_r"] * R_pct * 100
        print(f"{label:<50} {s['n']:>5} {s['wins']:>4} {s['losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+8.3f} "
              f"{s['max_dd']:>+8.2f} {total_pct:>+7.0f}%")


if __name__ == "__main__":
    main()
