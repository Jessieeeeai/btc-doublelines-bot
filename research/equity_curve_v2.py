"""
用 10x 杠杆 + 5% 单笔风险跑 5 轮迭代 (无 F6) 版本
模拟 1000 USD 起本的真实账户走势
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
            if bar["low"] <= sl: return {"net_r": -1.0, "exit_date": bar["date"], "exit_idx": k}
            if bar["high"] >= tp: return {"net_r": 2.0, "exit_date": bar["date"], "exit_idx": k}
        else:
            if bar["high"] >= sl: return {"net_r": -1.0, "exit_date": bar["date"], "exit_idx": k}
            if bar["low"] <= tp: return {"net_r": 2.0, "exit_date": bar["date"], "exit_idx": k}
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

    trades = []
    for sig in sigs:
        idx = sig["index"]
        if not apply_ema_only(bars, sig, idx, ema):
            continue
        t = simulate(bars, sig, cfg)
        if t is None: continue
        # entry date for sorting
        t["entry_date"] = bars[sig["index"] + 1]["date"] if sig["index"] + 1 < len(bars) else None
        trades.append(t)

    trades.sort(key=lambda x: x["exit_idx"])
    n = len(trades)
    print(f"Total trades: {n}")
    wins = sum(1 for t in trades if t["net_r"] > 0)
    print(f"Win rate: {wins/n*100:.1f}% | Total R: {sum(t['net_r'] for t in trades):+.1f}\n")

    # 不同 risk pct 测试
    for risk_pct in [0.02, 0.05, 0.08, 0.10]:
        capital = 1000.0
        curve = [(bars[0]["date"], capital)]
        for t in trades:
            gain = t["net_r"] * risk_pct
            capital = max(capital * (1 + gain), 0.01)  # 防 0
            curve.append((t["exit_date"], round(capital, 2)))

        peak_idx = max(range(len(curve)), key=lambda i: curve[i][1])
        trough_idx = max(range(peak_idx, len(curve)), key=lambda i: -curve[i][1])
        peak_date, peak_val = curve[peak_idx]
        trough_date, trough_val = curve[trough_idx]
        final_val = curve[-1][1]

        print(f"=== Risk {risk_pct*100:.0f}% per trade ===")
        print(f"  起始: $1000 → 终值: ${final_val:.0f}")
        print(f"  峰值: {peak_date} = ${peak_val:.0f}")
        print(f"  谷底: {trough_date} = ${trough_val:.0f}")
        print(f"  回撤: {(trough_val-peak_val)/peak_val*100:.1f}% (持续 {trough_idx-peak_idx} 笔交易)")
        # 几个月? 用 exit_date 算
        try:
            peak_dt = datetime.strptime(peak_date.split()[0], "%Y-%m-%d")
            trough_dt = datetime.strptime(trough_date.split()[0], "%Y-%m-%d")
            months = (trough_dt - peak_dt).days / 30
            print(f"  时长: {months:.1f} 个月")
        except: pass
        print()

    # 选 5% risk 的曲线输出
    risk_pct = 0.05
    capital = 1000.0
    curve = [(bars[0]["date"], capital)]
    detailed_trades = []
    for t in trades:
        prev_cap = capital
        gain = t["net_r"] * risk_pct
        capital = max(capital * (1 + gain), 0.01)
        curve.append((t["exit_date"], round(capital, 2)))
        detailed_trades.append({
            "exit_date": t["exit_date"],
            "net_r": t["net_r"],
            "capital_before": round(prev_cap, 2),
            "capital_after": round(capital, 2),
            "dollar_gain": round(capital - prev_cap, 2),
        })

    output = {
        "risk_pct": 0.05,
        "start_capital": 1000,
        "curve": curve,
        "trades": detailed_trades,
    }
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "equity_5pct.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"5% risk 资金曲线 + 全部交易已保存: {out_path}")

    # 找 5% 配置下最痛的 4 笔
    losing_trades = [t for t in detailed_trades if t["net_r"] < 0]
    losing_trades.sort(key=lambda x: x["dollar_gain"])
    print(f"\n=== 5% risk 下最痛的 4 笔 (按美金损失排) ===")
    for t in losing_trades[:4]:
        print(f"  {t['exit_date']} R={t['net_r']:+.1f} 亏 ${-t['dollar_gain']:.0f} (账户 ${t['capital_before']:.0f} → ${t['capital_after']:.0f})")


if __name__ == "__main__":
    main()
