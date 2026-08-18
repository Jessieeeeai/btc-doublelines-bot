#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优化⑤：止损单画像 + 预注册过滤器测试（重构版S01：c1+c3+fr>=0，L01，doc TP，6h冷却）
    python3 profile_stops.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pandas as pd
from strategy import build_features, l01_stop
from run import load_real, CFG, OUT

COST = (CFG["costs"]["taker_fee_pct"] + CFG["costs"]["slippage_pct"]) / 100.0
pd.set_option("display.width", 200)


def simulate(feat):
    px = feat["close"]
    near = np.where(feat["us_open"], 0.02, 0.015)
    c1 = ((feat["resistance"] / px - 1) < near) & (px < feat["resistance"] * 1.005)
    c3 = feat["spot_cvd_24h"] < 0
    c5 = feat["funding"] >= 0
    cov = feat["spot_cvd_24h"].notna()
    mask = (c1 & c3 & c5 & cov).values

    # 4H动量：最近2根已完成4H是否连阳
    h4 = feat["close"].resample("4h").agg(["first", "last"])
    green = (h4["last"] > h4["first"])
    up2 = (green & green.shift(1)).shift(1).reindex(feat.index, method="ffill")

    idx = feat.index
    n = len(feat)
    c, h, l = px.values, feat["high"].values, feat["low"].values
    trades = []
    i, n_ = 0, n
    while i < n_ - 2:
        if not mask[i]:
            i += 1
            continue
        row = feat.iloc[i]
        entry = c[i]
        stop = l01_stop(row, "SHORT", entry)
        if stop is None or stop <= entry or stop / entry - 1 > 0.05:
            i += 1
            continue
        r = stop - entry
        tp1, tp2 = entry - 1.1 * r, entry - 2.0 * r
        half, pnl, xj, stopped = False, 0.0, None, False
        cur = stop
        for j in range(i + 1, min(i + 73, n_)):
            if h[j] >= cur:
                pnl += (0.5 if half else 1.0) * ((entry - cur) / entry - 2 * COST)
                xj, stopped = j, (not half)
                break
            if not half and l[j] <= tp1:
                pnl += 0.5 * ((entry - tp1) / entry - 2 * COST); half, cur = True, entry; continue
            if half and l[j] <= tp2:
                pnl += 0.5 * ((entry - tp2) / entry - 2 * COST); xj = j; break
        if xj is None:
            j = min(i + 72, n_ - 1)
            pnl += (0.5 if half else 1.0) * ((entry - c[j]) / entry - 2 * COST)
            xj = j
        trades.append({
            "t": idx[i], "pnl": pnl * 100, "stopped": stopped,
            "res_dist": (row["resistance"] / entry - 1) * 100,
            "cvd24": row["spot_cvd_24h"],
            "funding": row["funding"] * 100,
            "atr_pct": row["atr24"] / entry * 100,
            "h4_up2": bool(up2.iloc[i]) if pd.notna(up2.iloc[i]) else False,
            "hour": idx[i].hour,
            "risk_pct": (stop / entry - 1) * 100,
        })
        i = xj + (6 if stopped else 1)
    return pd.DataFrame(trades)


def seg(tr, mid):
    a, b = tr[tr.t < mid], tr[tr.t >= mid]
    f = lambda x: f"n={len(x):3d} net={x.pnl.sum():+6.2f}%" if len(x) else "n=0"
    return f(a), f(b)


def main():
    df = load_real()
    feat = build_features(df)
    tr = simulate(feat)
    cov = feat["spot_cvd_24h"].notna()
    ci = np.where(cov.values)[0]
    mid = feat.index[ci[len(ci) // 2]]

    print(f"基线: 共{len(tr)}笔  train/oos: {seg(tr, mid)}")
    stops = tr[tr.stopped]
    wins = tr[tr.pnl > 0]
    print(f"止损单 {len(stops)} 笔（net {stops.pnl.sum():+.1f}%），盈利单 {len(wins)} 笔\n")

    print("== 止损单 vs 盈利单：入场时特征对比（均值 / 中位数）==")
    for col in ["res_dist", "cvd24", "funding", "atr_pct", "risk_pct"]:
        s, w = stops[col], wins[col]
        print(f"{col:10}  止损: {s.mean():9.3f} / {s.median():9.3f}   "
              f"盈利: {w.mean():9.3f} / {w.median():9.3f}")
    print(f"{'h4_up2':10}  止损: {stops.h4_up2.mean()*100:.0f}%          盈利: {wins.h4_up2.mean()*100:.0f}%")
    print("\n止损单时段分布(UTC):", dict(stops.hour.value_counts().sort_index()))
    print("盈利单时段分布(UTC):", dict(wins.hour.value_counts().sort_index()))

    print("\n== 预注册过滤器（剔除集应为负贡献，剩余应双正）==")
    atr_p90 = tr.atr_pct.quantile(0.90)
    stop_hours = set(stops.hour.value_counts().head(3).index)
    filters = {
        "F1_4H连阳不空": ~tr.h4_up2,
        "F2_ATR极端不进": tr.atr_pct < atr_p90,
        f"F3_回避时段{sorted(stop_hours)}": ~tr.hour.isin(stop_hours),
        "F4_贴脸<0.5%不进": tr.res_dist >= 0.5,
    }
    for name, keep in filters.items():
        kept, cut = tr[keep], tr[~keep]
        a, b = seg(kept, mid)
        print(f"{name:22} 剔除{len(cut):3d}笔(net {cut.pnl.sum():+6.2f}%) | 剩余 train {a} | oos {b}")

    tr.to_csv(os.path.join(OUT, "s01_trades_profiled.csv"), index=False)


if __name__ == "__main__":
    main()
