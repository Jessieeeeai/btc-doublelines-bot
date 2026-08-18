import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""
重叠颈线策略 · 第二轮预注册 (2026-08-17)

预注册声明 (跑之前写死, 测完不加变体):
- 基线对照: second @ ratio=0.5, TP=2L/SL=1.5L (第一轮冠军, 训练+$3,175/样本外+$5,963)
- 5 个变形 (全部基于 second @ ratio=0.5):
    A. TP=3L          — 拉远止盈 (与B构成家族)
    B. TP=4L          — 拉远止盈
    C. L>=0.25%价格   — 微型形态门槛 (第一轮机理诊断)
    D. F6式趋势跳过    — ADX>25 且 |close-EMA200|>2% 不进单
    E. 保本推损        — 浮盈+1L 时 SL 移到入场价
- 纪律附加 (不算变体, 平台检验): second 模式 ratio 0.3~0.8 邻域扫描
- 评判: 训练/样本外同号且样本外为正; 与基线对照孰优
- 口径: 每单 $10,000 名义仓位, 不计手续费
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
                         "close": float(row["close"])})
    bars.sort(key=lambda x: x["date"])
    return bars


def seg(trades, a, b):
    s = [t for t in trades if a <= t["entry_date"] < b]
    n = len(s)
    if n == 0:
        return {"n": 0, "wr": 0, "usd": 0.0}
    w = sum(1 for t in s if t["win"])
    return {"n": n, "wr": w / n, "usd": sum(t["pnl_usd"] for t in s)}


VARIANTS = [
    NecklineConfig(name="N2_base_second",  ref_mode="second", ratio=0.5),
    NecklineConfig(name="N2_A_tp3",        ref_mode="second", ratio=0.5, tp_mult=3.0),
    NecklineConfig(name="N2_B_tp4",        ref_mode="second", ratio=0.5, tp_mult=4.0),
    NecklineConfig(name="N2_C_minL025",    ref_mode="second", ratio=0.5, min_l_pct=0.0025),
    NecklineConfig(name="N2_D_regime",     ref_mode="second", ratio=0.5, regime_skip_trend=True),
    NecklineConfig(name="N2_E_be1L",       ref_mode="second", ratio=0.5, breakeven_at_l=1.0),
]


def main():
    bars = load_bars(DATA)
    n = len(bars)
    mid = bars[n // 2]["date"]
    print(f"数据: {bars[0]['date']} → {bars[-1]['date']}  共{n}根 | 分界 {mid}")
    print("口径: 每单 $10,000 名义, 零手续费\n")

    rows, all_trades = [], []
    hdr = (f"{'variant':<16}{'成交':>6}{'胜率':>7}{'总盈亏$':>10}{'每笔$':>8}{'回撤$':>9}"
           f" | {'训练$':>9}{'样本外$':>9}")
    print(hdr); print("-" * 86)
    for cfg in VARIANTS:
        r = run_neckline_backtest(bars, cfg)
        tr = r["trades"]
        train, oos = seg(tr, bars[0]["date"], mid), seg(tr, mid, "9999")
        print(f"{r['variant']:<16}{r['n_trades']:>6}{r['win_rate']*100:>6.1f}%"
              f"{r['total_usd']:>10,.0f}{r['avg_usd']:>8.2f}{r['max_drawdown_usd']:>9,.0f}"
              f" |{train['usd']:>9,.0f}{oos['usd']:>9,.0f}")
        rows.append({
            "variant": r["variant"], "n_trades": r["n_trades"],
            "win_rate": r["win_rate"], "total_usd": r["total_usd"],
            "avg_usd": r["avg_usd"], "max_dd_usd": r["max_drawdown_usd"],
            "train_n": train["n"], "train_usd": round(train["usd"], 0),
            "oos_n": oos["n"], "oos_usd": round(oos["usd"], 0),
        })
        for t in tr:
            t2 = dict(t); t2["variant"] = r["variant"]
            all_trades.append(t2)

    # ---- 纪律附加: ratio 邻域扫描 (second, 其余默认) ----
    print("\nratio 邻域扫描 (second 模式, 平台检验):")
    print(f"{'ratio':>6}{'成交':>7}{'胜率':>7}{'总盈亏$':>10} | {'训练$':>9}{'样本外$':>9}")
    sweep = []
    for ratio in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        cfg = NecklineConfig(name=f"sweep_r{int(ratio*100)}", ref_mode="second", ratio=ratio)
        r = run_neckline_backtest(bars, cfg)
        tr = r["trades"]
        train, oos = seg(tr, bars[0]["date"], mid), seg(tr, mid, "9999")
        print(f"{ratio:>6.1f}{r['n_trades']:>7}{r['win_rate']*100:>6.1f}%"
              f"{r['total_usd']:>10,.0f} |{train['usd']:>9,.0f}{oos['usd']:>9,.0f}")
        sweep.append({"ratio": ratio, "n_trades": r["n_trades"], "win_rate": r["win_rate"],
                      "total_usd": r["total_usd"], "train_usd": round(train["usd"], 0),
                      "oos_usd": round(oos["usd"], 0)})

    with open(os.path.join(OUT, "neckline_round2_summary.json"), "w") as f:
        json.dump({"variants": rows, "ratio_sweep": sweep}, f, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT, "neckline_round2_trades.csv"), "w", newline="") as f:
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
    print("\n已保存: results/neckline_round2_summary.json / neckline_round2_trades.csv")


if __name__ == "__main__":
    main()
