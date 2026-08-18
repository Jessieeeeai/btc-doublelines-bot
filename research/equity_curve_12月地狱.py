"""
跑"5 轮迭代但没加 F6 反共识"的策略, 生成资金曲线
用于视频素材: 12 个月地狱 ($7,098 → $1,878)
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
    """5 轮迭代只有 EMA 顺势, 没有 F6 reg ime"""
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
            if bar["low"] <= sl:
                return {"net_r": -1.0, "exit_date": bar["date"], "exit_ts": k}
            if bar["high"] >= tp:
                return {"net_r": 2.0, "exit_date": bar["date"], "exit_ts": k}
        else:
            if bar["high"] >= sl:
                return {"net_r": -1.0, "exit_date": bar["date"], "exit_ts": k}
            if bar["low"] <= tp:
                return {"net_r": 2.0, "exit_date": bar["date"], "exit_ts": k}
    return None


def main():
    bars = load_bars(os.path.join(os.path.dirname(__file__), "..", "data", "BTCUSDT_1h.csv"))
    cfg = VariantConfig(
        name="pre_F6", body_ratio=0.5, entanglement_tolerance=0.0,
        r_multiple=2.0, sl_buffer_pct=0.02,
        entry_mode="breakout_confirm", entry_wait_bars=3,
    )
    sigs = detect_signals(bars, cfg.body_ratio, cfg.entanglement_tolerance)
    ema = _compute_ema(bars, 200)

    # 跑出所有 trade
    trades = []
    for sig in sigs:
        idx = sig["index"]
        if not apply_ema_only(bars, sig, idx, ema):
            continue
        t = simulate(bars, sig, cfg)
        if t is None: continue
        trades.append(t)

    print(f"Total trades: {len(trades)}")
    n = len(trades)
    wins = sum(1 for t in trades if t["net_r"] > 0)
    total_r = sum(t["net_r"] for t in trades)
    print(f"Win rate: {wins/n*100:.1f}% | Total R: {total_r:+.1f}\n")

    # 算资金曲线 (每单 risk 2% 复利)
    risk_pct = 0.02
    capital = 1000.0
    curve = [(trades[0]["exit_date"], capital)]
    for t in trades:
        gain = t["net_r"] * risk_pct  # +2R → +4%, -1R → -2%
        capital = capital * (1 + gain)
        curve.append((t["exit_date"], round(capital, 2)))

    # 找峰值 + 谷底
    peak_idx = max(range(len(curve)), key=lambda i: curve[i][1])
    trough_idx = max(range(peak_idx, len(curve)), key=lambda i: -curve[i][1])
    peak_date, peak_val = curve[peak_idx]
    trough_date, trough_val = curve[trough_idx]

    print(f"=== 资金曲线极值 ===")
    print(f"峰值: {peak_date} = ${peak_val:.0f}")
    print(f"谷底: {trough_date} = ${trough_val:.0f}")
    print(f"回撤: {(trough_val-peak_val)/peak_val*100:.1f}%")
    print(f"持续: 从 peak 到 trough 经过 {trough_idx-peak_idx} 笔交易\n")

    # 找最痛的 4 笔
    losing_trades = sorted([t for t in trades if t["net_r"] < 0], key=lambda x: x["net_r"])
    print(f"=== 最痛的 4 笔 (R 单位) ===")
    for t in losing_trades[:4]:
        print(f"  {t['exit_date']} R={t['net_r']:+.1f}")

    # 输出 curve 给 SVG 画图
    output = {
        "start_capital": 1000,
        "peak": {"date": peak_date, "value": peak_val},
        "trough": {"date": trough_date, "value": trough_val},
        "drawdown_pct": (trough_val-peak_val)/peak_val*100,
        "n_trades": n,
        "win_rate": wins/n,
        "total_r": total_r,
        "curve": curve,
    }
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "equity_12_geyou.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n资金曲线数据已保存: {out_path}")


if __name__ == "__main__":
    main()
