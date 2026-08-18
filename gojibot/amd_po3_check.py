#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S层残值复检轮：ICT AMD/PO3 三段式 —— python3 amd_po3_check.py

轮次定位（预注册声明）：
  这不是重开 S 层发掘（本数据集 S 层已四轮 22 结构 / 25 判定线 0 生还，全尺度关闭），
  而是二轮已登记残值 sH_L（亚洲区间清扫多@BTC：+0.341pp、t_adj 1.87、三段全正，
  死于量级线 0.40pp 与 ETH 反向）的"待单独预注册"票据兑现。
  AMD 与 sH 的机理差异：Accumulation(亚洲区间)-Manipulation(扫破一侧)-
  Distribution(收破另一侧) 要求派发确认（close 破区间另一侧）而非仅收回(reclaim)。
  按 skill 阶段3：残值复检同样折价解读；全灭 = session 清扫家族正式全线关闭。

4 条预注册判定线（口径一次固定，测完不加；与 r2 sH 完全可比的部分逐字沿用）：
  亚洲区间 = 当日 UTC 0:00-7:59 的 8 根 1h high/low（须满 8 根才定义，同 sH）；
  区间形成后（08:00 起）才可触发，无前视。
  sX   AMD多：UTC 8-16（bar 时戳 hour∈[8,16)）内出现 bar low < 区间low（操纵腿）；
       其后同日 hour≤20 的 bar 内首次 1h close > 区间high（派发确认）→ 该bar收盘做多。
       每日最多 1 次。口径固定：确认bar 允许=操纵bar 本身（bar 内低点先于收盘发生）。
  sX_S 镜像空（家族自检）：8-16 内 bar high > 区间high；其后同日 hour≤20 内
       首次 close < 区间low → 收盘做空。每日最多 1 次。
  sX_m 宽松多（预注册邻域，判平台/悬崖）：派发确认放宽为 close > 区间中点
       (asia_high+asia_low)/2；其余同 sX。
  sX_f 流确认多（唯一带独立状态量的变体）：sX 全条件 + (操纵bar, 确认bar] 的
       累计 1h 现货 taker净流 > 0；确认bar=操纵bar 时取该bar自身净流。
       零前视口径（v1.2 规矩，同 r4 量能代理）：粗粒度净流先 shift(1)（该粗bar
       完结前不可见）再摊薄；1h 粒度 bar 自身净流于该bar收盘已知、不 shift。
       流段内全 NaN 视为条件不成立。

主分析窗 = 前四轮口径：2025-07-08 → 2026-07-01；三段：上行 2025-08-03→11-01 /
崩盘 →2026-01-07 / 下跌 →2026-07-01。纯价格 3 线（sX/sX_S/sX_m）另报扩窗参考列
（2024-07 起全价格窗，含牛市段），仅参考不判定（预注册，同 r2）。sX_f 有效窗=流量窗。

阶段一淘汰线（预注册，量级线=S层永久默认 0.40pp）：
  双品种 diff24 同向（与方向一致）且 主品种 BTC |diff24|≥0.40pp；
  双品种去重事件各 ≥8（不足=无法判定，按零信息处理）；n<15 标"样本饥饿"。
  同表附 sH_L 二轮原始数字对照行（+0.341pp，直接引自 results/s_layer_r2_stage1.csv）。

阶段二（仅幸存者）：
  原生止损 = 操纵腿极值（操纵bar→确认bar 间 min low）×0.997；空侧镜像 max high×1.003；
  止损距离 >5% 拒单保留；TP=1.5R；72h 超时平仓；成本 0.0007 单边；止损后 6h 冷却；
  同bar双触发止损优先；信号bar收盘入场；持仓互斥（串行）。
  BTC 训/外 = cvd+funding 齐备窗时间对半（同前四轮 mid）；ETH 整段零调整。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pandas as pd
from grid_all import assemble  # noqa: E402
from run import _jsonl, _ts_index, _pick, CFG, OUT  # noqa: E402

COST = (CFG["costs"]["taker_fee_pct"] + CFG["costs"]["slippage_pct"]) / 100.0
pd.set_option("display.width", 300)

BTC_SUFS = [("cg_taker_spot.jsonl", 1), ("cg_taker_spot_2h.jsonl", 2), ("cg_taker_spot_4h.jsonl", 4),
            ("cg_taker_spot_6h.jsonl", 6), ("cg_taker_spot_12h.jsonl", 12)]
ETH_SUFS = [("cg_taker_spot_eth.jsonl", 1), ("cg_taker_spot_eth_2h.jsonl", 2), ("cg_taker_spot_eth_4h.jsonl", 4),
            ("cg_taker_spot_eth_6h.jsonl", 6), ("cg_taker_spot_eth_12h.jsonl", 12)]

W0 = pd.Timestamp("2025-07-08", tz="UTC")
SEGS = [("上行", "2025-08-03", "2025-11-01"),
        ("崩盘", "2025-11-01", "2026-01-07"),
        ("下跌", "2026-01-07", "2026-07-01")]

LINES = {"sX": ("AMD派发确认多", "L"), "sX_S": ("AMD镜像空", "S"),
         "sX_m": ("AMD中点宽松多", "L"), "sX_f": ("AMD流确认多", "L")}
PRICE_ONLY = {"sX", "sX_S", "sX_m"}

# sH_L 二轮原始对照（直接引自 results/s_layer_r2_stage1.csv，不重算）
SH_L_REF = {
    "BTC": {"n": 137, "diff24pp": 0.341, "t_adj24": 1.87, "diff72pp": 0.530,
            "上行": "+0.29(37)", "崩盘": "+0.63(26)", "下跌": "+0.14(63)", "扩窗": "+0.10(288)"},
    "ETH": {"n": 140, "diff24pp": -0.155, "t_adj24": -0.53, "diff72pp": -0.014,
            "上行": "-0.84(32)", "崩盘": "-0.18(32)", "下跌": "+0.46(68)", "扩窗": "-0.27(283)"},
}


def netflow_nolookahead(sufs, close):
    """现货 taker净流(买-卖)/close，零前视：粗粒度 shift(1) 再摊薄；1h 不 shift。"""
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
        v = pd.Series((b - s).values, index=t.index)
        if hours > 1:
            v = v.shift(1)  # 该粗bar完结前不可见
            kw = {"method": "ffill", "limit": hours - 1}
        else:
            kw = {}
        parts.append((v.reindex(close.index, **kw) / hours, hours))
    out = None
    for d, _ in sorted(parts, key=lambda x: x[1]):
        out = d if out is None else out.combine_first(d)
    return out / close


def prep(feat, sufs):
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
    feat["netflow_nl"] = netflow_nolookahead(sufs, feat["close"])
    return feat


def amd_scan(feat):
    """逐日扫描 AMD 事件。返回 {线: DataFrame(t, ext, flow, flow_valid)}；
    sX_f 由 sX 事件 + 流条件派生。"""
    idx = feat.index
    lo, hi, cl = feat["low"].values, feat["high"].values, feat["close"].values
    ah, al = feat["asia_high"].values, feat["asia_low"].values
    fl = feat["netflow_nl"].values
    hrs = idx.hour
    days = idx.normalize()
    res = {k: [] for k in ("sX", "sX_S", "sX_m")}
    pos_by_day = {}
    for i, d in enumerate(days):
        pos_by_day.setdefault(d, []).append(i)
    for d, pos in pos_by_day.items():
        a_h, a_l = ah[pos[0]], al[pos[0]]
        if not (np.isfinite(a_h) and np.isfinite(a_l)):
            continue
        mid = (a_h + a_l) / 2
        sess = [i for i in pos if 8 <= hrs[i] < 16]
        w20 = [i for i in pos if hrs[i] <= 20]
        # 多侧：操纵腿 = 首个 low<区间low
        tm = next((i for i in sess if np.isfinite(lo[i]) and lo[i] < a_l), None)
        if tm is not None:
            for thr, key in ((a_h, "sX"), (mid, "sX_m")):
                tc = next((j for j in w20 if j >= tm and np.isfinite(cl[j]) and cl[j] > thr), None)
                if tc is not None:
                    ext = np.nanmin(lo[tm:tc + 1])
                    seg = fl[tm + 1:tc + 1] if tc > tm else fl[tc:tc + 1]
                    fv = np.isfinite(seg).any()
                    res[key].append({"t": idx[tc], "ext": ext,
                                     "flow": np.nansum(seg) if fv else np.nan, "flow_valid": fv})
        # 空侧镜像：操纵腿 = 首个 high>区间high
        tm = next((i for i in sess if np.isfinite(hi[i]) and hi[i] > a_h), None)
        if tm is not None:
            tc = next((j for j in w20 if j >= tm and np.isfinite(cl[j]) and cl[j] < a_l), None)
            if tc is not None:
                ext = np.nanmax(hi[tm:tc + 1])
                res["sX_S"].append({"t": idx[tc], "ext": ext, "flow": np.nan, "flow_valid": False})
    out = {k: pd.DataFrame(v) for k, v in res.items()}
    sx = out["sX"]
    out["sX_f"] = sx[sx["flow_valid"] & (sx["flow"] > 0)].reset_index(drop=True) if len(sx) else sx
    return out


def stage1_row(feat, ev, side, win, tag):
    px = feat["close"]
    fwd = {24: px.shift(-24) / px - 1, 72: px.shift(-72) / px - 1}
    row = {"线": tag[0], "品种": tag[1], "方向": side, "n": len(ev)}
    for N in (24, 72):
        f = fwd[N]
        base = f[win].mean()
        e = f.reindex(ev).dropna()
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


def judge(tab):
    """预注册淘汰线：BTC diff24 符号一致且|.|≥0.40pp；ETH 同号；双 n≥8；n<15 标饥饿。"""
    verdicts = {}
    for s in LINES:
        b = tab[(tab["线"] == s) & (tab["品种"] == "BTC")].iloc[0]
        e = tab[(tab["线"] == s) & (tab["品种"] == "ETH")].iloc[0]
        want = -1 if LINES[s][1] == "S" else 1
        reasons, ok = [], True
        if b["n"] < 8 or e["n"] < 8:
            ok = False
            reasons.append(f"样本不足(BTC n={b['n']}, ETH n={e['n']})，按零信息处理")
        else:
            db, de = b["diff24pp"], e["diff24pp"]
            if not (np.isfinite(db) and np.sign(db) == want):
                ok = False
                reasons.append(f"BTC diff24={db:+.3f}pp 符号不符")
            elif abs(db) < 0.40:
                ok = False
                reasons.append(f"BTC |diff24|={abs(db):.3f}pp <0.40pp 量级不足")
            if not (np.isfinite(de) and np.sign(de) == want):
                ok = False
                reasons.append(f"ETH diff24={de:+.3f}pp 不同向")
        hungry = b["n"] < 15 or e["n"] < 15
        verdicts[s] = {"pass": ok, "hungry": hungry,
                       "reason": "; ".join(reasons) if reasons else "通过"}
    return verdicts


def sim_events(feat, evd, side):
    """阶段二：原生止损=操纵腿极值×0.997/×1.003；1.5R；72h；6h冷却；串行互斥。"""
    if evd is None or len(evd) == 0:
        return pd.DataFrame(columns=["t", "pnl"])
    idx = feat.index
    n = len(feat)
    c, h, l = feat["close"].values, feat["high"].values, feat["low"].values
    loc = {t: i for i, t in enumerate(idx)}
    S = side == "S"
    sgn = -1 if S else 1
    out, busy_until = [], -1
    for _, r in evd.sort_values("t").iterrows():
        i = loc.get(r["t"])
        if i is None or i >= n - 2 or i <= busy_until:
            continue
        entry = c[i]
        stop = r["ext"] * (1.003 if S else 0.997)
        ok = np.isfinite(stop) and (
            (stop > entry and stop / entry - 1 <= 0.05) if S
            else (stop < entry and 1 - stop / entry <= 0.05))
        if not ok:
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
        busy_until = xj + (6 if stopped else 1) - 1
    return pd.DataFrame(out)


def stats(tr):
    if tr is None or len(tr) == 0:
        return {"n": 0, "net": 0.0, "wr": np.nan}
    return {"n": len(tr), "net": round(tr.pnl.sum(), 2), "wr": round((tr.pnl > 0).mean() * 100, 0)}


def seg_net(tr):
    parts = []
    for sn, s0, s1 in SEGS:
        a, b = pd.Timestamp(s0, tz="UTC"), pd.Timestamp(s1, tz="UTC")
        s = tr[(tr.t >= a) & (tr.t < b)] if len(tr) else tr
        parts.append(f"{sn}{s.pnl.sum():+.1f}({len(s)})" if len(s) else f"{sn}+0.0(0)")
    return " ".join(parts)


def main():
    btc_full = prep(assemble("price_1h.jsonl", BTC_SUFS, "cg_funding.jsonl"), BTC_SUFS)
    eth_full = prep(assemble("price_1h_eth.jsonl", ETH_SUFS, "cg_funding_eth.jsonl"), ETH_SUFS)
    print(f"BTC 价格全窗: {btc_full.index[0]} → {btc_full.index[-1]}")
    print(f"ETH 价格全窗: {eth_full.index[0]} → {eth_full.index[-1]}")
    btc, eth = btc_full.loc[W0:], eth_full.loc[W0:]
    bw = btc.index[btc["spot_cvd_24h"].notna() & btc["funding"].notna()]
    mid = bw[0] + (bw[-1] - bw[0]) / 2
    print(f"主窗: {W0} 起；BTC 训/外分界: {mid}\n")

    ev = {"BTC": amd_scan(btc), "ETH": amd_scan(eth)}
    evf = {"BTC": amd_scan(btc_full), "ETH": amd_scan(eth_full)}
    feats = {"BTC": btc, "ETH": eth}
    featsf = {"BTC": btc_full, "ETH": eth_full}

    print("=" * 120)
    print("阶段一 · 事件级信息量（残值复检轮；量级线 0.40pp；diff=事件均值-无条件基线）")
    rows = []
    for s, (nm, side) in LINES.items():
        for sym in ("BTC", "ETH"):
            feat = feats[sym]
            d = ev[sym][s]
            times = pd.DatetimeIndex(d["t"]) if len(d) else pd.DatetimeIndex([], tz="UTC")
            win = feat["asia_low"].notna()
            if s == "sX_f":
                win = win & feat["netflow_nl"].notna()
            row = stage1_row(feat, times, side, win, (s, sym))
            if s in PRICE_ONLY:
                df = evf[sym][s]
                tf = pd.DatetimeIndex(df["t"]) if len(df) else pd.DatetimeIndex([], tz="UTC")
                px = featsf[sym]["close"]
                f24 = px.shift(-24) / px - 1
                e = f24.reindex(tf).dropna()
                base = f24[featsf[sym]["asia_low"].notna()].mean()
                row["扩窗diff24pp"] = round((e.mean() - base) * 100, 3) if len(e) else np.nan
                row["扩窗n"] = len(tf)
            else:
                row["扩窗diff24pp"], row["扩窗n"] = np.nan, 0
            rows.append(row)
    tab = pd.DataFrame(rows)
    print(tab.to_string(index=False))
    tab.to_csv(os.path.join(OUT, "amd_po3_stage1.csv"), index=False)
    print("\n[对照] sH_L(二轮原始): BTC n=137 diff24=+0.341pp t_adj=1.87 | ETH n=140 diff24=-0.155pp")

    verdicts = judge(tab)
    print("\n-- 阶段一判定（预注册淘汰线）--")
    for s, v in verdicts.items():
        tag = "幸存" if v["pass"] else "淘汰"
        if v["hungry"]:
            tag += "·样本饥饿"
        print(f"{s} {LINES[s][0]:10s} [{tag}] {v['reason']}")

    survivors = [s for s, v in verdicts.items() if v["pass"]]
    if not survivors:
        print("\n阶段一全灭：4 条判定线均未过。残值票据未兑现，session 清扫家族全线关闭。")
        return

    print("\n" + "=" * 120)
    print("阶段二 · 整机（幸存者；原生止损=操纵腿极值×0.997/1.003；1.5R+72h+6h冷却+0.0007单边+>5%拒单）")
    rows2 = []
    for s in survivors:
        side = LINES[s][1]
        recs = {"线": f"{s} {LINES[s][0]}"}
        for sym in ("BTC", "ETH"):
            tr = sim_events(feats[sym], ev[sym][s], side)
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
    tab2.to_csv(os.path.join(OUT, "amd_po3_stage2.csv"), index=False)


if __name__ == "__main__":
    main()
