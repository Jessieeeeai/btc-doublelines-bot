#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组合仓位优化：BTC空 + BTC多 + ETH多 三条流，五种资金方案。
    python3 pos_opt.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pandas as pd
from strategy import l01_stop
from grid_all import assemble, rsi
from run import CFG, OUT

COST = (CFG["costs"]["taker_fee_pct"] + CFG["costs"]["slippage_pct"]) / 100.0


def gen_trades(feat, sym, side):
    px = feat["close"]
    cvd = feat["spot_cvd_24h"]
    win = cvd.notna() & feat["funding"].notna()
    if side == "S":
        near = np.where(feat["us_open"], 0.02, 0.015)
        mask = (((feat["resistance"] / px - 1) < near) & (px < feat["resistance"] * 1.005)
                & (cvd < 0) & (feat["funding"] >= 0) & (px < px.rolling(168).mean()) & win).values
    else:
        thr = cvd[win].quantile(0.15)
        r4 = rsi(px.resample("4h").last()).shift(1).reindex(feat.index, method="ffill")
        mask = ((cvd < thr) & (feat["spot_cvd_slope"] > 0) & (r4 > 50) & win).values
    idx = feat.index
    n = len(feat)
    c, h, l = px.values, feat["high"].values, feat["low"].values
    out = []
    i = 0
    while i < n - 2:
        if not mask[i]:
            i += 1
            continue
        row = feat.iloc[i]
        entry = c[i]
        if side == "S":
            stop = l01_stop(row, "SHORT", entry)
            ok = stop and stop > entry and stop / entry - 1 <= 0.05
        else:
            l4, d1 = row["h4_low3"], row["d1_low5"]
            stop = None
            if np.isfinite(l4):
                if l4 < entry * 0.998:
                    stop = d1 * 0.997 if (np.isfinite(d1) and d1 < l4 and 1 - d1 / entry < 0.05) else l4 * 0.998
                else:
                    stop = l4 * 0.998 if l4 < entry else entry * 0.992
            ok = stop and stop < entry and 1 - stop / entry <= 0.05
        if not ok:
            i += 1
            continue
        r = abs(entry - stop)
        sgn = -1 if side == "S" else 1
        tgt = entry + sgn * 1.5 * r
        pnl, xj, stopped = 0.0, None, False
        for j in range(i + 1, min(i + 73, n)):
            hs = h[j] >= stop if side == "S" else l[j] <= stop
            ht = l[j] <= tgt if side == "S" else h[j] >= tgt
            if hs:
                pnl = sgn * (stop - entry) / entry - 2 * COST; xj = j; stopped = True; break
            if ht:
                pnl = sgn * (tgt - entry) / entry - 2 * COST; xj = j; break
        if xj is None:
            j = min(i + 72, n - 1)
            pnl = sgn * (c[j] - entry) / entry - 2 * COST; xj = j
        out.append({"sym": sym, "side": side, "t_in": idx[i], "t_out": idx[xj],
                    "pnl": pnl, "risk": r / entry, "atr": row["atr24"] / entry})
        i = xj + (6 if stopped else 1)
    return pd.DataFrame(out)


def scheme_lev(row, scheme, open_count, dd_state):
    atr, risk = row["atr"], row["risk"]
    if scheme == "A_固定风险1%":
        lev = min(0.01 / risk, 5.0)
    elif scheme == "B_波动率目标":
        lev = min(0.006 / atr, 5.0)
    elif scheme == "C_B+策略分级":
        m = 1.0 if row["side"] == "S" else 0.5
        lev = min(0.006 * m / atr, 5.0)
    elif scheme == "D_C+并发减半":
        m = 1.0 if row["side"] == "S" else 0.5
        lev = min(0.006 * m / atr, 5.0)
        if open_count > 0:
            lev *= 0.5
    else:  # E_D+回撤降档
        m = 1.0 if row["side"] == "S" else 0.5
        lev = min(0.006 * m / atr, 5.0)
        if open_count > 0:
            lev *= 0.5
        if dd_state:
            lev *= 0.5
    return lev


def run_scheme(trades, scheme):
    tr = trades.sort_values("t_in").reset_index(drop=True)
    eq, peak, mdd = 1.0, 1.0, 0.0
    open_pos = []  # (t_out)
    dd_state = False
    events = []
    for _, row in tr.iterrows():
        open_pos = [t for t in open_pos if t > row["t_in"]]
        lev = scheme_lev(row, scheme, len(open_pos), dd_state)
        eq *= 1 + lev * row["pnl"]
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
        dd_state = eq / peak - 1 < -0.05
        open_pos.append(row["t_out"])
        events.append(eq)
    days = (tr["t_out"].max() - tr["t_in"].min()).days
    ann = eq ** (365 / days) - 1
    calmar = ann / abs(mdd) if mdd < 0 else float("inf")
    return {"total%": round((eq - 1) * 100, 2), "ann%": round(ann * 100, 1),
            "mdd%": round(mdd * 100, 2), "calmar": round(calmar, 2)}


def main():
    btc = assemble("price_1h.jsonl",
                   [("cg_taker_spot.jsonl", 1), ("cg_taker_spot_2h.jsonl", 2), ("cg_taker_spot_4h.jsonl", 4),
                    ("cg_taker_spot_6h.jsonl", 6), ("cg_taker_spot_12h.jsonl", 12)], "cg_funding.jsonl")
    eth = assemble("price_1h_eth.jsonl",
                   [("cg_taker_spot_eth.jsonl", 1), ("cg_taker_spot_eth_2h.jsonl", 2), ("cg_taker_spot_eth_4h.jsonl", 4),
                    ("cg_taker_spot_eth_6h.jsonl", 6), ("cg_taker_spot_eth_12h.jsonl", 12)], "cg_funding_eth.jsonl")
    streams = pd.concat([
        gen_trades(btc, "BTC", "S"),
        gen_trades(btc, "BTC", "L"),
        gen_trades(eth, "ETH", "L"),
    ]).reset_index(drop=True)
    print(f"合并交易流: {len(streams)}笔 "
          f"(空{(streams.side=='S').sum()} / BTC多{((streams.side=='L')&(streams.sym=='BTC')).sum()} "
          f"/ ETH多{((streams.side=='L')&(streams.sym=='ETH')).sum()})")
    # 并发统计
    ov = 0
    for _, r in streams.iterrows():
        ov += ((streams.t_in < r.t_out) & (streams.t_out > r.t_in)).sum() - 1
    print(f"存在时间重叠的持仓对: {ov//2}")
    print()
    print(f"{'方案':14} {'总收益%':>8} {'年化%':>7} {'MDD%':>7} {'Calmar':>7}")
    for s in ["A_固定风险1%", "B_波动率目标", "C_B+策略分级", "D_C+并发减半", "E_D+回撤降档"]:
        m = run_scheme(streams, s)
        print(f"{s:14} {m['total%']:>8} {m['ann%']:>7} {m['mdd%']:>7} {m['calmar']:>7}")
    streams.to_csv(os.path.join(OUT, "portfolio_streams.csv"), index=False)


if __name__ == "__main__":
    main()
