#!/usr/bin/env python3
"""一次性迁移: 修正阶梯锁时间穿越 bug 伪造的历史出场 (v5).

背景: 旧版 update_signal_status 每轮用最新 current_sl 重扫进场后所有旧 K 线,
导致阶梯锁触发后, 下一轮在进场后第 1 根旧 K 线上"出场", 出场时间/价格均为伪造
(状态还标成 tp_hit)。本脚本把这些单子重置回 entered, 用修复后的引擎
(单次调用 update_signal_status, K 线按时间序推进) 重放出真实结果。

用法: python3 fix_states_v5.py <candles.csv> [--dry-run]
candles.csv: ts,low,high,open,close (1h, 升序, 需覆盖最早进场时间到现在)
只处理 B/C (A 无阶梯锁, 不受此 bug 影响)。
"""
import csv
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import signal_bot_race as m  # noqa: E402


def load_candles(path):
    bars = []
    with open(path) as f:
        for row in csv.DictReader(f):
            ts = int(row["ts"])
            bars.append({
                "ts": ts,
                "date": datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M"),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })
    bars.sort(key=lambda b: b["ts"])
    return bars


def is_fake_lock_exit(sig):
    """tp_hit 但出场价不是 TP → 锁价出场记录 (时间穿越 bug 的产物)"""
    if sig.get("status") != "tp_hit":
        return False
    exit_p = sig.get("exit_price") or 0
    tp = sig.get("tp") or 0
    return abs(exit_p - tp) >= 1


def reset_to_entered(sig):
    sig["status"] = "entered"
    sig["current_sl"] = sig["sl0"]
    sig["stair_2r_locked"] = False
    sig["stair_4r_locked"] = False
    sig["pyramid_entered"] = False
    sig["pyramid_entry_price"] = None
    sig["exit_price"] = None
    sig["exit_time"] = None
    sig["exit_ts"] = None
    sig["result_r"] = None
    sig["result_r_raw"] = None
    sig["last_checked_ts"] = None


def main():
    if len(sys.argv) < 2:
        sys.exit("用法: python3 fix_states_v5.py <candles.csv> [--dry-run]")
    dry = "--dry-run" in sys.argv
    bars = load_candles(sys.argv[1])
    print(f"K线: {len(bars)} 根, {bars[0]['date']} → {bars[-1]['date']} UTC")

    for strategy in m.STRATEGIES:
        if not strategy.use_stair:
            print(f"\n[{strategy.code}] 无阶梯锁, 跳过")
            continue
        path = os.path.join(REPO, os.path.basename(strategy.state_file))
        with open(path) as f:
            state = json.load(f)

        print(f"\n[{strategy.code}] {path}")
        for idx, sig in enumerate(state["signals"], 1):
            old = (sig["status"], sig.get("exit_time"), sig.get("result_r"))
            if is_fake_lock_exit(sig):
                if sig.get("entry_ts", 0) < bars[0]["ts"]:
                    print(f"  #{idx:03d} 进场早于K线覆盖范围, 跳过!")
                    continue
                reset_to_entered(sig)
                m.update_signal_status(strategy, bars, sig)
                action = "重放"
            elif sig.get("status") == "entered":
                # 开放单: 用修复后引擎补 last_checked_ts / 锁状态
                m.update_signal_status(strategy, bars, sig)
                action = "推进"
            else:
                continue
            print(f"  #{idx:03d} {action}: {old[0]} {old[1]} R={old[2]}"
                  f"  →  {sig['status']} {sig.get('exit_time')} R={sig.get('result_r')}"
                  f" exit=${sig.get('exit_price')} sl={sig.get('current_sl')}"
                  f" lock2R={sig.get('stair_2r_locked')} pyr={sig.get('pyramid_entered')}")

        if not dry:
            with open(path, "w") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            print(f"  已写回 {path}")

    print("\n完成" + (" (dry-run, 未写盘)" if dry else ""))


if __name__ == "__main__":
    main()
