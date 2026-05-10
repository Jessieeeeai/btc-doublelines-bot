"""
Hedge 模式资金曲线模拟器 (符合币安/OKX 双向持仓实盘机制)

核心机制:
1. 多空可同时持有, 各占独立保证金
2. 每笔信号按固定%风险开仓 (risk_per_trade × 当前余额)
3. 保证金占用 = position_notional / leverage
4. 总占用保证金不超过 capital × max_leverage_total (默认10x = 100%占用) -> 否则跳过
5. SL/TP 触发各仓位独立平仓; EOD 强平
6. 任何瞬间 free_balance + 浮盈/亏 跌破 0 -> 爆仓清零

可调维度: risk_per_trade, max_leverage_total, position_mode (hedge / single)
"""
import os
import csv
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from backtest import run_backtest
from variants import VARIANTS
from equity_backtest import load_bars

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(OUT_DIR, exist_ok=True)


@dataclass
class OpenPosition:
    entry_idx: int
    exit_idx: int
    entry_date: str
    direction: str
    entry: float
    sl: float
    tp: float
    qty: float
    notional: float
    margin: float


def simulate_hedge(bars, trades, starting=1000.0, risk_per_trade=0.02,
                   max_leverage_total=10.0, fee_rate=0.0005, mode="hedge"):
    """
    bars: 时间排列的K线 (用于日期->索引映射)
    trades: 来自 run_backtest 的交易列表 (已含 entry_date/exit_date/direction/entry/sl/tp/exit)
    mode: "hedge" / "single_position" / "reverse"
    """
    date_to_idx = {b["date"]: i for i, b in enumerate(bars)}

    capital = starting
    peak = starting
    max_dd_pct = 0.0
    open_positions: List[OpenPosition] = []
    curve = [{"date": "start", "capital": starting, "open_positions": 0}]

    n_signals_received = 0
    n_signals_taken = 0
    n_signals_skipped = 0
    n_wins = 0
    n_losses = 0
    liquidated = False

    # 把交易按 entry_idx 排序
    sigs = []
    for t in trades:
        e_idx = date_to_idx.get(t["entry_date"])
        x_idx = date_to_idx.get(t["exit_date"])
        if e_idx is None or x_idx is None:
            continue
        sigs.append({**t, "entry_idx": e_idx, "exit_idx": x_idx})
    sigs.sort(key=lambda x: x["entry_idx"])

    # 主循环: 按 bar 走时间, 在每根 bar:
    # 1) 处理所有应在该 bar 平仓的 open_positions
    # 2) 处理在该 bar 触发的新信号
    sig_ptr = 0
    for bar_idx, bar in enumerate(bars):
        if capital <= 0:
            break

        # Step 1: 平仓 open_positions where exit_idx == bar_idx
        still_open = []
        for pos in open_positions:
            if pos.exit_idx == bar_idx:
                # 计算 PnL
                # 找到对应的 trade 记录获取 exit_price
                exit_price = None
                for t in sigs:
                    if t["entry_idx"] == pos.entry_idx and t["direction"] == pos.direction:
                        exit_price = t["exit"]
                        break
                if exit_price is None:
                    exit_price = bar["close"]

                if pos.direction == "long":
                    pnl = pos.qty * (exit_price - pos.entry)
                else:
                    pnl = pos.qty * (pos.entry - exit_price)
                exit_notional = pos.qty * exit_price
                fees = (pos.notional + exit_notional) * fee_rate
                net = pnl - fees

                capital += net
                if net > 0: n_wins += 1
                else: n_losses += 1

                if capital <= 0:
                    capital = 0
                    liquidated = True
                    curve.append({"date": bar["date"], "capital": 0,
                                  "event": "LIQUIDATED",
                                  "open_positions": len(still_open)})
                    break
            else:
                still_open.append(pos)

        if liquidated:
            break
        open_positions = still_open

        # 更新峰值/回撤
        peak = max(peak, capital)
        dd = (peak - capital) / peak if peak > 0 else 0
        max_dd_pct = max(max_dd_pct, dd)

        # Step 2: 处理在该 bar 入场的新信号
        while sig_ptr < len(sigs) and sigs[sig_ptr]["entry_idx"] == bar_idx:
            sig = sigs[sig_ptr]
            sig_ptr += 1
            n_signals_received += 1

            # 模式检查
            if mode == "single_position" and open_positions:
                n_signals_skipped += 1
                continue

            if mode == "reverse" and open_positions:
                # 仅当反向时才动作: 全部平掉再开新
                same_dir = any(p.direction == sig["direction"] for p in open_positions)
                if same_dir:
                    n_signals_skipped += 1
                    continue
                # 反向: 把所有现有仓位按 bar 当前 close 强平
                for pos in open_positions:
                    if pos.direction == "long":
                        pnl = pos.qty * (bar["close"] - pos.entry)
                    else:
                        pnl = pos.qty * (pos.entry - bar["close"])
                    fees = (pos.notional + pos.qty * bar["close"]) * fee_rate
                    capital += (pnl - fees)
                    if (pnl - fees) > 0: n_wins += 1
                    else: n_losses += 1
                open_positions = []
                if capital <= 0:
                    capital = 0
                    liquidated = True
                    break

            # 计算新仓位
            risk_amount = capital * risk_per_trade
            sl_dist = abs(sig["entry"] - sig["sl"])
            if sl_dist <= 0:
                n_signals_skipped += 1
                continue
            qty = risk_amount / sl_dist
            notional = qty * sig["entry"]

            # 保证金: notional / leverage_cap
            new_margin = notional / max_leverage_total
            used_margin = sum(p.margin for p in open_positions)
            free_margin = capital - used_margin
            if new_margin > free_margin:
                # 保证金不够 -> 缩仓到能开
                if free_margin <= 0:
                    n_signals_skipped += 1
                    continue
                allowable_notional = free_margin * max_leverage_total
                qty = allowable_notional / sig["entry"]
                notional = allowable_notional
                new_margin = free_margin

            open_positions.append(OpenPosition(
                entry_idx=sig["entry_idx"], exit_idx=sig["exit_idx"],
                entry_date=sig["entry_date"], direction=sig["direction"],
                entry=sig["entry"], sl=sig["sl"], tp=sig["tp"],
                qty=qty, notional=notional, margin=new_margin,
            ))
            n_signals_taken += 1

        curve.append({"date": bar["date"], "capital": round(capital, 2),
                      "open_positions": len(open_positions)})

    return {
        "mode": mode,
        "starting": starting,
        "risk_per_trade": risk_per_trade,
        "max_leverage_total": max_leverage_total,
        "final": round(capital, 2),
        "return_pct": round((capital - starting) / starting * 100, 2),
        "peak": round(peak, 2),
        "max_dd_pct": round(max_dd_pct * 100, 2),
        "n_signals_received": n_signals_received,
        "n_signals_taken": n_signals_taken,
        "n_signals_skipped": n_signals_skipped,
        "n_wins": n_wins,
        "n_losses": n_losses,
        "win_rate": round(n_wins / (n_wins + n_losses), 4) if (n_wins + n_losses) else 0,
        "liquidated": liquidated,
        "curve": curve,
    }


def main():
    csvs = [f for f in os.listdir(DATA_DIR) if f.endswith("_1h.csv")]
    if not csvs:
        print("ERROR: 先运行 fetch_data.py")
        return
    bars = load_bars(os.path.join(DATA_DIR, csvs[0]))
    sym = csvs[0].replace("_1h.csv", "")

    # 优先找 F6 (新冠军), 再找 W4, 再 R1, 兜底取第一个
    r1_cfg = next((v for v in VARIANTS if v.name.startswith("F6_")),
                  next((v for v in VARIANTS if v.name.startswith("W4_")),
                       next((v for v in VARIANTS if v.name.startswith("R1_")),
                            VARIANTS[0])))
    bt = run_backtest(bars, r1_cfg)
    trades = sorted(bt["trades"], key=lambda x: x["entry_date"])

    print(f"策略: {r1_cfg.name}, 数据: {sym} {len(bars)} 根 1h")
    print(f"R1 原始信号 {len(trades)} 笔\n")

    # 三模式 × 多种风险百分比 = 12 个 PK 组合
    configs = []
    for mode in ["single_position", "reverse", "hedge"]:
        for risk in [0.01, 0.02, 0.05]:
            configs.append((mode, risk))

    print(f"{'模式':<18} {'风险%/笔':>9} {'信号收':>8} {'实际开':>8} {'胜率':>7} {'终值$':>10} {'回报%':>9} {'回撤%':>8} {'爆仓':>5}")
    print("-" * 105)

    results = []
    for mode, risk in configs:
        r = simulate_hedge(bars, trades, starting=1000.0, risk_per_trade=risk,
                          max_leverage_total=10.0, mode=mode)
        results.append(r)
        liq = "Y" if r["liquidated"] else "-"
        print(f"{mode:<18} {risk*100:>8.1f}% "
              f"{r['n_signals_received']:>8} {r['n_signals_taken']:>8} "
              f"{r['win_rate']*100:>6.1f}% {r['final']:>10.2f} "
              f"{r['return_pct']:>+8.1f}% {r['max_dd_pct']:>7.1f}% {liq:>5}")

    # 保存
    path = os.path.join(OUT_DIR, "hedge_comparison.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mode", "risk_pct", "signals_received", "signals_taken", "win_rate",
                    "final", "return_pct", "max_dd_pct", "liquidated"])
        for r in results:
            w.writerow([r["mode"], r["risk_per_trade"], r["n_signals_received"], r["n_signals_taken"],
                        r["win_rate"], r["final"], r["return_pct"], r["max_dd_pct"], r["liquidated"]])

    # 保存重点曲线: hedge mode + 2% risk
    best = next(r for r in results if r["mode"] == "hedge" and r["risk_per_trade"] == 0.02)
    curve_path = os.path.join(OUT_DIR, "hedge_curve_2pct.csv")
    with open(curve_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "capital", "open_positions", "event"])
        for c in best["curve"]:
            w.writerow([c["date"], c["capital"], c.get("open_positions", 0), c.get("event", "")])

    print(f"\n汇总: {path}")
    print(f"Hedge 2% 风险曲线: {curve_path}")


if __name__ == "__main__":
    main()
