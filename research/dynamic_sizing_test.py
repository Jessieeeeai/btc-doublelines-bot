"""
动态仓位 + 加仓 + 反向出场 — 在 "H + 连亏 2 停 24h" 基础上继续找 alpha

新方向:
1. Kelly 仓位 — 连胜后下一单加仓, 连败后回归
2. 金字塔加仓 — 达到 +1R 时加 0.5× 仓位 (顺势加仓)
3. 反向信号平仓 — 持仓中出现反向信号, 强制平仓
4. 波动率感知仓位 — 低 ATR 时仓位 1.5×, 高 ATR 时仓位 0.5×
5. 时段感知仓位 — 吉时段 1.5×, 一般时段 1×, 毒时段跳过
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


def simulate_with_H(bars, sig, cfg, sigs_lookup=None, allow_inverse_exit=False, pyramid=False):
    """
    H 阶梯锁版 (8R, 2R 锁 1R, 4R 锁 2R)
    可选: 加仓 (pyramid) 和反向出场
    """
    direction = sig["direction"]
    er = _resolve_entry(bars, sig, cfg)
    if er is None: return None
    entry = er["entry"]; entry_idx = er["entry_idx"]
    sl0 = _stop_loss_price(direction, sig, cfg.sl_buffer_pct)
    r = abs(entry - sl0)
    if r <= 0: return None
    tp = entry + 8*r if direction == "long" else entry - 8*r
    sl = sl0
    pyramided = False
    pyramid_entry = None  # 加仓的入场价
    running_ext = entry
    triggered_1r = False
    triggered_2r = False

    for k in range(entry_idx + 1, len(bars)):
        bar = bars[k]
        # 更新极值
        if direction == "long":
            running_ext = max(running_ext, bar["high"])
        else:
            running_ext = min(running_ext, bar["low"])

        # 反向信号检查
        if allow_inverse_exit and sigs_lookup is not None:
            for s2 in sigs_lookup.get(k, []):
                if s2["direction"] != direction:
                    # 平仓: 用当前 close
                    px = bar["close"]
                    gross = (px - entry) / r if direction == "long" else (entry - px) / r
                    r_extra = 0
                    if pyramided and pyramid_entry is not None:
                        if direction == "long":
                            r_extra = 0.5 * (px - pyramid_entry) / r
                        else:
                            r_extra = 0.5 * (pyramid_entry - px) / r
                    return (entry_idx, k, gross + r_extra)

        # H 阶梯锁
        if direction == "long":
            if not triggered_1r and running_ext >= entry + 2*r:
                sl = max(sl, entry + r); triggered_1r = True
            if not triggered_2r and running_ext >= entry + 4*r:
                sl = max(sl, entry + 2*r); triggered_2r = True
        else:
            if not triggered_1r and running_ext <= entry - 2*r:
                sl = min(sl, entry - r); triggered_1r = True
            if not triggered_2r and running_ext <= entry - 4*r:
                sl = min(sl, entry - 2*r); triggered_2r = True

        # 加仓 (达到 +1R 时加 0.5×)
        if pyramid and not pyramided:
            if direction == "long" and bar["high"] >= entry + r:
                pyramid_entry = entry + r
                pyramided = True
            elif direction == "short" and bar["low"] <= entry - r:
                pyramid_entry = entry - r
                pyramided = True

        # 检查出场
        if direction == "long":
            if bar["low"] <= sl:
                gross = (sl - entry) / r
                r_extra = 0
                if pyramided and pyramid_entry is not None:
                    r_extra = 0.5 * (sl - pyramid_entry) / r
                return (entry_idx, k, gross + r_extra)
            if bar["high"] >= tp:
                gross = 8.0
                r_extra = 0
                if pyramided and pyramid_entry is not None:
                    r_extra = 0.5 * (tp - pyramid_entry) / r
                return (entry_idx, k, gross + r_extra)
        else:
            if bar["high"] >= sl:
                gross = (entry - sl) / r
                r_extra = 0
                if pyramided and pyramid_entry is not None:
                    r_extra = 0.5 * (pyramid_entry - sl) / r
                return (entry_idx, k, gross + r_extra)
            if bar["low"] <= tp:
                gross = 8.0
                r_extra = 0
                if pyramided and pyramid_entry is not None:
                    r_extra = 0.5 * (pyramid_entry - tp) / r
                return (entry_idx, k, gross + r_extra)
    return None


def run(bars, sigs, ema, adx, atr, cfg,
         use_cooldown=True, loss_threshold=2, pause_bars=24,
         use_kelly=False,  # 连胜加仓
         use_pyramid=False,
         use_vol_sizing=False,
         use_time_sizing=False,
         use_inverse_exit=False,
         direction_aware=False,
         only_long=False,
         skip_bad_hours=False):
    """带各种修饰的回测, 返回总 R 和统计"""
    history = []
    pause_until = -1
    pause_dir = None
    BAD_HOURS = {9, 13, 17, 18, 20}
    GOOD_HOURS = {19, 21, 22}

    # 准备反向信号 lookup (按 bar index 索引)
    sigs_lookup = {}
    if use_inverse_exit:
        for s in sigs:
            sigs_lookup.setdefault(s["index"], []).append(s)

    # 计算 ATR 百分位 (用于 vol sizing)
    atr_valid = sorted([a for a in atr if a is not None])
    p33 = atr_valid[len(atr_valid)//3] if atr_valid else 0
    p67 = atr_valid[2*len(atr_valid)//3] if atr_valid else 0

    sigs_sorted = sorted(sigs, key=lambda s: s["index"])
    for sig in sigs_sorted:
        idx = sig["index"]

        if only_long and sig["direction"] != "long": continue

        try:
            dt = datetime.strptime(bars[idx]["date"], "%Y-%m-%d %H:%M")
            hour = dt.hour
        except: hour = -1

        if skip_bad_hours and hour in BAD_HOURS: continue

        # 冷却
        if use_cooldown and idx < pause_until:
            if not direction_aware or (direction_aware and sig["direction"] == pause_dir):
                continue

        if not apply_f6(bars, sig, idx, ema, adx, cfg):
            continue

        t = simulate_with_H(bars, sig, cfg, sigs_lookup if use_inverse_exit else None,
                            allow_inverse_exit=use_inverse_exit, pyramid=use_pyramid)
        if t is None: continue
        entry_idx, exit_idx, r = t

        # 仓位计算
        size = 1.0
        if use_kelly:
            # 看最近 3 笔, 连胜 ≥ 2 次 → 1.5×, 连胜 ≥ 3 次 → 2×, 连败 → 0.5×
            recent = history[-3:] if len(history) >= 3 else history
            if len(recent) >= 2 and all(t["net_r"] > 0 for t in recent[-2:]):
                size = 1.5
            if len(recent) >= 3 and all(t["net_r"] > 0 for t in recent):
                size = 2.0
            if len(recent) >= 1 and recent[-1]["net_r"] < 0:
                size = 0.7

        if use_vol_sizing:
            a = atr[idx] if atr[idx] else p33
            if a < p33: size = 1.5      # 低波动 = 反转更可靠 = 大仓
            elif a > p67: size = 0.5    # 高波动 = 风险大 = 小仓
            else: size = 1.0

        if use_time_sizing:
            if hour in GOOD_HOURS: size = 1.5
            elif hour in BAD_HOURS: continue  # 直接跳
            else: size = 1.0

        scaled_r = r * size
        history.append({"entry_idx": entry_idx, "exit_idx": exit_idx,
                         "net_r": scaled_r, "raw_r": r,
                         "direction": sig["direction"], "size": size})

        # 冷却触发 (基于原始 r, 不是 scaled)
        if use_cooldown and loss_threshold > 0 and len(history) >= loss_threshold:
            recent_raw = history[-loss_threshold:]
            if all(t["raw_r"] < 0 for t in recent_raw):
                last_exit = recent_raw[-1]["exit_idx"]
                if last_exit + pause_bars > pause_until:
                    pause_until = last_exit + pause_bars
                    pause_dir = recent_raw[-1]["direction"]

    n = len(history)
    if n == 0: return {"n": 0}
    wins = sum(1 for t in history if t["net_r"] > 0)
    total_r = sum(t["net_r"] for t in history)
    eq, peak, max_dd = 0, 0, 0
    for t in history:
        eq += t["net_r"]; peak = max(peak, eq); max_dd = min(max_dd, eq - peak)
    return {"n": n, "wins": wins, "losses": n - wins,
            "win_rate": wins / n, "total_r": total_r,
            "avg_r": total_r / n, "max_dd": max_dd}


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    cfg = VariantConfig(
        name="dyn", body_ratio=0.5, entanglement_tolerance=0.005,
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
        ("★ H + 连亏 2 停 24h (前王)",     {}),
        ("+ Kelly 加仓 (连胜后 1.5×/2×)",   {"use_kelly": True}),
        ("+ 金字塔 (1R 后加 0.5×)",         {"use_pyramid": True}),
        ("+ 波动率仓位 (低 ATR 1.5×)",       {"use_vol_sizing": True}),
        ("+ 时段加仓 (吉时段 1.5×)",         {"use_time_sizing": True}),
        ("+ 反向信号平仓",                  {"use_inverse_exit": True}),

        # 双叠加
        ("+ Kelly + 金字塔",                {"use_kelly": True, "use_pyramid": True}),
        ("+ Kelly + 单向冷却",              {"use_kelly": True, "direction_aware": True}),
        ("+ 金字塔 + 单向冷却",              {"use_pyramid": True, "direction_aware": True}),
        ("+ 时段加仓 + 单向冷却",            {"use_time_sizing": True, "direction_aware": True}),

        # 三叠加
        ("+ Kelly + 金字塔 + 单向冷却",      {"use_kelly": True, "use_pyramid": True, "direction_aware": True}),
        ("+ 金字塔 + 波动率仓位 + 单向冷却",  {"use_pyramid": True, "use_vol_sizing": True, "direction_aware": True}),

        # 仅多 组合
        ("+ 金字塔 + 仅多",                 {"use_pyramid": True, "only_long": True}),
        ("+ 金字塔 + 仅多 + 单向冷却",        {"use_pyramid": True, "only_long": True, "direction_aware": True}),

        # 终极王
        ("+ Kelly + 金字塔 + 时段 + 单向",   {"use_kelly": True, "use_pyramid": True, "use_time_sizing": True, "direction_aware": True}),
    ]

    print(f"{'方案':<42} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R':>8} {'回撤':>8} {'3年%':>8}")
    print("-" * 115)
    R_pct = 0.026
    for label, kw in schemes:
        s = run(bars, sigs, ema, adx, atr, cfg, **kw)
        if s["n"] == 0: continue
        total_pct = s["total_r"] * R_pct * 100
        print(f"{label:<42} {s['n']:>5} {s['wins']:>4} {s['losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+8.3f} "
              f"{s['max_dd']:>+8.2f} {total_pct:>+7.0f}%")


if __name__ == "__main__":
    main()
