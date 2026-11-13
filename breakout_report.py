"""强突破四马 / AMD马 · 关单图文战报: 平仓时生成复盘K线图 + caption, TG sendPhoto 推送。
与颈线马的 neckline_report.py 同一套 SOP (出场文字 → 关单复盘图 + caption + 单马战绩栏)。
matplotlib 不可用或出图失败自动降级纯文字, 永不抛异常。图上标注用英文, 防 CJK 字体缺失。

trade (机器人 state 里的成交记录) 用到的字段:
  seq code sym d e x ts xts n why net_base hold_h sl sl0 tp  [ch] [legs hit tg s1 box]
bars: 该币 1h K线 [{ts, open, high, low, close}, ...]
"""
from datetime import datetime, timezone

from tg_notify import send_photo, send_message

RED, TEAL, BLUE, UP, DOWN, SL_RED, ZONE, AMBER = "#E24B4A", "#1D9E75", "#378ADD", "#1D9E75", "#E24B4A", "#A32D2D", "#378ADD", "#BA7517"
H = 3600
PRINCIPAL_USD = 1000.0


def _d(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)


def _t(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M")


def fp(x):
    if x >= 1000: return f"{x:,.1f}"
    if x >= 10: return f"{x:,.2f}"
    if x >= 1: return f"{x:,.4f}"
    return f"{x:.5f}"


def sl_path(t, bars):
    """止损随时间的阶梯 [(t0, t1, level)]。固定止盈马一段; 吊灯马按 1h K线近似复算; AMD马在第一止盈后上移一次。"""
    e_ts, x_ts, d = t["ts"], t["xts"], t["d"]
    if t.get("legs") is not None:                       # AMD马
        tp_ts = [l[3] for l in t["legs"] if l[2] == "tp"]
        if tp_ts and t.get("s1") is not None and t["sl"] != t["sl0"]:
            return [(e_ts, min(tp_ts), t["sl0"]), (min(tp_ts), x_ts, t["sl"])]
        return [(e_ts, x_ts, t["sl0"])]
    if not t.get("ch"):                                 # 固定止盈马
        return [(e_ts, x_ts, t["sl0"])]
    segs, sl, pk, t0 = [], t["sl0"], t["e"], e_ts
    for b in bars:
        if b["ts"] + H <= e_ts or b["ts"] >= x_ts:
            continue
        ns = pk - d * t["ch"]
        if (ns - sl) * d > 0 and b["ts"] > t0:
            segs.append((t0, b["ts"], sl)); sl, t0 = ns, b["ts"]
        pk = max(pk, b["high"]) if d == 1 else min(pk, b["low"])
    if (t["sl"] - sl) * d > 0 and x_ts - H > t0:        # 收尾对齐到实际出场时的止损
        segs.append((t0, x_ts - H, sl)); sl, t0 = t["sl"], x_ts - H
    segs.append((t0, x_ts, sl))
    return segs


def zone_of(t, bars):
    """图上的形态框 (x0_ts, x1_ts, lo, hi, 标签)。突破马 = 突破K; AMD马 = 吸筹箱体。"""
    if t.get("legs") is not None:
        if not t.get("box"):
            return None
        lo, hi = t["box"]
        return (t["ts"] - 60 * H, t["ts"], lo, hi, f"box {fp(lo)}~{fp(hi)}")
    bo = next((b for b in bars if b["ts"] == t["ts"] // H * H - 2 * H), None)
    if not bo:
        return None
    return (bo["ts"] - H // 2, bo["ts"] + H // 2, bo["low"], bo["high"], "breakout bar")


def render_chart(t, bars):
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import matplotlib.patches as mpatches

    amd = t.get("legs") is not None
    e_ts, x_ts, d = t["ts"], t["xts"], t["d"]
    pad_l, pad_r = (72 if amd else 24) * H, 8 * H
    win = [b for b in bars if e_ts - pad_l <= b["ts"] <= x_ts + pad_r]
    if len(win) < 5:
        raise ValueError(f"窗口内K线不足({len(win)})")
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    w = 1 / 24 * 0.65
    for b in win:
        x = mdates.date2num(_d(b["ts"])); up = b["close"] >= b["open"]; c = UP if up else DOWN
        ax.vlines(x, b["low"], b["high"], color=c, linewidth=0.7, alpha=0.9)
        body = abs(b["close"] - b["open"]) or (b["high"] - b["low"]) * 0.01 or b["close"] * 1e-5
        ax.bar(x, body, width=w, bottom=min(b["open"], b["close"]), color=c, alpha=0.9 if up else 0.85, linewidth=0)
    x0, x1 = _d(e_ts), _d(x_ts)
    segs = sl_path(t, bars)
    z = zone_of(t, bars)
    if z:
        zx0 = mdates.date2num(_d(max(win[0]["ts"], z[0]))); zx1 = mdates.date2num(_d(z[1]))
        ax.add_patch(mpatches.Rectangle((zx0, z[2]), zx1 - zx0, z[3] - z[2], linewidth=1.0, edgecolor=ZONE, facecolor=ZONE, alpha=0.15))
        ax.annotate(z[4], (zx0, z[3]), fontsize=7, color=ZONE, ha="left", va="bottom")
    lo = min(min(b["low"] for b in win), *[s[2] for s in segs], t["e"], t["x"])
    hi = max(max(b["high"] for b in win), *[s[2] for s in segs], t["e"], t["x"])
    rng = hi - lo
    tps = [("TP1", t["tg"][0]), ("TP2", t["tg"][1]), ("TP3", t["tg"][2])] if amd and t.get("tg") else ([("TP", t["tp"])] if t.get("tp") else [])
    for name, tp in tps:
        if lo - 0.35 * rng <= tp <= hi + 0.35 * rng:
            ax.hlines(tp, x0, x1, color=TEAL, linestyle="--", linewidth=1.2)
            ax.annotate(f"{name} {fp(tp)}", (x0, tp), fontsize=8, color=TEAL, ha="left", va="bottom")
            lo, hi = min(lo, tp), max(hi, tp)
    rng = hi - lo
    for t0s, t1s, lvl in segs:
        ax.hlines(lvl, _d(t0s), _d(t1s), color=SL_RED, linewidth=1.6)
    ax.annotate(f"SL0 {fp(segs[0][2])}", (x0, segs[0][2]), fontsize=8, color=SL_RED, ha="left", va="top" if d == 1 else "bottom")
    ax.set_ylim(lo - 0.07 * rng, hi + 0.07 * rng)
    short = d == -1
    ax.plot([x0], [t["e"]], marker="v" if short else "^", color=BLUE, markersize=10, zorder=5)
    ax.annotate(f"entry {fp(t['e'])}", (x0, t["e"]), fontsize=9, color=BLUE, ha="left", va="top" if short else "bottom",
                xytext=(6, -10 if short else 10), textcoords="offset points")
    col = TEAL if t["net_base"] >= 0 else RED
    if amd:
        for i, px, why, lts in t["legs"]:
            ax.plot([_d(lts)], [px], marker="o", color=TEAL if why == "tp" else (RED if why == "sl" else AMBER), markersize=7, zorder=5)
    else:
        ax.plot([x1], [t["x"]], marker="o", color=col, markersize=9, zorder=5)
    ax.annotate(f"exit {fp(t['x'])}", (x1, t["x"]), fontsize=9, color=col, ha="left" if amd else "right",
                xytext=(8, -4) if amd else (-6, 10), textcoords="offset points")
    ax.set_title(f"[{t['code']}] {t['sym']} #{t['seq']:03d} {'SHORT' if short else 'LONG'}  {t['net_base']:+,.0f} USD  (paper)", fontsize=11, loc="left")
    ax.yaxis.set_major_formatter(lambda v, _: f"${fp(v)}" if v > 0 else "")
    span_days = (win[-1]["ts"] - win[0]["ts"]) / 86400
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=7))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M" if span_days < 4 else "%m-%d"))
    ax.tick_params(axis="x", labelsize=8)
    ax.grid(True, linewidth=0.3, alpha=0.4)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png"); plt.close(fig)
    return buf.getvalue()


def build_caption(t, horse_name, bars, footer=""):
    amd = t.get("legs") is not None
    short = t["d"] == -1
    z = zone_of(t, bars)
    if amd:
        shape = (f"📐 吸筹箱体 {fp(t['box'][0])}~{fp(t['box'][1])} (4h) → 扫{'高' if short else '低'}点 → 收回" if t.get("box")
                 else f"📐 4h 横盘 → 扫{'高' if short else '低'}点 → 收回箱体")
        names = {"tp": "止盈", "sl": "止损", "time": "到时平仓"}
        reason = "\n".join(f"{'🎯' if w == 'tp' else ('🛑' if w == 'sl' else '⏱')} {_t(lts)} 第{i}份{names[w]} <code>${fp(px)}</code>" for i, px, w, lts in t["legs"])
    else:
        shape = f"📐 突破K {fp(z[2])}~{fp(z[3])} (1h) + 跟进K" if z else "📐 1h 强突破K + 跟进K"
        trail = t["sl"] != t["sl0"]
        reason = {"tp": "🎯 打到TP目标价, 止盈出场", "time": "⏱ 持仓到时, 按收盘价平仓",
                  "sl": "🔒 回踩打到吊灯止损出场" if trail else "🛑 打到止损出场"}[t["why"]]
    lines = [f"🧾 <b>[{t['code']}] #{t['seq']:03d} 关单复盘</b> — {horse_name}",
             f"{t['sym']} {'📉 空单' if short else '📈 多单'} · 名义 ${t['n']:,.0f}",
             "━━━━━━━━━━━━━━━", shape,
             f"✅ {_t(t['ts'])} 进场 <code>${fp(t['e'])}</code>", reason]
    if not amd:
        lines.append(f"🏁 {_t(t['xts'])} 出场 <code>${fp(t['x'])}</code>")
    lines += ["━━━━━━━━━━━━━━━",
              f"💰 <b>{'+' if t['net_base'] >= 0 else '-'}${abs(t['net_base']):,.2f}</b> (<b>{t['net_base'] / PRINCIPAL_USD * 100:+.2f}%</b>) · 持仓 {t['hold_h']:g} 小时"]
    return "\n".join(lines) + footer


def send_trade_report(t, horse_name, bars, footer=""):
    """平仓战报入口。出图失败自动降级纯文字, 永不抛异常。"""
    try:
        caption = build_caption(t, horse_name, bars, footer)
    except Exception as e:
        print(f"  [report] caption 失败: {e}"); return
    try:
        if send_photo(render_chart(t, bars), caption):
            return
    except Exception as e:
        print(f"  [report] 出图失败, 降级纯文字: {type(e).__name__}: {e}")
    send_message(caption)
