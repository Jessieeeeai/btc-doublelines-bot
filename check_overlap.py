"""
检查 R1 信号的重叠情况: 多少笔信号是在前一单还没平仓时触发的?
"""
import os
import csv
from backtest import run_backtest
from variants import VARIANTS
from equity_backtest import load_bars

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def main():
    csvs = [f for f in os.listdir(DATA_DIR) if f.endswith("_1h.csv")]
    bars = load_bars(os.path.join(DATA_DIR, csvs[0]))

    cfg = next(v for v in VARIANTS if v.name.startswith("R1_"))
    bt = run_backtest(bars, cfg)
    trades = sorted(bt["trades"], key=lambda x: x["entry_date"])

    # 把日期映射回 bar 索引方便比较
    date_to_idx = {b["date"]: i for i, b in enumerate(bars)}
    annotated = []
    for t in trades:
        e_idx = date_to_idx.get(t["entry_date"], -1)
        x_idx = date_to_idx.get(t["exit_date"], -1)
        annotated.append({**t, "entry_idx": e_idx, "exit_idx": x_idx})

    # 检查每笔: 它的 entry 是否在前面任意一笔还未平的窗口里
    overlap_same_dir = 0     # 重叠且同方向
    overlap_opp_dir = 0      # 重叠且反方向
    standalone = 0
    by_overlap_type = {"long_in_long": 0, "long_in_short": 0,
                       "short_in_long": 0, "short_in_short": 0}

    for i, t in enumerate(annotated):
        in_overlap = False
        overlap_dir = None
        for j in range(i):
            prev = annotated[j]
            # 如果前一笔还在车上 (prev.entry_idx < t.entry_idx <= prev.exit_idx)
            if prev["entry_idx"] < t["entry_idx"] <= prev["exit_idx"]:
                in_overlap = True
                overlap_dir = prev["direction"]
                break
        if not in_overlap:
            standalone += 1
        else:
            key = f"{t['direction']}_in_{overlap_dir}"
            by_overlap_type[key] = by_overlap_type.get(key, 0) + 1
            if t["direction"] == overlap_dir:
                overlap_same_dir += 1
            else:
                overlap_opp_dir += 1

    n = len(annotated)
    print(f"R1 共 {n} 笔交易")
    print(f"\n独立信号 (前一单已平): {standalone} ({standalone/n*100:.1f}%)")
    print(f"重叠信号 (前一单还在车上): {n - standalone} ({(n - standalone)/n*100:.1f}%)")
    print(f"  └ 同方向重叠 (e.g. 多上加多): {overlap_same_dir}")
    print(f"  └ 反向重叠 (e.g. 多单未平来空信号): {overlap_opp_dir}")
    print(f"\n分类:")
    for k, v in by_overlap_type.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
