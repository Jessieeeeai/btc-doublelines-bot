#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S03 专项参数网格：对齐实盘细节（即时入场、突破位止损锚），
训练段（前50%）选参 → 样本外（后50%）验证。
    python3 opt_s03.py
"""
import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pandas as pd
from strategy import build_features
from run import load_real, CFG, OUT

COST_SIDE = (CFG["costs"]["taker_fee_pct"] + CFG["costs"]["slippage_pct"]) / 100.0
NY_HOURS = set(range(13, 16))
ALL_KZ = set(range(0, 3)) | set(range(7, 10)) | set(range(13, 16))

GRID = {
    "entry_mode": ["close", "next_open"],
    "stop_anchor": ["prev5max", "bar_high"],
    "stop_mult": [1.005, 1.012],
    "breakout_margin": [0.0, 0.002],
    "kz": ["all", "ny"],
}


def run_s03(feat, entry_mode, stop_anchor, stop_mult, breakout_margin, kz):
    hours = NY_HOURS if kz == "ny" else ALL_KZ
    idx = feat.index
    n = len(feat)
    trades = []
    i = 0
    close = feat["close"].values
    open_ = feat["open"].values
    high = feat["high"].values
    low = feat["low"].values
    p5max = feat["prev5_max"].values
    p5rng = feat["prev5_range"].values
    h4bear = feat["h4_bearish"].values
    hrs = idx.hour

    while i < n - 2:
        ok = (hrs[i] in hours and h4bear[i] is True
              and np.isfinite(p5rng[i]) and p5rng[i] < 0.03
              and np.isfinite(p5max[i]) and close[i] > p5max[i] * (1 + breakout_margin))
        if not ok:
            i += 1
            continue

        anchor = p5max[i] if stop_anchor == "prev5max" else high[i]
        stop = anchor * stop_mult
        entry = close[i] if entry_mode == "close" else open_[i + 1]
        j0 = i + 1
        if stop <= entry:  # 止损必须在入场价上方
            i += 1
            continue
        r = stop - entry
        tp1, tp2 = entry - 1.1 * r, entry - 2.0 * r

        half, pnl, exit_reason, exit_j = False, 0.0, "time", None
        cur_stop = stop
        for j in range(j0, min(j0 + 48, n)):
            if high[j] >= cur_stop:
                frac = 0.5 if half else 1.0
                pnl += frac * ((entry - cur_stop) / entry - 2 * COST_SIDE)
                exit_reason = "be_stop" if half else "stop"
                exit_j = j
                break
            if not half and low[j] <= tp1:
                pnl += 0.5 * ((entry - tp1) / entry - 2 * COST_SIDE)
                half, cur_stop = True, entry
                continue
            if half and low[j] <= tp2:
                pnl += 0.5 * ((entry - tp2) / entry - 2 * COST_SIDE)
                exit_reason, exit_j = "tp2", j
                break
        if exit_j is None:
            j = min(j0 + 48, n) - 1
            frac = 0.5 if half else 1.0
            pnl += frac * ((entry - close[j]) / entry - 2 * COST_SIDE)
            exit_j = j
        trades.append({"t": idx[i], "pnl_pct": pnl * 100, "reason": exit_reason,
                       "stopped": exit_reason == "stop"})
        i = exit_j + 1  # 持仓互斥；止损后1bar冷却近似含在推进里

    return pd.DataFrame(trades)


def seg_stats(tr):
    if tr.empty:
        return {"n": 0, "net%": 0.0, "wr%": 0.0, "pf": 0.0}
    w = tr[tr.pnl_pct > 0]
    l = tr[tr.pnl_pct <= 0]
    pf = w.pnl_pct.sum() / abs(l.pnl_pct.sum()) if len(l) and l.pnl_pct.sum() != 0 else np.inf
    return {"n": len(tr), "net%": round(tr.pnl_pct.sum(), 2),
            "wr%": round((tr.pnl_pct > 0).mean() * 100, 1), "pf": round(pf, 2)}


def main():
    df = load_real()
    feat = build_features(df)
    split = feat.index[int(len(feat) * 0.5)]

    rows = []
    for combo in itertools.product(*GRID.values()):
        params = dict(zip(GRID.keys(), combo))
        tr = run_s03(feat, **params)
        if tr.empty:
            continue
        tra, oos = tr[tr.t < split], tr[tr.t >= split]
        rows.append({**params,
                     **{f"train_{k}": v for k, v in seg_stats(tra).items()},
                     **{f"oos_{k}": v for k, v in seg_stats(oos).items()}})
    res = pd.DataFrame(rows).sort_values("train_net%", ascending=False)
    res.to_csv(os.path.join(OUT, "s03_grid.csv"), index=False)

    print("== 按训练段净收益排序 TOP 8（右侧为对应样本外）==")
    cols = ["entry_mode", "stop_anchor", "stop_mult", "breakout_margin", "kz",
            "train_n", "train_net%", "train_wr%", "train_pf",
            "oos_n", "oos_net%", "oos_wr%", "oos_pf"]
    print(res[cols].head(8).to_string(index=False))
    print()
    print("== 文档基线（bar_high×1.012, next_open, margin0, all-KZ）==")
    base = res[(res.entry_mode == "next_open") & (res.stop_anchor == "bar_high")
               & (res.stop_mult == 1.012) & (res.breakout_margin == 0.0) & (res.kz == "all")]
    print(base[cols].to_string(index=False))
    print()
    print("== 实盘对齐版（close入场, prev5max锚）各变体 ==")
    live = res[(res.entry_mode == "close") & (res.stop_anchor == "prev5max")]
    print(live[cols].to_string(index=False))


if __name__ == "__main__":
    main()
