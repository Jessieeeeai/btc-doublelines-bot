"""
仓位管理赛马: 固定使用 R1 (baseline body=0.5) 策略, PK 10 种仓位管理方式

3大类:
  全仓滚动 (capital × leverage):  1x / 3x / 5x / 10x — 看杠杆放大效应
  固定%风险 + 10x上限:             0.5% / 1% / 2% / 3% / 5% / 10%(Kelly) — 看风控强度
  固定u下注 × 10x:                 每笔固定100u × 10倍 — 不复利的对照组

输出: results/sizing_summary.csv + 各曲线 CSV
"""
import os
import csv
import json
from dataclasses import dataclass
from typing import List, Optional

from backtest import VariantConfig, run_backtest
from variants import VARIANTS
from equity_backtest import load_bars

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(OUT_DIR, exist_ok=True)


@dataclass
class SizingConfig:
    name: str
    mode: str               # "compound" / "fixed_risk" / "fixed_notional"
    leverage: float = 1.0
    risk_pct: float = 0.0   # fixed_risk only
    leverage_cap: float = 10.0  # fixed_risk only
    notional: float = 0.0   # fixed_notional only


SIZING_GRID = [
    SizingConfig("S1_compound_1x",    "compound", leverage=1),
    SizingConfig("S2_compound_3x",    "compound", leverage=3),
    SizingConfig("S3_compound_5x",    "compound", leverage=5),
    SizingConfig("S4_compound_10x",   "compound", leverage=10),
    SizingConfig("S5_risk0.5pct",     "fixed_risk", risk_pct=0.005, leverage_cap=10),
    SizingConfig("S6_risk1pct",       "fixed_risk", risk_pct=0.01,  leverage_cap=10),
    SizingConfig("S7_risk2pct",       "fixed_risk", risk_pct=0.02,  leverage_cap=10),
    SizingConfig("S8_risk3pct",       "fixed_risk", risk_pct=0.03,  leverage_cap=10),
    SizingConfig("S9_risk5pct",       "fixed_risk", risk_pct=0.05,  leverage_cap=10),
    SizingConfig("S10_risk10pct_Kelly","fixed_risk", risk_pct=0.10,  leverage_cap=10),
]


def simulate(trades, sizing: SizingConfig, starting=1000.0, fee_rate=0.0005):
    """统一模拟器, 根据 mode 分支。"""
    capital = starting
    peak = starting
    max_dd_pct = 0.0
    curve = [{"date": "start", "capital": starting}]
    n_trades = 0
    n_wins = 0
    liquidated_at = None

    for t in trades:
        if capital <= 0:
            break
        n_trades += 1

        # 计算 notional
        if sizing.mode == "compound":
            notional = capital * sizing.leverage
        elif sizing.mode == "fixed_risk":
            risk_amount = capital * sizing.risk_pct
            sl_dist = abs(t["entry"] - t["sl"])
            if sl_dist <= 0:
                continue
            qty_by_risk = risk_amount / sl_dist
            notional_by_risk = qty_by_risk * t["entry"]
            notional_cap = capital * sizing.leverage_cap
            notional = min(notional_by_risk, notional_cap)
        elif sizing.mode == "fixed_notional":
            notional = min(sizing.notional, capital * 10)
        else:
            continue

        qty = notional / t["entry"]
        if t["direction"] == "long":
            pnl_per_unit = t["exit"] - t["entry"]
        else:
            pnl_per_unit = t["entry"] - t["exit"]
        gross_pnl = qty * pnl_per_unit
        fees = (notional + qty * t["exit"]) * fee_rate
        net_pnl = gross_pnl - fees

        new_capital = capital + net_pnl
        if new_capital <= 0:
            curve.append({"date": t["exit_date"], "capital": 0})
            capital = 0
            liquidated_at = n_trades
            break

        if net_pnl > 0:
            n_wins += 1
        capital = new_capital
        peak = max(peak, capital)
        dd = (peak - capital) / peak if peak > 0 else 0
        max_dd_pct = max(max_dd_pct, dd)
        curve.append({"date": t["exit_date"], "capital": round(capital, 2)})

    return {
        "name": sizing.name,
        "mode": sizing.mode,
        "starting": starting,
        "final": round(capital, 2),
        "return_pct": round((capital - starting) / starting * 100, 2) if starting else 0,
        "peak": round(peak, 2),
        "max_dd_pct": round(max_dd_pct * 100, 2),
        "n_trades": n_trades,
        "n_wins": n_wins,
        "win_rate": round(n_wins / n_trades, 4) if n_trades else 0,
        "liquidated_at_trade": liquidated_at,
        "curve": curve,
    }


def main():
    csvs = [f for f in os.listdir(DATA_DIR) if f.endswith("_1h.csv")]
    if not csvs:
        print("ERROR: 先运行 fetch_data.py")
        return
    bars = load_bars(os.path.join(DATA_DIR, csvs[0]))
    sym = csvs[0].replace("_1h.csv", "")

    # 用 R1 baseline 出交易
    r1_cfg = next((v for v in VARIANTS if v.name.startswith("R1_")), VARIANTS[0])
    print(f"策略: {r1_cfg.name}")
    print(f"数据: {sym} {len(bars)} 根 1h K线\n")
    bt = run_backtest(bars, r1_cfg)
    trades = sorted(bt["trades"], key=lambda x: x["entry_date"])
    print(f"R1 共 {len(trades)} 笔交易, 胜率 {bt['win_rate']*100:.1f}%\n")

    print(f"{'仓位方案':<26} {'模式':<14} {'终值($)':>11} {'回报%':>10} {'回撤%':>8} {'胜率':>7} {'爆仓笔数':>9}")
    print("-" * 95)

    results = []
    for s in SIZING_GRID:
        r = simulate(trades, s)
        results.append(r)
        liq = f"#{r['liquidated_at_trade']}" if r['liquidated_at_trade'] else "-"
        print(f"{r['name']:<26} {r['mode']:<14} {r['final']:>11} {r['return_pct']:>+9.1f}% {r['max_dd_pct']:>7.1f}% {r['win_rate']*100:>6.1f}% {liq:>9}")

    # 保存 summary
    sum_path = os.path.join(OUT_DIR, "sizing_summary.csv")
    with open(sum_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sizing", "mode", "starting", "final", "return_pct", "max_dd_pct",
                    "n_trades", "win_rate", "liquidated_at"])
        for r in results:
            w.writerow([r["name"], r["mode"], r["starting"], r["final"], r["return_pct"],
                        r["max_dd_pct"], r["n_trades"], r["win_rate"], r["liquidated_at_trade"] or ""])

    # 保存全部曲线 (宽表格式)
    curves_path = os.path.join(OUT_DIR, "sizing_curves.csv")
    max_len = max(len(r["curve"]) for r in results)
    with open(curves_path, "w", newline="") as f:
        w = csv.writer(f)
        # header
        header = ["step"]
        for r in results:
            header += [f"{r['name']}_date", f"{r['name']}_capital"]
        w.writerow(header)
        for i in range(max_len):
            row = [i]
            for r in results:
                if i < len(r["curve"]):
                    row += [r["curve"][i]["date"], r["curve"][i]["capital"]]
                else:
                    row += ["", ""]
            w.writerow(row)

    print(f"\n汇总: {sum_path}")
    print(f"曲线: {curves_path}")


if __name__ == "__main__":
    main()
