#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L层（止损）两段式调研：python3 l_layer_scan.py

阶段一 · 元件级：现役 l1 + t1 引擎下的止损单死后验尸（s1@BTC、s1@ETH、s2@BTC+ETH）
  - 止损后 24h/72h 路径：回到入场价%、到达原 1.5R 目标价%（=冤杀率）、
    继续向不利方向再走 ≥1R%（=真救命率）
  - 止损距离分布（% of entry）与 l1 分支占比（4H结构 / 1D升级 / 近端0.8% / h1兜底）
  - 盈利单（TP出场）的 MAE/R 分布——回答"还有多少收紧空间"
  - 分段（上行/崩盘/下跌，按入场时间）冤杀率

阶段二 · 配对级：9 个预注册 L 变体串行整机（测前锁定，测完不加）
  l1 基准：l01_stop（3×4H极值×1.002 / 1D升级×1.003 / 近端0.8% / h1兜底）
  lA l1 去 1D 升级条款（其余分支与 l1 完全一致）——隔离升级条款价值
  lB 5×4H极值×1.002（更宽结构窗，其余分支同 lA）
  lC 纯 1D 结构：5×1D极值×1.003（结构错侧退化近端0.8%；无1D数据拒单）
  lD 2×ATR24h    lE 3×ATR24h（ATR家族）
  lF 固定 1.5%   lG 固定 2.5%（比例家族）
  lH max(lA结构位, 入场价×1.012)——结构位保底 1.2%（垫远，不是拒单）

其余元素全程锁死（与 deploy/bot.py、t_layer_scan.py 一致）：
  s1 入场：res=近20根已完成4H高点max，(res/px-1)<near(1.5%，UTC13-15点2%)，
           px<res*1.005，spot_cvd24h<0，funding>=0，px<SMA168h
  s2 入场：spot_cvd24h < 滚动p15阈值(776h,min100)，6h净流>0，4hRSI14(Wilder)>50
  T：TP=1.5×新止损距离（L层固有联动，如实保留）；72h 超时收盘平仓
  执行：同bar双触发止损优先；止损后6h冷却；成本单边0.0007；>5% 拒单对所有变体统一保留
  ⚠️ 方法论边界：MIN_STOP 下限过滤已被串行重放证伪，本轮不含任何"按止损距离拒单"的新阈值

口径声明（阶段2.5，固定单一解释，不做多口径扫描）：
  - 冤杀率 = 止损单中，止损bar起（含双触发bar）至其后 72h（24h 版另报）内价格触及
    该笔原 TP 价的比例；回本 = 同窗内触及入场价；救命 = 同窗内价格越过止损价再走 ≥1R
  - 赢单 MAE/R = TP 出场单在持仓期间（含 TP bar 的不利极值，1h 粒度内不可分序，保守计入）
    最大不利偏移 ÷ 止损距离
  - atr24 = (high-low).rolling(24).mean()，含信号bar（已收盘，无前视，与 bot.py atr_pct 同窗）
  - lA/lB 的 h1 兜底与近端 0.8% 分支照抄 l1（数据热身后 h4 恒有值，兜底极少触发），
    保证 lA−l1 的唯一差异就是 1D 升级条款
  - 4H/1D 特征 resample 后 shift(1) 再 reindex-ffill，只用已完成K线（同 o/t_layer_scan）
  - p15 阈值 = spot_cvd_24h 滚动776h(含当前bar)分位0.15，min_periods=100（同 t_layer_scan）
  - BTC 训练/样本外 = s1 有效窗口时间对半（分界打印）；ETH 整段零调整
  - 行情分段沿用 o_info_profile.SEGS：上行 2025-08-03→11-01，崩盘 →2026-01-07，下跌 →07-01
  - 对账锚点：l1 行须与 t_layer_scan t1 行逐位一致
    （s1@BTC 训13/−1.88 外16/+15.93 合计+14.05(29)，ETH +9.77(20)；
      s2@BTC 训5/+9.93 外9/−6.76 合计+3.17(14)，ETH +13.32(21)）
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

VARIANTS = ["l1", "lA", "lB", "lC", "lD", "lE", "lF", "lG", "lH"]
SEGS = [("上行", "2025-08-03", "2025-11-01"),
        ("崩盘", "2025-11-01", "2026-01-07"),
        ("下跌", "2026-01-07", "2026-07-01")]


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
    h4 = feat[["high", "low"]].resample("4h").agg({"high": "max", "low": "min"})
    feat["h4_high5"] = h4["high"].shift(1).rolling(5).max().reindex(feat.index, method="ffill")
    feat["h4_low5"] = h4["low"].shift(1).rolling(5).min().reindex(feat.index, method="ffill")
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


# ----------------------------------------------------------------------
# 9 个止损变体
# ----------------------------------------------------------------------
def stop_lv(lv, row, entry, side, atr):
    if lv == "l1":
        return l01_stop(row, "SHORT" if side == "S" else "LONG", entry)
    if side == "S":
        h4, h45, d1, h1 = row["h4_high3"], row["h4_high5"], row["d1_high5"], row["h1_high6"]
        if lv in ("lA", "lH"):
            if np.isfinite(h4):
                base = h4 * 1.002 if h4 > entry else entry * 1.008
            else:
                base = h1 * 1.002 if np.isfinite(h1) else None
            if lv == "lA":
                return base
            return max(base, entry * 1.012) if base is not None else entry * 1.012
        if lv == "lB":
            if np.isfinite(h45):
                return h45 * 1.002 if h45 > entry else entry * 1.008
            return h1 * 1.002 if np.isfinite(h1) else None
        if lv == "lC":
            return (d1 * 1.003 if d1 > entry else entry * 1.008) if np.isfinite(d1) else None
        if lv == "lD":
            return entry + 2 * atr if np.isfinite(atr) else None
        if lv == "lE":
            return entry + 3 * atr if np.isfinite(atr) else None
        if lv == "lF":
            return entry * 1.015
        if lv == "lG":
            return entry * 1.025
    else:
        l4, l45, d1, h1l = row["h4_low3"], row["h4_low5"], row["d1_low5"], row["h1_low6"]
        if lv in ("lA", "lH"):
            if np.isfinite(l4):
                base = l4 * 0.998 if l4 < entry else entry * 0.992
            else:
                base = h1l * 0.998 if np.isfinite(h1l) else None
            if lv == "lA":
                return base
            return min(base, entry * 0.988) if base is not None else entry * 0.988
        if lv == "lB":
            if np.isfinite(l45):
                return l45 * 0.998 if l45 < entry else entry * 0.992
            return h1l * 0.998 if np.isfinite(h1l) else None
        if lv == "lC":
            return (d1 * 0.997 if d1 < entry else entry * 0.992) if np.isfinite(d1) else None
        if lv == "lD":
            return entry - 2 * atr if np.isfinite(atr) else None
        if lv == "lE":
            return entry - 3 * atr if np.isfinite(atr) else None
        if lv == "lF":
            return entry * 0.985
        if lv == "lG":
            return entry * 0.975
    return None


def l1_branch(row, entry, side):
    """复刻 l01_stop 的分支判定（只做标注，不参与模拟）。"""
    if side == "S":
        h4, d1 = row["h4_high3"], row["d1_high5"]
        if not np.isfinite(h4):
            return "h1兜底"
        if h4 > entry * 1.002:
            if np.isfinite(d1) and d1 > h4 and (d1 / entry - 1) < 0.05:
                return "1D升级"
            return "4H结构"
        return "4H结构" if h4 > entry else "近端0.8%"
    l4, d1 = row["h4_low3"], row["d1_low5"]
    if not np.isfinite(l4):
        return "h1兜底"
    if l4 < entry * 0.998:
        if np.isfinite(d1) and d1 < l4 and (1 - d1 / entry) < 0.05:
            return "1D升级"
        return "4H结构"
    return "4H结构" if l4 < entry else "近端0.8%"


# ----------------------------------------------------------------------
# 串行模拟（含死后验尸字段）
# ----------------------------------------------------------------------
def postmortem(j0, stop, tgt, entry, R, sgn, h, l, n):
    """止损bar j0 起 24h/72h 窗内：回本/到原TP(冤杀)/越过止损再走≥1R(救命)。"""
    res = {}
    for w, tag in ((24, "24"), (72, "72")):
        end = min(j0 + w + 1, n)
        back = tp = save = False
        for k in range(j0, end):
            if sgn < 0:
                back = back or l[k] <= entry
                tp = tp or l[k] <= tgt
                save = save or h[k] >= stop + R
            else:
                back = back or h[k] >= entry
                tp = tp or h[k] >= tgt
                save = save or l[k] <= stop - R
        res[f"back{tag}"], res[f"tp{tag}"], res[f"save{tag}"] = back, tp, save
    return res


def sim_l(feat, mask, side, lv):
    idx = feat.index
    n = len(feat)
    c, h, l = feat["close"].values, feat["high"].values, feat["low"].values
    atr = feat["atr24"].values
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
        stop = stop_lv(lv, row, entry, side, atr[i])
        ok = stop is not None and (
            (stop > entry and stop / entry - 1 <= 0.05) if S
            else (stop < entry and 1 - stop / entry <= 0.05))
        if not ok:
            i += 1
            continue
        R = abs(entry - stop)
        tgt = entry + sgn * 1.5 * R
        pnl, xj, ext, mae = 0.0, None, "time", 0.0
        for j in range(i + 1, min(i + 73, n)):
            mae = max(mae, ((h[j] - entry) if S else (entry - l[j])) / R)
            if (h[j] >= stop) if S else (l[j] <= stop):  # 同bar双触发止损优先
                pnl = sgn * (stop - entry) / entry - 2 * COST
                xj, ext = j, "stop"
                break
            if (l[j] <= tgt) if S else (h[j] >= tgt):
                pnl = sgn * (tgt - entry) / entry - 2 * COST
                xj, ext = j, "tp"
                break
        if xj is None:
            j = min(i + 72, n - 1)
            pnl = sgn * (c[j] - entry) / entry - 2 * COST
            xj = j
        rec = {"t": idx[i], "pnl": pnl * 100, "exit": ext, "hold": xj - i,
               "Rpct": R / entry * 100, "mae": mae,
               "branch": l1_branch(row, entry, side) if lv == "l1" else ""}
        if ext == "stop":
            rec.update(postmortem(xj, stop, tgt, entry, R, sgn, h, l, n))
        out.append(rec)
        i = xj + (6 if ext == "stop" else 1)
    return pd.DataFrame(out)


# ----------------------------------------------------------------------
# 阶段一：画像统计
# ----------------------------------------------------------------------
def pct(s):
    # object 列里的 np.bool_ 相加是逻辑或（sum 恒为 True），必须先转 float
    return round(float(np.asarray(s, dtype=float).mean()) * 100, 0) if len(s) else np.nan


def prof_stats(tr, tag):
    if not len(tr):
        return {"人群": tag, "n": 0}
    st = tr[tr.exit == "stop"]
    tp = tr[tr.exit == "tp"]
    d = {"人群": tag, "n": len(tr), "止损n": len(st),
         "止损占比%": round(len(st) / len(tr) * 100, 0),
         "TPn": len(tp), "超时n": int((tr.exit == "time").sum()),
         "R%p25": round(tr.Rpct.quantile(0.25), 2), "R%p50": round(tr.Rpct.median(), 2),
         "R%p75": round(tr.Rpct.quantile(0.75), 2)}
    for k in ("back24", "back72", "tp24", "tp72", "save24", "save72"):
        d[{"back24": "回本24%", "back72": "回本72%", "tp24": "冤杀24%", "tp72": "冤杀72%",
           "save24": "救命24%", "save72": "救命72%"}[k]] = pct(st[k]) if len(st) else np.nan
    if len(tp):
        d.update({"赢MAE_p50": round(tp.mae.quantile(0.5), 2),
                  "赢MAE_p75": round(tp.mae.quantile(0.75), 2),
                  "赢MAE_p90": round(tp.mae.quantile(0.9), 2),
                  "赢MAE≥0.5R%": pct(tp.mae >= 0.5), "赢MAE≥0.8R%": pct(tp.mae >= 0.8)})
    return d


def seg_rows(tr, tag):
    rows = []
    for sn, s0, s1 in SEGS:
        a = pd.Timestamp(s0, tz="UTC")
        b = pd.Timestamp(s1, tz="UTC")
        s = tr[(tr.t >= a) & (tr.t < b)]
        st = s[s.exit == "stop"]
        rows.append({"人群": tag, "行情段": sn, "n": len(s), "止损n": len(st),
                     "止损占比%": round(len(st) / len(s) * 100, 0) if len(s) else np.nan,
                     "冤杀72%": pct(st.tp72) if len(st) else np.nan,
                     "救命72%": pct(st.save72) if len(st) else np.nan,
                     "段净%": round(s.pnl.sum(), 2)})
    return rows


# ----------------------------------------------------------------------
# 阶段二：矩阵统计
# ----------------------------------------------------------------------
def stats(tr):
    if tr is None or len(tr) == 0:
        return {"n": 0, "net": 0.0, "wr": np.nan, "R": np.nan, "stop%": np.nan, "yz": np.nan}
    st = tr[tr.exit == "stop"]
    return {"n": len(tr), "net": round(tr.pnl.sum(), 2),
            "wr": round((tr.pnl > 0).mean() * 100, 0),
            "R": round(tr.Rpct.mean(), 2),
            "stop%": round(len(st) / len(tr) * 100, 0),
            "yz": pct(st.tp72) if len(st) else np.nan}


def main():
    btc = prep(assemble("price_1h.jsonl", BTC_SUFS, "cg_funding.jsonl"))
    eth = prep(assemble("price_1h_eth.jsonl", ETH_SUFS, "cg_funding_eth.jsonl"))
    bw = btc.index[btc["spot_cvd_24h"].notna() & btc["funding"].notna()]
    mid = bw[0] + (bw[-1] - bw[0]) / 2
    print(f"BTC 有效窗口: {bw[0]} → {bw[-1]}  训练/样本外分界(对半): {mid}")
    ew = eth.index[eth["spot_cvd_24h"].notna() & eth["funding"].notna()]
    print(f"ETH 有效窗口: {ew[0]} → {ew[-1]}（整段零调整）\n")

    masks = {}
    for sym, feat in (("BTC", btc), ("ETH", eth)):
        for strat in ("s1", "s2"):
            masks[(strat, sym)] = entry_mask(feat, strat)

    # ---------- 阶段一：l1+t1 引擎下的止损画像 ----------
    print("=" * 110)
    print("阶段一 · 止损画像（现役 l1+t1 引擎；冤杀=止损后72h内触及原TP；救命=越过止损再走≥1R）")
    base_tr = {}
    prows, srows, brows = [], [], []
    for strat, sym in (("s1", "BTC"), ("s1", "ETH"), ("s2", "BTC"), ("s2", "ETH")):
        feat = btc if sym == "BTC" else eth
        mk, side = masks[(strat, sym)]
        base_tr[(strat, sym)] = sim_l(feat, mk, side, "l1")
    pools = [("s1@BTC", base_tr[("s1", "BTC")]), ("s1@ETH", base_tr[("s1", "ETH")]),
             ("s2@BTC", base_tr[("s2", "BTC")]), ("s2@ETH", base_tr[("s2", "ETH")]),
             ("s2@BTC+ETH合并", pd.concat([base_tr[("s2", "BTC")], base_tr[("s2", "ETH")]]))]
    for tag, tr in pools:
        prows.append(prof_stats(tr, tag))
        srows += seg_rows(tr, tag)
        for br, cnt in tr.branch.value_counts().items():
            brows.append({"人群": tag, "分支": br, "笔数": cnt,
                          "占比%": round(cnt / len(tr) * 100, 0),
                          "其中止损%": round((tr[tr.branch == br].exit == "stop").mean() * 100, 0)})
    ptab = pd.DataFrame(prows).set_index("人群")
    print(ptab.to_string())
    print("\n-- l1 止损分支占比 --")
    btab = pd.DataFrame(brows)
    print(btab.to_string(index=False))
    print("\n-- 分段（按入场时间；ETH/BTC 同段界）--")
    stab = pd.DataFrame(srows)
    print(stab.to_string(index=False))
    ptab.to_csv(os.path.join(OUT, "l_layer_profile.csv"))
    stab.to_csv(os.path.join(OUT, "l_layer_profile_segs.csv"), index=False)
    pd.concat([tr.assign(pool=tag) for tag, tr in pools[:4]]).to_csv(
        os.path.join(OUT, "l_layer_profile_trades.csv"), index=False)

    # ---------- 阶段二 ----------
    print("\n" + "=" * 110)
    print("阶段二 · 9 变体 × 配对整机（串行、锁死其余元素、TP=1.5×新止损距离）")
    rows = []
    for lv in VARIANTS:
        rec = {"L": lv}
        for strat in ("s1", "s2"):
            mkb, side = masks[(strat, "BTC")]
            mke, _ = masks[(strat, "ETH")]
            trb = base_tr[(strat, "BTC")] if lv == "l1" else sim_l(btc, mkb, side, lv)
            tre = base_tr[(strat, "ETH")] if lv == "l1" else sim_l(eth, mke, side, lv)
            allt = pd.concat([trb, tre])
            a = trb[trb.t < mid] if len(trb) else trb
            b = trb[trb.t >= mid] if len(trb) else trb
            sa, sb, sB, sE, sM = stats(a), stats(b), stats(trb), stats(tre), stats(allt)
            rec.update({f"{strat}B训n": sa["n"], f"{strat}B训net": sa["net"], f"{strat}B训wr": sa["wr"],
                        f"{strat}B外n": sb["n"], f"{strat}B外net": sb["net"], f"{strat}B外wr": sb["wr"],
                        f"{strat}Bnet": sB["net"], f"{strat}Bn": sB["n"],
                        f"{strat}Enet": sE["net"], f"{strat}En": sE["n"],
                        f"{strat}合计": round(sB["net"] + sE["net"], 2),
                        f"{strat}wr": sM["wr"], f"{strat}均stop%": sM["R"],
                        f"{strat}止损占比": sM["stop%"], f"{strat}冤杀72": sM["yz"]})
            rec[f"{strat}训外同号"] = bool(sa["net"] > 0 and sb["net"] > 0)
            rec[f"{strat}ETH同向"] = bool(sE["net"] > 0)
        rows.append(rec)
    tab = pd.DataFrame(rows).set_index("L")
    for strat in ("s1", "s2"):
        cols = [c for c in tab.columns if c.startswith(strat)]
        print(f"\n---- {strat} ({'阻力衰竭空' if strat == 's1' else '恐慌衰竭多p15'}) ----")
        print(tab[cols].to_string())
    tab.to_csv(os.path.join(OUT, "l_layer_scan.csv"))
    print(f"\n已保存 {os.path.join(OUT, 'l_layer_profile.csv')} / l_layer_profile_segs.csv"
          f" / l_layer_profile_trades.csv / l_layer_scan.csv")


if __name__ == "__main__":
    main()
