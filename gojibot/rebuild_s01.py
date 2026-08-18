#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S01 重构验证：信号组合 × L01止损变体 × O1冷却，训练/样本外。
    python3 rebuild_s01.py
"""
import itertools
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pandas as pd
from strategy import build_features, calibrate_thresholds, l01_stop
from run import load_real, CFG, OUT

COST = (CFG["costs"]["taker_fee_pct"] + CFG["costs"]["slippage_pct"]) / 100.0

SIGS = {  # 信号组合（按信息量诊断重构）
    "A_阻力+费率":        ["c1", "c5"],
    "B_阻力+费率+现货CVD": ["c1", "c5", "c3"],
    "C_阻力+费率+盘口":    ["c1", "c5", "c4"],
    "D_阻力+现货CVD":      ["c1", "c3"],
    "E_仅费率":            ["c5"],
    "F_文档原版":          ["c1", "c2", "c3", "c4", "c5", "c6", "c7"],
}
STOPS = ["l01_doc", "h4_only", "fixed15"]
COOLDOWNS = [1, 6]


def build_conds(feat, thr):
    px = feat["close"]
    near = np.where(feat["us_open"], 0.02, 0.015)
    cvd_thr = np.where(feat["us_open"], thr["s01_cvd_neg_usopen"], thr["s01_cvd_neg"])
    return {
        "c1": ((feat["resistance"] / px - 1) < near) & (px < feat["resistance"] * 1.005),
        "c2": feat["perp_cvd_24h"] < cvd_thr,
        "c3": feat["spot_cvd_24h"] < 0,
        "c4": feat["ob_imb"] < 0,
        "c5": feat["funding"] >= thr["s01_fr_hi"],
        "c6": feat["perp_cvd_slope"] < 0,
        "c7": feat["oi_chg_24h"] < 0.02,
    }


def coverage_mask(feat, keys):
    """信号需要的数据都存在的bar。"""
    need = {"c1": ["resistance"], "c2": ["perp_cvd_24h"], "c3": ["spot_cvd_24h"],
            "c4": ["ob_imb"], "c5": ["funding"], "c6": ["perp_cvd_slope"], "c7": ["oi_chg_24h"]}
    m = pd.Series(True, index=feat.index)
    for k in keys:
        for col in need[k]:
            m &= feat[col].notna()
    return m


def calc_stop(row, entry, mode):
    if mode == "l01_doc":
        return l01_stop(row, "SHORT", entry)
    if mode == "h4_only":
        h4 = row["h4_high3"]
        return h4 * 1.002 if np.isfinite(h4) and h4 > entry else entry * 1.008
    return entry * 1.015  # fixed15


def run_cfg(feat, sig_mask, stop_mode, cooldown_h):
    idx = feat.index
    n = len(feat)
    c, h, l = feat["close"].values, feat["high"].values, feat["low"].values
    sv = sig_mask.values
    trades = []
    i, block_until = 0, -1
    while i < n - 2:
        if not sv[i] or i < block_until:
            i += 1
            continue
        row = feat.iloc[i]
        entry = c[i]
        stop = calc_stop(row, entry, stop_mode)
        if stop is None or stop <= entry or (stop / entry - 1) > 0.05:
            i += 1
            continue
        r = stop - entry
        tp1, tp2 = entry - 1.1 * r, entry - 2.0 * r
        half, pnl, xj, stopped = False, 0.0, None, False
        cur = stop
        for j in range(i + 1, min(i + 73, n)):
            if h[j] >= cur:
                pnl += (0.5 if half else 1.0) * ((entry - cur) / entry - 2 * COST)
                xj, stopped = j, (not half)
                break
            if not half and l[j] <= tp1:
                pnl += 0.5 * ((entry - tp1) / entry - 2 * COST); half, cur = True, entry; continue
            if half and l[j] <= tp2:
                pnl += 0.5 * ((entry - tp2) / entry - 2 * COST); xj = j; break
        if xj is None:
            j = min(i + 72, n - 1)
            pnl += (0.5 if half else 1.0) * ((entry - c[j]) / entry - 2 * COST)
            xj = j
        trades.append({"t": idx[i], "pnl": pnl * 100,
                       "risk": (stop / entry - 1) * 100})
        block_until = xj + cooldown_h if stopped else xj
        i = xj + 1
    return pd.DataFrame(trades)


def stats(tr):
    if tr.empty:
        return {"n": 0, "net": 0.0, "wr": 0.0, "pf": 0.0}
    w, l_ = tr[tr.pnl > 0], tr[tr.pnl <= 0]
    pf = w.pnl.sum() / abs(l_.pnl.sum()) if len(l_) and l_.pnl.sum() != 0 else np.inf
    return {"n": len(tr), "net": round(tr.pnl.sum(), 1),
            "wr": round((tr.pnl > 0).mean() * 100), "pf": round(pf, 2)}


def main():
    df = load_real()
    feat = build_features(df)
    thr = calibrate_thresholds(feat, train_frac=0.5)
    conds = build_conds(feat, thr)

    rows = []
    for sig_name, stop_mode, cd in itertools.product(SIGS, STOPS, COOLDOWNS):
        keys = SIGS[sig_name]
        cov = coverage_mask(feat, keys)
        mask = cov.copy()
        for k in keys:
            mask &= conds[k]
        tr = run_cfg(feat, mask, stop_mode, cd)
        # 训练/样本外按该信号自身覆盖窗口对半
        cov_idx = np.where(cov.values)[0]
        if len(cov_idx) < 100:
            continue
        mid = feat.index[cov_idx[len(cov_idx) // 2]]
        a = tr[tr.t < mid] if not tr.empty else tr
        b = tr[tr.t >= mid] if not tr.empty else tr
        sa, sb = stats(a), stats(b)
        rows.append({"sig": sig_name, "stop": stop_mode, "cd": cd,
                     "win_start": str(feat.index[cov_idx[0]])[:10],
                     "tr_n": sa["n"], "tr_net%": sa["net"], "tr_wr": sa["wr"], "tr_pf": sa["pf"],
                     "oos_n": sb["n"], "oos_net%": sb["net"], "oos_wr": sb["wr"], "oos_pf": sb["pf"]})

    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(OUT, "s01_rebuild_grid.csv"), index=False)
    pd.set_option("display.width", 200)
    print(res.sort_values("tr_net%", ascending=False).to_string(index=False))
    print("\n双正配置（训练与样本外均>0）:")
    both = res[(res["tr_net%"] > 0) & (res["oos_net%"] > 0)]
    print(both.to_string(index=False) if len(both) else "  无")


if __name__ == "__main__":
    main()
