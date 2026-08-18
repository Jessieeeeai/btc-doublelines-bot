#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S03 第三轮预注册验证：5方向7变体。python3 s03_round3.py"""
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pandas as pd
from grid_all import assemble
from run import CFG

COST = (CFG["costs"]["taker_fee_pct"] + CFG["costs"]["slippage_pct"]) / 100.0
pd.set_option("display.width", 220)

BTC_SUFS = [("cg_taker_spot.jsonl", 1), ("cg_taker_spot_2h.jsonl", 2), ("cg_taker_spot_4h.jsonl", 4),
            ("cg_taker_spot_6h.jsonl", 6), ("cg_taker_spot_12h.jsonl", 12)]
ETH_SUFS = [("cg_taker_spot_eth.jsonl", 1), ("cg_taker_spot_eth_2h.jsonl", 2), ("cg_taker_spot_eth_4h.jsonl", 4),
            ("cg_taker_spot_eth_6h.jsonl", 6), ("cg_taker_spot_eth_12h.jsonl", 12)]


def prep(feat):
    """S03 专用特征（口径声明：prev5=前5根不含当前；压缩分母=close；4H按UTC对齐）"""
    f = feat.copy()
    f["prev5_max"] = f["high"].shift(1).rolling(5).max()
    f["prev5_min"] = f["low"].shift(1).rolling(5).min()
    f["c3_comp"] = (f["prev5_max"] - f["prev5_min"]) / f["close"] < 0.03
    f["c4_brk"] = f["close"] > f["prev5_max"]
    h4c = f["close"].resample("4h").agg(["first", "last"])
    f["c2_bear4h"] = (h4c["last"] < h4c["first"]).shift(1).reindex(f.index, method="ffill")
    hrs = f.index.hour
    f["c1_kz"] = pd.Series(hrs, index=f.index).isin(list(range(0, 3)) + list(range(7, 10)) + list(range(13, 16)))
    f["ma7f"] = f["close"].rolling(168).mean()
    f["mid5"] = (f["prev5_max"] + f["prev5_min"]) / 2
    return f


def sim(f, mask, side, stop_fn, tp_mult=1.5, max_hold=48):
    idx, n = f.index, len(f)
    c, h, l = f["close"].values, f["high"].values, f["low"].values
    m = mask.values
    sgn = -1 if side == "S" else 1
    out, i = [], 200
    while i < n - 2:
        if not m[i]:
            i += 1
            continue
        entry = c[i]
        stop = stop_fn(f, i, entry)
        ok = stop and ((stop > entry and side == "S") or (stop < entry and side == "L")) \
            and abs(stop / entry - 1) <= 0.05 and abs(stop / entry - 1) >= 0.001
        if not ok:
            i += 1
            continue
        r = abs(entry - stop)
        tgt = entry + sgn * tp_mult * r
        pnl, xj, stopped = 0.0, None, False
        for j in range(i + 1, min(i + max_hold + 1, n)):
            hs = h[j] >= stop if side == "S" else l[j] <= stop
            ht = l[j] <= tgt if side == "S" else h[j] >= tgt
            if hs:
                pnl = sgn * (stop - entry) / entry - 2 * COST
                xj, stopped = j, True
                break
            if ht:
                pnl = sgn * (tgt - entry) / entry - 2 * COST
                xj = j
                break
        if xj is None:
            j = min(i + max_hold, n - 1)
            pnl = sgn * (c[j] - entry) / entry - 2 * COST
            xj = j
        out.append({"t": idx[i], "pnl": pnl * 100})
        i = xj + (6 if stopped else 1)
    return pd.DataFrame(out)


def seg_str(tr):
    if tr is None or tr.empty:
        return "n=0"
    mid = tr.t.iloc[0] + (tr.t.iloc[-1] - tr.t.iloc[0]) / 2
    a, b = tr[tr.t < mid], tr[tr.t >= mid]
    fmt = lambda x: f"{x.pnl.sum():+6.1f}%({len(x):3d},{(x.pnl > 0).mean() * 100:3.0f}%)" if len(x) else "  n=0"
    return f"训 {fmt(a)} | 外 {fmt(b)} | 合计 {tr.pnl.sum():+7.2f}%({len(tr)})"


# 止损函数
stop_brk_high = lambda f, i, e: f["high"].values[i] * 1.012                # 原版：突破K线高点
stop_rng_top = lambda f, i, e: f["prev5_max"].values[i] * 1.002            # 区间上沿（做空）
stop_rng_bot = lambda f, i, e: f["prev5_min"].values[i] * 0.998            # 区间下沿（做多）


def main():
    btc = prep(assemble("price_1h.jsonl", BTC_SUFS, "cg_funding.jsonl"))
    eth = prep(assemble("price_1h_eth.jsonl", ETH_SUFS, "cg_funding_eth.jsonl"))

    # ===== 方向5 诊断：子时段信息量（在原4条件基础上分时段） =====
    print("===== 方向5 诊断：子时段（4条件全真时的未来24h收益，按时段拆分）=====")
    for tag, f in (("BTC", btc), ("ETH", eth)):
        base = f["c1_kz"] & f["c2_bear4h"].fillna(False).astype(bool) & f["c3_comp"] & f["c4_brk"]
        fwd = f["close"].shift(-24) / f["close"] - 1
        hrs = f.index.hour
        for nm, rng in (("亚洲0-3", range(0, 3)), ("伦敦7-10", range(7, 10)), ("纽约13-16", range(13, 16))):
            sel = base & pd.Series(hrs, index=f.index).isin(list(rng))
            n = int(sel.sum())
            print(f"  {tag} {nm}: n={n:4d}  fwd24={fwd[sel].mean() * 100 if n else 0:+.3f}%")

    # ===== 7个预注册变体 =====
    print("\n===== 变体结果（串行/含成本0.14%/1.5R单目标/48h/止损后6h冷却）=====")
    for tag, f in (("BTC", btc), ("ETH", eth)):
        c1 = f["c1_kz"]
        c2 = f["c2_bear4h"].fillna(False).astype(bool)
        c3 = f["c3_comp"]
        c4 = f["c4_brk"]
        cvd_ok = f["spot_cvd_24h"].notna()
        below = f["close"] < f["ma7f"]
        above = f["close"] > f["ma7f"]

        # V4 需要"突破后3根内收盘跌回区间中点下方"+突破时taker净流<0
        brk = (c3 & c4)
        mid_at_brk = f["mid5"].where(brk).ffill(limit=3)
        brk_delta_neg = (f["spot_delta"].where(brk) < 0).ffill(limit=3).fillna(False)
        recently_brk = brk.shift(1).rolling(3).max().fillna(0) > 0
        v4_mask = recently_brk & (f["close"] < mid_at_brk) & brk_delta_neg & cvd_ok

        variants = [
            ("V1 反向做多(4条件→LONG)", c1 & c2 & c3 & c4, "L", stop_rng_bot),
            ("V2a 压缩+MA7下→空", c3 & below, "S", stop_rng_top),
            ("V2b 压缩+MA7上→多", c3 & above, "L", stop_rng_bot),
            ("V3 突破+CVD负背离→空", c3 & c4 & (f["spot_cvd_24h"] < 0) & cvd_ok, "S", stop_brk_high),
            ("V4 强失败确认→空", v4_mask, "S", stop_rng_top),
            ("V0 原版对照(4条件→空)", c1 & c2 & c3 & c4, "S", stop_brk_high),
        ]
        print(f"--- {tag} ---")
        for nm, mask, side, sf in variants:
            tr = sim(f, mask, side, sf)
            print(f"  {nm:26} {seg_str(tr)}")


if __name__ == "__main__":
    main()
