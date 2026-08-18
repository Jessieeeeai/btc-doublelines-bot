#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""O层门控 元件级信息量档案（skill 阶段2：条件信息量诊断）。
python3 o_info_profile.py

与 o_layer_scan.py 的区别：本脚本不做任何交易模拟。每个门控被当作
独立的行情分类器评价——"它说熊，市场之后真的熊吗"。与任何 S 结构无关。

预注册协议（测前锁定，测完不加）：
  门控：o_layer_scan 的 11 个 + o2_SMA312 + o3_Vegas下沿，共 13 个。
        统一定义"看空态=True"，全程只用已完成K线（复用 make_o_gates，无前视）。
  考题：前瞻收益 fwd24 / fwd72（close-to-close，%，不含成本——分类考题不是交易）。
  核心指标：diff = mean(fwd|gate=True) − mean(fwd|gate=False)。看空门控要求 diff<0。
  显著性：Welch t（样本按小时数计）。fwd 为重叠收益，自相关使方差低估约 H 倍，
        故另报 t_adj = t/sqrt(H) 作保守下界。两者都只作粗排，不作精确推断。
  分析窗口：2025-08-03 → 2026-07-01（三段行情之并），且 13 门控全部就绪、
        fwd72 可算的小时（各门控用同一掩码，保证可比）。
  行情分段：上行 2025-08-03→2025-11-01；崩盘 2025-11-01→2026-01-07；
        下跌 2026-01-07→2026-07-01。报每段 fwd72 diff 符号。
  冗余：13×13 Jaccard（True 集合交并比），BTC/ETH 各一张。J≥0.80 视为高度冗余。
  判级规则（预注册，sign 为主、t_adj 为辅）：
    A：BTC、ETH 全程 fwd72 diff 均<0，且 6 个段×品种格中≥5 格<0，且上行段两品种均<0
    B：BTC、ETH 全程均<0，但不满足 A 的分段条件（行情依赖/只会跟着跌市喊熊）
    D：BTC、ETH 全程均>0，且至少一个品种 |t_adj|≥0.5（稳定反向）
    C：其余（品种间符号打架，或幅度弱到噪声）
  边界声明：判级只回答"有没有信息"，不回答"配哪个S赚钱"——那是配对级问题。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pandas as pd
from grid_all import assemble  # noqa: E402
from o_layer_scan import make_o_gates, BTC_SUFS, ETH_SUFS  # noqa: E402
from run import OUT  # noqa: E402

pd.set_option("display.width", 250)

SEGS = [("上行", "2025-08-03", "2025-11-01"),
        ("崩盘", "2025-11-01", "2026-01-07"),
        ("下跌", "2026-01-07", "2026-07-01")]
WIN0, WIN1 = "2025-08-03", "2026-07-01"
ORDER = ["o1_SMA168", "o2_SMA312", "o3_Vegas", "oA_SMA480", "oB_EMA200",
         "oC_DC20mid", "oD_MACD4h", "oE_RSI4h50", "oF_SuperTrend",
         "oG_MA7slope", "oH_MA7andVegas", "oI_SMA72", "oJ_Ichimoku4h"]


def T(s, idx):
    t = pd.Timestamp(s)
    return t.tz_localize(idx.tz) if idx.tz is not None else t


def all_gates(feat):
    """13 门控浮点序列（1/0/NaN），补齐 o2、o3。"""
    g = make_o_gates(feat)
    px = feat["close"]
    ma312 = px.rolling(312).mean()
    e144 = px.ewm(span=144, adjust=False).mean()
    e169 = px.ewm(span=169, adjust=False).mean()
    veg_lo = pd.concat([e144, e169], axis=1).min(axis=1)
    g["o2_SMA312"] = (px < ma312).astype(float).where(ma312.notna())
    g["o3_Vegas"] = (px < veg_lo).astype(float).where(veg_lo.notna())
    return {k: g[k] for k in ORDER}


def diff_t(fwd, gate_bool):
    """diff = mean(fwd|T) − mean(fwd|F)，Welch t。"""
    a, b = fwd[gate_bool], fwd[~gate_bool]
    if len(a) < 10 or len(b) < 10:
        return np.nan, np.nan
    d = a.mean() - b.mean()
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return d, d / se if se > 0 else np.nan


def profile(feat, tag):
    idx = feat.index
    px = feat["close"]
    fwd24 = (px.shift(-24) / px - 1) * 100
    fwd72 = (px.shift(-72) / px - 1) * 100
    gates = all_gates(feat)
    gdf = pd.DataFrame(gates)
    win = ((idx >= T(WIN0, idx)) & (idx < T(WIN1, idx))
           & gdf.notna().all(axis=1).values & fwd72.notna().values & fwd24.notna().values)
    win = pd.Series(win, index=idx)
    nwin = int(win.sum())
    print(f"[{tag}] 分析窗口 {WIN0}→{WIN1}，可用小时 {nwin}")

    rows, segrows = [], []
    for nm in ORDER:
        gb = gates[nm][win] == 1
        d24, t24 = diff_t(fwd24[win], gb)
        d72, t72 = diff_t(fwd72[win], gb)
        segsign = {}
        for sn, s0, s1 in SEGS:
            m = win & (idx >= T(s0, idx)) & (idx < T(s1, idx))
            ds, _ = diff_t(fwd72[m], gates[nm][m] == 1)
            segsign[sn] = ds
        rows.append({
            "gate": nm, "sym": tag, "pass%": round(gb.mean() * 100, 1),
            "d24": round(d24, 3), "t24": round(t24, 1), "t24_adj": round(t24 / np.sqrt(24), 2),
            "d72": round(d72, 3), "t72": round(t72, 1), "t72_adj": round(t72 / np.sqrt(72), 2),
            **{f"seg_{sn}": round(v, 3) for sn, v in segsign.items()},
        })
    # Jaccard 13×13
    G = gdf[win.values] == 1
    jac = pd.DataFrame(index=ORDER, columns=ORDER, dtype=float)
    for i in ORDER:
        for j in ORDER:
            u = (G[i] | G[j]).sum()
            jac.loc[i, j] = round((G[i] & G[j]).sum() / u, 2) if u else np.nan
    return pd.DataFrame(rows).set_index("gate"), jac


def grade(b, e):
    """预注册判级：A/B/C/D。b、e 为 BTC/ETH 单行 Series。"""
    negb, nege = b.d72 < 0, e.d72 < 0
    strong = max(abs(b.t72_adj), abs(e.t72_adj)) >= 0.5
    segs = [b[f"seg_{s}"] for s, _, _ in SEGS] + [e[f"seg_{s}"] for s, _, _ in SEGS]
    nneg = sum(1 for v in segs if v < 0)
    up_ok = (b["seg_上行"] < 0) and (e["seg_上行"] < 0)
    if negb and nege:
        return "A" if (up_ok and nneg >= 5) else "B"
    if (not negb) and (not nege):
        return "D" if strong else "C"
    return "C"


def main():
    btc = assemble("price_1h.jsonl", BTC_SUFS, "cg_funding.jsonl")
    eth = assemble("price_1h_eth.jsonl", ETH_SUFS, "cg_funding_eth.jsonl")
    tb, jb = profile(btc, "BTC")
    te, je = profile(eth, "ETH")

    summary = pd.DataFrame(index=ORDER)
    summary["BTC放行%"] = tb["pass%"]
    summary["ETH放行%"] = te["pass%"]
    summary["BTC_d24"] = tb.d24
    summary["ETH_d24"] = te.d24
    summary["BTC_d72"] = tb.d72
    summary["BTC_t72adj"] = tb.t72_adj
    summary["ETH_d72"] = te.d72
    summary["ETH_t72adj"] = te.t72_adj
    for sn, _, _ in SEGS:
        summary[f"BTC{sn}"] = tb[f"seg_{sn}"]
        summary[f"ETH{sn}"] = te[f"seg_{sn}"]
    summary["J_o1_BTC"] = jb["o1_SMA168"]
    summary["判级"] = [grade(tb.loc[n], te.loc[n]) for n in ORDER]

    print("\n===== 全程 diff（fwd72，%）与判级 =====")
    print(summary.to_string())
    print("\n===== BTC 13×13 Jaccard =====")
    print(jb.to_string())
    print("\n===== ETH 13×13 Jaccard =====")
    print(je.to_string())

    summary.to_csv(os.path.join(OUT, "o_info_profile_summary.csv"))
    jb.to_csv(os.path.join(OUT, "o_info_jaccard_btc.csv"))
    je.to_csv(os.path.join(OUT, "o_info_jaccard_eth.csv"))
    tb.to_csv(os.path.join(OUT, "o_info_detail_btc.csv"))
    te.to_csv(os.path.join(OUT, "o_info_detail_eth.csv"))
    print(f"\n已保存 summary/jaccard/detail CSV → {OUT}")


if __name__ == "__main__":
    main()
