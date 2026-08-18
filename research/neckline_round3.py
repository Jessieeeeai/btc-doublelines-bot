import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""
重叠颈线策略 · 第三轮预注册 (2026-08-17)

来源: 网上假突破过滤工具箱调研 (StrategyQuant inside-bar / LuxAlgo breakout-confirmation)
基座 = 第二轮冠军结构: second @ ratio=0.5, TP=3L / SL=1.5L (训练+$8,138 / 样本外+$12,450)
每个变形只加一个机制, 单独归因:

    F. 收盘确认   entry_confirm="close"   1h收盘越过颈线才确认, 下根开盘进 (TP/SL仍锚颈线)
    G. 突破缓冲   buffer_l=0.25           穿过颈线0.25L才触发 (TP/SL锚触发价)
    H. 回踩进场   entry_confirm="retest"  盘中破颈线不追, 等回踩颈线限价进
    I. 放量形态   vol_expansion=1.5       第二根K线量 >= 1.5x 前20根均量
    J. 压缩前置   squeeze_atr=1.0         两根K线总波幅 <= 1.0x ATR14

评判: 训练/样本外同号且样本外为正, 与基座对照孰优。
口径: 每单 $10,000 名义仓位, 不计手续费。
"""
import csv
import json
from neckline_backtest import NecklineConfig, run_neckline_backtest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "BTCUSDT_1h.csv")
OUT = os.path.join(ROOT, "results")
os.makedirs(OUT, exist_ok=True)


def load_bars(path):
    bars = []
    with open(path) as f:
        for row in csv.DictReader(f):
            bars.append({"date": row["date"], "open": float(row["open"]),
                         "high": float(row["high"]), "low": float(row["low"]),
                         "close": float(row["close"]),
                         "volume": float(row.get("volume", 0) or 0)})
    bars.sort(key=lambda x: x["date"])
    return bars


def seg(trades, a, b):
    s = [t for t in trades if a <= t["entry_date"] < b]
    n = len(s)
    if n == 0:
        return {"n": 0, "wr": 0, "usd": 0.0}
    w = sum(1 for t in s if t["win"])
    return {"n": n, "wr": w / n, "usd": sum(t["pnl_usd"] for t in s)}


BASE = dict(ref_mode="second", ratio=0.5, tp_mult=3.0)

VARIANTS = [
    NecklineConfig(name="N3_base_tp3",    **BASE),
    NecklineConfig(name="N3_F_close",     **BASE, entry_confirm="close"),
    NecklineConfig(name="N3_G_buf025",    **BASE, buffer_l=0.25),
    NecklineConfig(name="N3_H_retest",    **BASE, entry_confirm="retest"),
    NecklineConfig(name="N3_I_vol15",     **BASE, vol_expansion=1.5),
    NecklineConfig(name="N3_J_sqz10",     **BASE, squeeze_atr=1.0),
]


def main():
    bars = load_bars(DATA)
    n = len(bars)
    mid = bars[n // 2]["date"]
    print(f"数据: {bars[0]['date']} → {bars[-1]['date']}  共{n}根 | 分界 {mid}")
    print("口径: 每单 $10,000 名义, 零手续费 | 基座 second@0.5 TP=3L\n")

    rows, all_trades = [], []
    hdr = (f"{'variant':<15}{'信号':>7}{'成交':>6}{'胜率':>7}{'总盈亏$':>10}{'每笔$':>8}{'回撤$':>9}"
           f" | {'训练$':>9}{'样本外$':>9}")
    print(hdr); print("-" * 92)
    for cfg in VARIANTS:
        r = run_neckline_backtest(bars, cfg)
        tr = r["trades"]
        train, oos = seg(tr, bars[0]["date"], mid), seg(tr, mid, "9999")
        print(f"{r['variant']:<15}{r['n_signals']:>7}{r['n_trades']:>6}{r['win_rate']*100:>6.1f}%"
              f"{r['total_usd']:>10,.0f}{r['avg_usd']:>8.2f}{r['max_drawdown_usd']:>9,.0f}"
              f" |{train['usd']:>9,.0f}{oos['usd']:>9,.0f}")
        rows.append({
            "variant": r["variant"], "n_signals": r["n_signals"], "n_trades": r["n_trades"],
            "win_rate": r["win_rate"], "total_usd": r["total_usd"],
            "avg_usd": r["avg_usd"], "max_dd_usd": r["max_drawdown_usd"],
            "train_n": train["n"], "train_usd": round(train["usd"], 0),
            "oos_n": oos["n"], "oos_usd": round(oos["usd"], 0),
        })
        for t in tr:
            t2 = dict(t); t2["variant"] = r["variant"]
            all_trades.append(t2)

    with open(os.path.join(OUT, "neckline_round3_summary.json"), "w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT, "neckline_round3_trades.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant", "signal_date", "entry_date", "exit_date", "direction",
                    "entry", "level", "L", "sl", "tp", "exit", "exit_reason",
                    "bars_held", "pnl_usd", "win"])
        for t in all_trades:
            w.writerow([t["variant"], t["signal_date"], t["entry_date"], t["exit_date"],
                        t["direction"], round(t["entry"], 2), round(t["level"], 2),
                        round(t["L"], 2), round(t["sl"], 2), round(t["tp"], 2),
                        round(t["exit"], 2), t["exit_reason"], t["bars_held"],
                        round(t["pnl_usd"], 2), t["win"]])
    print("\n已保存: results/neckline_round3_summary.json / neckline_round3_trades.csv")


if __name__ == "__main__":
    main()
