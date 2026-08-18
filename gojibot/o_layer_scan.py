#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""O层（趋势门控）预注册扫描：S10 基准 o1 vs 10 个替代门控。
python3 o_layer_scan.py

预注册变体（测前锁定，测完不加）：
  o1  px < SMA168h（基准，S10 现役）
  oA  px < SMA480h（MA20日）
  oB  px < EMA200h
  oC  px < Donchian20日中轨（已完成1D K线）
  oD  4H MACD(12,26,9) 柱 < 0（已完成4H）
  oE  4H RSI14(Wilder) < 50（已完成4H收盘）
  oF  SuperTrend(4H, ATR14, x3) 空头态（已完成4H）
  oG  SMA168h(now) < SMA168h(24h前)（MA7斜率向下）
  oH  px < SMA168h 且 px < min(EMA144h, EMA169h)（o1∧o3）
  oI  px < SMA72h
  oJ  4H一目云(9,26,52)下方：px < min(先行A,先行B)，云前移26根4H

其余五元素（S/L/T/C 及入场条件）与 S10=o1s1l1t1c1 完全一致：
  入场：res=近20根已完成4H高点max，(res/px-1)<near(1.5%，UTC13-15点2%)，
        px<res*1.005，spot_cvd24h<0，funding>=0，门控
  止损：l01_stop（3根4H高*1.002 / 升级5根1D高*1.003 / >5%拒单）
  出场：1.5R 单目标；72h 超时收盘平仓；同bar双触发止损优先；止损后6h冷却
  成本：单边 0.0007

口径声明（阶段2.5，固定单一解释，不做多口径扫描）：
  - 4H/1D 全部 resample 后 shift(1) 再 reindex-ffill，只用已完成K线
  - RSI 用 ewm(alpha=1/14, adjust=False)（Wilder 平滑，与 bot.py 递推等价渐近）
  - SuperTrend 用 Wilder ATR（ewm alpha=1/14），标准 final band 递推
  - 一目云 senkou shift(26) 本身保证无前视，reindex 不再额外 shift
  - BTC 训练/样本外 = 数据时间跨度对半（分界打印在结果里）；ETH 整段零调整
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pandas as pd
from grid_all import assemble  # noqa: E402
from strategy import l01_stop  # noqa: E402
from run import CFG, OUT  # noqa: E402

COST = (CFG["costs"]["taker_fee_pct"] + CFG["costs"]["slippage_pct"]) / 100.0
pd.set_option("display.width", 250)

BTC_SUFS = [("cg_taker_spot.jsonl", 1), ("cg_taker_spot_2h.jsonl", 2), ("cg_taker_spot_4h.jsonl", 4),
            ("cg_taker_spot_6h.jsonl", 6), ("cg_taker_spot_12h.jsonl", 12)]
ETH_SUFS = [("cg_taker_spot_eth.jsonl", 1), ("cg_taker_spot_eth_2h.jsonl", 2), ("cg_taker_spot_eth_4h.jsonl", 4),
            ("cg_taker_spot_eth_6h.jsonl", 6), ("cg_taker_spot_eth_12h.jsonl", 12)]


def wilder_rsi(s, period=14):
    d = s.diff()
    up = d.clip(lower=0)
    dn = (-d).clip(lower=0)
    ru = up.ewm(alpha=1 / period, adjust=False).mean()
    rd = dn.ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + ru / rd.replace(0, np.nan))


def supertrend_bear(h4, period=14, mult=3.0):
    """已完成4H上的 SuperTrend 空头态（返回4H布尔序列，含NaN段=不确定）。"""
    h, l, c = h4["high"], h4["low"], h4["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    hl2 = (h + l) / 2
    bu = (hl2 + mult * atr).values
    bl = (hl2 - mult * atr).values
    cv = c.values
    n = len(h4)
    fu = np.full(n, np.nan)
    fl = np.full(n, np.nan)
    bear = np.full(n, np.nan)
    start = period  # 前 period 根 ATR 未热身
    for i in range(start, n):
        if i == start or np.isnan(fu[i - 1]):
            fu[i], fl[i] = bu[i], bl[i]
            bear[i] = 1.0  # 初始态任取，几根内被真实穿越覆盖
            continue
        fu[i] = bu[i] if (bu[i] < fu[i - 1] or cv[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = bl[i] if (bl[i] > fl[i - 1] or cv[i - 1] < fl[i - 1]) else fl[i - 1]
        if bear[i - 1] == 1.0:
            bear[i] = 0.0 if cv[i] > fu[i] else 1.0
        else:
            bear[i] = 1.0 if cv[i] < fl[i] else 0.0
    return pd.Series(bear, index=h4.index)


def make_o_gates(feat):
    """返回 {name: 浮点门控序列}（1=真 0=假 NaN=指标未就绪），按1h对齐、无前视。"""
    px = feat["close"]
    ma168 = px.rolling(168).mean()
    e144 = px.ewm(span=144, adjust=False).mean()
    e169 = px.ewm(span=169, adjust=False).mean()

    # 4H 已完成 OHLC
    h4 = feat[["high", "low", "close"]].resample("4h").agg(
        {"high": "max", "low": "min", "close": "last"})
    c4 = h4["close"]
    # 1D 已完成高低
    d1 = feat[["high", "low"]].resample("1D").agg({"high": "max", "low": "min"})

    def to1h(s4):  # shift(1)=只用已完成bar，再铺回1h
        return s4.shift(1).reindex(feat.index, method="ffill")

    # oC Donchian 20日中轨
    dc_mid = ((d1["high"].shift(1).rolling(20).max()
               + d1["low"].shift(1).rolling(20).min()) / 2).reindex(feat.index, method="ffill")
    # oD MACD 柱
    macd = c4.ewm(span=12, adjust=False).mean() - c4.ewm(span=26, adjust=False).mean()
    hist = to1h(macd - macd.ewm(span=9, adjust=False).mean())
    # oE RSI
    r4 = to1h(wilder_rsi(c4))
    # oF SuperTrend
    st_bear = to1h(supertrend_bear(h4))
    # oJ 一目云（senkou 已前移26根4H，shift(26)自带无前视；reindex不再额外shift）
    hh9 = h4["high"].rolling(9).max(); ll9 = h4["low"].rolling(9).min()
    hh26 = h4["high"].rolling(26).max(); ll26 = h4["low"].rolling(26).min()
    hh52 = h4["high"].rolling(52).max(); ll52 = h4["low"].rolling(52).min()
    tenkan = (hh9 + ll9) / 2
    kijun = (hh26 + ll26) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((hh52 + ll52) / 2).shift(26)
    cloud_lo = pd.concat([span_a, span_b], axis=1).min(axis=1).reindex(feat.index, method="ffill")

    def cmp(lhs, rhs):  # 比较，指标NaN处留NaN（用于放行率分母）
        v = (lhs < rhs).astype(float)
        return v.where(lhs.notna() & rhs.notna())

    ma168_prev = ma168.shift(24)
    gates = {
        "o1_SMA168": cmp(px, ma168),
        "oA_SMA480": cmp(px, px.rolling(480).mean()),
        "oB_EMA200": cmp(px, px.ewm(span=200, adjust=False).mean()),
        "oC_DC20mid": cmp(px, dc_mid),
        "oD_MACD4h": hist.where(hist.notna()).lt(0).astype(float).where(hist.notna()),
        "oE_RSI4h50": r4.lt(50).astype(float).where(r4.notna()),
        "oF_SuperTrend": st_bear,
        "oG_MA7slope": (ma168 < ma168_prev).astype(float).where(
            ma168.notna() & ma168_prev.notna()),
        "oH_MA7andVegas": ((px < ma168) & (px < pd.concat([e144, e169], axis=1).min(axis=1)))
        .astype(float).where(ma168.notna()),
        "oI_SMA72": cmp(px, px.rolling(72).mean()),
        "oJ_Ichimoku4h": cmp(px, cloud_lo),
    }
    return gates


def sim(feat, mask):
    """串行模拟：SHORT / l01止损 / 1.5R单目标 / 72h超时 / 同bar止损优先 / 止损后6h冷却。
    与 grid_all.sim(side='S', tp_style='single', buf=1.002) 逐行一致。"""
    idx = feat.index
    n = len(feat)
    c, h, l = feat["close"].values, feat["high"].values, feat["low"].values
    m = mask.values
    out = []
    i = 0
    while i < n - 2:
        if not m[i]:
            i += 1
            continue
        row = feat.iloc[i]
        entry = c[i]
        stop = l01_stop(row, "SHORT", entry)
        if not (stop and stop > entry and stop / entry - 1 <= 0.05):
            i += 1
            continue
        r = stop - entry
        tgt = entry - 1.5 * r
        pnl, xj, stopped = 0.0, None, False
        for j in range(i + 1, min(i + 73, n)):
            if h[j] >= stop:  # 同bar双触发：止损优先
                pnl = -(stop - entry) / entry - 2 * COST
                xj, stopped = j, True
                break
            if l[j] <= tgt:
                pnl = -(tgt - entry) / entry - 2 * COST
                xj = j
                break
        if xj is None:
            j = min(i + 72, n - 1)
            pnl = -(c[j] - entry) / entry - 2 * COST
            xj = j
        out.append({"t": idx[i], "pnl": pnl * 100})
        i = xj + (6 if stopped else 1)
    return pd.DataFrame(out)


def stats(tr):
    if tr is None or len(tr) == 0:
        return {"n": 0, "net": 0.0, "wr": float("nan")}
    return {"n": len(tr), "net": round(tr.pnl.sum(), 2),
            "wr": round((tr.pnl > 0).mean() * 100, 0)}


def main():
    btc = assemble("price_1h.jsonl", BTC_SUFS, "cg_funding.jsonl")
    eth = assemble("price_1h_eth.jsonl", ETH_SUFS, "cg_funding_eth.jsonl")
    # 有效窗口 = cvd+funding 同时就绪的段（价格数据更长，只用来热身指标）
    bwin = btc["spot_cvd_24h"].notna() & btc["funding"].notna()
    bw = btc.index[bwin]
    mid = bw[0] + (bw[-1] - bw[0]) / 2
    print(f"BTC 有效窗口: {bw[0]} → {bw[-1]}  训练/样本外分界(对半): {mid}")
    ewin = eth["spot_cvd_24h"].notna() & eth["funding"].notna()
    ew = eth.index[ewin]
    print(f"ETH 有效窗口: {ew[0]} → {ew[-1]}（整段零调整）\n")

    rows = []
    for tag, feat in (("BTC", btc), ("ETH", eth)):
        px = feat["close"]
        cvd = feat["spot_cvd_24h"]
        win = cvd.notna() & feat["funding"].notna()
        near = np.where(feat["us_open"], 0.02, 0.015)
        base = (((feat["resistance"] / px - 1) < near) & (px < feat["resistance"] * 1.005)
                & (cvd < 0) & (feat["funding"] >= 0) & win)
        gates = make_o_gates(feat)
        o1 = gates["o1_SMA168"]
        for nm, g in gates.items():
            gb = g.fillna(0).astype(bool)
            tr = sim(feat, base & gb)
            rate = g[win].mean() * 100  # 放行率：有效窗口内门控为真的K线占比
            both = ((g == 1) & (o1 == 1) & win).sum()
            either = (((g == 1) | (o1 == 1)) & win).sum()
            jac = both / either * 100 if either else np.nan
            if tag == "BTC":
                a, b = tr[tr.t < mid] if len(tr) else tr, tr[tr.t >= mid] if len(tr) else tr
                rows.append({"gate": nm, "sym": tag, **{f"tr_{k}": v for k, v in stats(a).items()},
                             **{f"oos_{k}": v for k, v in stats(b).items()},
                             **{f"all_{k}": v for k, v in stats(tr).items()},
                             "pass%": round(rate, 1), "jac_o1%": round(jac, 0)})
            else:
                rows.append({"gate": nm, "sym": tag,
                             **{f"all_{k}": v for k, v in stats(tr).items()},
                             "pass%": round(rate, 1), "jac_o1%": round(jac, 0)})
    df = pd.DataFrame(rows)
    b = df[df.sym == "BTC"].set_index("gate")
    e = df[df.sym == "ETH"].set_index("gate")
    tab = pd.DataFrame({
        "BTC训n": b.tr_n.astype(int), "BTC训net%": b.tr_net, "BTC训wr%": b.tr_wr,
        "BTC外n": b.oos_n.astype(int), "BTC外net%": b.oos_net, "BTC外wr%": b.oos_wr,
        "BTC合计%": b.all_net, "BTC合计n": b.all_n.astype(int),
        "ETHn": e.all_n.astype(int), "ETHnet%": e.all_net, "ETHwr%": e.all_wr,
        "BTC放行%": b["pass%"], "ETH放行%": e["pass%"],
        "BTC与o1重叠%": b["jac_o1%"],
    })
    tab["训外同号"] = (tab["BTC训net%"] > 0) & (tab["BTC外net%"] > 0)
    tab["ETH同向"] = tab["ETHnet%"] > 0
    tab["候选"] = tab["训外同号"] & tab["ETH同向"]
    tab = tab.sort_values("BTC合计%", ascending=False)
    print(tab.to_string())
    tab.to_csv(os.path.join(OUT, "o_layer_scan.csv"))
    print(f"\n已保存 {os.path.join(OUT, 'o_layer_scan.csv')}")


if __name__ == "__main__":
    main()
