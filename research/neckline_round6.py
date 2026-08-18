import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""
重叠颈线策略 · 第六轮预注册 (2026-08-17): 出场/仓位管理

基座 = 第五轮总利润王 C3: second @ ratio=0.7, 缓冲0.25L, TP=3L / SL=1.5L
       (+$31,633, 训练16,712/样本外14,921, 每笔$11.94, 回撤$1,590)

5个设计 (每个只改出场/仓位一件事):
    P1. chandelier  吊灯跟踪: 无固定TP, SL=峰值-3xATR14, 只紧不松
    P2. stair       阶梯锁利: TP=6L; +2L锁+1L, +4L锁+2L (双线反战B策略同思路)
    P3. trail_l     L距离跟踪: 无固定TP, SL=峰值-1.5L
    P4. scaled      分批止盈: +1.5L平一半+SL推入场价, 余半TP=4L
    P5. risk_par    等风险仓位: 每单固定风险$40, 名义=风险/止损距离% (上限$100k), 出场同基座
口径: 同bar先用旧跟踪线判出场、再用本bar极值更新跟踪线 (保守)。
评判: 训练/样本外同号且样本外为正; 总盈亏/每笔/回撤/利润回撤比。
记账: 基座与P1-P4每单$10,000名义; P5为变动名义(表中另列均值)。零手续费。
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
    if not s:
        return {"n": 0, "usd": 0.0}
    return {"n": len(s), "usd": sum(t["pnl_usd"] for t in s)}


BASE = dict(ref_mode="second", ratio=0.7, tp_mult=3.0, buffer_l=0.25)

VARIANTS = [
    NecklineConfig(name="ref_C3",       **BASE),
    NecklineConfig(name="P1_chandelier", **BASE, exit_mode="chandelier"),
    NecklineConfig(name="P2_stair",      **BASE, exit_mode="stair"),
    NecklineConfig(name="P3_trail_l",    **BASE, exit_mode="trail_l"),
    NecklineConfig(name="P4_scaled",     **BASE, exit_mode="scaled"),
    NecklineConfig(name="P5_risk40",     **BASE, risk_sizing_usd=40.0, notional_cap_usd=100000.0),
]


def main():
    bars = load_bars(DATA)
    n = len(bars)
    mid = bars[n // 2]["date"]
    print(f"数据: {bars[0]['date']} → {bars[-1]['date']}  共{n}根 | 分界 {mid}")
    print("口径: 零手续费; 基座/P1-P4 每单$10,000名义, P5等风险$40/单\n")

    rows, all_trades = [], []
    hdr = (f"{'variant':<14}{'成交':>6}{'胜率':>7}{'总盈亏$':>10}{'每笔$':>8}{'回撤$':>9}"
           f"{'利润/回撤':>9}{'均持仓h':>8}{'均名义$':>9} | {'训练$':>9}{'样本外$':>9}")
    print(hdr); print("-" * 112)
    for cfg in VARIANTS:
        r = run_neckline_backtest(bars, cfg)
        tr = r["trades"]
        train, oos = seg(tr, bars[0]["date"], mid), seg(tr, mid, "9999")
        pf = r["total_usd"] / r["max_drawdown_usd"] if r["max_drawdown_usd"] > 0 else 0
        avg_hold = sum(t["bars_held"] for t in tr) / len(tr) if tr else 0
        avg_notional = sum(t.get("notional", 10000) for t in tr) / len(tr) if tr else 0
        print(f"{r['variant']:<14}{r['n_trades']:>6}{r['win_rate']*100:>6.1f}%"
              f"{r['total_usd']:>10,.0f}{r['avg_usd']:>8.2f}{r['max_drawdown_usd']:>9,.0f}"
              f"{pf:>9.1f}{avg_hold:>8.1f}{avg_notional:>9,.0f}"
              f" |{train['usd']:>9,.0f}{oos['usd']:>9,.0f}")
        rows.append({
            "variant": r["variant"], "n_trades": r["n_trades"], "win_rate": r["win_rate"],
            "total_usd": r["total_usd"], "avg_usd": r["avg_usd"],
            "max_dd_usd": r["max_drawdown_usd"], "profit_dd": round(pf, 1),
            "avg_hold_bars": round(avg_hold, 1), "avg_notional": round(avg_notional, 0),
            "train_usd": round(train["usd"], 0), "oos_usd": round(oos["usd"], 0),
        })
        for t in tr:
            t2 = dict(t); t2["variant"] = r["variant"]
            all_trades.append(t2)

    with open(os.path.join(OUT, "neckline_round6_summary.json"), "w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT, "neckline_round6_trades.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant", "signal_date", "entry_date", "exit_date", "direction",
                    "entry", "level", "L", "sl", "tp", "exit", "exit_reason",
                    "bars_held", "notional", "pnl_usd", "win"])
        for t in all_trades:
            w.writerow([t["variant"], t["signal_date"], t["entry_date"], t["exit_date"],
                        t["direction"], round(t["entry"], 2), round(t["level"], 2),
                        round(t["L"], 2), round(t["sl"], 2),
                        (round(t["tp"], 2) if t["tp"] is not None else ""),
                        round(t["exit"], 2), t["exit_reason"], t["bars_held"],
                        t.get("notional", 10000), round(t["pnl_usd"], 2), t["win"]])
    print("\n已保存: results/neckline_round6_summary.json / neckline_round6_trades.csv")


if __name__ == "__main__":
    main()
