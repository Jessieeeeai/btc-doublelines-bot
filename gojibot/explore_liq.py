#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清算潮反转假设检验（探索性，样本 5.5 个月）：
  L-LONG ：多头清算潮（长仓强平激增）+ 价格已急跌 → 做多反弹
  L-SHORT：空头清算潮 + 价格已急拉 → 做空回落
阈值 = 过去14天滚动分位数（无前视）。训练/样本外对半。
    python3 explore_liq.py
"""
import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pandas as pd
from run import load_real, _jsonl, _ts_index, CFG, OUT

COST = (CFG["costs"]["taker_fee_pct"] + CFG["costs"]["slippage_pct"]) / 100.0


def load_liq(index):
    """1h 优先、4h 摊薄补历史 → 小时级多/空清算流。"""
    out_l, out_s = None, None
    for suffix, div in (("_4h", 4.0), ("", 1.0)):
        df = _jsonl(f"cg_liquidation{suffix}.jsonl")
        if df is None:
            continue
        df = _ts_index(df)
        lo = pd.to_numeric(df.get("long_liquidation_usd"), errors="coerce")
        sh = pd.to_numeric(df.get("short_liquidation_usd"), errors="coerce")
        kw = {"method": "ffill", "limit": int(div) - 1} if div > 1 else {}
        lo = pd.Series(lo.values, index=df.index).reindex(index, **kw) / div
        sh = pd.Series(sh.values, index=df.index).reindex(index, **kw) / div
        out_l = lo if out_l is None else lo.combine_first(out_l)
        out_s = sh if out_s is None else sh.combine_first(out_s)
    return out_l, out_s


def run_liq(px, liq, side, win, q, ret_filter):
    """liq: 该方向的清算流；side: 'long'（多头清算→做多）或 'short'。"""
    roll = liq.rolling(win).sum()
    thr = roll.rolling(24 * 14, min_periods=24 * 5).quantile(q).shift(1)
    ret24 = px["close"].pct_change(24)

    c, o, h, l = px["close"].values, px["open"].values, px["high"].values, px["low"].values
    idx = px.index
    sig = (roll > thr)
    if ret_filter:
        sig &= (ret24 < -0.02) if side == "long" else (ret24 > 0.02)
    sigv = sig.values
    lo6 = px["low"].shift(1).rolling(6).min().values
    hi6 = px["high"].shift(1).rolling(6).max().values

    trades, i, n = [], 24 * 5, len(px)
    while i < n - 2:
        if not sigv[i]:
            i += 1
            continue
        entry = c[i]
        if side == "long":
            stop = min(lo6[i] * 0.997, entry * 0.99) if np.isfinite(lo6[i]) else entry * 0.97
            if stop >= entry:
                i += 1; continue
            r = entry - stop
            tp1, tp2 = entry + 1.1 * r, entry + 2.0 * r
        else:
            stop = max(hi6[i] * 1.003, entry * 1.01) if np.isfinite(hi6[i]) else entry * 1.03
            if stop <= entry:
                i += 1; continue
            r = stop - entry
            tp1, tp2 = entry - 1.1 * r, entry - 2.0 * r

        half, pnl, xj = False, 0.0, None
        cur = stop
        d = 1 if side == "long" else -1
        for j in range(i + 1, min(i + 49, n)):
            hit_stop = l[j] <= cur if side == "long" else h[j] >= cur
            hit_tp1 = h[j] >= tp1 if side == "long" else l[j] <= tp1
            hit_tp2 = h[j] >= tp2 if side == "long" else l[j] <= tp2
            if hit_stop:
                pnl += (0.5 if half else 1.0) * (d * (cur - entry) / entry - 2 * COST); xj = j; break
            if not half and hit_tp1:
                pnl += 0.5 * (d * (tp1 - entry) / entry - 2 * COST); half, cur = True, entry; continue
            if half and hit_tp2:
                pnl += 0.5 * (d * (tp2 - entry) / entry - 2 * COST); xj = j; break
        if xj is None:
            j = min(i + 48, n - 1)
            pnl += (0.5 if half else 1.0) * (d * (c[j] - entry) / entry - 2 * COST); xj = j
        trades.append({"t": idx[i], "pnl": pnl * 100})
        i = xj + 1
    return pd.DataFrame(trades)


def stats(tr):
    if tr.empty:
        return "n=0"
    return (f"n={len(tr):3d} net={tr.pnl.sum():+6.1f}% wr={(tr.pnl > 0).mean() * 100:3.0f}% "
            f"avg={tr.pnl.mean():+.2f}%")


def main():
    px = load_real()
    liq_l, liq_s = load_liq(px.index)
    cov = liq_l.notna()
    print(f"清算数据覆盖: {cov.mean()*100:.0f}% bars "
          f"({px.index[cov.argmax()]} 起)")
    lo_idx = np.where(cov.values)[0]
    mid = px.index[lo_idx[len(lo_idx) // 2]]

    rows = []
    for side, win, q, rf in itertools.product(["long", "short"], [3, 12], [0.95, 0.98], [True, False]):
        liq = liq_l if side == "long" else liq_s
        tr = run_liq(px, liq, side, win, q, rf)
        if tr.empty:
            rows.append((side, win, q, rf, "n=0", "n=0")); continue
        a, b = tr[tr.t < mid], tr[tr.t >= mid]
        rows.append((side, win, q, rf, stats(a), stats(b)))
        tr.to_csv(os.path.join(OUT, f"liq_{side}_w{win}_q{int(q*100)}_{'rf' if rf else 'norf'}.csv"), index=False)

    print(f"\n{'side':5} {'win':3} {'q':4} {'mom':5} | train | oos")
    for r in rows:
        print(f"{r[0]:5} {r[1]:3d} {r[2]:.2f} {str(r[3]):5} | {r[4]} | {r[5]}")


if __name__ == "__main__":
    main()
