import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""
重叠颈线策略 · 第五轮预注册 (2026-08-17): 组合冲刺

幸存部件: G缓冲0.25L(冠军) / H回踩(回撤王) / ADX>=20强度门(唯一高性价比过滤) /
          放量1.5x(优质但砍量) / ratio 0.6~0.8平台(内部点0.7) / BE推损(小加分)
G与H入场逻辑互斥, 不叠加。

预注册8格 (+3个参照, 全部旧配置复跑):
  参照: G / G+ADX(=四轮K4) / H
  C1: G + ADX + 放量1.5
  C2: G + ADX + ratio0.7
  C3: G + ratio0.7
  C4: G + 放量1.5
  C5: H + ADX
  C6: H + ADX + ratio0.7
  C7: G + ADX + BE推损1L
  C8: H + 放量1.5
评判: 训练/样本外同号且样本外为正; 看总盈亏/每笔/回撤三指标; 样本量<300笔标注小样本。
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
        return {"n": 0, "usd": 0.0}
    return {"n": n, "usd": sum(t["pnl_usd"] for t in s)}


G = dict(ref_mode="second", tp_mult=3.0, buffer_l=0.25)
H = dict(ref_mode="second", tp_mult=3.0, entry_confirm="retest")

VARIANTS = [
    NecklineConfig(name="ref_G",        **G, ratio=0.5),
    NecklineConfig(name="ref_G_ADX",    **G, ratio=0.5, trend_filter="adx20"),
    NecklineConfig(name="ref_H",        **H, ratio=0.5),
    NecklineConfig(name="C1_G_ADX_vol", **G, ratio=0.5, trend_filter="adx20", vol_expansion=1.5),
    NecklineConfig(name="C2_G_ADX_r70", **G, ratio=0.7, trend_filter="adx20"),
    NecklineConfig(name="C3_G_r70",     **G, ratio=0.7),
    NecklineConfig(name="C4_G_vol",     **G, ratio=0.5, vol_expansion=1.5),
    NecklineConfig(name="C5_H_ADX",     **H, ratio=0.5, trend_filter="adx20"),
    NecklineConfig(name="C6_H_ADX_r70", **H, ratio=0.7, trend_filter="adx20"),
    NecklineConfig(name="C7_G_ADX_be",  **G, ratio=0.5, trend_filter="adx20", breakeven_at_l=1.0),
    NecklineConfig(name="C8_H_vol",     **H, ratio=0.5, vol_expansion=1.5),
]


def main():
    bars = load_bars(DATA)
    n = len(bars)
    mid = bars[n // 2]["date"]
    print(f"数据: {bars[0]['date']} → {bars[-1]['date']}  共{n}根 | 分界 {mid}")
    print("口径: 每单 $10,000 名义, 零手续费\n")

    rows, all_trades = [], []
    hdr = (f"{'variant':<14}{'成交':>6}{'胜率':>7}{'总盈亏$':>10}{'每笔$':>8}{'回撤$':>9}"
           f"{'利润/回撤':>9} | {'训练$':>9}{'样本外$':>9}")
    print(hdr); print("-" * 95)
    for cfg in VARIANTS:
        r = run_neckline_backtest(bars, cfg)
        tr = r["trades"]
        train, oos = seg(tr, bars[0]["date"], mid), seg(tr, mid, "9999")
        pf = r["total_usd"] / r["max_drawdown_usd"] if r["max_drawdown_usd"] > 0 else 0
        flag = " ⚠小样本" if r["n_trades"] < 300 else ""
        print(f"{r['variant']:<14}{r['n_trades']:>6}{r['win_rate']*100:>6.1f}%"
              f"{r['total_usd']:>10,.0f}{r['avg_usd']:>8.2f}{r['max_drawdown_usd']:>9,.0f}"
              f"{pf:>9.1f} |{train['usd']:>9,.0f}{oos['usd']:>9,.0f}{flag}")
        rows.append({
            "variant": r["variant"], "n_trades": r["n_trades"], "win_rate": r["win_rate"],
            "total_usd": r["total_usd"], "avg_usd": r["avg_usd"],
            "max_dd_usd": r["max_drawdown_usd"], "profit_dd": round(pf, 1),
            "train_n": train["n"], "train_usd": round(train["usd"], 0),
            "oos_n": oos["n"], "oos_usd": round(oos["usd"], 0),
        })
        for t in tr:
            t2 = dict(t); t2["variant"] = r["variant"]
            all_trades.append(t2)

    with open(os.path.join(OUT, "neckline_round5_summary.json"), "w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT, "neckline_round5_trades.csv"), "w", newline="") as f:
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
    print("\n已保存: results/neckline_round5_summary.json / neckline_round5_trades.csv")


if __name__ == "__main__":
    main()
