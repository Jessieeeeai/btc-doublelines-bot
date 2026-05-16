"""
冷却机制进阶测试 - 在 "连亏 2 停 24h" 基础上探索更多组合
1. 暂停时长扫盘 (6h~168h)
2. 暂停 + 跳毒时段
3. 暂停 + H 阶梯锁 (8R, 触及 2R 锁+1R, 触及 4R 锁+2R)
4. 暂停 + 只多
5. 单向暂停 (只暂停连亏的那个方向)
6. 暂停后高质量过滤 (body ≥ 0.6)
7. 连胜激进 (连胜 3 次后 TP 拉到 3R)
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


def simulate_trade(bars, sig, cfg, tp_mult=2.0, use_runner=False, atr=None):
    """跑一笔. use_runner=True 时 启用 H 阶梯锁逻辑"""
    direction = sig["direction"]
    er = _resolve_entry(bars, sig, cfg)
    if er is None: return None
    entry = er["entry"]; entry_idx = er["entry_idx"]
    sl0 = _stop_loss_price(direction, sig, cfg.sl_buffer_pct)
    r = abs(entry - sl0)
    if r <= 0: return None
    tp = entry + tp_mult * r if direction == "long" else entry - tp_mult * r
    sl = sl0
    triggered = {"lock1r": False, "lock2r": False}
    running_ext = entry

    for k in range(entry_idx + 1, len(bars)):
        bar = bars[k]
        # 更新极值
        if direction == "long":
            running_ext = max(running_ext, bar["high"])
        else:
            running_ext = min(running_ext, bar["low"])
        # H 阶梯锁
        if use_runner:
            if direction == "long":
                if not triggered["lock1r"] and running_ext >= entry + 2*r:
                    sl = max(sl, entry + r); triggered["lock1r"] = True
                if not triggered["lock2r"] and running_ext >= entry + 4*r:
                    sl = max(sl, entry + 2*r); triggered["lock2r"] = True
            else:
                if not triggered["lock1r"] and running_ext <= entry - 2*r:
                    sl = min(sl, entry - r); triggered["lock1r"] = True
                if not triggered["lock2r"] and running_ext <= entry - 4*r:
                    sl = min(sl, entry - 2*r); triggered["lock2r"] = True
        # 检查触发
        if direction == "long":
            if bar["low"] <= sl:
                gross = (sl - entry) / r
                return (entry_idx, k, gross)
            if bar["high"] >= tp:
                return (entry_idx, k, tp_mult)
        else:
            if bar["high"] >= sl:
                gross = (entry - sl) / r
                return (entry_idx, k, gross)
            if bar["low"] <= tp:
                return (entry_idx, k, tp_mult)
    return None


def run(bars, sigs, ema, adx, cfg, atr,
         loss_threshold=0, pause_bars=0,
         direction_aware=False,
         only_long=False, only_good_hours=False,
         skip_bad_hours=False,
         post_cooldown_strict=False,
         use_runner=False,
         tp_mult=2.0):
    """带冷却的回测"""
    history = []
    pause_until = -1
    pause_direction = None  # 单向冷却时记录哪个方向被暂停
    just_came_out_of_cooldown = False
    BAD_HOURS = {9, 13, 17, 18, 20}
    GOOD_HOURS = {19, 21, 22}

    sigs_sorted = sorted(sigs, key=lambda s: s["index"])
    for sig in sigs_sorted:
        idx = sig["index"]
        # 时段过滤
        try:
            dt = datetime.strptime(bars[idx]["date"], "%Y-%m-%d %H:%M")
            hour = dt.hour
        except:
            hour = -1

        if skip_bad_hours and hour in BAD_HOURS: continue
        if only_good_hours and hour not in GOOD_HOURS: continue
        if only_long and sig["direction"] != "long": continue

        # 冷却检查
        if loss_threshold > 0 and idx < pause_until:
            if not direction_aware or (direction_aware and sig["direction"] == pause_direction):
                continue

        # 刚从 cooldown 出来要求严格过滤
        if post_cooldown_strict and just_came_out_of_cooldown:
            if (sig["body_ratio_B"] < 0.6 or sig["body_ratio_C"] < 0.6):
                continue
            just_came_out_of_cooldown = False

        if not apply_f6(bars, sig, idx, ema, adx, cfg):
            continue

        t = simulate_trade(bars, sig, cfg, tp_mult=tp_mult, use_runner=use_runner, atr=atr)
        if t is None: continue
        entry_idx, exit_idx, r = t
        history.append({"entry_idx": entry_idx, "exit_idx": exit_idx, "net_r": r,
                         "direction": sig["direction"]})

        # 检查 cooldown 触发
        if loss_threshold > 0 and len(history) >= loss_threshold:
            recent = history[-loss_threshold:]
            if all(t["net_r"] < 0 for t in recent):
                last_exit = recent[-1]["exit_idx"]
                if last_exit + pause_bars > pause_until:
                    pause_until = last_exit + pause_bars
                    pause_direction = recent[-1]["direction"]
                    just_came_out_of_cooldown = True  # 标志, 下次出 cooldown 后严格

    n = len(history)
    if n == 0: return {"n": 0}
    wins = sum(1 for t in history if t["net_r"] > 0)
    total_r = sum(t["net_r"] for t in history)
    eq, peak, max_dd = 0, 0, 0
    for t in history:
        eq += t["net_r"]; peak = max(peak, eq); max_dd = min(max_dd, eq - peak)
    max_streak = cur = 0
    for t in history:
        if t["net_r"] < 0:
            cur += 1; max_streak = max(max_streak, cur)
        else: cur = 0
    return {"n": n, "wins": wins, "losses": n - wins,
            "win_rate": wins / n, "total_r": total_r,
            "avg_r": total_r / n, "max_dd": max_dd,
            "max_loss_streak": max_streak}


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    cfg = VariantConfig(
        name="cd_adv", body_ratio=0.5, entanglement_tolerance=0.005,
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
        # 基线 + 单维度
        ("★ baseline (无冷却)",              {}),
        ("★ 连亏 2 停 24h (上轮王)",          {"loss_threshold": 2, "pause_bars": 24}),

        # 不同暂停时长
        ("连亏 2 停 6h",                     {"loss_threshold": 2, "pause_bars": 6}),
        ("连亏 2 停 12h",                    {"loss_threshold": 2, "pause_bars": 12}),
        ("连亏 2 停 48h",                    {"loss_threshold": 2, "pause_bars": 48}),
        ("连亏 2 停 72h",                    {"loss_threshold": 2, "pause_bars": 72}),
        ("连亏 2 停 168h (一周)",             {"loss_threshold": 2, "pause_bars": 168}),

        # 单向冷却
        ("连亏 2 停 24h + 单向冷却",          {"loss_threshold": 2, "pause_bars": 24, "direction_aware": True}),
        ("连亏 3 停 24h + 单向冷却",          {"loss_threshold": 3, "pause_bars": 24, "direction_aware": True}),

        # 冷却 + 跳毒时段
        ("连亏 2 停 24h + 跳毒时段",          {"loss_threshold": 2, "pause_bars": 24, "skip_bad_hours": True}),

        # 冷却 + 只多
        ("连亏 2 停 24h + 仅多",              {"loss_threshold": 2, "pause_bars": 24, "only_long": True}),

        # 冷却 + 只多 + 跳毒时段
        ("连亏 2 停 24h + 仅多 + 跳毒",        {"loss_threshold": 2, "pause_bars": 24, "only_long": True, "skip_bad_hours": True}),

        # 冷却 + H 阶梯锁 (终极组合)
        ("H 阶梯锁 (8R, 2R锁1R, 4R锁2R)",     {"use_runner": True, "tp_mult": 8.0}),
        ("H + 连亏 2 停 24h",                {"loss_threshold": 2, "pause_bars": 24, "use_runner": True, "tp_mult": 8.0}),
        ("H + 连亏 3 停 24h",                {"loss_threshold": 3, "pause_bars": 24, "use_runner": True, "tp_mult": 8.0}),
        ("H + 连亏 2 停 24h + 跳毒",          {"loss_threshold": 2, "pause_bars": 24, "use_runner": True, "tp_mult": 8.0, "skip_bad_hours": True}),
        ("H + 连亏 2 停 24h + 仅多",          {"loss_threshold": 2, "pause_bars": 24, "use_runner": True, "tp_mult": 8.0, "only_long": True}),

        # 冷却 + 出 cooldown 后严格
        ("连亏 2 停 24h + 出冷却后 body≥0.6", {"loss_threshold": 2, "pause_bars": 24, "post_cooldown_strict": True}),

        # 极致守势
        ("连亏 2 停 168h + 仅多 + 跳毒",       {"loss_threshold": 2, "pause_bars": 168, "only_long": True, "skip_bad_hours": True}),
    ]

    print(f"{'方案':<40} {'笔数':>5} {'胜':>4} {'败':>4} {'胜率':>7} {'总R':>9} {'平均R':>8} {'最大连败':>9} {'回撤':>8} {'3年%':>8}")
    print("-" * 125)
    R_pct = 0.026
    for label, kw in schemes:
        s = run(bars, sigs, ema, adx, cfg, atr, **kw)
        if s["n"] == 0: continue
        total_pct = s["total_r"] * R_pct * 100
        print(f"{label:<40} {s['n']:>5} {s['wins']:>4} {s['losses']:>4} "
              f"{s['win_rate']*100:>6.1f}% {s['total_r']:>+9.2f} {s['avg_r']:>+8.3f} "
              f"{s['max_loss_streak']:>9} {s['max_dd']:>+8.2f} {total_pct:>+7.0f}%")


if __name__ == "__main__":
    main()
