import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""
重叠颈线策略 · 第四轮预注册 (2026-08-17): 5种不同家族的趋势过滤器

来源: 网调研 (AlgomaticTrading 11 trend filters / SuperTrend 各家教程)
基座 = 第三轮冠军: second @ ratio=0.5, TP=3L / SL=1.5L, 突破缓冲 0.25L
                  (训练+$14,876 / 样本外+$14,606, 回撤$2,039)

5个过滤器, 各选一个家族, 全部方向门语义 (触发被禁方向 → 信号作废):
    K1. ema200      位置类:  close vs EMA200
    K2. ema50_slope 斜率类:  EMA50 vs 8根前
    K3. supertrend  波动带:  SuperTrend(10, 3) 方向
    K4. adx20       强度类:  ADX14 >= 20 才交易 (不限方向, 第二轮D变形的镜像)
    K5. rsi50       动量类:  RSI14 中轴

口径: 趋势状态取信号bar收盘时点, 无前视; 指标热身期信号丢弃。
评判: 训练/样本外同号且样本外为正, 与基座对照孰优。
记账: 每单 $10,000 名义, 零手续费。
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


BASE = dict(ref_mode="second", ratio=0.5, tp_mult=3.0, buffer_l=0.25)

VARIANTS = [
    NecklineConfig(name="N4_base_G",      **BASE),
    NecklineConfig(name="N4_K1_ema200",   **BASE, trend_filter="ema200"),
    NecklineConfig(name="N4_K2_ema50slp", **BASE, trend_filter="ema50_slope"),
    NecklineConfig(name="N4_K3_suptrend", **BASE, trend_filter="supertrend"),
    NecklineConfig(name="N4_K4_adx20",    **BASE, trend_filter="adx20"),
    NecklineConfig(name="N4_K5_rsi50",    **BASE, trend_filter="rsi50"),
]


def main():
    bars = load_bars(DATA)
    n = len(bars)
    mid = bars[n // 2]["date"]
    print(f"数据: {bars[0]['date']} → {bars[-1]['date']}  共{n}根 | 分界 {mid}")
    print("口径: 每单 $10,000 名义, 零手续费 | 基座 second@0.5 TP=3L 缓冲0.25L\n")

    rows, all_trades = [], []
    hdr = (f"{'variant':<16}{'信号':>6}{'方向拦':>6}{'成交':>6}{'胜率':>7}{'总盈亏$':>10}{'每笔$':>8}"
           f"{'回撤$':>9} | {'训练$':>9}{'样本外$':>9}")
    print(hdr); print("-" * 98)
    for cfg in VARIANTS:
        r = run_neckline_backtest(bars, cfg)
        tr = r["trades"]
        train, oos = seg(tr, bars[0]["date"], mid), seg(tr, mid, "9999")
        print(f"{r['variant']:<16}{r['n_signals']:>6}{r.get('n_dir_filtered', 0):>6}"
              f"{r['n_trades']:>6}{r['win_rate']*100:>6.1f}%"
              f"{r['total_usd']:>10,.0f}{r['avg_usd']:>8.2f}{r['max_drawdown_usd']:>9,.0f}"
              f" |{train['usd']:>9,.0f}{oos['usd']:>9,.0f}")
        rows.append({
            "variant": r["variant"], "n_signals": r["n_signals"],
            "n_dir_filtered": r.get("n_dir_filtered", 0), "n_trades": r["n_trades"],
            "win_rate": r["win_rate"], "total_usd": r["total_usd"],
            "avg_usd": r["avg_usd"], "max_dd_usd": r["max_drawdown_usd"],
            "train_n": train["n"], "train_usd": round(train["usd"], 0),
            "oos_n": oos["n"], "oos_usd": round(oos["usd"], 0),
        })
        for t in tr:
            t2 = dict(t); t2["variant"] = r["variant"]
            all_trades.append(t2)

    with open(os.path.join(OUT, "neckline_round4_summary.json"), "w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT, "neckline_round4_trades.csv"), "w", newline="") as f:
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
    print("\n已保存: results/neckline_round4_summary.json / neckline_round4_trades.csv")


if __name__ == "__main__":
    main()
