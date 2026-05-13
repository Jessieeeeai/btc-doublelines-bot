import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""
资金曲线模拟器 - 在R-Multiple回测出来的交易序列上, 加上杠杆 + 起始本金 + 复利。

模型 (默认全仓滚动):
  每次开仓:    notional = 当前余额 × leverage
  数量:        qty = notional / entry_price
  止损被触发:  亏损 = qty × (entry - SL) (long) 或 qty × (SL - entry) (short)
  止盈被触发:  盈利 = qty × (TP - entry) 或 qty × (entry - TP)
  手续费:      maker/taker单边 0.05%, 双边对 notional 收 0.1%
  爆仓判定:    若亏损 ≥ 当前余额 → 爆仓, 余额清零, 后续交易不再发生

可选 fixed_risk_pct (e.g., 0.01 = 每笔只赌 1% 本金):
  position 按 SL 距离反推, 不管 leverage 上限, 但加 cap = 余额 × leverage
"""
import os
import csv
import json
from typing import List, Dict, Any, Tuple

from backtest import VariantConfig, run_backtest
from variants import VARIANTS
from signals import detect_signals

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(OUT_DIR, exist_ok=True)


def load_bars(path):
    bars = []
    with open(path) as f:
        for r in csv.DictReader(f):
            bars.append({
                "date": r["date"],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            })
    bars.sort(key=lambda x: x["date"])
    return bars


def simulate_full_compound(trades: List[Dict[str, Any]], starting: float = 1000.0,
                            leverage: float = 10.0, fee_rate: float = 0.0005
                           ) -> Tuple[List[Dict], Dict]:
    """全仓滚动: 每次开仓用当前余额 × leverage"""
    capital = starting
    peak = starting
    max_dd_pct = 0.0
    max_dd_abs = 0.0
    curve = [{"date": "start", "capital": starting, "event": "init"}]

    liquidated_at = None
    n_trades = 0
    n_wins = 0
    n_losses = 0

    for t in trades:
        if capital <= 0:
            break
        n_trades += 1

        notional = capital * leverage
        qty = notional / t["entry"]
        if t["direction"] == "long":
            pnl_per_unit = t["exit"] - t["entry"]
        else:
            pnl_per_unit = t["entry"] - t["exit"]
        gross_pnl = qty * pnl_per_unit
        # 手续费: 入场notional + 出场notional 各收一次
        exit_notional = qty * t["exit"]
        fees = (notional + exit_notional) * fee_rate
        net_pnl = gross_pnl - fees

        new_capital = capital + net_pnl

        if new_capital <= 0:
            # 爆仓
            curve.append({
                "date": t["exit_date"],
                "capital": 0.0,
                "event": "LIQUIDATED",
                "pnl": -capital,
                "direction": t["direction"],
                "exit_reason": t["exit_reason"],
                "trade_idx": n_trades,
            })
            capital = 0
            liquidated_at = n_trades
            if net_pnl > 0:
                n_wins += 1
            else:
                n_losses += 1
            break

        if net_pnl > 0:
            n_wins += 1
        else:
            n_losses += 1
        capital = new_capital
        peak = max(peak, capital)
        dd = (peak - capital)
        dd_pct = dd / peak if peak > 0 else 0
        max_dd_abs = max(max_dd_abs, dd)
        max_dd_pct = max(max_dd_pct, dd_pct)

        curve.append({
            "date": t["exit_date"],
            "capital": round(capital, 2),
            "event": t["exit_reason"],
            "pnl": round(net_pnl, 2),
            "direction": t["direction"],
            "trade_idx": n_trades,
        })

    summary = {
        "starting": starting,
        "leverage": leverage,
        "final": round(capital, 2),
        "return_pct": round((capital - starting) / starting * 100, 2) if starting else 0,
        "peak": round(peak, 2),
        "max_dd_abs": round(max_dd_abs, 2),
        "max_dd_pct": round(max_dd_pct * 100, 2),
        "n_trades_taken": n_trades,
        "n_trades_in_strategy": len(trades),
        "n_wins": n_wins,
        "n_losses": n_losses,
        "win_rate": round(n_wins / n_trades, 4) if n_trades else 0,
        "liquidated_at_trade": liquidated_at,
    }
    return curve, summary


def simulate_fixed_risk(trades, starting=1000.0, risk_per_trade_pct=0.02,
                        leverage_cap=10.0, fee_rate=0.0005):
    """按固定风险百分比下注: position size 让 SL hit = risk_per_trade_pct 的本金"""
    capital = starting
    peak = starting
    max_dd_pct = 0
    max_dd_abs = 0
    curve = [{"date": "start", "capital": starting, "event": "init"}]

    n_trades = 0
    n_wins = 0
    n_losses = 0

    for t in trades:
        if capital <= 0:
            break
        n_trades += 1

        # 每笔风险: capital * risk_per_trade_pct
        risk_amount = capital * risk_per_trade_pct
        sl_distance_per_unit = abs(t["entry"] - t["sl"])
        if sl_distance_per_unit <= 0:
            continue
        qty = risk_amount / sl_distance_per_unit
        notional = qty * t["entry"]
        # 不超过 cap
        max_notional = capital * leverage_cap
        if notional > max_notional:
            qty = max_notional / t["entry"]
            notional = max_notional

        if t["direction"] == "long":
            pnl_per_unit = t["exit"] - t["entry"]
        else:
            pnl_per_unit = t["entry"] - t["exit"]
        gross_pnl = qty * pnl_per_unit
        fees = (notional + qty * t["exit"]) * fee_rate
        net_pnl = gross_pnl - fees

        new_capital = capital + net_pnl
        if new_capital <= 0:
            curve.append({"date": t["exit_date"], "capital": 0, "event": "LIQUIDATED", "trade_idx": n_trades})
            capital = 0
            break

        if net_pnl > 0:
            n_wins += 1
        else:
            n_losses += 1

        capital = new_capital
        peak = max(peak, capital)
        dd = peak - capital
        max_dd_abs = max(max_dd_abs, dd)
        max_dd_pct = max(max_dd_pct, dd / peak if peak else 0)

        curve.append({
            "date": t["exit_date"], "capital": round(capital, 2),
            "event": t["exit_reason"], "pnl": round(net_pnl, 2),
            "direction": t["direction"], "trade_idx": n_trades,
        })

    return curve, {
        "starting": starting,
        "risk_per_trade_pct": risk_per_trade_pct,
        "leverage_cap": leverage_cap,
        "final": round(capital, 2),
        "return_pct": round((capital - starting) / starting * 100, 2) if starting else 0,
        "peak": round(peak, 2),
        "max_dd_pct": round(max_dd_pct * 100, 2),
        "n_trades_taken": n_trades,
        "n_wins": n_wins,
        "n_losses": n_losses,
        "win_rate": round(n_wins / n_trades, 4) if n_trades else 0,
    }


def run_for_variant(cfg: VariantConfig, bars, starting=1000.0, leverage=10.0):
    result = run_backtest(bars, cfg)
    trades = sorted(result["trades"], key=lambda x: x["entry_date"])
    if not trades:
        return None

    curve_compound, sum_compound = simulate_full_compound(trades, starting, leverage)
    curve_fixed, sum_fixed = simulate_fixed_risk(trades, starting, risk_per_trade_pct=0.02, leverage_cap=leverage)
    return {
        "variant": cfg.name,
        "n_signals": len(trades),
        "compound": {"curve": curve_compound, "summary": sum_compound},
        "fixed_risk": {"curve": curve_fixed, "summary": sum_fixed},
    }


def main():
    csvs = [f for f in os.listdir(DATA_DIR) if f.endswith("_1h.csv")]
    if not csvs:
        print("ERROR: 找不到 data/*_1h.csv, 先运行 fetch_data.py")
        return
    bars = load_bars(os.path.join(DATA_DIR, csvs[0]))
    symbol = csvs[0].replace("_1h.csv", "")

    # 默认对所有变体都模拟, 但重点关注 R1
    print(f"基于 {symbol} 共 {len(bars)} 根 1h K线\n")
    print(f"起始资金: $1000 USDT, 杠杆: 10x\n")
    print(f"{'变体':<28} {'信号':>4} {'全仓终值':>10} {'回报%':>9} {'回撤%':>8} {'爆仓':>6} | {'固定2%风险终值':>14} {'回报%':>8} {'回撤%':>7}")
    print("-" * 115)

    all_results = []
    for cfg in VARIANTS:
        r = run_for_variant(cfg, bars)
        if r is None:
            continue
        all_results.append(r)
        c = r["compound"]["summary"]
        f = r["fixed_risk"]["summary"]
        liq_marker = f"#{c['liquidated_at_trade']}" if c['liquidated_at_trade'] else "-"
        print(f"{cfg.name:<28} {r['n_signals']:>4} "
              f"${c['final']:>9} {c['return_pct']:>+8.1f}% {c['max_dd_pct']:>7.1f}% {liq_marker:>6} | "
              f"${f['final']:>12} {f['return_pct']:>+7.1f}% {f['max_dd_pct']:>6.1f}%")

    # 保存R1 baseline的完整资金曲线 (重点变体)
    r1 = next((r for r in all_results if r["variant"].startswith("R1_")), all_results[0])
    curve_path = os.path.join(OUT_DIR, "equity_curve_R1.csv")
    with open(curve_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "capital_compound", "capital_fixed_risk", "event"])
        compound_curve = r1["compound"]["curve"]
        fixed_curve = r1["fixed_risk"]["curve"]
        # 按 trade_idx 对齐
        cur_compound = {c.get("trade_idx", 0): c["capital"] for c in compound_curve}
        for fp in fixed_curve:
            idx = fp.get("trade_idx", 0)
            comp_cap = cur_compound.get(idx, "")
            w.writerow([fp["date"], comp_cap, fp["capital"], fp.get("event", "")])

    summary_path = os.path.join(OUT_DIR, "equity_summary.json")
    with open(summary_path, "w") as f:
        json.dump([{
            "variant": r["variant"],
            "n_signals": r["n_signals"],
            "compound": r["compound"]["summary"],
            "fixed_risk": r["fixed_risk"]["summary"],
        } for r in all_results], f, indent=2)

    print(f"\n资金曲线 (R1): {curve_path}")
    print(f"全部摘要: {summary_path}")


if __name__ == "__main__":
    main()
