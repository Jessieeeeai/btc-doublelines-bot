"""
拆分多/空方向的表现 - 看是否有一个方向是拖累
读取 results/all_trades.csv, 按 variant x direction 分组统计
"""
import os
import csv
from collections import defaultdict

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def main():
    path = os.path.join(RESULTS_DIR, "all_trades.csv")
    if not os.path.exists(path):
        print(f"ERROR: 找不到 {path}, 请先运行 run_backtest.py")
        return

    # groups[(variant, direction)] = list of net_r
    groups = defaultdict(list)
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row["variant"], row["direction"])
            groups[key].append(float(row["net_r"]))

    # 按 variant 分组
    variants = sorted({k[0] for k in groups})

    print(f"{'变体':<28} {'方向':<6} {'交易数':>7} {'胜率':>8} {'Total R':>9} {'Avg R':>8} {'差值':>8}")
    print("-" * 80)
    for v in variants:
        long_rs = groups.get((v, "long"), [])
        short_rs = groups.get((v, "short"), [])

        for direction, rs in [("long", long_rs), ("short", short_rs)]:
            n = len(rs)
            if n == 0:
                continue
            wins = sum(1 for r in rs if r > 0)
            wr = wins / n
            tot = sum(rs)
            avg = tot / n
            print(f"{v:<28} {direction:<6} {n:>7} {wr*100:>7.1f}% {tot:>9.2f} {avg:>8.3f}", end="")

            # 显示与对侧方向的差异
            other = short_rs if direction == "long" else long_rs
            if other:
                other_avg = sum(other) / len(other)
                diff = avg - other_avg
                print(f"  {diff:>+7.3f}")
            else:
                print()
        print()


if __name__ == "__main__":
    main()
