import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""
横向对比10个变体在3年和"那12个月震荡期"的表现差异
找出: (a) 谁在长跑赢, (b) 谁在震荡期不输
"""
import os
from backtest import run_backtest
from variants import VARIANTS
from equity_backtest import load_bars

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
WIN_START = "2024-03-20"
WIN_END = "2025-04-01"


def main():
    bars = load_bars(os.path.join(DATA_DIR, "BTCUSDT_1h.csv"))
    print(f"对比窗口: {WIN_START} ~ {WIN_END}\n")
    print(f"{'变体':<28} {'3年信号':>7} {'3年胜率':>8} {'3年TotalR':>10} | {'窗口信号':>8} {'窗口胜率':>9} {'窗口R':>8} {'窗口DD':>7}")
    print("-" * 115)

    for cfg in VARIANTS:
        bt = run_backtest(bars, cfg)
        all_trades = bt["trades"]
        n3 = len(all_trades)
        w3 = sum(1 for t in all_trades if t["win"])
        tr3 = sum(t["net_r"] for t in all_trades)

        wnd = [t for t in all_trades if WIN_START <= t["entry_date"][:10] <= WIN_END]
        nw = len(wnd)
        ww = sum(1 for t in wnd if t["win"])
        trw = sum(t["net_r"] for t in wnd)

        # 窗口内R累积回撤
        wnd_sorted = sorted(wnd, key=lambda x: x["entry_date"])
        eq, pk, dd = 0, 0, 0
        for t in wnd_sorted:
            eq += t["net_r"]
            pk = max(pk, eq)
            dd = max(dd, pk - eq)

        wr3 = (w3/n3*100) if n3 else 0
        wrw = (ww/nw*100) if nw else 0
        print(f"{cfg.name:<28} {n3:>7} {wr3:>7.1f}% {tr3:>+9.2f} | {nw:>8} {wrw:>8.1f}% {trw:>+8.2f} {dd:>7.2f}")


if __name__ == "__main__":
    main()
