#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全排列网格：python3 grid_all.py short|long"""
import itertools
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pandas as pd
from strategy import build_features, l01_stop
from run import _jsonl, _ts_index, _pick, CFG, OUT

COST = (CFG["costs"]["taker_fee_pct"] + CFG["costs"]["slippage_pct"]) / 100.0
SPLIT = pd.Timestamp("2026-01-15", tz="UTC")  # 前半=上行+崩盘，后半=下跌×2


def taker_stitched(sufs, close):
    parts = []
    for name, hours in sufs:
        t = _jsonl(name)
        if t is None:
            continue
        t = _ts_index(t)
        b = _pick(t, "taker_buy_volume_usd")
        s = _pick(t, "taker_sell_volume_usd")
        if b is None:
            continue
        d = pd.Series((b - s).values, index=t.index)
        kw = {"method": "ffill", "limit": hours - 1} if hours > 1 else {}
        parts.append((d.reindex(close.index, **kw) / hours, hours))
    out = None
    for d, _ in sorted(parts, key=lambda x: x[1]):
        out = d if out is None else out.combine_first(d)
    return out / close


def assemble(pf, sufs, ff):
    cp = _ts_index(_jsonl(pf), ("open_time_ms",))
    df = cp[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    df["volume"] = np.nan
    df["taker_buy_base"] = np.nan
    df["spot_close"] = df["close"]
    df["spot_volume"] = np.nan
    df["spot_taker_buy_base"] = np.nan
    d = taker_stitched(sufs, df["close"])
    df["spot_delta"] = d
    df["perp_delta"] = d
    fb = _ts_index(_jsonl(ff))
    fr = _pick(fb, "close").astype(float)
    if fr.abs().median() > 1e-3:
        fr = fr / 100
    df["funding"] = pd.Series(fr.values, index=fb.index).reindex(df.index, method="ffill", limit=12)
    df["oi"] = np.nan
    return build_features(df.sort_index())


def rsi(s, period=14):
    d = s.diff()
    up = d.clip(lower=0)
    dn = (-d).clip(lower=0)
    ru = up.ewm(alpha=1 / period, adjust=False).mean()
    rd = dn.ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + ru / rd.replace(0, np.nan))


def make_gates(feat):
    px = feat["close"]
    e144 = px.ewm(span=144, adjust=False).mean()
    e169 = px.ewm(span=169, adjust=False).mean()
    r4 = rsi(px.resample("4h").last()).shift(1).reindex(feat.index, method="ffill")
    r1d = rsi(px.resample("1D").last()).shift(1).reindex(feat.index, method="ffill")
    return {
        "MA7": px < px.rolling(168).mean(),
        "MA13": px < px.rolling(312).mean(),
        "VG": px < pd.concat([e144, e169], axis=1).min(axis=1),
        "none": pd.Series(True, index=feat.index),
        "L_r4": r4 > 50, "L_r1d50": r1d > 50, "L_r1d45": r1d > 45,
    }


def sim(feat, mask, side, tp_style, buf, tp_mult=1.5):
    idx = feat.index
    n = len(feat)
    c, h, l = feat["close"].values, feat["high"].values, feat["low"].values
    h4h3, h4l3 = feat["h4_high3"].values, feat["h4_low3"].values
    m = mask.values
    out = []
    i = 0
    while i < n - 2:
        if not m[i]:
            i += 1
            continue
        row = feat.iloc[i]
        entry = c[i]
        if side == "S":
            stop = l01_stop(row, "SHORT", entry)
            if stop is not None and buf > 1.002:
                stop = stop * (buf / 1.002)
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
        pnl, xj, stopped, half = 0.0, None, False, False
        cur = stop
        if tp_style == "single":
            tgt = entry + sgn * tp_mult * r
            for j in range(i + 1, min(i + 73, n)):
                hs = h[j] >= cur if side == "S" else l[j] <= cur
                ht = l[j] <= tgt if side == "S" else h[j] >= tgt
                if hs:
                    pnl = sgn * (cur - entry) / entry - 2 * COST; xj = j; stopped = True; break
                if ht:
                    pnl = sgn * (tgt - entry) / entry - 2 * COST; xj = j; break
        else:  # partial / trail
            tp1 = entry + sgn * 1.1 * r
            tp2 = entry + sgn * 2.0 * r if tp_style == "partial" else None
            for j in range(i + 1, min(i + 73, n)):
                if half and tp_style == "trail":
                    tr_ref = h4h3[j] * 1.002 if side == "S" else h4l3[j] * 0.998
                    if np.isfinite(tr_ref):
                        cur = min(cur, tr_ref) if side == "S" else max(cur, tr_ref)
                hs = h[j] >= cur if side == "S" else l[j] <= cur
                if hs:
                    pnl += (0.5 if half else 1.0) * (sgn * (cur - entry) / entry - 2 * COST)
                    xj = j; stopped = not half; break
                h1 = l[j] <= tp1 if side == "S" else h[j] >= tp1
                if not half and h1:
                    pnl += 0.5 * (sgn * (tp1 - entry) / entry - 2 * COST); half = True; cur = entry; continue
                if half and tp2:
                    h2 = l[j] <= tp2 if side == "S" else h[j] >= tp2
                    if h2:
                        pnl += 0.5 * (sgn * (tp2 - entry) / entry - 2 * COST); xj = j; break
        if xj is None:
            j = min(i + 72, n - 1)
            pnl += (0.5 if half else 1.0) * (sgn * (c[j] - entry) / entry - 2 * COST)
            xj = j
        out.append({"t": idx[i], "pnl": pnl * 100})
        i = xj + (6 if stopped else 1)
    return pd.DataFrame(out)


def main():
    side = sys.argv[1]
    btc = assemble("price_1h.jsonl",
                   [("cg_taker_spot.jsonl", 1), ("cg_taker_spot_2h.jsonl", 2), ("cg_taker_spot_4h.jsonl", 4),
                    ("cg_taker_spot_6h.jsonl", 6), ("cg_taker_spot_12h.jsonl", 12)], "cg_funding.jsonl")
    eth = assemble("price_1h_eth.jsonl",
                   [("cg_taker_spot_eth.jsonl", 1), ("cg_taker_spot_eth_2h.jsonl", 2), ("cg_taker_spot_eth_4h.jsonl", 4),
                    ("cg_taker_spot_eth_6h.jsonl", 6), ("cg_taker_spot_eth_12h.jsonl", 12)], "cg_funding_eth.jsonl")
    rows = []
    for tag, feat in [("BTC", btc), ("ETH", eth)]:
        g = make_gates(feat)
        px = feat["close"]
        cvd = feat["spot_cvd_24h"]
        win = cvd.notna() & feat["funding"].notna()
        near = np.where(feat["us_open"], 0.02, 0.015)
        base_s = (((feat["resistance"] / px - 1) < near) & (px < feat["resistance"] * 1.005)
                  & (cvd < 0) & (feat["funding"] >= 0) & win)
        for combo in (itertools.product(["MA7", "MA13", "VG", "none"], ["single", "partial", "trail"], [1.002, 1.004])
                      if side == "short" else
                      itertools.product(["L_r4", "L_r1d50", "L_r1d45"], [0.10, 0.15, 0.20], [1.5, 2.0])):
            if side == "short":
                gate, tp, buf = combo
                tr = sim(feat, base_s & g[gate], "S", tp, buf)
                key = f"{gate}|{tp}|{buf}"
            else:
                gate, q, tpm = combo
                thr = cvd[win].quantile(q)
                mask = (cvd < thr) & (feat["spot_cvd_slope"] > 0) & g[gate] & win
                tr = sim(feat, mask, "L", "single", 1.002, tpm)
                key = f"{gate}|p{int(q*100)}|{tpm}R"
            a = tr[tr.t < SPLIT] if len(tr) else tr
            b = tr[tr.t >= SPLIT] if len(tr) else tr
            rows.append({"combo": key, "sym": tag, "n": len(tr), "net": round(tr.pnl.sum(), 2) if len(tr) else 0,
                         "h1": round(a.pnl.sum(), 2) if len(a) else 0, "h2": round(b.pnl.sum(), 2) if len(b) else 0})
    df = pd.DataFrame(rows)
    piv = df.pivot_table(index="combo", columns="sym", values=["net", "n", "h1", "h2"])
    piv.columns = [f"{a}_{b}" for a, b in piv.columns]
    piv["total"] = piv["net_BTC"] + piv["net_ETH"]
    piv["双正"] = (piv["net_BTC"] > 0) & (piv["net_ETH"] > 0)
    piv["四段同号"] = (piv["h1_BTC"] > 0) & (piv["h2_BTC"] > 0) & (piv["h1_ETH"] > 0) & (piv["h2_ETH"] > 0)
    piv = piv.sort_values("total", ascending=False)
    piv.to_csv(os.path.join(OUT, f"grid_{side}.csv"))
    pd.set_option("display.width", 250)
    print(piv[["total", "net_BTC", "n_BTC", "h1_BTC", "h2_BTC", "net_ETH", "n_ETH", "h1_ETH", "h2_ETH", "双正", "四段同号"]].head(10).to_string())
    print(f"\n网格中位数 total={piv['total'].median():+.2f}%  双正比例={piv['双正'].mean()*100:.0f}%  全同号比例={piv['四段同号'].mean()*100:.0f}%")


if __name__ == "__main__":
    main()
