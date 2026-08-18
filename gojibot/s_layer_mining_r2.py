#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S层发掘·第二轮（教程圈结构：ICT/SMC/经典技术分析）：python3 s_layer_mining_r2.py

轮次声明：这是 S 层第二轮预注册（首轮 7 结构全灭，见 results/S层发掘报告.md）。
按 skill 阶段3：新一轮先预注册、报告注明轮次，轮次越多结论信用越低。

5 个预注册结构（sH 拆多空两行判定，共 6 条判定线；口径测前锁定，一次解释，测完不加）：
  sH 亚洲区间清扫反转（ICT流动性清扫，双向）
  sI 供给区回测空（SMC订单块）
  sJ 看跌FVG回补空（ICT缺口）
  sK 唐奇安20日突破多（海龟；体系首个纯顺势结构，兼首轮 sG 残值落地测试）
  sL 4H RSI顶背离空（经典背离；与首轮 sC 构成背离家族——同死则家族立碑）

口径声明（阶段2.5，固定单一解释，不做多口径扫描）：
  - 主分析窗 = 首轮窗口（2025-07-08 → 2026-07-01），保证三段表/训外分界/墓地对比口径一致。
    价格数据实际起 2024-07-02；纯价格结构(sH/sJ/sK/sL)另报"扩窗参考"列
    （2024-07 起全价格窗 diff24，含 2024-2025 牛市段），仅供参考、不参与判定——
    此决定在跑数前写入本 docstring（预注册），非事后加窗。
  - sH：亚洲区间 = 当日 UTC bar 0:00-7:00（8根1h，须满8根才定义区间）的 high max / low min；
    触发窗 = 当日 bar 时戳 hour∈[8,16)（8:00-15:59 收盘评估）；
    多：bar low<区间low 且 close>区间low；空：bar high>区间high 且 close<区间high；
    每日每方向只取当日首次。区间 8:00 后才可用，无前视。
  - sI：检测 bar t：close[t]/close[t-4]-1 ≤ -0.02 且 CVD24h[t]<0；
    起点bar 候选A=下冲前最后一根阳线（t-4 起向前扫至 t-9，close>open 首个；无则取 t-4），
    候选B=下冲段(t-3..t)内第一根阴线（close<open；无则取 t-3）；取二者 high 更高者；
    供给区=[该bar open, 该bar high]（open 为下沿）；
    触发：t 后 48h 内首次 bar high≥区下沿 且 close<区下沿 → 收盘空。每区只用一次；
    检测节流：距上次接受的检测 <4h（冲量窗长）不再立新区（防单次下跌级联立区）。
  - sJ：连续3根1h bar1..bar3，bar1.low > bar3.high → 看跌FVG，缺口区=[bar3.high, bar1.low]；
    bar3 后 24h 内首次 bar high > bar3.high（进入缺口区）→ 收盘空。每缺口只用一次。
  - sK：thr = 前20根已完成 1D close 最大值（1D close shift(1) rolling20 max，ffill 到 1h）；
    1h close > thr → 收盘多。阶段一 24h 去重；阶段二串行持仓自然互斥（持仓期不重复触发）。
  - sL：4H close 序列 c4 与 Wilder RSI14；已完成 4H bar k：c4[k] ≥ max(c4[k-29..k])（30根窗含自身最高）
    且 RSI[k] < RSI[j]，j = argmax(c4[k-29..k-1])（次高峰=窗内除当前外 close 最高 bar，固定此解释）；
    信号在该 4H 完结后的下一个 1h bar（时戳=4H起点+4h）收盘入场（与体系 shift(1) 惯例一致）；24h 去重。
  - 事件去重：sH 每日每向首次（预注册规则，不再叠 24h）；sI/sJ 触发事件 + 24h 去重；sK/sL 24h 去重。
  - fwdN / 基线 / t_adj / 三段（上行 2025-08-03→11-01，崩盘 →2026-01-07，下跌 →2026-07-01）
    全部沿用首轮口径；纯价格结构主窗 2025-07-08 起，其 07-08→08-03 事件计入总计/训练、不落三段
    （同首轮热身段处理）；sI 有效窗=CVD 窗。
  - t_adj = [(事件均值-基线)/(事件std/√n)] / √(N/24)。

阶段一淘汰线（预注册，量级线按首轮残值5提至 0.4pp）：
  - BTC fwd24 diff 符号与方向一致 且 |diff24| ≥ 0.40pp；ETH fwd24 diff 同号；
    双品种去重事件各 ≥8（不足=无法判定，按零信息处理）；
  - 只在单一行情段成立 → 标"行情战术件"；阶段一全灭 = 合格结论。

阶段二（只对幸存者；执行腿锁死=现役 l1+t1，与首轮完全一致）：
  L01(含1D升级) / TP=1.5R / 72h超时 / 成本单边0.0007 / 止损后6h冷却 /
  同bar双触发止损优先 / 止损距离>5%拒单 / 信号bar收盘入场
  每幸存者两配置（预声明）：① 裸跑 ② 机理门控：空配 o1(px<SMA168)，多配 o4(4hRSI14>50)；
  sK 例外——顺势多与 o4 高度共线，② 改配 fr_up(FR>24h前FR)（首轮 sG 残值直接检验；
  该门控有效窗从费率窗 2025-08-03 起）。
  BTC 训练/样本外 = cvd+funding 齐备窗时间对半（同首轮 mid）；ETH 整段零调整。
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

W0 = pd.Timestamp("2025-07-08", tz="UTC")  # 主分析窗起点（=首轮 CVD 窗起）

SEGS = [("上行", "2025-08-03", "2025-11-01"),
        ("崩盘", "2025-11-01", "2026-01-07"),
        ("下跌", "2026-01-07", "2026-07-01")]

STRUCT_NAMES = {
    "sH_L": "亚洲区间清扫·多", "sH_S": "亚洲区间清扫·空",
    "sI": "供给区回测空", "sJ": "看跌FVG回补空",
    "sK": "唐奇安20日突破多", "sL": "4H RSI顶背离空",
}
PRICE_ONLY = {"sH_L", "sH_S", "sJ", "sK", "sL"}  # 扩窗参考列适用


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
    # sH 亚洲区间（当日 0-7 点 8 根，满 8 根才定义）
    day = feat.index.normalize()
    hrs = feat.index.hour
    asia = pd.Series(hrs < 8, index=feat.index)
    ah = feat["high"].where(asia).groupby(day).max()
    al = feat["low"].where(asia).groupby(day).min()
    cnt = asia.groupby(day).sum()
    ah, al = ah.where(cnt == 8), al.where(cnt == 8)
    dser = pd.Series(day, index=feat.index)
    feat["asia_high"] = dser.map(ah)
    feat["asia_low"] = dser.map(al)
    feat["insess"] = (hrs >= 8) & (hrs < 16)
    # sK 唐奇安
    d1c = px.resample("1D").last()
    feat["don20"] = d1c.shift(1).rolling(20).max().reindex(feat.index, method="ffill")
    # sK 门控：FR 较 24h 前上升
    feat["fr_lag24"] = feat["funding"].shift(24)
    return feat


def first_per_day(m):
    g = m.groupby(m.index.normalize()).cumsum()
    return m & (g == 1)


def si_trigger_mask(feat):
    """sI 供给区回测空：返回触发 mask。"""
    px, op, hi, cl = feat["close"].values, feat["open"].values, feat["high"].values, feat["close"].values
    opn = feat["open"].values
    cvd = feat["spot_cvd_24h"].values
    ret4 = feat["close"] / feat["close"].shift(4) - 1
    det = (ret4.values <= -0.02) & (cvd < 0)
    n = len(feat)
    mask = np.zeros(n, dtype=bool)
    last_det = -10**9
    for t in range(9, n):
        if not det[t] or t - last_det < 4:
            continue
        last_det = t
        # 候选A：t-4 起向前扫至 t-9 首根阳线；无则 t-4
        a = t - 4
        for j in range(t - 4, t - 10, -1):
            if cl[j] > opn[j]:
                a = j
                break
        # 候选B：t-3..t 首根阴线；无则 t-3
        b = t - 3
        for j in range(t - 3, t + 1):
            if cl[j] < opn[j]:
                b = j
                break
        k = a if hi[a] >= hi[b] else b
        zlow = opn[k]
        # 48h 内首次 high≥zlow 且 close<zlow
        for j in range(t + 1, min(t + 49, n)):
            if hi[j] >= zlow and cl[j] < zlow:
                mask[j] = True
                break
    return pd.Series(mask, index=feat.index)


def sj_trigger_mask(feat):
    """sJ 看跌FVG回补空：bar1.low>bar3.high；24h 内首次 high>bar3.high。"""
    hi, lo = feat["high"].values, feat["low"].values
    n = len(feat)
    mask = np.zeros(n, dtype=bool)
    for i in range(2, n):
        if not (np.isfinite(lo[i - 2]) and np.isfinite(hi[i])) or lo[i - 2] <= hi[i]:
            continue
        zbot = hi[i]
        for j in range(i + 1, min(i + 25, n)):
            if hi[j] > zbot:
                mask[j] = True
                break
    return pd.Series(mask, index=feat.index)


def sl_event_mask(feat):
    """sL 4H RSI顶背离：事件映射到 4H 完结后下一个 1h bar。"""
    c4 = feat["close"].resample("4h").last()
    r4 = wilder_rsi(c4)
    c = c4.values
    r = r4.values
    n = len(c)
    ev = []
    for k in range(29, n):
        if not np.isfinite(c[k]):
            continue
        w = c[k - 29:k]
        if not np.isfinite(w).any():
            continue
        if c[k] < np.nanmax(w):
            continue  # 当前须为 30 根窗最高
        j = k - 29 + int(np.nanargmax(w))
        if np.isfinite(r[k]) and np.isfinite(r[j]) and r[k] < r[j]:
            ev.append(c4.index[k] + pd.Timedelta(hours=4))
    m = pd.Series(False, index=feat.index)
    hit = [t for t in ev if t in m.index]
    m.loc[hit] = True
    return m


def struct_masks(feat):
    """返回 {名字: (触发mask, 方向, 输入齐备窗win)}，全部 fillna(False)。主窗裁剪在外层。"""
    px = feat["close"]
    d = {}
    wA = feat["asia_low"].notna()
    mL = feat["insess"] & (feat["low"] < feat["asia_low"]) & (px > feat["asia_low"])
    mS = feat["insess"] & (feat["high"] > feat["asia_high"]) & (px < feat["asia_high"])
    d["sH_L"] = (first_per_day(mL.fillna(False)), "L", wA)
    d["sH_S"] = (first_per_day(mS.fillna(False)), "S", wA)
    wI = feat["spot_cvd_24h"].notna()
    d["sI"] = (si_trigger_mask(feat) & wI, "S", wI)
    wJ = px.notna()
    d["sJ"] = (sj_trigger_mask(feat), "S", wJ)
    wK = feat["don20"].notna()
    d["sK"] = ((px > feat["don20"]).fillna(False) & wK, "L", wK)
    wL = px.notna()
    d["sL"] = (sl_event_mask(feat), "S", wL)
    return {k: (mm.fillna(False), sd, ww.fillna(False)) for k, (mm, sd, ww) in d.items()}


def dedup24(times):
    kept, last = [], None
    for t in times:
        if last is None or (t - last) >= pd.Timedelta(hours=24):
            kept.append(t)
            last = t
    return pd.DatetimeIndex(kept)


def events_of(s, feat, mask):
    """阶段一事件序列：sH 每日每向首次（mask 已是），其余 24h 去重。"""
    t = feat.index[mask]
    if s.startswith("sH"):
        return pd.DatetimeIndex(t)
    return dedup24(t)


# ----------------------------------------------------------------------
# 阶段一
# ----------------------------------------------------------------------
def stage1_row(feat, ev, side, win, tag):
    px = feat["close"]
    fwd = {24: px.shift(-24) / px - 1, 72: px.shift(-72) / px - 1}
    row = {"结构": tag[0], "品种": tag[1], "方向": side, "n": len(ev)}
    for N in (24, 72):
        f = fwd[N]
        base = f[win].mean()
        e = f.reindex(ev).dropna()
        row[f"事件fwd{N}%"] = round(e.mean() * 100, 3) if len(e) else np.nan
        row[f"基线fwd{N}%"] = round(base * 100, 3)
        row[f"diff{N}pp"] = round((e.mean() - base) * 100, 3) if len(e) else np.nan
        if len(e) >= 3 and e.std() > 0:
            t = (e.mean() - base) / (e.std() / np.sqrt(len(e)))
            row[f"t_adj{N}"] = round(t / np.sqrt(N / 24), 2)
        else:
            row[f"t_adj{N}"] = np.nan
    for sn, s0, s1 in SEGS:
        a, b = pd.Timestamp(s0, tz="UTC"), pd.Timestamp(s1, tz="UTC")
        inseg = pd.Series((feat.index >= a) & (feat.index < b), index=feat.index)
        ei = ev[(ev >= a) & (ev < b)]
        e = fwd[24].reindex(ei).dropna()
        base = fwd[24][win & inseg].mean()
        row[f"{sn}diff24pp"] = round((e.mean() - base) * 100, 3) if len(e) else np.nan
        row[f"{sn}n"] = len(ei)
    return row


def judge_stage1(tab):
    """预注册淘汰线：BTC diff24 符号匹配且|.|≥0.40pp；ETH 同号；双 n≥8。"""
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
            elif abs(db) < 0.40:
                ok = False
                reasons.append(f"BTC |diff24|={abs(db)}pp <0.40pp 量级不足")
            if not (np.isfinite(de) and np.sign(de) == want):
                ok = False
                reasons.append(f"ETH diff24={de}pp 不同向")
        segs_ok = [sn for sn, _, _ in SEGS
                   if np.isfinite(b[f"{sn}diff24pp"]) and np.sign(b[f"{sn}diff24pp"]) == want]
        tactical = ok and len(segs_ok) <= 1
        verdicts[s] = {"pass": ok, "tactical": tactical,
                       "segs_ok": ",".join(segs_ok) if segs_ok else "无",
                       "reason": "; ".join(reasons) if reasons else "通过"}
    return verdicts


# ----------------------------------------------------------------------
# 阶段二（同首轮，逐字复用）
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
            if (h[j] >= stop) if S else (l[j] <= stop):
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
    if s == "sK":
        return (feat["funding"] > feat["fr_lag24"]), "fr_up(FR>24h前)"
    if side == "S":
        return feat["close"] < feat["ma168"], "o1(px<SMA168)"
    return feat["rsi4h"] > 50, "o4(4hRSI>50)"


def main():
    btc_full = prep(assemble("price_1h.jsonl", BTC_SUFS, "cg_funding.jsonl"))
    eth_full = prep(assemble("price_1h_eth.jsonl", ETH_SUFS, "cg_funding_eth.jsonl"))
    print(f"BTC 价格全窗: {btc_full.index[0]} → {btc_full.index[-1]}")
    print(f"ETH 价格全窗: {eth_full.index[0]} → {eth_full.index[-1]}")
    btc, eth = btc_full.loc[W0:], eth_full.loc[W0:]
    bw = btc.index[btc["spot_cvd_24h"].notna() & btc["funding"].notna()]
    mid = bw[0] + (bw[-1] - bw[0]) / 2
    print(f"主窗(=首轮): {W0} 起；BTC cvd+funding 窗: {bw[0]} → {bw[-1]}  训/外分界: {mid}\n")

    mb, me = struct_masks(btc), struct_masks(eth)
    mbf, mef = struct_masks(btc_full), struct_masks(eth_full)

    # ---------- 阶段一 ----------
    print("=" * 120)
    print("阶段一 · 事件级信息量（第二轮；量级线 0.40pp；diff=事件均值-无条件基线）")
    rows = []
    for s in STRUCT_NAMES:
        for sym, feat, featf, mk, mkf in (("BTC", btc, btc_full, mb, mbf),
                                          ("ETH", eth, eth_full, me, mef)):
            m, side, w = mk[s]
            ev = events_of(s, feat, m)
            row = stage1_row(feat, ev, side, w, (s, sym))
            if s in PRICE_ONLY:  # 扩窗参考（2024-07 起，仅参考不判定）
                mf, _, wf = mkf[s]
                evf = events_of(s, featf, mf)
                px = featf["close"]
                f24 = px.shift(-24) / px - 1
                e = f24.reindex(evf).dropna()
                base = f24[wf].mean()
                row["扩窗diff24pp"] = round((e.mean() - base) * 100, 3) if len(e) else np.nan
                row["扩窗n"] = len(evf)
            else:
                row["扩窗diff24pp"], row["扩窗n"] = np.nan, 0
            rows.append(row)
    tab = pd.DataFrame(rows)
    print(tab.to_string(index=False))
    tab.to_csv(os.path.join(OUT, "s_layer_r2_stage1.csv"), index=False)

    verdicts = judge_stage1(tab)
    print("\n-- 阶段一判定（预注册淘汰线 0.40pp）--")
    for s, v in verdicts.items():
        tag = "幸存" if v["pass"] else "淘汰"
        if v["pass"] and v["tactical"]:
            tag += "(行情战术件)"
        print(f"{s} {STRUCT_NAMES[s]:12s} [{tag}] {v['reason']}  BTC段内成立: {v['segs_ok']}")

    survivors = [s for s, v in verdicts.items() if v["pass"]]
    if not survivors:
        print("\n阶段一全灭：6 条判定线均未过。这是合格结论，不进阶段二。")
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
    tab2.to_csv(os.path.join(OUT, "s_layer_r2_stage2.csv"), index=False)
    print(f"\n已保存 {os.path.join(OUT, 's_layer_r2_stage1.csv')} / s_layer_r2_stage2.csv")


if __name__ == "__main__":
    main()
