#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S层发掘·第四轮（YouTube"投机实验室"Top10 盘点提炼的 5 个机械化结构）：
python3 s_layer_mining_r4.py

轮次声明：这是 S 层第四轮预注册。前三轮 17 结构（19 判定线）0 生还
（results/S层发掘报告.md / -二轮.md / -三轮.md）。按 skill 阶段3：轮次越多
结论信用越低——本轮任何"幸存"按第四轮折价解读。
尺度声明：本轮 sS/sT/sU 为**日线尺度**结构（1D bar 由 1h 聚合，UTC 0 点为界，
只用已完成日线）。前三轮"突破/跌破类在 1h-4H 尺度关闭"的墓地结论**不覆盖
日线尺度**，故 sS（周线级旗形）不属墓地复用；sV 是幸存现役 s2 的家族变体
（允许测试）；sW 与已死 sP 的区别=回调区入场而非破位入场。

数据与成交量代理声明：无真实成交量。量能代理 = 现货 taker_buy+taker_sell
（CoinGlass，1h/2h/4h/6h/12h 多粒度拼接，粗粒度先 shift(1) 再摊薄 =
**零前视口径**，v1.2 规矩）。粗粒度期的小时量被均摊，"单bar天量"事件系统性
偏向 1h 细粒度覆盖段（同 sF/sM 声明，如实报告不修）。

5 个预注册结构（口径测前锁定，一次解释，测完不加）：
  sS 旗形突破多（Qullamaggie）：日线状态机，逐日重估。上涨腿=20 个 1D 窗口
     close[末]/close[首]-1 ≥ 30%，腿须整体落在过去 90 个 1D 内（整理长度 L≤70）；
     腿高点=腿窗口内最高 high。整理=腿结束后紧接的 L 个 1D（10≤L≤70）：
     ①整理期 max(high) ≤ 腿高点×1.02；②低点抬高：前⌈L/2⌉日 min(low) ≤
     后⌊L/2⌋日 min(low)；③收窄：末 5 个 1D 的高低幅 < 其前 10 个 1D 的高低幅
     （前 10 日可伸入腿末，固定解释）。多个 L 同时合格取最长 L（突破位更保守）。
     armed 后次日内 1h close > 整理区间高点 → 收盘做多。
     "每个旗形只触发一次"实现口径：触发后 480h（20 日）锁定，期间不重触发。
  sT 外包线反转（Larry Williams，双向拆两判定线=家族自检）：日线 d 满足
     high>前日high 且 low<前日low 且 |实体|≥前日|实体|×2（前日实体>0）：
     · 多：close[d] < 前日 low → 次日 UTC0 点第一根 1h bar 为事件 bar（=次日
       开盘做多的收盘价近似，预声明）；止损=外包线 low[d]。
     · 空：close[d] > 前日 high → 同上做空；止损=外包线 high[d]。无额外去重。
  sU 抛物线首阴空（Alex Temiz）：抛物线日 d = 连续≥3 个 1D 阳线（close>open）
     且 close[d]/close[d-3]-1 ≥ 10% 且日涨幅递增 r[d]>r[d-1]>r[d-2]。
     连续抛物线日构成一段（run）。段内自首个抛物线日的次日起，第一根
     1h close < 前一已完成 1D close（参考价逐日滚动）→ 收盘做空；
     每段只触发一次；触发窗=末个抛物线日后 3 个自然日内，过期作废。
     止损=被跌破参考价那个 1D 的 high。
  sV s2 天量加速变体（Flight）：现役 s2（S20）条件 CVD24h<滚动30日p15(shift1)
     + 4hRSI14(Wilder)>50，把"6h净流>0"替换为"过去 24 根 1h 内出现单bar量能
     （零前视口径）> 滚动30日p97(shift1)" → 收盘做多。24h 去重。止损=L01。
  sW OTE 顺势回调多（Mayne）：4H swing high/low pivot 口径逐字同三轮 sP
     （严格 2-2、滞后 2 根 4H 确认、无前视、首破即消耗）。1h close 首破最近
     已确认 swing high（无流门控）→ 结构成立，要求彼时最近已确认 swing low
     存在且低于突破收盘价（=突破起点低点）。此后 40 根 1h（=10 个 4H）内：
     突破后高点=自突破 bar 起 high 滚动最大值（先更新后判定）；斐波区=
     [高点-0.79×(高点-起点低点), 高点-0.62×(高点-起点低点)]；1h close 落区内
     且 close>open → 收盘做多，每结构一次；close<起点低点=结构失效；
     突破 bar 当根不判定。止损=触发时斐波区下沿×0.997。无额外时间去重。

口径声明（阶段2.5，固定单一解释，不做多口径扫描）：
  - 1D bar：feat 1h resample("1D") OHLC，UTC 0 点为界；当日 1h 根数<20 的
    1D 丢弃（数据首日不满）。日线特征在该日结束后（次日 0 点起）才可见。
  - 主分析窗：纯价格结构（sS/sT/sU/sW）= 全价格窗 2024-07-02→2026-07-01
    （日线尺度事件稀疏，扩窗为主窗是本轮预注册决定，含 2024-25 牛市段）；
    sV = 流量窗（vol/cvd/rsi 齐备，约 2025-08 起）。基线=各自 win 内无条件均值。
  - 行情四段：前段(2024-07-02→2025-08-03，仅纯价格结构有事件)、上行、崩盘、
    下跌（后三段边界同前三轮）。段列报 diff24；"三段行情符号"指后三段。
  - fwd 口径：全结构报 fwd24/fwd72；日线尺度（sS/sT/sU）加报 fwd5D=fwd120h。
  - t_adj = [(事件均值-基线)/(事件std/√n)] / √(N/24)。
阶段一淘汰线（预注册）：
  - 主品种 BTC：diff 符号与方向一致 且 |diff|≥0.40pp——fwd24 达标即过；
    日线尺度结构 fwd5D 达标亦算，但另一口径不得反向（反向=符号相反且
    |diff|>0.05pp）；非日线结构只看 fwd24。
  - ETH 在达标口径上同号；双品种去重事件各 ≥8。
  - n<15 标"样本饥饿"并加报双品种合并行（事件超额=相对各自品种基线）；
    任一品种 n<8 时以合并样本判定（合并 n≥8，达标者标"合并判定·证据降级"，
    因无法做跨品种自检）；合并 n<8 = 样本不足按零信息处理。
  - 只在单一行情段成立 → 标"行情战术件"；全灭=合格结论。
阶段二（仅幸存者，预声明）：
  - 执行腿：信号bar收盘入场 / TP=1.5R 单目标 / 超时 72h（sS/sT/sU 改 7D=168h，
    预声明）/ 成本单边 0.0007 / 止损后 6h 冷却 / 同bar双触发止损优先 /
    止损距离>5% 拒单统一保留 / 串行持仓互斥。
  - 止损按各结构原生（见上）；sV 用 L01。
  - BTC 训/外=各自 win 时间对半；ETH 整段零调整。
  - sV 若幸存：与现役 s2（cvd<p15 + rsi4h>50 + 6h净流>0，L01+1.5R+72h）同窗
    对比——增量交易数（入场时刻距任一 s2 交易>24h）与提前入场统计。
  - 预注册外诊断（仅解读不判定）：无论 sV 存亡，报告 sV 与 s2 事件级重叠度
    及 sV 独有事件的 diff24，用于回答"sV 相对 s2 有无增量"。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pandas as pd
from grid_all import assemble  # noqa: E402
from strategy import l01_stop  # noqa: E402
from run import _jsonl, _ts_index, _pick, CFG, OUT  # noqa: E402

COST = (CFG["costs"]["taker_fee_pct"] + CFG["costs"]["slippage_pct"]) / 100.0
pd.set_option("display.width", 340)

BTC_SUFS = [("cg_taker_spot.jsonl", 1), ("cg_taker_spot_2h.jsonl", 2), ("cg_taker_spot_4h.jsonl", 4),
            ("cg_taker_spot_6h.jsonl", 6), ("cg_taker_spot_12h.jsonl", 12)]
ETH_SUFS = [("cg_taker_spot_eth.jsonl", 1), ("cg_taker_spot_eth_2h.jsonl", 2), ("cg_taker_spot_eth_4h.jsonl", 4),
            ("cg_taker_spot_eth_6h.jsonl", 6), ("cg_taker_spot_eth_12h.jsonl", 12)]

SEGS4 = [("前段", "2024-07-02", "2025-08-03"),
         ("上行", "2025-08-03", "2025-11-01"),
         ("崩盘", "2025-11-01", "2026-01-07"),
         ("下跌", "2026-01-07", "2026-07-01")]
SEGS3 = SEGS4[1:]

LINES = ["sS", "sT_L", "sT_S", "sU", "sV", "sW"]
NAMES = {"sS": "旗形突破多", "sT_L": "外包线反转多", "sT_S": "外包线反转空",
         "sU": "抛物线首阴空", "sV": "s2天量加速多", "sW": "OTE顺势回调多"}
SIDE = {"sS": "L", "sT_L": "L", "sT_S": "S", "sU": "S", "sV": "L", "sW": "L"}
DAILY = {"sS", "sT_L", "sT_S", "sU"}  # fwd5D 判定资格 + 168h 超时
H1 = pd.Timedelta(hours=1)
D1 = pd.Timedelta(days=1)


def wilder_rsi(s, period=14):
    d = s.diff()
    up = d.clip(lower=0)
    dn = (-d).clip(lower=0)
    ru = up.ewm(alpha=1 / period, adjust=False).mean()
    rd = dn.ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + ru / rd.replace(0, np.nan))


def vol_stitched_nolookahead(sufs, close):
    """taker买+卖 量能代理，零前视：粗粒度先 shift(1)（只用上一根已完结粗bar）再摊薄。"""
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
        v = pd.Series((b + s).values, index=t.index)
        if hours > 1:
            v = v.shift(1)  # 零前视：该粗bar完结前不可见
            kw = {"method": "ffill", "limit": hours - 1}
        else:
            kw = {}
        parts.append((v.reindex(close.index, **kw) / hours, hours))
    out = None
    for d, _ in sorted(parts, key=lambda x: x[1]):
        out = d if out is None else out.combine_first(d)
    return out / close  # 币单位/小时


def prep(feat, sufs):
    px = feat["close"]
    c4 = px.resample("4h").last()
    feat["rsi4h"] = wilder_rsi(c4).shift(1).reindex(feat.index, method="ffill")
    feat["cvd_p15"] = feat["spot_cvd_24h"].rolling(720, min_periods=240).quantile(0.15).shift(1)
    vol = vol_stitched_nolookahead(sufs, px)
    feat["vol_hr"] = vol
    feat["vol_p97"] = vol.rolling(720, min_periods=240).quantile(0.97).shift(1)
    surge = (vol > feat["vol_p97"]) & vol.notna() & feat["vol_p97"].notna()
    feat["surge24"] = surge.rolling(24, min_periods=1).sum() > 0
    return feat


def daily_bars(feat):
    g = feat[["open", "high", "low", "close"]].resample("1D")
    d = g.agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    cnt = feat["close"].resample("1D").count()
    d = d[cnt >= 20].dropna()
    return d


# ----------------------------------------------------------------------
# 结构事件（每事件 = (1h bar 时戳, 原生止损价)）
# ----------------------------------------------------------------------
def ss_events(feat):
    d = daily_bars(feat)
    O, H, L, C, dates = d["open"].values, d["high"].values, d["low"].values, d["close"].values, d.index
    armed = {}
    for k in range(30, len(dates)):
        best = None
        for Lc in range(10, 71):
            s0 = k - Lc + 1          # 整理起点
            le = k - Lc              # 腿末日
            ls = le - 19             # 腿首日
            if ls < 0 or k - 14 < 0:
                continue
            if C[le] / C[ls] - 1 < 0.30:
                continue
            leg_high = H[ls:le + 1].max()
            consH, consL = H[s0:k + 1], L[s0:k + 1]
            if consH.max() > leg_high * 1.02:
                continue
            half = int(np.ceil(Lc / 2))
            if consL[half:].min() < consL[:half].min():
                continue
            r5 = H[k - 4:k + 1].max() - L[k - 4:k + 1].min()
            r10 = H[k - 14:k - 4].max() - L[k - 14:k - 4].min()
            if not (r5 < r10):
                continue
            best = (consH.max(), consL.min())  # 取最长合格 L（循环递增覆盖）
        if best:
            armed[dates[k]] = best
    ev, lock = [], None
    for t, c in feat["close"].items():
        a = armed.get(t.normalize() - D1)
        if a is None or not np.isfinite(c):
            continue
        if lock is not None and t < lock:
            continue
        if c > a[0]:
            ev.append((t, a[1]))
            lock = t + pd.Timedelta(hours=480)
    return ev


def st_events(feat):
    d = daily_bars(feat)
    O, H, L, C, dates = d["open"].values, d["high"].values, d["low"].values, d["close"].values, d.index
    idx = feat.index
    longs, shorts = [], []
    for k in range(1, len(dates)):
        body, pbody = abs(C[k] - O[k]), abs(C[k - 1] - O[k - 1])
        if not (H[k] > H[k - 1] and L[k] < L[k - 1] and pbody > 0 and body >= 2 * pbody):
            continue
        t = dates[k] + D1  # 次日第一根 1h bar
        if t not in idx:
            continue
        if C[k] < L[k - 1]:
            longs.append((t, L[k]))
        elif C[k] > H[k - 1]:
            shorts.append((t, H[k]))
    return longs, shorts


def su_events(feat):
    d = daily_bars(feat)
    O, H, L, C, dates = d["open"].values, d["high"].values, d["low"].values, d["close"].values, d.index
    didx = {ts: i for i, ts in enumerate(dates)}
    n = len(dates)
    qual = np.zeros(n, dtype=bool)
    r = np.full(n, np.nan)
    r[1:] = C[1:] / C[:-1] - 1
    for k in range(3, n):
        green3 = all(C[j] > O[j] for j in (k - 2, k - 1, k))
        qual[k] = green3 and (C[k] / C[k - 3] - 1 >= 0.10) and (r[k] > r[k - 1] > r[k - 2])
    ev = []
    k = 0
    while k < n:
        if not qual[k]:
            k += 1
            continue
        q0 = k
        while k + 1 < n and qual[k + 1]:
            k += 1
        q1 = k
        start, end = dates[q0] + D1, dates[q1] + 4 * D1
        for t in feat.loc[start:end - H1].index:
            p = didx.get(t.normalize() - D1)
            if p is None:
                continue
            c = feat.at[t, "close"]
            if np.isfinite(c) and c < C[p]:
                ev.append((t, H[p]))
                break
        k += 1
    return ev


def pivots_4h(feat, kind):
    """严格 2-2 pivot（逐字同三轮 sP）；返回 [(avail_time, pivot_time, price)]。"""
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


def sw_events(feat):
    pivH, pivL = pivots_4h(feat, "H"), pivots_4h(feat, "L")
    idx = feat.index
    cl, op, hi = feat["close"].values, feat["open"].values, feat["high"].values
    piH = piL = 0
    curH, consumed, curL = None, True, None
    actives, ev = [], []
    for i, t in enumerate(idx):
        while piH < len(pivH) and pivH[piH][0] <= t:
            curH, consumed = pivH[piH][2], False
            piH += 1
        while piL < len(pivL) and pivL[piL][0] <= t:
            curL = pivL[piL][2]
            piL += 1
        keep = []
        for a in actives:
            a["ph"] = max(a["ph"], hi[i]) if np.isfinite(hi[i]) else a["ph"]
            if i >= a["exp"] or not np.isfinite(cl[i]):
                continue
            if cl[i] < a["ol"]:
                continue  # 结构失效
            rng = a["ph"] - a["ol"]
            zt, zb = a["ph"] - 0.62 * rng, a["ph"] - 0.79 * rng
            if zb <= cl[i] <= zt and cl[i] > op[i]:
                ev.append((t, zb * 0.997))
                continue  # 每结构一次
            keep.append(a)
        actives = keep
        if not consumed and curH is not None and np.isfinite(cl[i]) and cl[i] > curH:
            consumed = True  # 首破即消耗（同 sP）
            if curL is not None and curL < cl[i]:
                actives.append({"ol": curL, "ph": hi[i], "exp": i + 41})
    return ev


def dedup_h(times, hours):
    kept, last = [], None
    for t in times:
        if last is None or (t - last) >= pd.Timedelta(hours=hours):
            kept.append(t)
            last = t
    return kept


def sv_mask(feat):
    win = (feat["cvd_p15"].notna() & feat["spot_cvd_24h"].notna()
           & feat["rsi4h"].notna() & feat["vol_hr"].notna() & feat["vol_p97"].notna())
    m = ((feat["spot_cvd_24h"] < feat["cvd_p15"]) & (feat["rsi4h"] > 50)
         & feat["surge24"] & win)
    return m.fillna(False), win.fillna(False)


def s2_mask(feat):
    win = feat["cvd_p15"].notna() & feat["spot_cvd_24h"].notna() & feat["rsi4h"].notna()
    m = ((feat["spot_cvd_24h"] < feat["cvd_p15"]) & (feat["rsi4h"] > 50)
         & (feat["spot_cvd_slope"] > 0) & win)
    return m.fillna(False), win.fillna(False)


def build_all(feat):
    """返回 {判定线: (事件列表[(t,stop)], win)}；sV 事件=24h去重、stop=None(L01)。"""
    d = {}
    full_win = pd.Series(feat["close"].notna(), index=feat.index)
    d["sS"] = (ss_events(feat), full_win)
    lg, sh = st_events(feat)
    d["sT_L"] = (lg, full_win)
    d["sT_S"] = (sh, full_win)
    d["sU"] = (su_events(feat), full_win)
    mv, wv = sv_mask(feat)
    d["sV"] = ([(t, None) for t in dedup_h(list(feat.index[mv]), 24)], wv)
    d["sW"] = (sw_events(feat), full_win)
    return d


# ----------------------------------------------------------------------
# 阶段一
# ----------------------------------------------------------------------
def fwd_returns(feat):
    px = feat["close"]
    return {24: px.shift(-24) / px - 1, 72: px.shift(-72) / px - 1, 120: px.shift(-120) / px - 1}


def stage1_row(feat, ev_times, side, win, tag, fwd):
    row = {"结构": tag[0], "品种": tag[1], "方向": side, "n": len(ev_times)}
    ev = pd.DatetimeIndex(ev_times)
    for N in (24, 72, 120):
        f = fwd[N]
        base = f[win].mean()
        e = f.reindex(ev).dropna()
        row[f"diff{N}pp"] = round((e.mean() - base) * 100, 3) if len(e) else np.nan
        row[f"事件fwd{N}%"] = round(e.mean() * 100, 3) if len(e) else np.nan
        row[f"基线fwd{N}%"] = round(base * 100, 3)
        if len(e) >= 3 and e.std() > 0:
            t = (e.mean() - base) / (e.std() / np.sqrt(len(e)))
            row[f"t_adj{N}"] = round(t / np.sqrt(N / 24), 2)
        else:
            row[f"t_adj{N}"] = np.nan
    for sn, s0, s1 in SEGS4:
        a, b = pd.Timestamp(s0, tz="UTC"), pd.Timestamp(s1, tz="UTC")
        inseg = pd.Series((feat.index >= a) & (feat.index < b), index=feat.index)
        ei = ev[(ev >= a) & (ev < b)]
        e = fwd[24].reindex(ei).dropna()
        base = fwd[24][win & inseg].mean()
        row[f"{sn}diff24pp"] = round((e.mean() - base) * 100, 3) if len(e) else np.nan
        row[f"{sn}n"] = len(ei)
    return row


def merged_row(s, evb, evd_b, eve, evd_e, fb, fe, wb, we):
    """双品种合并行：事件超额 = fwd - 各自品种基线，合并求均值。"""
    row = {"结构": s, "品种": "合并", "方向": SIDE[s]}
    exs = {}
    for N in (24, 72, 120):
        xb = (fb[N].reindex(pd.DatetimeIndex(evb)) - fb[N][wb].mean()).dropna()
        xe = (fe[N].reindex(pd.DatetimeIndex(eve)) - fe[N][we].mean()).dropna()
        x = pd.concat([xb, xe])
        exs[N] = x
        row[f"diff{N}pp"] = round(x.mean() * 100, 3) if len(x) else np.nan
        if len(x) >= 3 and x.std() > 0:
            row[f"t_adj{N}"] = round((x.mean() / (x.std() / np.sqrt(len(x)))) / np.sqrt(N / 24), 2)
        else:
            row[f"t_adj{N}"] = np.nan
    row["n"] = len(evb) + len(eve)
    return row


def judge_stage1(tab):
    verdicts = {}
    for s in LINES:
        b = tab[(tab["结构"] == s) & (tab["品种"] == "BTC")].iloc[0]
        e = tab[(tab["结构"] == s) & (tab["品种"] == "ETH")].iloc[0]
        mr = tab[(tab["结构"] == s) & (tab["品种"] == "合并")]
        m = mr.iloc[0] if len(mr) else None
        want = -1 if SIDE[s] == "S" else 1
        hzs = [24, 120] if s in DAILY else [24]
        starving = (b["n"] < 15) or (e["n"] < 15)
        ok, reasons, mode = False, [], "双品种"
        if b["n"] >= 8 and e["n"] >= 8:
            for N in hzs:
                db, de = b[f"diff{N}pp"], e[f"diff{N}pp"]
                if not (np.isfinite(db) and np.sign(db) == want and abs(db) >= 0.40):
                    continue
                other_ok = True
                for M in hzs:
                    if M == N:
                        continue
                    dm = b[f"diff{M}pp"]
                    if np.isfinite(dm) and np.sign(dm) == -want and abs(dm) > 0.05:
                        other_ok = False
                if not other_ok:
                    continue
                if np.isfinite(de) and np.sign(de) == want:
                    ok = True
                    reasons.append(f"过线口径 fwd{N}: BTC {db:+.2f}pp / ETH {de:+.2f}pp")
                    break
            if not ok:
                d24b = b["diff24pp"]
                r = f"BTC diff24={d24b:+.3f}pp"
                if s in DAILY:
                    r += f", diff5D={b['diff120pp']:+.3f}pp"
                r += f"; ETH diff24={e['diff24pp']:+.3f}pp"
                if np.isfinite(d24b) and np.sign(d24b) == want and abs(d24b) < 0.40:
                    reasons.append("量级不足: " + r)
                elif np.isfinite(d24b) and np.sign(d24b) != want:
                    reasons.append("BTC 符号不符: " + r)
                else:
                    reasons.append(r)
                eok = any(np.isfinite(b[f"diff{N}pp"]) and np.sign(b[f"diff{N}pp"]) == want
                          and abs(b[f"diff{N}pp"]) >= 0.40
                          and not (np.isfinite(e[f"diff{N}pp"]) and np.sign(e[f"diff{N}pp"]) == want)
                          for N in hzs)
                if eok:
                    reasons.append("ETH 不同向")
        elif m is not None and m["n"] >= 8:
            mode = "合并判定·证据降级"
            for N in hzs:
                dm = m[f"diff{N}pp"]
                if not (np.isfinite(dm) and np.sign(dm) == want and abs(dm) >= 0.40):
                    continue
                other_ok = all(not (np.isfinite(m[f"diff{M}pp"]) and np.sign(m[f"diff{M}pp"]) == -want
                                    and abs(m[f"diff{M}pp"]) > 0.05) for M in hzs if M != N)
                if other_ok:
                    ok = True
                    reasons.append(f"合并过线 fwd{N}: {dm:+.2f}pp (n={m['n']})")
                    break
            if not ok:
                reasons.append(f"合并未过线: diff24={m['diff24pp']}pp"
                               + (f", diff5D={m['diff120pp']}pp" if s in DAILY else "")
                               + f" (n={m['n']})")
        else:
            reasons.append(f"样本不足(BTC n={b['n']}, ETH n={e['n']})，按零信息处理")
        segs_ok = [sn for sn, _, _ in SEGS3
                   if np.isfinite(b.get(f"{sn}diff24pp", np.nan))
                   and np.sign(b[f"{sn}diff24pp"]) == want]
        verdicts[s] = {"pass": ok, "mode": mode, "starving": starving,
                       "tactical": ok and len(segs_ok) <= 1,
                       "segs_ok": ",".join(segs_ok) if segs_ok else "无",
                       "reason": "; ".join(reasons) if reasons else "通过"}
    return verdicts


# ----------------------------------------------------------------------
# 阶段二
# ----------------------------------------------------------------------
def sim_ev(feat, events, side, max_hold):
    """事件列表串行整机：stop=None 用 L01，否则用事件自带原生止损。"""
    idx = feat.index
    n = len(feat)
    c, h, l = feat["close"].values, feat["high"].values, feat["low"].values
    pos = {t: i for i, t in enumerate(idx)}
    S = side == "S"
    sgn = -1 if S else 1
    out, next_free = [], 0
    for t, stp in sorted(events, key=lambda x: x[0]):
        i = pos.get(t)
        if i is None or i < next_free or i >= n - 2:
            continue
        entry = c[i]
        stop = l01_stop(feat.iloc[i], "SHORT" if S else "LONG", entry) if stp is None else stp
        ok = stop is not None and np.isfinite(stop) and (
            (stop > entry and stop / entry - 1 <= 0.05) if S
            else (stop < entry and 1 - stop / entry <= 0.05))
        if not ok:
            continue
        R = abs(entry - stop)
        tgt = entry + sgn * 1.5 * R
        pnl, xj, stopped = 0.0, None, False
        for j in range(i + 1, min(i + max_hold + 1, n)):
            if (h[j] >= stop) if S else (l[j] <= stop):
                pnl = sgn * (stop - entry) / entry - 2 * COST
                xj, stopped = j, True
                break
            if (l[j] <= tgt) if S else (h[j] >= tgt):
                pnl = sgn * (tgt - entry) / entry - 2 * COST
                xj = j
                break
        if xj is None:
            j = min(i + max_hold, n - 1)
            pnl = sgn * (c[j] - entry) / entry - 2 * COST
            xj = j
        out.append({"t": t, "pnl": pnl * 100})
        next_free = xj + (6 if stopped else 1)
    return pd.DataFrame(out)


def stats(tr):
    if tr is None or len(tr) == 0:
        return {"n": 0, "net": 0.0, "wr": np.nan}
    return {"n": len(tr), "net": round(tr.pnl.sum(), 2), "wr": round((tr.pnl > 0).mean() * 100, 0)}


def seg_net(tr):
    parts = []
    for sn, s0, s1 in SEGS4:
        a, b = pd.Timestamp(s0, tz="UTC"), pd.Timestamp(s1, tz="UTC")
        s = tr[(tr.t >= a) & (tr.t < b)] if len(tr) else tr
        parts.append(f"{sn}{s.pnl.sum():+.1f}({len(s)})" if len(s) else f"{sn}+0.0(0)")
    return " ".join(parts)


def main():
    print("加载 BTC/ETH（全价格窗，日线尺度结构不裁剪到流量窗）……")
    btc = prep(assemble("price_1h.jsonl", BTC_SUFS, "cg_funding.jsonl"), BTC_SUFS)
    eth = prep(assemble("price_1h_eth.jsonl", ETH_SUFS, "cg_funding_eth.jsonl"), ETH_SUFS)
    fb, fe = fwd_returns(btc), fwd_returns(eth)
    eb, ee = build_all(btc), build_all(eth)

    # 训/外分界
    mid_px_b = btc.index[0] + (btc.index[-1] - btc.index[0]) / 2
    wv_b = btc.index[eb["sV"][1]]
    mid_v_b = wv_b[0] + (wv_b[-1] - wv_b[0]) / 2 if len(wv_b) else None
    print(f"BTC 价格窗 {btc.index[0]} → {btc.index[-1]}  训/外分界(价格结构): {mid_px_b}")
    if mid_v_b is not None:
        print(f"BTC sV 窗 {wv_b[0]} → {wv_b[-1]}  训/外分界(sV): {mid_v_b}")

    # ---------- 阶段一 ----------
    print("=" * 130)
    print("阶段一 · 事件级信息量（第四轮；量级线 0.40pp；日线结构加报 fwd5D=120h；diff=事件均值-基线）")
    rows = []
    for s in LINES:
        evb, wb = eb[s]
        eve, we = ee[s]
        tb = [t for t, _ in evb]
        te = [t for t, _ in eve]
        rows.append(stage1_row(btc, tb, SIDE[s], wb, (s, "BTC"), fb))
        rows.append(stage1_row(eth, te, SIDE[s], we, (s, "ETH"), fe))
        if len(tb) < 15 or len(te) < 15:
            rows.append(merged_row(s, tb, evb, te, eve, fb, fe, wb, we))
    tab = pd.DataFrame(rows)
    cols = ["结构", "品种", "方向", "n", "diff24pp", "t_adj24", "diff72pp", "diff120pp", "t_adj120"] + \
           [c for c in tab.columns if c.endswith("diff24pp") and c != "diff24pp"] + \
           [c for c in tab.columns if c.endswith("n") and c != "n"]
    print(tab[cols].to_string(index=False))
    tab.to_csv(os.path.join(OUT, "s_layer_r4_stage1.csv"), index=False)

    verdicts = judge_stage1(tab)
    print("\n-- 阶段一判定（预注册淘汰线 0.40pp；日线结构 fwd24/fwd5D 任一达标且另一口径不反向）--")
    for s, v in verdicts.items():
        tag = "幸存" if v["pass"] else "淘汰"
        if v["pass"] and v["tactical"]:
            tag += "(行情战术件)"
        extra = "[样本饥饿]" if v["starving"] else ""
        print(f"{s} {NAMES[s]:10s} [{tag}]{extra} 判定={v['mode']} {v['reason']}  BTC三段成立: {v['segs_ok']}")

    # ---------- sV vs s2 事件级重叠（预注册外诊断，仅解读） ----------
    print("\n-- sV vs 现役 s2 事件级重叠诊断（预注册外，仅解读不判定）--")
    for sym, feat, ed, f in (("BTC", btc, eb, fb), ("ETH", eth, ee, fe)):
        m2, w2 = s2_mask(feat)
        e2 = dedup_h(list(feat.index[m2]), 24)
        ev = [t for t, _ in ed["sV"][0]]
        e2i = pd.DatetimeIndex(e2)
        only = [t for t in ev if len(e2i) == 0 or (abs(e2i - t) > pd.Timedelta(hours=24)).all()]
        base = f[24][ed["sV"][1]].mean()
        d_only = (f[24].reindex(pd.DatetimeIndex(only)).dropna().mean() - base) * 100 if only else np.nan
        print(f"{sym}: sV事件 {len(ev)} / s2事件 {len(e2)} / sV独有(距任一s2>24h) {len(only)}"
              f" / sV独有 diff24 = {d_only:+.3f}pp" if only else
              f"{sym}: sV事件 {len(ev)} / s2事件 {len(e2)} / sV独有 0")

    survivors = [s for s, v in verdicts.items() if v["pass"]]
    if not survivors:
        print("\n阶段一全灭：6 条判定线均未过淘汰线。这是合格结论，不进阶段二。")
        return

    # ---------- 阶段二 ----------
    print("\n" + "=" * 130)
    print("阶段二 · 整机（幸存者；原生止损/1.5R/超时72h·日线结构168h/6h冷却/成本0.0007单边/>5%拒单）")
    rows2 = []
    for s in survivors:
        hold = 168 if s in DAILY else 72
        recs = {"结构": f"{s} {NAMES[s]}", "超时": f"{hold}h"}
        for sym, feat, ed in (("BTC", btc, eb), ("ETH", eth, ee)):
            evs, w = ed[s]
            tr = sim_ev(feat, evs, SIDE[s], hold)
            if sym == "BTC":
                widx = feat.index[w]
                mid = widx[0] + (widx[-1] - widx[0]) / 2
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
        # sV 幸存时与 s2 整机同窗对比
        if s == "sV":
            for sym, feat in (("BTC", btc), ("ETH", eth)):
                m2, _ = s2_mask(feat)
                tr2 = sim_ev(feat, [(t, None) for t in feat.index[m2]], "L", 72)
                evs, _ = (eb if sym == "BTC" else ee)["sV"]
                trv = sim_ev(feat, evs, "L", 72)
                t2 = pd.DatetimeIndex(tr2.t) if len(tr2) else pd.DatetimeIndex([])
                inc = [t for t in (trv.t if len(trv) else []) if len(t2) == 0
                       or (abs(t2 - t) > pd.Timedelta(hours=24)).all()]
                print(f"[sV vs s2 @{sym}] s2整机: {stats(tr2)}  sV整机: {stats(trv)}"
                      f"  sV增量交易(距s2>24h): {len(inc)}")
    tab2 = pd.DataFrame(rows2)
    print(tab2.to_string(index=False))
    tab2.to_csv(os.path.join(OUT, "s_layer_r4_stage2.csv"), index=False)
    print(f"\n已保存 {os.path.join(OUT, 's_layer_r4_stage1.csv')} / s_layer_r4_stage2.csv")


if __name__ == "__main__":
    main()
