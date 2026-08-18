#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第四轮 S 层发掘 · 阶段0：五个新数据源（OI/盘口/清算/合约taker/多空比）元件级信息量档案。
python3 v4_state_profile.py

本脚本不做任何交易模拟。每个状态量被当作独立的行情分类器评价（方法照 o_info_profile.py）。
档案结论只回答"有没有信息"，决定第四轮预注册哪些结构；不回答"配哪个执行腿赚钱"。

预注册协议（测前锁定，测完不加）：
  状态量：V1–V12 共 22 判定行 × BTC/ETH（定义见 make_states 内注释）。
  考题：前瞻收益 fwd24 / fwd72（close-to-close，%，不含成本）。
  核心指标（状态行）：diff = mean(fwd|state=True) − mean(fwd|state=False)，Welch t，
    t_adj = t/√H 作重叠收益的保守下界。主判定口径 = d24（S 层 0.40pp 量级经验线即 diff24 口径）。
  连续量另报：全窗十分位组 fwd24 单调性（描述性、样本内分组，不参与判级）。
  事件口径：状态 onset 24h 去重；ev_d24 = mean(fwd24|event) − 全窗无条件基线。
  窗口：2025-08-03 → 2026-07-01。分段：上行→2025-11-01 / 崩盘→2026-01-07 / 下跌→2026-07-01。
    表外热身段 2025-07-21→08-03（12h 源可覆盖）只入 detail CSV，不参与判级。
  无前视：
    水平量（OI/盘口/LSR）在原生粒度 shift(1)（=上一根已完成 bar 的收值）后 ffill(limit=h−1) 拼接，
      细粒度 combine_first 覆盖粗粒度；禁止除以小时数。
    流量（清算/taker）除以粒度小时数摊薄拼接、不 shift——与全体系既有 CVD 拼接口径一致；
      粗粒度期存在 bar 内平滑前视，作为局限声明（同 S 层首轮 sF 声明，不修）。
    taker 单位按 playbook 启发式定：拼接后 buy 侧 median>1e6 视为 USD、除以价格转币单位
      （实测 cg_taker_perp 的 *_usd 键实为币单位，cg_taker_spot 为 USD——口径修正属单位纠错，非扫描）。
    滚动分位阈值 rolling(30d, min_periods=10d).quantile(q).shift(1)。
  判级（照 O 层 A/B/C/D 标准，改为方向不定式；主口径 d24）：
    A：BTC、ETH 全程 d24 同号，且 6 个段×品种格中 ≥5 格与全程同号，且上行段两品种与全程同号；
    B：BTC、ETH 全程 d24 同号，但分段不达 A（行情依赖）；
    D：仅对预注册了机理先验方向的行（V2_Q1:+ / V2_Q2:− / V10_long:+ / V10_short:−，
       方向 = "拥挤/极端流=顺势" 假设的预测）——双品种全程与假设反号且 max|t_adj|≥0.5 判 D；
       与假设同号即记"顺势假设复现"（写进专项结论）。
    C：其余（品种间符号打架，或弱到噪声）。
  冗余：22 行 + 4 参考门（现货CVD24/px、FR 的 >p90 / <p10 极值态）Jaccard，J≥0.80 视为高度冗余；
    8 个连续量与 spot_cvd24/px、funding 的 Pearson 相关（窗口内）。
  数据质量声明：新源 1h 仅 ~42 天（2026-05-21 起）；主判定序列为
    12h(2025-07-11 起) + 6h(2025-10-29 起) + 4h(2026-01 中起) + 2h + 1h 的拼接，
    上行段几乎纯 12h 粒度——状态在段内呈 12h 台阶、逐小时样本高度自相关，t_adj 只部分补偿；
    LSR 无 2h 粒度；结论按"粒度混合档案"解读，不与纯 1h 档案直接比较量级。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pandas as pd
from run import _jsonl, _ts_index, _pick, OUT  # noqa: E402

pd.set_option("display.width", 250)

SEGS = [("上行", "2025-08-03", "2025-11-01"),
        ("崩盘", "2025-11-01", "2026-01-07"),
        ("下跌", "2026-01-07", "2026-07-01")]
WIN0, WIN1 = "2025-08-03", "2026-07-01"
WARM0, WARM1 = "2025-07-21", "2025-08-03"   # 表外热身段（仅 detail CSV）
GRANS = [("", 1), ("_2h", 2), ("_4h", 4), ("_6h", 6), ("_12h", 12)]


def T(s, idx):
    t = pd.Timestamp(s)
    return t.tz_localize(idx.tz) if idx.tz is not None else t


def _load(base, sym_suf, gran_suf, fields):
    df = _jsonl(f"{base}{sym_suf}{gran_suf}.jsonl")
    if df is None:
        return None
    df = _ts_index(df)
    s = _pick(df, *fields)
    return None if s is None else pd.Series(s.values, index=df.index)


def stitch_level(base, fields, sym_suf, index):
    """水平量：原生粒度 shift(1)=上一根已完成bar → ffill(limit=h-1)，细粒度覆盖粗粒度。"""
    parts = []
    for g, h in GRANS:
        s = _load(base, sym_suf, g, fields)
        if s is None:
            continue
        s = s.shift(1)
        kw = {"method": "ffill", "limit": h - 1} if h > 1 else {}
        parts.append((s.reindex(index, **kw), h))
    out = None
    for d, _ in sorted(parts, key=lambda x: x[1]):
        out = d if out is None else out.combine_first(d)
    return out


def stitch_flow(base, fields, sym_suf, index, shift_bar=False):
    """流量：除以粒度小时数摊薄，细粒度覆盖粗粒度（与 grid_all.taker_stitched 同口径）。
    shift_bar=True：口径敏感复核用——原生粒度先 shift(1)，彻底消除粗粒度 bar 内前视
    （代价：信息滞后一根原生 bar，粗粒度段最多滞后 12h）。"""
    parts = []
    for g, h in GRANS:
        s = _load(base, sym_suf, g, fields)
        if s is None:
            continue
        if shift_bar:
            s = s.shift(1)
        kw = {"method": "ffill", "limit": h - 1} if h > 1 else {}
        parts.append((s.reindex(index, **kw) / h, h))
    out = None
    for d, _ in sorted(parts, key=lambda x: x[1]):
        out = d if out is None else out.combine_first(d)
    return out


def rp(s, q):
    """滚动30日分位（min_periods 10日），shift(1) 无前视。"""
    return s.rolling(24 * 30, min_periods=24 * 10).quantile(q).shift(1)


def diff_t(fwd, sb):
    a, b = fwd[sb], fwd[~sb]
    if len(a) < 10 or len(b) < 10:
        return np.nan, np.nan
    d = a.mean() - b.mean()
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return d, d / se if se > 0 else np.nan


def dedup_events(state, hours=24):
    """状态 onset，24h 去重。返回时间戳列表。"""
    ts = state.index[state == 1]
    out, last = [], None
    for t in ts:
        if last is None or (t - last) >= pd.Timedelta(hours=hours):
            out.append(t)
            last = t
    return out


def build(sym_suf, price_file, funding_file, flow_shift=False):
    cp = _ts_index(_jsonl(price_file), ("open_time_ms",))
    px = pd.to_numeric(cp["close"], errors="coerce")
    idx = px.index

    oi = stitch_level("cg_oi", ("close",), sym_suf, idx)
    ob_b = stitch_level("cg_orderbook", ("bids_usd",), sym_suf, idx)
    ob_a = stitch_level("cg_orderbook", ("asks_usd",), sym_suf, idx)
    lsr_g = stitch_level("cg_lsr_global", ("global_account_long_short_ratio",), sym_suf, idx)
    lsr_t = stitch_level("cg_lsr_top", ("top_position_long_short_ratio",), sym_suf, idx)
    liq_l = stitch_flow("cg_liquidation", ("long_liquidation_usd",), sym_suf, idx, flow_shift)
    liq_s = stitch_flow("cg_liquidation", ("short_liquidation_usd",), sym_suf, idx, flow_shift)
    pk_b = stitch_flow("cg_taker_perp", ("taker_buy_volume_usd",), sym_suf, idx, flow_shift)
    pk_s = stitch_flow("cg_taker_perp", ("taker_sell_volume_usd",), sym_suf, idx, flow_shift)
    sp_b = stitch_flow("cg_taker_spot", ("taker_buy_volume_usd",), sym_suf, idx, flow_shift)
    sp_s = stitch_flow("cg_taker_spot", ("taker_sell_volume_usd",), sym_suf, idx, flow_shift)

    fb = _ts_index(_jsonl(funding_file))
    fr = _pick(fb, "close").astype(float)
    if fr.abs().median() > 1e-3:
        fr = fr / 100
    fr = pd.Series(fr.values, index=fb.index).reindex(idx, method="ffill", limit=12)

    # ---- 连续量（8 个新 + 2 个参考）----
    dOI = oi.pct_change(24, fill_method=None) * 100                    # V1
    ret24 = px.pct_change(24, fill_method=None)
    liqL24 = liq_l.rolling(24, min_periods=24).sum()
    liqS24 = liq_s.rolling(24, min_periods=24).sum()
    liqT24 = liqL24 + liqS24
    liqL_oi = liqL24 / oi * 100                                        # V3（% of OI）
    liq_imb = (liqL24 - liqS24) / liqT24.replace(0, np.nan)            # V4
    depth = ob_b / (ob_b + ob_a).replace(0, np.nan)                    # V6

    def coin_flow(b, s):
        """playbook 单位启发式：median>1e6 视为 USD → 除以价格转币单位；否则已是币单位。
        实测 cg_taker_perp 的 *_usd 键实为币单位（BTC ~1.2e3/h），cg_taker_spot 为 USD。"""
        net = b - s
        return net / px if b.abs().median() > 1e6 else net

    perp_cvd = coin_flow(pk_b, pk_s).rolling(24, min_periods=24).sum()  # V8（币单位）
    spot_cvd = coin_flow(sp_b, sp_s).rolling(24, min_periods=24).sum()  # 参考（现役 spot CVD 同族）
    ratio_ts = lsr_t / lsr_g                                           # V11
    dLSR = lsr_g.pct_change(24, fill_method=None) * 100                # V12

    cont = {"c_dOI24": dOI, "c_liqL24_oi": liqL_oi, "c_liqImb24": liq_imb,
            "c_depthImb": depth, "c_perpCVD24": perp_cvd, "c_lsrG": lsr_g,
            "c_lsrRatio": ratio_ts, "c_dLSR24": dLSR,
            "r_spotCVD24": spot_cvd, "r_funding": fr}

    # ---- 判定行（布尔态，float 1/0/NaN；direction: 拥挤=顺势假设的预测符号，0=无先验）----
    def st(cond, valid):
        return cond.astype(float).where(valid)

    S, DIRS = {}, {}

    def add(name, cond, valid, d=0):
        S[name] = st(cond, valid)
        DIRS[name] = d

    v_oi = dOI.notna()
    add("V1_hi_ΔOI24>p90", dOI > rp(dOI, .90), v_oi & rp(dOI, .90).notna())
    add("V1_lo_ΔOI24<p10", dOI < rp(dOI, .10), v_oi & rp(dOI, .10).notna())
    v_q = v_oi & ret24.notna()
    add("V2_Q1_新多进场", (ret24 > 0) & (dOI > 0), v_q, +1)   # 价涨OI涨；顺势假设→继续涨
    add("V2_Q2_新空进场", (ret24 < 0) & (dOI > 0), v_q, -1)   # 价跌OI涨；顺势假设→继续跌
    add("V2_Q3_空头回补", (ret24 > 0) & (dOI < 0), v_q)       # 价涨OI跌
    add("V2_Q4_多头爆仓", (ret24 < 0) & (dOI < 0), v_q)       # 价跌OI跌
    add("V3_hi_多清/OI>p90", liqL_oi > rp(liqL_oi, .90), liqL_oi.notna() & rp(liqL_oi, .90).notna())
    add("V4_hi_清算失衡>p90", liq_imb > rp(liq_imb, .90), liq_imb.notna() & rp(liq_imb, .90).notna())
    add("V4_lo_清算失衡<p10", liq_imb < rp(liq_imb, .10), liq_imb.notna() & rp(liq_imb, .10).notna())
    add("V5_ev_总清算>p95", liqT24 > rp(liqT24, .95), liqT24.notna() & rp(liqT24, .95).notna())
    add("V6_hi_深度失衡>p90", depth > rp(depth, .90), depth.notna() & rp(depth, .90).notna())
    add("V6_lo_深度失衡<p10", depth < rp(depth, .10), depth.notna() & rp(depth, .10).notna())
    add("V8_hi_perpCVD>p90", perp_cvd > rp(perp_cvd, .90), perp_cvd.notna() & rp(perp_cvd, .90).notna())
    add("V8_lo_perpCVD<p10", perp_cvd < rp(perp_cvd, .10), perp_cvd.notna() & rp(perp_cvd, .10).notna())
    v9 = spot_cvd.notna() & perp_cvd.notna()
    add("V9_a_现货买合约卖", (spot_cvd > 0) & (perp_cvd < 0), v9)
    add("V9_b_现货卖合约买", (spot_cvd < 0) & (perp_cvd > 0), v9)
    add("V10_long_LSR>p90", lsr_g > rp(lsr_g, .90), lsr_g.notna() & rp(lsr_g, .90).notna(), +1)
    add("V10_short_LSR<p10", lsr_g < rp(lsr_g, .10), lsr_g.notna() & rp(lsr_g, .10).notna(), -1)
    add("V11_hi_大户/散户>p90", ratio_ts > rp(ratio_ts, .90), ratio_ts.notna() & rp(ratio_ts, .90).notna())
    add("V11_lo_大户/散户<p10", ratio_ts < rp(ratio_ts, .10), ratio_ts.notna() & rp(ratio_ts, .10).notna())
    add("V12_hi_ΔLSR24>p90", dLSR > rp(dLSR, .90), dLSR.notna() & rp(dLSR, .90).notna())
    add("V12_lo_ΔLSR24<p10", dLSR < rp(dLSR, .10), dLSR.notna() & rp(dLSR, .10).notna())

    # 参考门（冗余矩阵用）
    add("R_spotCVD>p90", spot_cvd > rp(spot_cvd, .90), spot_cvd.notna() & rp(spot_cvd, .90).notna())
    add("R_spotCVD<p10", spot_cvd < rp(spot_cvd, .10), spot_cvd.notna() & rp(spot_cvd, .10).notna())
    add("R_FR>p90", fr > rp(fr, .90), fr.notna() & rp(fr, .90).notna())
    add("R_FR<p10", fr < rp(fr, .10), fr.notna() & rp(fr, .10).notna())

    return px, cont, S, DIRS


NEW_ROWS = None  # 运行时填（S 中非 R_ 前缀的行）


def profile(tag, px, cont, S, DIRS):
    idx = px.index
    fwd24 = (px.shift(-24) / px - 1) * 100
    fwd72 = (px.shift(-72) / px - 1) * 100
    base_win = ((idx >= T(WIN0, idx)) & (idx < T(WIN1, idx))
                & fwd24.notna().values & fwd72.notna().values)
    base_win = pd.Series(base_win, index=idx)
    bl24 = fwd24[base_win].mean()
    print(f"[{tag}] 窗口 {WIN0}→{WIN1}，价格小时 {int(base_win.sum())}，基线 fwd24={bl24:+.3f}%")

    rows = []
    for nm, s in S.items():
        m = base_win & s.notna()
        sb = s[m] == 1
        d24, t24 = diff_t(fwd24[m], sb)
        d72, t72 = diff_t(fwd72[m], sb)
        seg = {}
        for sn, a, b in SEGS:
            mm = m & (idx >= T(a, idx)) & (idx < T(b, idx))
            ds, _ = diff_t(fwd24[mm], s[mm] == 1)
            seg[sn] = ds
        mw = s.notna() & (idx >= T(WARM0, idx)) & (idx < T(WARM1, idx)) & fwd24.notna()
        dwarm, _ = diff_t(fwd24[mw], s[mw] == 1)
        evs = dedup_events(s[m])
        ev_d24 = fwd24.loc[evs].mean() - bl24 if evs else np.nan
        rows.append({
            "row": nm, "sym": tag, "dir": DIRS[nm],
            "cov%": round(m.mean() * 100, 1), "pass%": round(sb.mean() * 100, 2),
            "n_hours": int(sb.sum()), "n_ev": len(evs),
            "d24": round(d24, 3) if pd.notna(d24) else np.nan,
            "t24_adj": round(t24 / np.sqrt(24), 2) if pd.notna(t24) else np.nan,
            "d72": round(d72, 3) if pd.notna(d72) else np.nan,
            "t72_adj": round(t72 / np.sqrt(72), 2) if pd.notna(t72) else np.nan,
            "ev_d24": round(ev_d24, 3) if pd.notna(ev_d24) else np.nan,
            **{f"seg_{sn}": (round(v, 3) if pd.notna(v) else np.nan) for sn, v in seg.items()},
            "warm_d24": round(dwarm, 3) if pd.notna(dwarm) else np.nan,
        })
    det = pd.DataFrame(rows).set_index("row")

    # 十分位单调性（描述性，样本内分组）
    dec_rows = []
    for nm, s in cont.items():
        v = s[base_win & s.notna()]
        f = fwd24.loc[v.index]
        if len(v) < 500:
            continue
        try:
            g = pd.qcut(v, 10, labels=False, duplicates="drop")
        except ValueError:
            continue
        means = f.groupby(g).mean()
        # Spearman = 组均值秩 与 分位序 的 Pearson（免 scipy）
        rho = means.rank().corr(pd.Series(means.index.astype(float), index=means.index).rank())
        dec_rows.append({"var": nm, "sym": tag, "n": len(v),
                         "rho_decile": round(rho, 2),
                         **{f"D{int(k)}": round(mv, 3) for k, mv in means.items()},
                         "top-base": round(means.iloc[-1] - f.mean(), 3),
                         "bot-base": round(means.iloc[0] - f.mean(), 3)})
    dec = pd.DataFrame(dec_rows).set_index("var")

    # Jaccard（含参考门）
    G = pd.DataFrame({k: (v[base_win] == 1) for k, v in S.items()})
    names = list(S.keys())
    jac = pd.DataFrame(index=names, columns=names, dtype=float)
    for i in names:
        for j in names:
            u = (G[i] | G[j]).sum()
            jac.loc[i, j] = round((G[i] & G[j]).sum() / u, 2) if u else np.nan

    # 连续量相关（Pearson，窗口内成对）
    C = pd.DataFrame({k: v[base_win] for k, v in cont.items()})
    corr = C.corr().round(2)
    return det, dec, jac, corr


def grade(b, e):
    if pd.isna(b.d24) or pd.isna(e.d24):
        return "C"
    sb, se = np.sign(b.d24), np.sign(e.d24)
    if sb == 0 or se == 0 or sb != se:
        return "C"
    s = sb
    strong = max(abs(b.t24_adj), abs(e.t24_adj)) >= 0.5
    d = b["dir"]
    if d != 0 and s == -d:
        return "D" if strong else "C"
    segs = ([b[f"seg_{sn}"] for sn, _, _ in SEGS] + [e[f"seg_{sn}"] for sn, _, _ in SEGS])
    nsame = sum(1 for v in segs if pd.notna(v) and np.sign(v) == s)
    up_ok = (pd.notna(b["seg_上行"]) and np.sign(b["seg_上行"]) == s
             and pd.notna(e["seg_上行"]) and np.sign(e["seg_上行"]) == s)
    return "A" if (up_ok and nsame >= 5) else "B"


def main():
    pb, cb, Sb, Db = build("", "price_1h.jsonl", "cg_funding.jsonl")
    pe, ce, Se, De = build("_eth", "price_1h_eth.jsonl", "cg_funding_eth.jsonl")
    tb, db_dec, jb, corr_b = profile("BTC", pb, cb, Sb, Db)
    te, de_dec, je, corr_e = profile("ETH", pe, ce, Se, De)

    rows = [n for n in Sb if not n.startswith("R_")]
    summ = pd.DataFrame(index=rows)
    summ["dir"] = [Db[n] for n in rows]
    for col in ["pass%", "n_ev", "d24", "t24_adj", "d72", "ev_d24"]:
        summ[f"BTC_{col}"] = tb.loc[rows, col]
        summ[f"ETH_{col}"] = te.loc[rows, col]
    for sn, _, _ in SEGS:
        summ[f"B{sn}"] = tb.loc[rows, f"seg_{sn}"]
        summ[f"E{sn}"] = te.loc[rows, f"seg_{sn}"]
    summ["判级"] = [grade(tb.loc[n], te.loc[n]) for n in rows]

    print("\n===== 判级汇总（主口径 d24, pp）=====")
    cols = ["dir", "BTC_pass%", "BTC_d24", "BTC_t24_adj", "ETH_d24", "ETH_t24_adj",
            "B上行", "B崩盘", "B下跌", "E上行", "E崩盘", "E下跌", "判级"]
    print(summ[cols].to_string())
    print("\n===== BTC 十分位单调性（fwd24 组均值, %）=====")
    print(db_dec.to_string())
    print("\n===== ETH 十分位单调性 =====")
    print(de_dec.to_string())
    print("\n===== 冗余：与参考门的最大 Jaccard（BTC）=====")
    ref = ["R_spotCVD>p90", "R_spotCVD<p10", "R_FR>p90", "R_FR<p10"]
    print(jb.loc[rows, ref].to_string())
    print("\n===== BTC 连续量 Pearson 相关 =====")
    print(corr_b.to_string())
    print("\n===== ETH 连续量 Pearson 相关 =====")
    print(corr_e.to_string())

    summ.to_csv(os.path.join(OUT, "v4_state_summary.csv"))
    tb.to_csv(os.path.join(OUT, "v4_state_detail_btc.csv"))
    te.to_csv(os.path.join(OUT, "v4_state_detail_eth.csv"))
    db_dec.to_csv(os.path.join(OUT, "v4_state_deciles_btc.csv"))
    de_dec.to_csv(os.path.join(OUT, "v4_state_deciles_eth.csv"))
    jb.to_csv(os.path.join(OUT, "v4_state_jaccard_btc.csv"))
    je.to_csv(os.path.join(OUT, "v4_state_jaccard_eth.csv"))
    corr_b.to_csv(os.path.join(OUT, "v4_state_corr_btc.csv"))
    corr_e.to_csv(os.path.join(OUT, "v4_state_corr_eth.csv"))

    # ---- 附录：流量拼接口径敏感复核（skill 阶段2.5：结果对口径敏感时补测两侧）----
    # 动机：清算族量级集中在 12h/6h 粗粒度段，标准摊薄口径存在 bar 内平滑前视，
    # 可能机械性夸大顺势 diff。复核口径 = 流量原生粒度 shift(1)（零前视、滞后一根原生 bar）。
    # 只看流量类行（V3/V4/V5/V8/V9），不改判级——差异写进报告"口径敏感"结论。
    flow_rows = [n for n in rows if n[:2] in ("V3", "V4", "V5", "V8", "V9")]
    pb2, cb2, Sb2, Db2 = build("", "price_1h.jsonl", "cg_funding.jsonl", flow_shift=True)
    pe2, ce2, Se2, De2 = build("_eth", "price_1h_eth.jsonl", "cg_funding_eth.jsonl", flow_shift=True)
    tb2, _, _, _ = profile("BTC(流shift)", pb2, cb2, Sb2, Db2)
    te2, _, _, _ = profile("ETH(流shift)", pe2, ce2, Se2, De2)
    fs = pd.DataFrame(index=flow_rows)
    for col in ["d24", "t24_adj", "ev_d24"]:
        fs[f"BTC_{col}_原"] = tb.loc[flow_rows, col]
        fs[f"BTC_{col}_shift"] = tb2.loc[flow_rows, col]
        fs[f"ETH_{col}_原"] = te.loc[flow_rows, col]
        fs[f"ETH_{col}_shift"] = te2.loc[flow_rows, col]
    for sn, _, _ in SEGS:
        fs[f"B{sn}_shift"] = tb2.loc[flow_rows, f"seg_{sn}"]
        fs[f"E{sn}_shift"] = te2.loc[flow_rows, f"seg_{sn}"]
    print("\n===== 附录：流量 shift 一根原生 bar 的口径复核 =====")
    print(fs.to_string())
    fs.to_csv(os.path.join(OUT, "v4_state_flowshift.csv"))
    print(f"\n已保存 summary/detail/deciles/jaccard/corr/flowshift CSV → {OUT}")


if __name__ == "__main__":
    main()
