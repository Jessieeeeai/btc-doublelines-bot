import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""
重叠颈线策略 · 第一轮基线 v2 (2026-08-17)

v2 改动 (用户要求):
- 记账单位: 每单实际金额 ($1,000 保证金 x 10x 杠杆 = $10,000 名义仓位, 与双线反战同约定)
- 不计手续费 (fee_rate = 0)

预注册变体不变: 4 个 = ref_mode ∈ {longer, shorter, first, second}, ratio 固定 0.5
TP=2L, SL=1.5L, expire=3, 无时间止损
训练/样本外: 时间对半切
"""
import csv
import json
from neckline_backtest import NecklineConfig, run_neckline_backtest
from neckline_signals import REF_MODES

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
                         "close": float(row["close"])})
    bars.sort(key=lambda x: x["date"])
    return bars


def seg_stats(trades, a, b):
    s = [t for t in trades if a <= t["entry_date"] < b]
    n = len(s)
    if n == 0:
        return {"n": 0, "wr": 0, "usd": 0}
    w = sum(1 for t in s if t["win"])
    return {"n": n, "wr": round(w / n, 3), "usd": round(sum(t["pnl_usd"] for t in s), 0)}


def main():
    bars = load_bars(DATA)
    n = len(bars)
    mid = bars[n // 2]["date"]
    print(f"数据: {bars[0]['date']} → {bars[-1]['date']}  共{n}根")
    print(f"训练/样本外分界: {mid}")
    print("口径: 每单 $10,000 名义仓位 (=$1,000 x 10x), 不计手续费\n")

    rows = []
    all_trades = []
    for m in REF_MODES:
        cfg = NecklineConfig(name=f"N1_{m}_r50", ref_mode=m, ratio=0.5,
                             fee_rate=0.0, notional_usd=10000.0)
        r = run_neckline_backtest(bars, cfg)
        tr = r["trades"]
        train = seg_stats(tr, bars[0]["date"], mid)
        oos = seg_stats(tr, mid, "9999")
        row = {
            "variant": r["variant"], "ref_mode": m,
            "n_signals": r["n_signals"], "n_trades": r["n_trades"],
            "win_rate": r["win_rate"],
            "total_usd": r["total_usd"], "avg_usd": r["avg_usd"],
            "max_dd_usd": r["max_drawdown_usd"],
            "train_n": train["n"], "train_wr": train["wr"], "train_usd": train["usd"],
            "oos_n": oos["n"], "oos_wr": oos["wr"], "oos_usd": oos["usd"],
            "ambiguous": r["n_ambiguous"], "expired": r["n_expired"],
            "skipped_in_pos": r["n_skipped_in_position"],
        }
        rows.append(row)
        for t in tr:
            t2 = dict(t); t2["variant"] = r["variant"]
            all_trades.append(t2)

    hdr = (f"{'variant':<16}{'信号':>7}{'成交':>6}{'胜率':>7}{'总盈亏$':>11}{'每笔$':>8}"
           f"{'最大回撤$':>11} | {'训练$':>10}{'样本外$':>10}")
    print(hdr)
    print("-" * 92)
    for r in rows:
        print(f"{r['variant']:<16}{r['n_signals']:>7}{r['n_trades']:>6}"
              f"{r['win_rate']*100:>6.1f}%{r['total_usd']:>11,.0f}{r['avg_usd']:>8.2f}"
              f"{r['max_dd_usd']:>11,.0f} |{r['train_usd']:>10,.0f}{r['oos_usd']:>10,.0f}")

    with open(os.path.join(OUT, "neckline_baseline_summary.json"), "w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT, "neckline_baseline_trades.csv"), "w", newline="") as f:
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
    print(f"\n已保存: results/neckline_baseline_summary.json / neckline_baseline_trades.csv")


if __name__ == "__main__":
    main()
