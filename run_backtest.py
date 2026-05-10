"""
主回测脚本: 加载本地CSV -> 跑10个变体 x 10币种 -> 输出报告
用法: python3 run_backtest.py
依赖: data/ 目录下要有10个币种的CSV (先跑 fetch_data.py)
"""
import os
import csv
import json
import sys
from collections import defaultdict

from backtest import run_backtest, VariantConfig
from variants import VARIANTS

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(OUT_DIR, exist_ok=True)


def load_csv(path):
    bars = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append({
                "date": row["date"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })
    bars.sort(key=lambda x: x["date"])
    return bars


def main():
    if not os.path.isdir(DATA_DIR) or not os.listdir(DATA_DIR):
        print(f"ERROR: 数据目录为空: {DATA_DIR}")
        print("请先运行: python3 fetch_data.py")
        sys.exit(1)

    # 只处理 _1h.csv 命名的文件 (跟当前策略时间周期一致)
    csvs = sorted([f for f in os.listdir(DATA_DIR) if f.endswith("_1h.csv")])
    print(f"找到 {len(csvs)} 个币种数据, {len(VARIANTS)} 个策略变体")
    print(f"开始回测 ({len(csvs)} x {len(VARIANTS)} = {len(csvs) * len(VARIANTS)} 组)...\n")

    # 结果矩阵: results[variant_name][symbol] = summary
    matrix = defaultdict(dict)
    # 跨币种汇总: agg[variant_name] = {n_trades, wins, total_r, ...}
    aggregate = defaultdict(lambda: {"n_trades": 0, "n_wins": 0, "total_r": 0.0, "trades": []})

    for csv_file in csvs:
        symbol = csv_file.replace(".csv", "")
        bars = load_csv(os.path.join(DATA_DIR, csv_file))
        if len(bars) < 30:
            print(f"  {symbol}: 数据不足({len(bars)}根), 跳过")
            continue

        for cfg in VARIANTS:
            r = run_backtest(bars, cfg)
            matrix[cfg.name][symbol] = r
            aggregate[cfg.name]["n_trades"] += r["n_trades"]
            aggregate[cfg.name]["n_wins"] += r.get("n_wins", 0)
            aggregate[cfg.name]["total_r"] += r["total_r"]
            for t in r["trades"]:
                t2 = dict(t); t2["symbol"] = symbol
                aggregate[cfg.name]["trades"].append(t2)

    # 打印汇总
    print(f"{'Variant':<22} {'Trades':>7} {'Wins':>6} {'WinRate':>8} {'TotalR':>8} {'AvgR':>7} {'MaxDD':>7}")
    print("-" * 70)
    summary_rows = []
    for cfg in VARIANTS:
        agg = aggregate[cfg.name]
        n = agg["n_trades"]
        wr = (agg["n_wins"] / n) if n else 0
        avg_r = (agg["total_r"] / n) if n else 0
        # 跨币种最大回撤
        equity = 0; peak = 0; max_dd = 0
        sorted_trades = sorted(agg["trades"], key=lambda x: x.get("entry_date", ""))
        for t in sorted_trades:
            equity += t["net_r"]
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        print(f"{cfg.name:<22} {n:>7} {agg['n_wins']:>6} {wr*100:>7.1f}% {agg['total_r']:>8.2f} {avg_r:>7.3f} {max_dd:>7.2f}")
        summary_rows.append({
            "variant": cfg.name,
            "n_trades": n,
            "n_wins": agg["n_wins"],
            "win_rate": round(wr, 4),
            "total_r": round(agg["total_r"], 2),
            "avg_r": round(avg_r, 3),
            "max_dd_r": round(max_dd, 2),
            "body_ratio": cfg.body_ratio,
            "r_multiple": cfg.r_multiple,
            "sl_buffer_pct": cfg.sl_buffer_pct,
            "time_stop_bars": cfg.time_stop_bars,
            "breakeven_at_r": cfg.breakeven_at_r,
        })

    # 保存详细结果
    with open(os.path.join(OUT_DIR, "summary.json"), "w") as f:
        json.dump(summary_rows, f, indent=2)
    with open(os.path.join(OUT_DIR, "summary.csv"), "w", newline="") as f:
        if summary_rows:
            w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
            w.writeheader()
            w.writerows(summary_rows)
    # 详细交易明细
    with open(os.path.join(OUT_DIR, "all_trades.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant", "symbol", "entry_date", "exit_date", "direction",
                    "entry", "sl", "tp", "exit", "exit_reason", "bars_held", "net_r", "win"])
        for vname in matrix:
            for sym, r in matrix[vname].items():
                for t in r["trades"]:
                    w.writerow([vname, sym, t["entry_date"], t["exit_date"], t["direction"],
                                round(t["entry"], 6), round(t["sl"], 6), round(t["tp"], 6),
                                round(t["exit"], 6), t["exit_reason"], t["bars_held"],
                                round(t["net_r"], 3), t["win"]])
    # 各币种各变体的胜率矩阵 (便于看哪个币最适合哪个变体)
    with open(os.path.join(OUT_DIR, "winrate_matrix.csv"), "w", newline="") as f:
        w = csv.writer(f)
        symbols = sorted({s for v in matrix.values() for s in v.keys()})
        w.writerow(["variant"] + symbols)
        for vname in matrix:
            row = [vname]
            for s in symbols:
                r = matrix[vname].get(s)
                if r and r["n_trades"] > 0:
                    row.append(f"{r['win_rate']*100:.0f}%({r['n_trades']})")
                else:
                    row.append("-")
            w.writerow(row)

    print(f"\n报告已保存到: {OUT_DIR}/")
    print("  - summary.csv      策略变体总汇总")
    print("  - winrate_matrix.csv  各币种 x 各变体的胜率矩阵")
    print("  - all_trades.csv   所有交易明细")
    print("  - summary.json     机器可读汇总")


if __name__ == "__main__":
    main()
