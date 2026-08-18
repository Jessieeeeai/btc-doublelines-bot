#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S01 诊断：条件漏斗 + 逐条件信息量（前瞻收益）。
    python3 diag_s01.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pandas as pd
from strategy import build_features, calibrate_thresholds
from run import load_real, CFG

pd.set_option("display.width", 160)


def main():
    df = load_real()
    feat = build_features(df)
    thr = calibrate_thresholds(feat, train_frac=0.5)

    px = feat["close"]
    fwd24 = px.shift(-24) / px - 1
    fwd48 = px.shift(-48) / px - 1

    near = np.where(feat["us_open"], 0.02, 0.015)
    cvd_thr = np.where(feat["us_open"], thr["s01_cvd_neg_usopen"], thr["s01_cvd_neg"])

    conds = {
        "c1_近阻力":  ((feat["resistance"] / px - 1) < near) & (px < feat["resistance"] * 1.005),
        "c2_CVD24h负": feat["perp_cvd_24h"] < cvd_thr,
        "c3_现货CVD<0": feat["spot_cvd_24h"] < 0,
        "c4_盘口偏卖": feat["ob_imb"] < 0,
        "c5_费率高位": feat["funding"] >= thr["s01_fr_hi"],
        "c6_CVD斜率<0": feat["perp_cvd_slope"] < 0,
        "c7_OI未扩张": feat["oi_chg_24h"] < 0.02,
    }

    # 只统计 CVD 有覆盖的窗口
    win = feat["perp_cvd_24h"].notna()
    n_win = int(win.sum())
    print(f"分析窗口: {n_win} bars（CVD覆盖段: {feat.index[win.values.argmax()]} 起）\n")

    print("== 逐条件：通过率 + 信息量（条件为真时的未来收益，SHORT希望为负）==")
    print(f"{'条件':14} {'通过率':>7} {'fwd24真':>9} {'fwd24假':>9} {'fwd48真':>9} {'差值24':>9}")
    for name, c in conds.items():
        cw = c & win
        t = fwd24[cw].mean() * 100
        f = fwd24[win & ~c].mean() * 100
        t48 = fwd48[cw].mean() * 100
        print(f"{name:14} {cw.sum()/n_win*100:6.1f}% {t:8.3f}% {f:8.3f}% {t48:8.3f}% {t-f:+8.3f}%")

    print("\n== 漏斗（按文档顺序叠加）==")
    acc = win.copy()
    for name, c in conds.items():
        acc = acc & c
        print(f"+ {name:14} → 剩 {int(acc.sum()):5d} bars")

    print("\n== 漏斗（每次只去掉一个条件，看谁是卡点）==")
    all_c = win.copy()
    for c in conds.values():
        all_c = all_c & c
    for skip in conds:
        acc = win.copy()
        for name, c in conds.items():
            if name != skip:
                acc = acc & c
        print(f"去掉 {skip:14} → {int(acc.sum()):5d} bars（全条件={int(all_c.sum())}）")

    # 阈值参考
    print("\n阈值:", {k: (round(v, 6) if isinstance(v, float) else v) for k, v in thr.items()})


if __name__ == "__main__":
    main()
