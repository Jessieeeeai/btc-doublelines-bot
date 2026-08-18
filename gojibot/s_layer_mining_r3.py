#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S层发掘·第三轮（订单流 + SMC市场结构×流确认）：python3 s_layer_mining_r3.py

轮次声明：这是 S 层第三轮预注册（首轮 7 结构全灭，二轮 5 结构 6 判定线全灭，
两轮累计 12 结构 0 生还——见 results/S层发掘报告.md 与 S层发掘报告-二轮.md）。
按 skill 阶段3：新一轮先预注册、报告注明轮次，轮次越多结论信用越低。
本轮机理来源切换：前两轮为纯价格几何/教程圈结构，本轮为
"主动成交流 vs 价格反应"（订单流 effort-vs-result）与"结构突破+流确认"（SMC+flow）。

代理粒度声明（测前锁定）：本数据集无 footprint/逐笔数据。
1h taker 净流（spot_delta，多粒度拼接摊薄）= 小时级 delta，
是 footprint 概念（bar内主动买卖差）的粗粒度代理。局限：
  ① bar 内吸收发生在价位档级（tick/level），1h 聚合抹掉档位信息，只剩
     "整根 bar 的净主动方向 vs 整根 bar 的价格位移"这一层 effort-vs-result；
  ② 拼接摊薄使粗粒度期（2h/4h/6h/12h 段）的小时流被均摊，p5/p95 极端事件
     系统性偏向 1h 细粒度覆盖段（同首轮 sF 已声明问题，如实报告不修）；
  ③ 现货 taker 流≠合约盘口挂单吸收，只是方向代理。
若本轮全灭，结论限定为"订单流概念在 1h 代理粒度上无信息"，不外推到 tick 级。

5 个预注册结构（口径测前锁定，一次解释，测完不加）：
  sM 卖压吸收多（absorption）：1h净流 < 其滚动30日p5 且 |close-open|/close ≤ 0.0015
     （重卖压但价格砸不动 = 被动买方吸收）→ 收盘做多。24h 去重。
     机理：主动卖单被限价买单吃掉而价不跌，effort(卖)与result(平)背离 → 卖压耗尽后回升。
     边界：首轮 sF 用 p1 极端 + 次bar不创新低确认（量级不足死）；sM 是同 bar
     "努力vs结果"背离，p5 门槛+实体门槛，不同构。风险如实声明：支撑侧/恐慌侧
     接多已四连死（对称多单、清算潮反转、sB、sF），sM 是逆势接多家族第五次尝试。
  sN 买压出货空（sM 镜像）：1h净流 > 其滚动30日p95 且 |close-open|/close ≤ 0.0015
     （重买压但价格拉不动 = 被动卖方出货）→ 收盘做空。24h 去重。
     sM/sN 为镜像家族自检：若仅单侧成立需解释不对称性，双侧同死=家族级否定。
  sO 叠单顺delta空（stacked imbalance 代理）：连续3根1h净流均 < 各自滚动30日p20
     且 close < 3根前close → 收盘做空。12h 去重。
     机理：持续压倒性主动卖流+价格配合下行 = 卖方主导确认，顺 delta 而非逆接。
     边界：二轮 sK 价格顺势（唐奇安）近零死；delta 顺势未测过，此为首个纯 delta 顺势件。
  sP BOS顺势多+流确认（SMC break of structure）：
     4H swing high pivot = 已完成 4H 高点 高于其前2根与后2根 4H 高点（严格>，
     确认滞后 2 根 4H，无前视）；1h close 首次突破最近已确认 swing high
     且 CVD24h > 0 → 收盘做多。同一 pivot 只用一次。
     机理：结构性高点被收盘突破且现货净流为正 = 真实需求推动的结构转换而非扫荡。
     边界：二轮 sK 唐奇安20日（水平线、无结构确认）近零死；sP 是数日级
     swing 结构 + 流门控，且 pivot 一次性（不重复追高）。
  sQ CHoCH转势空+流确认（SMC change of character，sP 的结构镜像）：
     swing low pivot 定义同上镜像（低于前2/后2根 4H 低点，滞后2根确认）；
     最近 3 个已确认 swing low 构成严格抬高序列（higher lows，上升结构成立）；
     1h close 首次跌破最近已确认 higher-low pivot 且 CVD24h < 0 → 收盘做空。
     同一 pivot 只用一次。sP/sQ 构成结构家族自检。
     机理：上升结构的最后一个 higher-low 被收盘跌破且流为负 = 结构性转势。

口径声明（阶段2.5，固定单一解释，不做多口径扫描）：
  - 主分析窗 = 前两轮窗口 W0=2025-07-08 起（=CVD/flow 窗起点），三段表/训外分界一致。
  - 流阈值：spot_delta.rolling(720, min_periods=240).quantile(q).shift(1)
    （q=0.05/0.20/0.95；shift(1) 保证阈值只用过去 bar，无前视；约10日热身）。
  - 实体门槛：|close-open|/close ≤ 0.0015（对应 BTC 1h 实体约 ≤0.15%，"砸不动/拉不动"）。
  - sO：三根 bar 各自与自身 bar 处的 p20 阈值比较（u & u.shift(1) & u.shift(2)），
    且 close < close.shift(3)；12h 去重（事件密度高于 sM/sN，预注册取 12h）。
  - pivot：4H high/low 由 1h resample("4h") max/min；pivot k 须严格高于(低于)
    k±1、k±2 四根；可用时刻 avail = 4H bar k+2 的收盘时刻（t4[k]+12h）；
    1h bar（时戳=bar起点）在 bar 起点 ≥ avail 时才可见该 pivot（保守再让 1h）。
  - "最近已确认 pivot"：avail 已到的 pivot 中 4H 时间最新者；新 pivot 可用即替换旧者
    （旧 pivot 未破也不再是"最近"，不回头用）。
  - "首次突破/跌破"：当前最近 pivot 的第一根收盘越线 bar 即消耗该 pivot
    （无论流门控是否通过——突破事实已发生，二次越线不再是"首次"）；
    事件成立还需流门控（sP: CVD24h>0；sQ: CVD24h<0）与 sQ 的 HL 结构条件。
  - sQ HL 结构："近5根已完成4H低点构成 higher-low 序列"固定解释为：
    破位时刻已确认的最近 3 个 swing low pivot 价格严格递增（含被破的最新者）。
  - 事件去重：sM/sN 24h；sO 12h；sP/sQ 每 pivot 一次（无叠加时间去重，天然稀疏）。
  - fwdN / 基线 / t_adj / 三段（上行 2025-08-03→11-01，崩盘 →2026-01-07，
    下跌 →2026-07-01）全部沿用前两轮口径；win = 各结构输入齐备窗；
    热身段（阈值/pivot 未就绪）事件计入总计、不落三段（同前两轮处理）。
  - t_adj = [(事件均值-基线)/(事件std/√n)] / √(N/24)。

阶段一淘汰线（预注册，量级线沿用二轮残值5确立的 0.40pp 永久默认）：
  - BTC fwd24 diff 符号与方向一致 且 |diff24| ≥ 0.40pp；ETH fwd24 diff 同号；
    双品种去重事件各 ≥8（不足=无法判定，按零信息处理）；
  - 只在单一行情段成立 → 标"行情战术件"；阶段一全灭 = 合格结论。

阶段二（只对幸存者；执行腿锁死=现役 l1+t1，与前两轮完全一致）：
  L01(含1D升级) / TP=1.5R / 72h超时 / 成本单边0.0007 / 止损后6h冷却 /
  同bar双触发止损优先 / 止损距离>5%拒单 / 信号bar收盘入场
  每幸存者两配置（预声明，不加第三个）：
    ① 裸跑  ② 机理门控：空配 o1(px<SMA168)，多配 o4(4hRSI14 Wilder>50)。本轮无例外件。
  BTC 训练/样本外 = cvd+funding 齐备窗时间对半（同前两轮 mid）；ETH 整段零调整。
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

W0 = pd.Timestamp("2025-07-08", tz="UTC")  # 主分析窗起点（=前两轮）

SEGS = [("上行", "2025-08-03", "2025-11-01"),
        ("崩盘", "2025-11-01", "2026-01-07"),
        ("下跌", "2026-01-07", "2026-07-01")]

STRUCT_NAMES = {
    "sM": "卖压吸收多", "sN": "买压出货空", "sO": "叠单顺delta空",
    "sP": "BOS顺势多+流", "sQ": "CHoCH转势空+流",
}

BODY_MAX = 0.0015


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
    flow = feat["spot_delta"]
    feat["flow_p5"] = flow.rolling(720, min_periods=240).quantile(0.05).shift(1)
    feat["flow_p20"] = flow.rolling(720, min_periods=240).quantile(0.20).shift(1)
    feat["flow_p95"] = flow.rolling(720, min_periods=240).quantile(0.95).shift(1)
    feat["body"] = (feat["close"] - feat["open"]).abs() / feat["close"]
    return feat


def pivots_4h(feat, kind):
    """严格 2-2 pivot；返回 [(avail_time, pivot_time, price)]，按时间序。"""
    if kind == "H":
        s4 = feat["high"].resample("4h").max()
    else:
        s4 = feat["low"].resample("4h").min()
    v, idx = s4.values, s4.index
    out = []
    for k in range(2, len(v) - 2):
        w = v[k - 2:k + 3]
        if not np.isfinite(w).all():
            continue
        if kind == "H":
            ok = v[k] > v[k - 1] and v[k] > v[k - 2] and v[k] > v[k + 1] and v[k] > v[k + 2]
        else:
            ok = v[k] < v[k - 1] and v[k] < v[k - 2] and v[k] < v[k + 1] and v[k] < v[k + 2]
        if ok:
            out.append((idx[k + 2] + pd.Timedelta(hours=4), idx[k], v[k]))
    return out


def sp_mask(feat):
    """sP：1h close 首破最近已确认 swing high 且 CVD24h>0；每 pivot 一次。"""
    piv = pivots_4h(feat, "H")
    cl = feat["close"].values
    cvd = feat["spot_cvd_24h"].values
    idx = feat.index
    mask = np.zeros(len(feat), dtype=bool)
    pi = 0
    cur_price, consumed = None, True
    for i, t in enumerate(idx):
        while pi < len(piv) and piv[pi][0] <= t:
            cur_price, consumed = piv[pi][2], False
            pi += 1
        if not consumed and np.isfinite(cl[i]) and cl[i] > cur_price:
            consumed = True  # 首破即消耗，无论门控
            if np.isfinite(cvd[i]) and cvd[i] > 0:
                mask[i] = True
    return pd.Series(mask, index=idx)


def sq_mask(feat):
    """sQ：最近3个已确认 swing low 严格抬高；1h close 首破最新者 且 CVD24h<0；每 pivot 一次。"""
    piv = pivots_4h(feat, "L")
    cl = feat["close"].values
    cvd = feat["spot_cvd_24h"].values
    idx = feat.index
    mask = np.zeros(len(feat), dtype=bool)
    pi = 0
    hist = []  # 已可用 pivot 价格（时间序）
    consumed = True
    for i, t in enumerate(idx):
        while pi < len(piv) and piv[pi][0] <= t:
            hist.append(piv[pi][2])
            consumed = False
            pi += 1
        if not consumed and hist and np.isfinite(cl[i]) and cl[i] < hist[-1]:
            consumed = True  # 首破即消耗，无论门控
            hl = len(hist) >= 3 and hist[-3] < hist[-2] < hist[-1]
            if hl and np.isfinite(cvd[i]) and cvd[i] < 0:
                mask[i] = True
    return pd.Series(mask, index=idx)


def struct_masks(feat):
    """返回 {名字: (触发mask, 方向, 输入齐备窗win)}，全部 fillna(False)。"""
    px = feat["close"]
    flow = feat["spot_delta"]
    cvd = feat["spot_cvd_24h"]
    d = {}
    # sM / sN：吸收/出货（effort vs result 背离）
    wMN = flow.notna() & feat["flow_p5"].notna() & feat["body"].notna()
    d["sM"] = ((flow < feat["flow_p5"]) & (feat["body"] <= BODY_MAX) & wMN, "L", wMN)
    d["sN"] = ((flow > feat["flow_p95"]) & (feat["body"] <= BODY_MAX) & wMN, "S", wMN)
    # sO：叠单顺 delta 空
    u = (flow < feat["flow_p20"])
    wO = flow.notna() & feat["flow_p20"].notna() & flow.shift(2).notna() & feat["flow_p20"].shift(2).notna()
    mO = u & u.shift(1) & u.shift(2) & (px < px.shift(3))
    d["sO"] = ((mO & wO).fillna(False), "S", wO)
    # sP / sQ：结构突破 + 流确认
    wPQ = cvd.notna()
    d["sP"] = ((sp_mask(feat) & wPQ).fillna(False), "L", wPQ)
    d["sQ"] = ((sq_mask(feat) & wPQ).fillna(False), "S", wPQ)
    return {k: (mm.fillna(False), sd, ww.fillna(False)) for k, (mm, sd, ww) in d.items()}


def dedup_h(times, hours):
    kept, last = [], None
    for t in times:
        if last is None or (t - last) >= pd.Timedelta(hours=hours):
            kept.append(t)
            last = t
    return pd.DatetimeIndex(kept)


def events_of(s, feat, mask):
    """阶段一事件序列：sM/sN 24h 去重；sO 12h；sP/sQ 每 pivot 一次（mask 已是）。"""
    t = feat.index[mask]
    if s in ("sP", "sQ"):
        return pd.DatetimeIndex(t)
    return dedup_h(t, 12 if s == "sO" else 24)


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
# 阶段二（同前两轮，逐字复用）
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
    if side == "S":
        return feat["close"] < feat["ma168"], "o1(px<SMA168)"
    return feat["rsi4h"] > 50, "o4(4hRSI>50)"


def main():
    btc = prep(assemble("price_1h.jsonl", BTC_SUFS, "cg_funding.jsonl")).loc[W0:]
    eth = prep(assemble("price_1h_eth.jsonl", ETH_SUFS, "cg_funding_eth.jsonl")).loc[W0:]
    bw = btc.index[btc["spot_cvd_24h"].notna() & btc["funding"].notna()]
    mid = bw[0] + (bw[-1] - bw[0]) / 2
    print(f"主窗(=前两轮): {W0} 起；BTC cvd+funding 窗: {bw[0]} → {bw[-1]}  训/外分界: {mid}")
    ew = eth.index[eth["spot_cvd_24h"].notna() & eth["funding"].notna()]
    print(f"ETH 窗口: {ew[0]} → {ew[-1]}（整段零调整）\n")

    mb, me = struct_masks(btc), struct_masks(eth)

    # ---------- 阶段一 ----------
    print("=" * 120)
    print("阶段一 · 事件级信息量（第三轮·订单流/SMC+流；量级线 0.40pp；diff=事件均值-无条件基线）")
    rows = []
    for s in STRUCT_NAMES:
        for sym, feat, mk in (("BTC", btc, mb), ("ETH", eth, me)):
            m, side, w = mk[s]
            ev = events_of(s, feat, m)
            rows.append(stage1_row(feat, ev, side, w, (s, sym)))
    tab = pd.DataFrame(rows)
    print(tab.to_string(index=False))
    tab.to_csv(os.path.join(OUT, "s_layer_r3_stage1.csv"), index=False)

    verdicts = judge_stage1(tab)
    print("\n-- 阶段一判定（预注册淘汰线 0.40pp）--")
    for s, v in verdicts.items():
        tag = "幸存" if v["pass"] else "淘汰"
        if v["pass"] and v["tactical"]:
            tag += "(行情战术件)"
        print(f"{s} {STRUCT_NAMES[s]:12s} [{tag}] {v['reason']}  BTC段内成立: {v['segs_ok']}")

    survivors = [s for s, v in verdicts.items() if v["pass"]]
    if not survivors:
        print("\n阶段一全灭：5 个结构均未过淘汰线。这是合格结论，不进阶段二。")
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
    tab2.to_csv(os.path.join(OUT, "s_layer_r3_stage2.csv"), index=False)
    print(f"\n已保存 {os.path.join(OUT, 's_layer_r3_stage1.csv')} / s_layer_r3_stage2.csv")


if __name__ == "__main__":
    main()
