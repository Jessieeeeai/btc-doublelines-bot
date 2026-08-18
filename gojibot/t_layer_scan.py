#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T层（止盈/出场）两段式调研：python3 t_layer_scan.py

阶段一 · 元件级：入场人群 MFE/MAE 画像（只入场不执行T出场）
  人群A s1@BTC：阻力衰竭空（S10 现役入场，含 o1 门控 px<SMA168h），参考 s1@ETH
  人群B s2@BTC+ETH：恐慌衰竭多 p15（S20 现役入场，含 o4 门控 4hRSI>50）
  每笔入场后 72h 逐时记录 MFE/MAE（以 L01 止损距离 R 为单位）：
  分布分位数、到达 1/1.5/2/3R 比例（止损前）、1R 后回吐率、MFE 到达时间中位数

阶段二 · 配对级：9 个预注册 T 变体串行整机（测前锁定，测完不加）
  t1 基准：1.5R 单目标 + 72h 超时
  t2 1.0R + 72h；t3 2.0R + 72h（R 邻域）
  t4 结构目标：空=入场时近3根已完成4H低点min / 多=近3根4H高点max；错侧退化为 t1
  t5 结构追踪：止损逐时按 h4_high3*1.002（空）/h4_low3*0.998（多）重算，只向有利方向移，无目标，72h
  t6 ATR吊灯：空=入场后最低价+3*ATR24h 追踪（多镜像），只向有利方向移，初始=L01，无目标，72h
  t7 纯时间：24h 收盘无条件离场（保留 L01 止损），无目标
  t8 分批：1R 平一半，剩余 2R 目标，止损不动（不移保本），72h 超时
  t9 反信号：空单在 spot_cvd_24h 翻正的 bar 收盘离场（多单翻负），无目标，72h（保留 L01）

其余元素全程锁死（与 deploy/bot.py 及 o_layer_scan.py 一致）：
  s1 入场：res=近20根已完成4H高点max，(res/px-1)<near(1.5%，UTC13-15点2%)，
           px<res*1.005，spot_cvd24h<0，funding>=0，px<SMA168h
  s2 入场：spot_cvd24h < 滚动p15阈值，6h净流(spot_cvd_slope)>0，4hRSI14(Wilder)>50
  止损：l01_stop（strategy.py，=bot.py l01 buf1.002）；>5% 拒单
  成本：单边 0.0007；止损后 6h 冷却；同 bar 双触发止损优先

口径声明（阶段2.5，固定单一解释，不做多口径扫描）：
  - s2 的 p15 阈值 = spot_cvd_24h 滚动 776h（含当前bar）分位 0.15，min_periods=100，
    精确复刻 bot.py 的 800 根取数窗口（bars<当前小时 → 约776个cvd24值，len>=100 才启用）。
    注意：历史 grid_long.csv 用的是全样本分位（含前视），本脚本口径与 bot 部署一致，
    数字与 grid_long 不逐位可比。
  - 4H/1D 特征全部 resample 后 shift(1) 再 reindex-ffill，只用已完成K线（与 o_layer_scan 相同，
    在 4H 桶边界小时比 bot.py 保守最多 1 根 bar）
  - MFE/MAE 画像人群 = "只有 L01 止损 + 72h 超时"假想策略的串行成交流（止损后 6h 冷却），
    保证人群与阶段二各变体的入场序列同源；MFE_prestop = 原始 L01 止损被触及前（同bar止损
    优先，止损bar的有利偏移不计）的最大有利偏移
  - MFE捕获率 = 实现盈亏(含成本) ÷ 该笔 MFE_prestop（72h窗全程、对原始L01），仅盈利单且MFE>0
  - t6 的 ATR24h = (high-low).rolling(24).mean()，用 j-1 bar 的 ATR 与截至 j-1 的极值价
    更新 j bar 生效的止损（无同bar循环依赖）；t5 沿用 grid_all trail 的 h4h3/h4l3 参考
  - 止损/追踪位成交价 = max(位, 上一bar收盘)（空，多取min）：滞后结构位穿到市场价另一侧时
    按市价（开盘代理）成交，防止在从未成交过的价位记账虚增利润（只影响 t5/t6 追踪系）
  - t8 同bar先查止损，未持半仓时同bar只成交 TP1 不连吃 TP2（保守）；半仓后止损不计冷却
  - t9 反信号在 bar 收盘评估并按该 bar 收盘价离场
  - BTC 训练/样本外 = s1 有效窗口（cvd+funding 就绪）时间对半，s2 沿用同一分界；ETH 整段零调整
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
pd.set_option("display.width", 260)

BTC_SUFS = [("cg_taker_spot.jsonl", 1), ("cg_taker_spot_2h.jsonl", 2), ("cg_taker_spot_4h.jsonl", 4),
            ("cg_taker_spot_6h.jsonl", 6), ("cg_taker_spot_12h.jsonl", 12)]
ETH_SUFS = [("cg_taker_spot_eth.jsonl", 1), ("cg_taker_spot_eth_2h.jsonl", 2), ("cg_taker_spot_eth_4h.jsonl", 4),
            ("cg_taker_spot_eth_6h.jsonl", 6), ("cg_taker_spot_eth_12h.jsonl", 12)]

VARIANTS = ["t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9"]


def wilder_rsi(s, period=14):
    d = s.diff()
    up = d.clip(lower=0)
    dn = (-d).clip(lower=0)
    ru = up.ewm(alpha=1 / period, adjust=False).mean()
    rd = dn.ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + ru / rd.replace(0, np.nan))


def prep(feat):
    px = feat["close"]
    feat["ma168"] = px.rolling(168).mean()
    c4 = px.resample("4h").last()
    feat["rsi4h"] = wilder_rsi(c4).shift(1).reindex(feat.index, method="ffill")
    feat["p15_thr"] = feat["spot_cvd_24h"].rolling(776, min_periods=100).quantile(0.15)
    return feat


def entry_mask(feat, strat):
    px = feat["close"]
    cvd = feat["spot_cvd_24h"]
    if strat == "s1":
        win = cvd.notna() & feat["funding"].notna()
        near = np.where(feat["us_open"], 0.02, 0.015)
        m = (((feat["resistance"] / px - 1) < near) & (px < feat["resistance"] * 1.005)
             & (cvd < 0) & (feat["funding"] >= 0) & (px < feat["ma168"]) & win)
        return m.fillna(False), "S"
    m = ((cvd < feat["p15_thr"]) & (feat["spot_cvd_slope"] > 0) & (feat["rsi4h"] > 50)
         & cvd.notna() & feat["p15_thr"].notna() & feat["rsi4h"].notna())
    return m.fillna(False), "L"


def get_stop(feat, i, side):
    """入场有效性 + L01 止损。返回 stop 或 None。"""
    row = feat.iloc[i]
    entry = feat["close"].values[i]
    stop = l01_stop(row, "SHORT" if side == "S" else "LONG", entry)
    if side == "S":
        ok = stop and stop > entry and stop / entry - 1 <= 0.05
    else:
        ok = stop and stop < entry and 1 - stop / entry <= 0.05
    return stop if ok else None


def mfe_prestop(i, entry, stop0, sgn, h, l, n):
    """72h窗内、原始L01止损触及前的最大有利偏移（价格比例）。同bar止损优先。"""
    m = 0.0
    for j in range(i + 1, min(i + 73, n)):
        hit = (h[j] >= stop0) if sgn < 0 else (l[j] <= stop0)
        if hit:
            break
        fav = sgn * ((l[j] if sgn < 0 else h[j]) - entry) / entry
        m = max(m, fav)
    return m


# ----------------------------------------------------------------------
# 阶段一：MFE/MAE 画像
# ----------------------------------------------------------------------
def profile(feat, mask, side):
    idx = feat.index
    n = len(feat)
    c, h, l = feat["close"].values, feat["high"].values, feat["low"].values
    m = mask.values
    sgn = -1 if side == "S" else 1
    recs = []
    i = 0
    while i < n - 2:
        if not m[i]:
            i += 1
            continue
        stop = get_stop(feat, i, side)
        if stop is None:
            i += 1
            continue
        entry = c[i]
        R = abs(entry - stop)
        end = min(i + 73, n)
        full_mfe = full_mae = 0.0
        pre_mfe, t_pre_mfe = 0.0, np.nan
        t_stop = None
        touch = {1.0: np.nan, 1.5: np.nan, 2.0: np.nan, 3.0: np.nan}
        t_1r = None
        giveback = False
        for j in range(i + 1, end):
            fav = sgn * ((l[j] if sgn < 0 else h[j]) - entry) / R
            adv = -sgn * ((h[j] if sgn < 0 else l[j]) - entry) / R
            full_mfe = max(full_mfe, fav)
            full_mae = max(full_mae, adv)
            hit = (h[j] >= stop) if sgn < 0 else (l[j] <= stop)
            if t_stop is None:
                if hit:
                    t_stop = j - i
                    if t_1r is not None:
                        giveback = True  # 到过1R后被打止损=回吐过入场价
                else:
                    if fav > pre_mfe:
                        pre_mfe, t_pre_mfe = fav, j - i
                    for k in touch:
                        if np.isnan(touch[k]) and fav >= k:
                            touch[k] = j - i
                    if t_1r is None and fav >= 1.0:
                        t_1r = j - i
                    elif t_1r is not None and not giveback:
                        back = (h[j] >= entry) if sgn < 0 else (l[j] <= entry)
                        if back:
                            giveback = True
        recs.append({"t": idx[i], "R_pct": R / entry * 100, "stophit": t_stop is not None,
                     "t_stop": t_stop, "full_mfe": full_mfe, "full_mae": full_mae,
                     "pre_mfe": pre_mfe, "t_pre_mfe": t_pre_mfe,
                     "r10": touch[1.0], "r15": touch[1.5], "r20": touch[2.0], "r30": touch[3.0],
                     "giveback": giveback})
        xj = (i + t_stop) if t_stop is not None else min(i + 72, n - 1)
        i = xj + (6 if t_stop is not None else 1)
    return pd.DataFrame(recs)


def profile_stats(df, tag):
    if not len(df):
        return {"人群": tag, "n": 0}
    q = df.pre_mfe.quantile
    r1 = df.r10.notna()
    return {
        "人群": tag, "n": len(df),
        "R%中位": round(df.R_pct.median(), 2),
        "止损触及%": round(df.stophit.mean() * 100, 0),
        "preMFE_p25": round(q(0.25), 2), "preMFE_p50": round(q(0.50), 2),
        "preMFE_p75": round(q(0.75), 2), "preMFE_p90": round(q(0.90), 2),
        "fullMFE_p50": round(df.full_mfe.quantile(0.5), 2),
        "fullMAE_p50": round(df.full_mae.quantile(0.5), 2),
        "到1R%": round(r1.mean() * 100, 0),
        "到1.5R%": round(df.r15.notna().mean() * 100, 0),
        "到2R%": round(df.r20.notna().mean() * 100, 0),
        "到3R%": round(df.r30.notna().mean() * 100, 0),
        "1R后回吐%": round(df.loc[r1, "giveback"].mean() * 100, 0) if r1.any() else np.nan,
        "tMFE中位h": round(df.loc[df.pre_mfe > 0, "t_pre_mfe"].median(), 0),
        "t1R中位h": round(df.loc[r1, "r10"].median(), 0) if r1.any() else np.nan,
    }


# ----------------------------------------------------------------------
# 阶段二：9 变体串行模拟
# ----------------------------------------------------------------------
def sim_t(feat, mask, side, tv):
    idx = feat.index
    n = len(feat)
    c, h, l = feat["close"].values, feat["high"].values, feat["low"].values
    h4h3, h4l3 = feat["h4_high3"].values, feat["h4_low3"].values
    atr = feat["atr24"].values
    cvd = feat["spot_cvd_24h"].values
    m = mask.values
    sgn = -1 if side == "S" else 1
    S = side == "S"
    out = []
    i = 0
    while i < n - 2:
        if not m[i]:
            i += 1
            continue
        stop = get_stop(feat, i, side)
        if stop is None:
            i += 1
            continue
        entry = c[i]
        R = abs(entry - stop)
        maxh = 24 if tv == "t7" else 72
        tgt = tp1 = tp2 = None
        if tv in ("t1", "t2", "t3"):
            tgt = entry + sgn * {"t1": 1.5, "t2": 1.0, "t3": 2.0}[tv] * R
        elif tv == "t4":
            st = h4l3[i] if S else h4h3[i]
            tgt = st if (np.isfinite(st) and sgn * (st - entry) > 0) else entry + sgn * 1.5 * R
        elif tv == "t8":
            tp1, tp2 = entry + sgn * 1.0 * R, entry + sgn * 2.0 * R
        cur, ext = stop, entry
        pnl, xj, stopped, half = 0.0, None, False, False
        for j in range(i + 1, min(i + maxh + 1, n)):
            if tv == "t5":
                ref = h4h3[j] * 1.002 if S else h4l3[j] * 0.998
                if np.isfinite(ref):
                    cur = min(cur, ref) if S else max(cur, ref)
            elif tv == "t6" and np.isfinite(atr[j - 1]):
                ref = ext + 3 * atr[j - 1] if S else ext - 3 * atr[j - 1]
                cur = min(cur, ref) if S else max(cur, ref)
            hs = h[j] >= cur if S else l[j] <= cur
            if hs:
                # 追踪位若已穿到市场价另一侧（滞后结构位低于开盘），按市价成交：
                # 用上一bar收盘做开盘代理（无前视、防止在从未成交过的价位记账）
                px_exec = max(cur, c[j - 1]) if S else min(cur, c[j - 1])
                pnl += (0.5 if half else 1.0) * (sgn * (px_exec - entry) / entry - 2 * COST)
                xj, stopped = j, not half
                break
            if tv == "t8":
                if not half:
                    if (l[j] <= tp1) if S else (h[j] >= tp1):
                        pnl += 0.5 * (sgn * (tp1 - entry) / entry - 2 * COST)
                        half = True
                        continue  # 同bar不连吃TP2（保守）
                elif (l[j] <= tp2) if S else (h[j] >= tp2):
                    pnl += 0.5 * (sgn * (tp2 - entry) / entry - 2 * COST)
                    xj = j
                    break
            elif tgt is not None:
                if (l[j] <= tgt) if S else (h[j] >= tgt):
                    pnl = sgn * (tgt - entry) / entry - 2 * COST
                    xj = j
                    break
            if tv == "t9" and np.isfinite(cvd[j]) and ((cvd[j] > 0) if S else (cvd[j] < 0)):
                pnl = sgn * (c[j] - entry) / entry - 2 * COST
                xj = j
                break
            if tv == "t6":
                ext = min(ext, l[j]) if S else max(ext, h[j])
        if xj is None:
            j = min(i + maxh, n - 1)
            pnl += (0.5 if half else 1.0) * (sgn * (c[j] - entry) / entry - 2 * COST)
            xj = j
        mfe = mfe_prestop(i, entry, stop, sgn, h, l, n)
        out.append({"t": idx[i], "pnl": pnl * 100, "hold": xj - i, "mfe": mfe * 100})
        i = xj + (6 if stopped else 1)
    return pd.DataFrame(out)


def stats(tr):
    if tr is None or len(tr) == 0:
        return {"n": 0, "net": 0.0, "wr": np.nan, "hold": np.nan, "capt": np.nan}
    w = tr[(tr.pnl > 0) & (tr.mfe > 0)]
    return {"n": len(tr), "net": round(tr.pnl.sum(), 2),
            "wr": round((tr.pnl > 0).mean() * 100, 0),
            "hold": round(tr.hold.mean(), 1),
            "capt": round((w.pnl / w.mfe).mean() * 100, 0) if len(w) else np.nan}


def main():
    btc = prep(assemble("price_1h.jsonl", BTC_SUFS, "cg_funding.jsonl"))
    eth = prep(assemble("price_1h_eth.jsonl", ETH_SUFS, "cg_funding_eth.jsonl"))
    bwin = btc["spot_cvd_24h"].notna() & btc["funding"].notna()
    bw = btc.index[bwin]
    mid = bw[0] + (bw[-1] - bw[0]) / 2
    print(f"BTC 有效窗口: {bw[0]} → {bw[-1]}  训练/样本外分界(对半): {mid}")
    ew = eth.index[eth["spot_cvd_24h"].notna() & eth["funding"].notna()]
    print(f"ETH 有效窗口: {ew[0]} → {ew[-1]}（整段零调整）\n")

    masks = {}
    for sym, feat in (("BTC", btc), ("ETH", eth)):
        for strat in ("s1", "s2"):
            masks[(strat, sym)] = entry_mask(feat, strat)

    # ---------- 阶段一 ----------
    print("=" * 100)
    print("阶段一 · 入场人群 MFE/MAE 画像（R=L01止损距离；preMFE=原始止损触及前；72h窗）")
    profs, prows = {}, []
    for strat, sym in (("s1", "BTC"), ("s1", "ETH"), ("s2", "BTC"), ("s2", "ETH")):
        feat = btc if sym == "BTC" else eth
        mk, side = masks[(strat, sym)]
        profs[(strat, sym)] = profile(feat, mk, side)
        prows.append(profile_stats(profs[(strat, sym)], f"{strat}@{sym}"))
    prows.append(profile_stats(pd.concat([profs[("s2", "BTC")], profs[("s2", "ETH")]]),
                               "s2@BTC+ETH合并"))
    ptab = pd.DataFrame(prows).set_index("人群")
    print(ptab.to_string())
    ptab.to_csv(os.path.join(OUT, "t_layer_profile.csv"))

    # ---------- 阶段二 ----------
    print("\n" + "=" * 100)
    print("阶段二 · 9 变体 × 配对整机（串行、锁死其余元素）")
    rows = []
    for tv in VARIANTS:
        rec = {"T": tv}
        for strat in ("s1", "s2"):
            mkb, side = masks[(strat, "BTC")]
            mke, _ = masks[(strat, "ETH")]
            trb = sim_t(btc, mkb, side, tv)
            tre = sim_t(eth, mke, side, tv)
            a = trb[trb.t < mid] if len(trb) else trb
            b = trb[trb.t >= mid] if len(trb) else trb
            sa, sb, sB, sE = stats(a), stats(b), stats(trb), stats(tre)
            rec.update({f"{strat}B训n": sa["n"], f"{strat}B训net": sa["net"], f"{strat}B训wr": sa["wr"],
                        f"{strat}B外n": sb["n"], f"{strat}B外net": sb["net"], f"{strat}B外wr": sb["wr"],
                        f"{strat}Bnet": sB["net"], f"{strat}Bn": sB["n"],
                        f"{strat}Enet": sE["net"], f"{strat}En": sE["n"],
                        f"{strat}hold": stats(pd.concat([trb, tre]))["hold"],
                        f"{strat}wr": stats(pd.concat([trb, tre]))["wr"],
                        f"{strat}capt": stats(pd.concat([trb, tre]))["capt"],
                        f"{strat}合计": round(sB["net"] + sE["net"], 2)})
            rec[f"{strat}训外同号"] = bool(sa["net"] > 0 and sb["net"] > 0)
            rec[f"{strat}ETH同向"] = bool(sE["net"] > 0)
        rows.append(rec)
    tab = pd.DataFrame(rows).set_index("T")
    for strat in ("s1", "s2"):
        cols = [c for c in tab.columns if c.startswith(strat)]
        print(f"\n---- {strat} ({'阻力衰竭空' if strat == 's1' else '恐慌衰竭多p15'}) ----")
        print(tab[cols].to_string())
    tab.to_csv(os.path.join(OUT, "t_layer_scan.csv"))
    print(f"\n已保存 {os.path.join(OUT, 't_layer_profile.csv')} / t_layer_scan.csv")


if __name__ == "__main__":
    main()
