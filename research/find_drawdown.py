import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""
找 Hedge + 5% 风险方案在 3 年里最深回撤发生的具体时间窗
输出: 峰值日期/值 -> 谷底日期/值 -> 恢复日期, 中间发生了什么
"""
import os
import csv
from datetime import datetime

from backtest import run_backtest
from variants import VARIANTS
from equity_backtest import load_bars
from hedge_simulator import simulate_hedge

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def main():
    bars = load_bars(os.path.join(DATA_DIR, "BTCUSDT_1h.csv"))
    cfg = next(v for v in VARIANTS if v.name.startswith("W4_"))
    print(f"策略: {cfg.name}\n")

    bt = run_backtest(bars, cfg)
    trades = sorted(bt["trades"], key=lambda x: x["entry_date"])
    print(f"信号总数: {len(trades)}")

    # 跑 Hedge 5% 详细
    result = simulate_hedge(bars, trades, starting=1000.0,
                            risk_per_trade=0.05, max_leverage_total=10.0, mode="hedge")
    curve = result["curve"]
    print(f"终值: ${result['final']:.2f}, 回报 {result['return_pct']}%, Max DD {result['max_dd_pct']}%\n")

    # 找最深回撤的精确位置 (peak-to-trough)
    peak_cap = curve[0]["capital"]
    peak_date = curve[0]["date"]
    max_dd_abs = 0.0
    max_dd_pct = 0.0
    dd_peak_date = curve[0]["date"]
    dd_peak_cap = peak_cap
    dd_trough_date = None
    dd_trough_cap = None

    # 当前回撤窗口的临时记录
    cur_peak_date = curve[0]["date"]
    cur_peak_cap = peak_cap

    for c in curve:
        cap = c["capital"]
        if cap >= cur_peak_cap:
            cur_peak_cap = cap
            cur_peak_date = c["date"]
        else:
            dd_abs = cur_peak_cap - cap
            dd_pct = dd_abs / cur_peak_cap if cur_peak_cap > 0 else 0
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
                max_dd_abs = dd_abs
                dd_peak_date = cur_peak_date
                dd_peak_cap = cur_peak_cap
                dd_trough_date = c["date"]
                dd_trough_cap = cap

    print(f"========= 最深回撤窗口 =========")
    print(f"峰值: {dd_peak_date}  -> ${dd_peak_cap:.2f}")
    print(f"谷底: {dd_trough_date} -> ${dd_trough_cap:.2f}")
    print(f"回撤: -${max_dd_abs:.2f} (-{max_dd_pct*100:.1f}%)")

    # 跨度
    try:
        dt_peak = datetime.strptime(dd_peak_date.split()[0], "%Y-%m-%d")
        dt_trough = datetime.strptime(dd_trough_date.split()[0], "%Y-%m-%d")
        days = (dt_trough - dt_peak).days
        print(f"持续: {days} 天 ({dt_peak.date()} -> {dt_trough.date()})")
    except Exception:
        pass

    # 找到从谷底回到原峰值用了多久 (复苏期)
    recovered_date = None
    found_trough = False
    for c in curve:
        if c["date"] == dd_trough_date:
            found_trough = True
            continue
        if found_trough and c["capital"] >= dd_peak_cap:
            recovered_date = c["date"]
            break
    if recovered_date:
        dt_rec = datetime.strptime(recovered_date.split()[0], "%Y-%m-%d")
        rec_days = (dt_rec - dt_trough).days
        print(f"复苏: {recovered_date} ({rec_days} 天)")
    else:
        print(f"复苏: 至今未回到峰值水平")

    # 在那段窗口里发生了什么 - 找 peak/trough 期间的最大单笔亏损
    print(f"\n========= 回撤期内交易明细 (峰值-谷底) =========")
    in_window = False
    losses = []
    for c in curve:
        if c["date"] == dd_peak_date:
            in_window = True
            continue
        if in_window:
            losses.append({
                "date": c["date"],
                "capital": c["capital"],
                "open_positions": c.get("open_positions", 0),
                "event": c.get("event", ""),
            })
            if c["date"] == dd_trough_date:
                break

    # 计算每条记录与前一条的差值 (PnL)
    prev_cap = dd_peak_cap
    detailed = []
    for x in losses:
        delta = x["capital"] - prev_cap
        detailed.append({**x, "delta": delta})
        prev_cap = x["capital"]

    # 看最大的连续亏损段
    worst = sorted(detailed, key=lambda r: r["delta"])[:10]
    print(f"\n前 10 笔最大亏损交易 (在回撤窗口内):")
    print(f"{'日期':<22} {'账户余额($)':>12} {'本笔PnL':>10} {'同时持仓':>9}")
    for w in worst:
        print(f"{w['date']:<22} {w['capital']:>12.2f} {w['delta']:>+10.2f} {w['open_positions']:>9}")

    # BTC 同期价格走势 (找该时间窗的 BTC 涨跌)
    print(f"\n========= BTC 同期表现 =========")
    bars_in = [b for b in bars if dd_peak_date <= b["date"] <= dd_trough_date]
    if bars_in:
        btc_start = bars_in[0]["close"]
        btc_end = bars_in[-1]["close"]
        btc_low = min(b["low"] for b in bars_in)
        btc_high = max(b["high"] for b in bars_in)
        print(f"  起 ({bars_in[0]['date']}): BTC ${btc_start:.0f}")
        print(f"  止 ({bars_in[-1]['date']}): BTC ${btc_end:.0f}")
        print(f"  期间最高: ${btc_high:.0f}, 最低: ${btc_low:.0f}")
        print(f"  BTC 区间涨跌: {(btc_end - btc_start) / btc_start * 100:+.1f}%")
        print(f"  BTC 振幅: {(btc_high - btc_low) / btc_start * 100:.1f}%")

    # 保存全曲线
    path = os.path.join(OUT_DIR, "hedge_curve_5pct.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "capital", "open_positions", "event"])
        for c in curve:
            w.writerow([c["date"], c["capital"], c.get("open_positions", 0), c.get("event", "")])
    print(f"\n5% 风险全曲线已保存: {path}")


if __name__ == "__main__":
    main()
