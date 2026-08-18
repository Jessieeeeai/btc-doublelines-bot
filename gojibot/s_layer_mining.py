#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S层（交易结构）两段式发掘：python3 s_layer_mining.py

7 个机理驱动的预注册结构（测前锁定口径，一次解释，测完不加）：
  sA 假突破·阻力扫荡空：bar high>res(近20根已完成4H高点max) 且 close<res 且 CVD24h<0 → 空
  sB 卖压衰减多：CVD24h<0 且 CVD24h>12h前CVD24h（卖压减速）且 距近20×4H低点<1.5% → 多
  sC CVD顶背离空：close=过去120根1h收盘最高 且 CVD24h<过去120h CVD24h中位数 → 空
  sD 费率挤压多：FR≤FR滚动30日p10 且 6h净流(spot_cvd_slope)>0 → 多
  sE 缩量回抽空（顺势）：close<SMA168 且 close较过去24h最低close反弹≥1.5% 且 CVD24h<0 → 空
  sF 单bar恐慌吸收多：上一bar 1h taker净流<其滚动30日p1 且 本bar low≥上一bar low → 多
  sG 费率-价格背离空：24h涨幅>1% 且 FR>FR滚动30日p85 且 FR>24h前FR → 空

与墓地（results/最终分析报告.md）的边界声明：
  - sA 是"阻力位扫荡后收回"事件（S03 是 KZ 时段区间压缩突破，已证伪，不复活）
  - sB/sD 用变化率（CVD 12h差分）与拥挤度分位（FR p10），对称多单死者用的是
    水平量组合（CVD>0 + 费率低绝对档），不同构
  - sF 是单bar taker 净流极端事件（清算潮死者用清算数据源+14天分位，不同源不同构）

口径声明（阶段2.5，固定单一解释，不做多口径扫描）：
  - res=feat.resistance（近20根已完成4H高点max，shift(1)，同 s1）；sup20 镜像取 4H低点min
  - sB "距离<1.5%"：px/sup20-1<0.015 且 px>sup20*0.995（镜像 s1 近阻力口径，容忍轻微下破0.5%）
  - sC "close=120根最高"：px>=rolling(120).max()（窗含当前bar）；中位数窗同（含当前bar）
  - sE "过去24h最低close"：close.shift(1).rolling(24).min()（不含当前bar）
  - sF p1 阈值 = spot_delta.rolling(720,min240).quantile(0.01)，在"上一bar"处取值
    （thr.shift(1) 与 flow.shift(1) 对齐，无前视）；spot_delta 为拼接摊薄流
    （粗粒度期被摊平，p1 极端事件天然集中在 1h 细粒度覆盖段——如实报告，不修）
  - FR 滚动分位窗=720h(30日)，min_periods=240；FR 为 8h 结算值 ffill 到小时
  - 事件去重：同结构同品种 24h 内只计首次触发（仅阶段一；阶段二由串行持仓自然互斥）
  - fwdN = close.shift(-N)/close-1；无条件基线 = 该结构输入齐备窗(win)内全bar均值
  - t_adj = [(事件均值-基线)/(事件std/√n)] / √(N/24)（粗略校正持有期重叠）
  - 行情分段沿用 SEGS：上行 2025-08-03→11-01，崩盘 →2026-01-07，下跌 →2026-07-01
  - 窗口注：CVD 起 2025-07-08 早于 funding 起 2025-08-03，不含费率条件的结构
    (sA/sB/sC/sE/sF) 有效窗比三段表早约26天；该热身段事件/交易计入总计与训/外，
    但不落入任何行情段（段n之和可小于总n，如实保留不裁剪）

阶段一淘汰线（预注册，测前锁定）：
  - 主品种 BTC：fwd24 diff 符号与方向一致（空→负，多→正）且 |diff24|≥0.25pp
  - ETH：fwd24 diff 同号；双品种去重后事件数各 ≥8（不足=无法判定，按零信息处理）
  - 只在单一行情段成立（其余段符号相反或≈0）→ 标"行情战术件"，仍可进阶段二但降级标注
  - 阶段一全灭也是合格结论

阶段二（只对幸存者；执行腿锁死=现役 l1+t1）：
  L01(l01_stop 含1D升级) / TP=1.5R 单目标 / 72h超时 / 成本单边0.0007 /
  止损后6h冷却 / 同bar双触发止损优先 / 止损距离>5%拒单 / 信号bar收盘入场
  每个幸存者两个配置（预声明，不加第三个）：
    ① 裸跑  ② 机理门控：空配 o1(px<SMA168h)，多配 o4(4hRSI14 Wilder>50)；
       sE 例外（自含 SMA168 条件）→ ② 改配 oD(4H MACD柱<0, 12/26/9, shift(1))
  BTC 训练/样本外 = cvd+funding 齐备窗时间对半（与 l/t_layer_scan 同一分界）；ETH 整段零调整
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
pd.set_option("display.width", 300)

BTC_SUFS = [("cg_taker_spot.jsonl", 1), ("cg_taker_spot_2h.jsonl", 2), ("cg_taker_spot_4h.jsonl", 4),
            ("cg_taker_spot_6h.jsonl", 6), ("cg_taker_spot_12h.jsonl", 12)]
ETH_SUFS = [("cg_taker_spot_eth.jsonl", 1), ("cg_taker_spot_eth_2h.jsonl", 2), ("cg_taker_spot_eth_4h.jsonl", 4),
            ("cg_taker_spot_eth_6h.jsonl", 6), ("cg_taker_spot_eth_12h.jsonl", 12)]

SEGS = [("上行", "2025-08-03", "2025-11-01"),
        ("崩盘", "2025-11-01", "2026-01-07"),
        ("下跌", "2026-01-07", "2026-07-01")]

STRUCT_NAMES = {
    "sA": "假突破·阻力扫荡空", "sB": "卖压衰减多", "sC": "CVD顶背离空",
    "sD": "费率挤压多", "sE": "缩量回抽空", "sF": "单bar恐慌吸收多", "sG": "费率-价格背离空",
}


def wilder_rsi(s, period=14):
    d = s.diff()
    up = d.clip(lower=0)
    dn = (-d).clip(lower=0)
    ru = up.ewm(alpha=1 / period, adjust=False).mean()
    rd = dn.ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + ru / rd.replace(0, np.nan))


def prep(feat):
    px = feat["close"]
    cvd = feat["spot_cvd_24h"]
    feat["ma168"] = px.rolling(168).mean()
    c4 = px.resample("4h").last()
    feat["rsi4h"] = wilder_rsi(c4).shift(1).reindex(feat.index, method="ffill")
    ema12 = c4.ewm(span=12, adjust=False).mean()
    ema26 = c4.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    hist = macd - macd.ewm(span=9, adjust=False).mean()
    feat["macd4h_hist"] = hist.shift(1).reindex(feat.index, method="ffill")
    h4 = feat[["high", "low"]].resample("4h").agg({"high": "max", "low": "min"})
    feat["support20"] = h4["low"].shift(1).rolling(20).min().reindex(feat.index, method="ffill")
    feat["cvd24_lag12"] = cvd.shift(12)
    feat["fr_p10_30d"] = feat["funding"].rolling(720, min_periods=240).quantile(0.10)
    feat["fr_p85_30d"] = feat["funding"].rolling(720, min_periods=240).quantile(0.85)
    feat["fr_lag24"] = feat["funding"].shift(24)
    feat["close_max120"] = px.rolling(120).max()
    feat["cvd_med120"] = cvd.rolling(120).median()
    feat["close_min24_prev"] = px.shift(1).rolling(24).min()
    flow = feat["spot_delta"]
    thr = flow.rolling(720, min_periods=240).quantile(0.01)
    feat["flow_prev"] = flow.shift(1)
    feat["flow_p1_prev"] = thr.shift(1)
    feat["ret24"] = px / px.shift(24) - 1
    return feat


def struct_masks(feat):
    """返回 {名字: (触发mask, 方向, 输入齐备窗win)}，全部 fillna(False)。"""
    px = feat["close"]
    cvd = feat["spot_cvd_24h"]
    fr = feat["funding"]
    d = {}
    wc = cvd.notna()
    # sA
    w = wc & feat["resistance"].notna()
    m = (feat["high"] > feat["resistance"]) & (px < feat["resistance"]) & (cvd < 0)
    d["sA"] = (m & w, "S", w)
    # sB
    w = wc & feat["cvd24_lag12"].notna() & feat["support20"].notna()
    near = (px / feat["support20"] - 1 < 0.015) & (px > feat["support20"] * 0.995)
    m = (cvd < 0) & (cvd > feat["cvd24_lag12"]) & near
    d["sB"] = (m & w, "L", w)
    # sC
    w = wc & feat["cvd_med120"].notna() & feat["close_max120"].notna()
    m = (px >= feat["close_max120"]) & (cvd < feat["cvd_med120"])
    d["sC"] = (m & w, "S", w)
    # sD
    w = fr.notna() & feat["fr_p10_30d"].notna() & feat["spot_cvd_slope"].notna()
    m = (fr <= feat["fr_p10_30d"]) & (feat["spot_cvd_slope"] > 0)
    d["sD"] = (m & w, "L", w)
    # sE
    w = wc & feat["ma168"].notna() & feat["close_min24_prev"].notna()
    m = (px < feat["ma168"]) & (px / feat["close_min24_prev"] - 1 >= 0.015) & (cvd < 0)
    d["sE"] = (m & w, "S", w)
    # sF
    w = feat["flow_prev"].notna() & feat["flow_p1_prev"].notna()
    m = (feat["flow_prev"] < feat["flow_p1_prev"]) & (feat["low"] >= feat["low"].shift(1))
    d["sF"] = (m & w, "L", w)
    # sG
    w = fr.notna() & feat["fr_p85_30d"].notna() & feat["fr_lag24"].notna()
    m = (feat["ret24"] > 0.01) & (fr > feat["fr_p85_30d"]) & (fr > feat["fr_lag24"])
    d["sG"] = (m & w, "S", w)
    return {k: (mm.fillna(False), sd, ww.fillna(False)) for k, (mm, sd, ww) in d.items()}


def dedup24(times):
    kept, last = [], None
    for t in times:
        if last is None or (t - last) >= pd.Timedelta(hours=24):
            kept.append(t)
            last = t
    return pd.DatetimeIndex(kept)


# ----------------------------------------------------------------------
# 阶段一 · 事件级信息量
# ----------------------------------------------------------------------
def stage1_row(feat, mask, side, win, tag):
    px = feat["close"]
    fwd = {24: px.shift(-24) / px - 1, 72: px.shift(-72) / px - 1}
    ev = dedup24(feat.index[mask])
    row = {"结构": tag[0], "品种": tag[1], "方向": side, "n": len(ev)}
    segrow = {}
    for N in (24, 72):
        f = fwd[N]
        base = f[win].mean()
        e = f.reindex(ev).dropna()
        diff = e.mean() - base if len(e) else np.nan
        row[f"事件fwd{N}%"] = round(e.mean() * 100, 3) if len(e) else np.nan
        row[f"基线fwd{N}%"] = round(base * 100, 3)
        row[f"diff{N}pp"] = round(diff * 100, 3) if len(e) else np.nan
        if len(e) >= 3 and e.std() > 0:
            t = (e.mean() - base) / (e.std() / np.sqrt(len(e)))
            row[f"t_adj{N}"] = round(t / np.sqrt(N / 24), 2)
        else:
            row[f"t_adj{N}"] = np.nan
    for sn, s0, s1 in SEGS:
        a, b = pd.Timestamp(s0, tz="UTC"), pd.Timestamp(s1, tz="UTC")
        inseg = (feat.index >= a) & (feat.index < b)
        ei = ev[(ev >= a) & (ev < b)]
        e = fwd[24].reindex(ei).dropna()
        base = fwd[24][win & pd.Series(inseg, index=feat.index)].mean()
        segrow[sn] = (round((e.mean() - base) * 100, 3) if len(e) else np.nan, len(ei))
    for sn, (v, k) in segrow.items():
        row[f"{sn}diff24pp"] = v
        row[f"{sn}n"] = k
    return row


def judge_stage1(tab):
    """预注册淘汰线：BTC diff24 符号匹配且|.|>=0.25pp；ETH 同号；双 n>=8。"""
    verdicts = {}
    for s in STRUCT_NAMES:
        b = tab[(tab["结构"] == s) & (tab["品种"] == "BTC")].iloc[0]
        e = tab[(tab["结构"] == s) & (tab["品种"] == "ETH")].iloc[0]
        want = -1 if b["方向"] == "S" else 1
        reasons = []
        ok = True
        if b["n"] < 8 or e["n"] < 8:
            ok = False
            reasons.append(f"样本不足(BTC n={b['n']}, ETH n={e['n']})")
        else:
            db, de = b["diff24pp"], e["diff24pp"]
            if not (np.isfinite(db) and np.sign(db) == want):
                ok = False
                reasons.append(f"BTC diff24={db}pp 符号不符")
            elif abs(db) < 0.25:
                ok = False
                reasons.append(f"BTC |diff24|={abs(db)}pp <0.25pp 量级不足")
            if not (np.isfinite(de) and np.sign(de) == want):
                ok = False
                reasons.append(f"ETH diff24={de}pp 不同向")
        # 行情战术件标注：三段中符号正确的段数（主品种）
        segs_ok = [sn for sn, _, _ in SEGS
                   if np.isfinite(b[f"{sn}diff24pp"]) and np.sign(b[f"{sn}diff24pp"]) == want]
        tactical = ok and len(segs_ok) <= 1
        verdicts[s] = {"pass": ok, "tactical": tactical,
                       "segs_ok": ",".join(segs_ok) if segs_ok else "无",
                       "reason": "; ".join(reasons) if reasons else "通过"}
    return verdicts


# ----------------------------------------------------------------------
# 阶段二 · 整机串行（l1+t1 锁死）
# ----------------------------------------------------------------------
def sim(feat, mask, side):
    idx = feat.index
    n = len(feat)
    c, h, l = feat["close"].values, feat["high"].values, feat["low"].values
    m = mask.values
    S = side == "S"
    sgn = -1 if S else 1
    out = []
    i = 0
    while i < n - 2:
        if not m[i]:
            i += 1
            continue
        row = feat.iloc[i]
        entry = c[i]
        stop = l01_stop(row, "SHORT" if S else "LONG", entry)
        ok = stop is not None and (
            (stop > entry and stop / entry - 1 <= 0.05) if S
            else (stop < entry and 1 - stop / entry <= 0.05))
        if not ok:
            i += 1
            continue
        R = abs(entry - stop)
        tgt = entry + sgn * 1.5 * R
        pnl, xj, stopped = 0.0, None, False
        for j in range(i + 1, min(i + 73, n)):
            if (h[j] >= stop) if S else (l[j] <= stop):  # 同bar双触发止损优先
                pnl = sgn * (stop - entry) / entry - 2 * COST
                xj, stopped = j, True
                break
            if (l[j] <= tgt) if S else (h[j] >= tgt):
                pnl = sgn * (tgt - entry) / entry - 2 * COST
                xj = j
                break
        if xj is None:
            j = min(i + 72, n - 1)
            pnl = sgn * (c[j] - entry) / entry - 2 * COST
            xj = j
        out.append({"t": idx[i], "pnl": pnl * 100})
        i = xj + (6 if stopped else 1)
    return pd.DataFrame(out)


def stats(tr):
    if tr is None or len(tr) == 0:
        return {"n": 0, "net": 0.0, "wr": np.nan}
    return {"n": len(tr), "net": round(tr.pnl.sum(), 2),
            "wr": round((tr.pnl > 0).mean() * 100, 0)}


def seg_net(tr):
    parts = []
    for sn, s0, s1 in SEGS:
        a, b = pd.Timestamp(s0, tz="UTC"), pd.Timestamp(s1, tz="UTC")
        s = tr[(tr.t >= a) & (tr.t < b)] if len(tr) else tr
        parts.append(f"{sn}{s.pnl.sum():+.1f}({len(s)})" if len(s) else f"{sn}+0.0(0)")
    return " ".join(parts)


def gate_series(feat, s, side):
    if s == "sE":
        return feat["macd4h_hist"] < 0, "oD(4H MACD柱<0)"
    if side == "S":
        return feat["close"] < feat["ma168"], "o1(px<SMA168)"
    return feat["rsi4h"] > 50, "o4(4hRSI>50)"


def main():
    btc = prep(assemble("price_1h.jsonl", BTC_SUFS, "cg_funding.jsonl"))
    eth = prep(assemble("price_1h_eth.jsonl", ETH_SUFS, "cg_funding_eth.jsonl"))
    bw = btc.index[btc["spot_cvd_24h"].notna() & btc["funding"].notna()]
    mid = bw[0] + (bw[-1] - bw[0]) / 2
    print(f"BTC cvd+funding 窗口: {bw[0]} → {bw[-1]}  训练/样本外分界(对半): {mid}")
    ew = eth.index[eth["spot_cvd_24h"].notna() & eth["funding"].notna()]
    print(f"ETH 窗口: {ew[0]} → {ew[-1]}（整段零调整）\n")

    mb, me = struct_masks(btc), struct_masks(eth)

    # ---------- 阶段一 ----------
    print("=" * 120)
    print("阶段一 · 事件级信息量（24h去重；diff=事件均值-无条件基线；空希望负、多希望正）")
    rows = []
    for s in STRUCT_NAMES:
        for sym, feat, mk in (("BTC", btc, mb), ("ETH", eth, me)):
            m, side, w = mk[s]
            rows.append(stage1_row(feat, m, side, w, (s, sym)))
    tab = pd.DataFrame(rows)
    print(tab.to_string(index=False))
    tab.to_csv(os.path.join(OUT, "s_layer_stage1.csv"), index=False)

    verdicts = judge_stage1(tab)
    print("\n-- 阶段一判定（预注册淘汰线）--")
    for s, v in verdicts.items():
        tag = "幸存" if v["pass"] else "淘汰"
        if v["pass"] and v["tactical"]:
            tag += "(行情战术件)"
        print(f"{s} {STRUCT_NAMES[s]:10s} [{tag}] {v['reason']}  BTC段内成立: {v['segs_ok']}")

    survivors = [s for s, v in verdicts.items() if v["pass"]]
    if not survivors:
        print("\n阶段一全灭：7 个结构均未过淘汰线。这是合格结论，不进阶段二。")
        return

    # ---------- 阶段二 ----------
    print("\n" + "=" * 120)
    print("阶段二 · 整机（幸存者×2配置；l1+1.5R+72h+6h冷却+成本0.0007单边+>5%拒单）")
    rows2 = []
    for s in survivors:
        for cfg in ("裸跑", "门控"):
            recs = {"结构": f"{s} {STRUCT_NAMES[s]}", "配置": cfg}
            for sym, feat, mk in (("BTC", btc, mb), ("ETH", eth, me)):
                m, side, w = mk[s]
                if cfg == "门控":
                    g, gname = gate_series(feat, s, side)
                    m = (m & g).fillna(False)
                    recs["门控名"] = gname
                tr = sim(feat, m, side)
                if sym == "BTC":
                    a = tr[tr.t < mid] if len(tr) else tr
                    b = tr[tr.t >= mid] if len(tr) else tr
                    sa, sb = stats(a), stats(b)
                    recs.update({"B训n": sa["n"], "B训net": sa["net"], "B训wr": sa["wr"],
                                 "B外n": sb["n"], "B外net": sb["net"], "B外wr": sb["wr"],
                                 "训外同号": bool(sa["net"] > 0 and sb["net"] > 0),
                                 "B分段": seg_net(tr)})
                else:
                    se = stats(tr)
                    recs.update({"En": se["n"], "Enet": se["net"], "Ewr": se["wr"],
                                 "ETH同向": bool(se["net"] > 0), "E分段": seg_net(tr)})
            rows2.append(recs)
    tab2 = pd.DataFrame(rows2)
    print(tab2.to_string(index=False))
    tab2.to_csv(os.path.join(OUT, "s_layer_stage2.csv"), index=False)
    print(f"\n已保存 {os.path.join(OUT, 's_layer_stage1.csv')} / s_layer_stage2.csv")


if __name__ == "__main__":
    main()
