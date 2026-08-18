import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""
重叠颈线策略 · 终局确认 (2026-08-17)

终局配置 FINAL = second @ ratio=0.7 + 缓冲0.25L + L距离跟踪出场(P3) + 等风险仓位$40/单(P5, 名义上限$100k)
对照: ref_C3(固定TP) / P3单件 / P5单件
附: FINAL 分行情段 / 分年度 / 多空拆分 / 手续费压力测试(参考, 不改零费口径)
"""
import csv
import json
from neckline_backtest import NecklineConfig, run_neckline_backtest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "BTCUSDT_1h.csv")
OUT = os.path.join(ROOT, "results")


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
        return {"n": 0, "wr": 0, "usd": 0.0}
    w = sum(1 for t in s if t["win"])
    return {"n": len(s), "wr": w / len(s), "usd": sum(t["pnl_usd"] for t in s)}


BASE = dict(ref_mode="second", ratio=0.7, tp_mult=3.0, buffer_l=0.25)

VARIANTS = [
    NecklineConfig(name="ref_C3",   **BASE),
    NecklineConfig(name="P3_trail", **BASE, exit_mode="trail_l"),
    NecklineConfig(name="P5_risk",  **BASE, risk_sizing_usd=40.0),
    NecklineConfig(name="FINAL",    **BASE, exit_mode="trail_l", risk_sizing_usd=40.0),
    # 稳健版: 剔除 L<0.1%价格 的微型单 (止损距离比真实滑点还小, 回测假设不可信,
    # 且等风险公式会把这类单放大到顶格仓位 — 审计发现原FINAL 63%利润来自这里)
    NecklineConfig(name="FINAL_R",  **BASE, exit_mode="trail_l", risk_sizing_usd=40.0,
                   min_l_pct=0.001),
    # 稳健版 + 真实taker费率 (参考)
    NecklineConfig(name="FINAL_Rfee", **BASE, exit_mode="trail_l", risk_sizing_usd=40.0,
                   min_l_pct=0.001, fee_rate=0.0005),
]

# 行情段 (按价格轮廓划定)
SEGMENTS = [
    ("上行1 27k→66k", "2023-05-11", "2024-03-06"),
    ("高位震荡 57-70k", "2024-03-06", "2024-11-01"),
    ("上行2 69k→114k", "2024-11-01", "2025-10-27"),
    ("崩盘 114k→64k", "2025-10-27", "2026-02-24"),
    ("反弹 64k→81k", "2026-02-24", "2026-05-11"),
]


def main():
    bars = load_bars(DATA)
    n = len(bars)
    mid = bars[n // 2]["date"]
    print(f"数据: {bars[0]['date']} → {bars[-1]['date']}  共{n}根 | 分界 {mid}\n")

    results = {}
    hdr = (f"{'variant':<10}{'成交':>6}{'胜率':>7}{'总盈亏$':>10}{'每笔$':>8}{'回撤$':>8}"
           f"{'利润/回撤':>9} | {'训练$':>9}{'样本外$':>9}")
    print(hdr); print("-" * 88)
    rows = []
    for cfg in VARIANTS:
        r = run_neckline_backtest(bars, cfg)
        results[cfg.name] = r
        tr = r["trades"]
        train, oos = seg(tr, bars[0]["date"], mid), seg(tr, mid, "9999")
        pf = r["total_usd"] / r["max_drawdown_usd"] if r["max_drawdown_usd"] > 0 else 0
        print(f"{r['variant']:<10}{r['n_trades']:>6}{r['win_rate']*100:>6.1f}%"
              f"{r['total_usd']:>10,.0f}{r['avg_usd']:>8.2f}{r['max_drawdown_usd']:>8,.0f}"
              f"{pf:>9.1f} |{train['usd']:>9,.0f}{oos['usd']:>9,.0f}")
        rows.append({"variant": r["variant"], "n_trades": r["n_trades"],
                     "win_rate": r["win_rate"], "total_usd": r["total_usd"],
                     "avg_usd": r["avg_usd"], "max_dd_usd": r["max_drawdown_usd"],
                     "profit_dd": round(pf, 1),
                     "train_usd": round(train["usd"], 0), "oos_usd": round(oos["usd"], 0)})

    ftr = results["FINAL_R"]["trades"]  # 分段/分年度/多空拆分用稳健版

    print("\nFINAL 分行情段:")
    seg_rows = []
    for nm, a, b in SEGMENTS:
        s = seg(ftr, a, b)
        print(f"  {nm:<18} n={s['n']:>4}  wr={s['wr']*100:>5.1f}%  ${s['usd']:>+10,.0f}")
        seg_rows.append({"segment": nm, **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()}})

    print("\nFINAL 分年度:")
    from collections import defaultdict
    yr = defaultdict(list)
    for t in ftr:
        yr[t["entry_date"][:4]].append(t)
    year_rows = []
    for y in sorted(yr):
        ts = yr[y]
        usd = sum(t["pnl_usd"] for t in ts)
        w = sum(1 for t in ts if t["win"]) / len(ts)
        print(f"  {y}: n={len(ts):>4}  wr={w*100:.1f}%  ${usd:>+10,.0f}")
        year_rows.append({"year": y, "n": len(ts), "wr": round(w, 3), "usd": round(usd, 0)})

    print("\nFINAL 多空拆分:")
    for d in ("long", "short"):
        ts = [t for t in ftr if t["direction"] == d]
        usd = sum(t["pnl_usd"] for t in ts)
        w = sum(1 for t in ts if t["win"]) / len(ts) if ts else 0
        print(f"  {d:<6} n={len(ts):>4}  wr={w*100:.1f}%  ${usd:>+10,.0f}")

    print("\n手续费压力测试 (FINAL, 单边费率, 仅供参考):")
    fee_rows = []
    for fee in (0.0, 0.0001, 0.0002, 0.0005):
        cfg = NecklineConfig(name=f"FINAL_fee{fee}", **BASE, exit_mode="trail_l",
                             risk_sizing_usd=40.0, fee_rate=fee)
        r = run_neckline_backtest(bars, cfg)
        print(f"  {fee*100:.2f}%/边: 总${r['total_usd']:>+10,.0f}  每笔${r['avg_usd']:>7.2f}")
        fee_rows.append({"fee_side": fee, "total_usd": r["total_usd"], "avg_usd": r["avg_usd"]})

    with open(os.path.join(OUT, "neckline_final_summary.json"), "w") as f:
        json.dump({"variants": rows, "final_segments": seg_rows,
                   "final_years": year_rows, "fee_stress": fee_rows}, f,
                  indent=2, ensure_ascii=False)
    with open(os.path.join(OUT, "neckline_final_trades.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["signal_date", "entry_date", "exit_date", "direction", "entry",
                    "level", "L", "sl", "tp", "exit", "exit_reason", "bars_held",
                    "notional", "pnl_usd", "win"])
        for t in ftr:
            w.writerow([t["signal_date"], t["entry_date"], t["exit_date"], t["direction"],
                        round(t["entry"], 2), round(t["level"], 2), round(t["L"], 2),
                        round(t["sl"], 2), (round(t["tp"], 2) if t["tp"] is not None else ""),
                        round(t["exit"], 2), t["exit_reason"], t["bars_held"],
                        t.get("notional", 10000), round(t["pnl_usd"], 2), t["win"]])
    print("\n已保存: results/neckline_final_summary.json / neckline_final_trades.csv")


if __name__ == "__main__":
    main()
